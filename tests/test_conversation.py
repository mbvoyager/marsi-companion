"""Prevent generated boilerplate from becoming a self-reinforcing chat example."""
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from marsi_local.config import ServerConfig
from marsi_local.conversation import main, recover_history, repeats_answer, repeats_itself
from marsi_local.core import Companion, Ollama, ServiceError


LITANY = (
    "The archive hums beneath its brass seals while the ancient cogs turn patiently in the red light. "
    "A little priest tends the quiet forge and counts its many lamps, reciting the same familiar litany "
    "while the mechanisms trace their well worn paths through the silent hall."
)


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = ServerConfig(database=Path(self.folder.name) / "test.sqlite3")
        self.llm = Mock()
        self.llm.chat.return_value = "4."
        self.app = Companion(self.config, llm=self.llm)

    def seed_repetition(self):
        self.app.memory.remember_turn("pi", "I am learning Python.", "One little step at a time.")
        self.app.memory.remember_turn("pi", "I enjoy drawing.", "A small preamble. " + LITANY)
        self.app.memory.remember_turn("pi", "I prefer quiet evenings.", "A different preamble. " + LITANY)

    def test_long_passages_are_detected_but_short_truths_are_not(self):
        self.assertTrue(repeats_answer("New opening! " + LITANY.upper(), [LITANY]))
        self.assertTrue(repeats_itself(LITANY + "\n\n" + LITANY))
        self.assertFalse(repeats_itself(LITANY))
        self.assertFalse(repeats_answer("4.", ["4."]))
        self.assertFalse(repeats_answer("A small salute. ^^", ["A small salute. ^^"]))
        self.assertFalse(repeats_answer("A distinct short useful answer.", [LITANY]))

    def test_recovery_preserves_human_facts_and_original_journal(self):
        self.seed_repetition()
        original = self.app.memory.context("pi")
        filtered, human = recover_history(original)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(human, ["I enjoy drawing.", "I prefer quiet evenings."])
        self.assertEqual(self.app.memory.context("pi"), original)
        result = self.app.chat("pi", "What is 2 + 2?")
        messages = self.llm.chat.call_args.args[0]
        self.assertNotIn(LITANY, "\n".join(m["content"] for m in messages))
        self.assertIn("I enjoy drawing.", messages[0]["content"])
        self.assertEqual(messages[-1]["content"], "What is 2 + 2?")
        self.assertEqual(result["text"], "4.")
        entries = self.app.memory.journal("pi")["entries"]
        self.assertEqual(len(entries), 8)
        self.assertTrue(any(LITANY in entry["text"] for entry in entries))

    def test_repair_removes_single_bad_example_then_saves_only_good_reply(self):
        self.app.memory.remember_turn("pi", "An earlier synthetic question.", LITANY)
        self.llm.chat.side_effect = [LITANY, "An Ethernet cable links devices to a wired network."]
        result = self.app.chat("pi", "What does an Ethernet cable do?")
        self.assertEqual(self.llm.chat.call_count, 2)
        retry = self.llm.chat.call_args.args[0]
        self.assertNotIn(LITANY, "\n".join(m["content"] for m in retry))
        self.assertIn("An earlier synthetic question.", retry[0]["content"])
        self.assertEqual(retry[-1]["content"], "What does an Ethernet cable do?")
        entries = self.app.memory.journal("pi")["entries"]
        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[-1]["text"], result["text"])

    def test_persistent_loop_is_not_saved_and_does_not_retry_forever(self):
        self.seed_repetition()
        self.llm.chat.return_value = LITANY
        with self.assertRaisesRegex(ServiceError, "stuck repeating"):
            self.app.chat("pi", "A new unrelated question.")
        self.assertEqual(self.llm.chat.call_count, 2)
        self.assertEqual(len(self.app.memory.journal("pi")["entries"]), 6)

    def test_explicit_repetition_and_same_question_are_allowed(self):
        self.app.memory.remember_turn("pi", "An earlier synthetic question.", LITANY)
        self.llm.chat.return_value = LITANY
        self.app.chat("pi", "An earlier synthetic question.")
        self.app.chat("pi", "Please repeat your last answer.")
        self.assertEqual(self.llm.chat.call_count, 2)

    def test_no_second_call_when_first_used_the_time_budget(self):
        self.llm.chat.return_value = LITANY + LITANY
        with patch.object(self.app.telemetry, "pair", return_value={}), \
                patch("marsi_local.core.time.monotonic", side_effect=[100, 281]):
            with self.assertRaisesRegex(ServiceError, "repeated a long passage"):
                self.app.chat("pi", "A synthetic question.")
        self.assertEqual(self.llm.chat.call_count, 1)
        self.assertEqual(self.app.memory.context("pi"), [])

    def test_real_adapter_receives_remaining_repair_budget(self):
        adapter = Ollama(self.config)
        app = Companion(self.config, llm=adapter)
        with patch.object(app.telemetry, "pair", return_value={}), \
                patch.object(adapter, "chat", side_effect=[LITANY + LITANY, "A fresh reply."]) as chat, \
                patch("marsi_local.core.time.monotonic", side_effect=[100, 150]):
            app.chat("pi", "A synthetic question.")
        self.assertEqual(chat.call_args.kwargs["timeout"], 130)

    def test_sampling_and_timeout_reach_ollama(self):
        adapter = Ollama(self.config)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"message":{"content":"4."}}'
        with patch.object(adapter.http, "open", return_value=response) as opened:
            adapter.chat([{"role": "user", "content": "2 + 2?"}], timeout=12)
        self.assertEqual(opened.call_args.kwargs["timeout"], 12)
        options = json.loads(opened.call_args.args[0].data)["options"]
        self.assertEqual((options["temperature"], options["top_p"], options["top_k"], options["min_p"]), (0.7, 0.8, 20, 0))
        self.assertGreater(options["presence_penalty"], 0)
        self.assertGreater(options["repeat_penalty"], 1)
        self.assertEqual(options["num_ctx"], 4096)

    def test_model_diagnostic_uses_temp_journal_not_configured_private_database(self):
        private = Path(self.folder.name) / "private.sqlite3"
        private.write_bytes(b"PRIVATE DATABASE PLACEHOLDER")
        config = replace(self.config, database=private)
        llm = Mock()
        llm.chat.side_effect = ["4.", "It connects network devices.", "You did well today. ^^"]
        test_paths = []
        def app_factory(configuration):
            test_paths.append(configuration.database)
            self.assertNotEqual(configuration.database, private)
            self.assertFalse(configuration.observances)
            return Companion(configuration, llm=llm)
        with patch("sys.argv", ["check", "--check"]), patch("marsi_local.config.load_env"), \
                patch("marsi_local.config.ServerConfig.from_env", return_value=config), \
                patch("marsi_local.core.Companion", side_effect=app_factory), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(), 0)
        self.assertEqual(private.read_bytes(), b"PRIVATE DATABASE PLACEHOLDER")
        self.assertFalse(test_paths[0].exists())
        self.assertEqual(llm.chat.call_count, 3)
        self.assertNotIn("[PASS]", output.getvalue())


if __name__ == "__main__":
    unittest.main()
