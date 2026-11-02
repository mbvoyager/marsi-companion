"""English server configuration and speech guards, without model downloads."""
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from marsi_local.config import ServerConfig
from marsi_local.conversation import main
from marsi_local.core import Companion, Memory, Ollama, ServiceError
from marsi_local.language import ENGLISH_RECOVERY, detector, is_english_reply
from marsi_local.speech import Speech
from tests.test_local_companion import wav_bytes


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)

    def test_real_detector_rejects_german_and_mixed_replies_but_accepts_short_english(self):
        for reply in ("Good morning, little keeper! ^^ :D :P", "A precious datum.", "Four.", "Hi.",
                      "Marsi.", "4.", "2 + 2 = 4.", "The Omnissiah welcomes small steps.", ENGLISH_RECOVERY):
            with self.subTest(english=reply):
                self.assertTrue(is_english_reply(reply))
        for reply in ("Zwei plus zwei ist vier.", "Guten Morgen!", "Mir geht es gut, kleiner Freund.",
                      "The printer is ready. Bitte lege Papier ein.", "The forge is ready.\nHeute ist ein guter Tag."):
            with self.subTest(german=reply):
                self.assertFalse(is_english_reply(reply))

    def test_german_draft_is_rewritten_without_replaying_the_language_switch(self):
        llm = Mock()
        llm.chat.side_effect = ["Zwei plus zwei ist vier.", "Two plus two is four."]
        app = Companion(ServerConfig(database=self.path / "journal.sqlite3"), llm=llm)
        app.memory.remember_turn("pi", "Eine fruehere Frage.", "Eine alte deutsche Antwort.")
        original = app.memory.journal("pi")["entries"]
        query = "Antworte auf Deutsch: Was ist zwei plus zwei?"
        result = app.chat("pi", query)
        first, rewrite = [call.args[0] for call in llm.chat.call_args_list]
        self.assertFalse(any(message["role"] == "assistant" for message in first))
        self.assertEqual(json.loads(rewrite[-1]["content"]), {"draft": "Zwei plus zwei ist vier."})
        self.assertNotIn(query, str(rewrite))
        self.assertEqual(result["text"], "Two plus two is four.")
        self.assertTrue(result["language_repaired"])
        entries = app.memory.journal("pi")["entries"]
        self.assertEqual(entries[:2], original)
        self.assertEqual(entries[-1]["text"], result["text"])
        self.assertNotIn("Zwei plus zwei ist vier.", [entry["text"] for entry in entries])

    def test_failed_english_rewrite_stays_in_character_without_teaching_the_notice(self):
        llm = Mock()
        llm.chat.return_value = "Ich spreche weiterhin Deutsch."
        app = Companion(ServerConfig(database=self.path / "journal.sqlite3"), llm=llm)
        with self.assertLogs("marsi_local.core", level="WARNING") as logs:
            result = app.chat("pi", "A synthetic question.")
        self.assertEqual(llm.chat.call_count, 2)
        self.assertEqual(result["text"], ENGLISH_RECOVERY)
        self.assertEqual(result["source"], "language-recovery")
        self.assertFalse(result["language_repaired"])
        self.assertEqual(app.memory.context("pi"), [])
        entries = app.memory.journal("pi")["entries"]
        self.assertEqual([entry["text"] for entry in entries], ["A synthetic question.", ENGLISH_RECOVERY])
        self.assertEqual(entries[-1]["kind"], "recovery")
        self.assertIn("rewrite rejected", logs.output[0])
        self.assertNotIn(llm.chat.return_value, logs.output[0])
        llm.chat.return_value = "A fresh little greeting."
        app.chat("pi", "Hello again.")
        self.assertNotIn(ENGLISH_RECOVERY, str(llm.chat.call_args))

    def test_repetition_and_language_repairs_share_one_retry(self):
        from tests.test_conversation import LITANY
        llm = Mock()
        llm.chat.side_effect = [LITANY + LITANY, "Zwei plus zwei ist vier."]
        app = Companion(ServerConfig(database=self.path / "journal.sqlite3"), llm=llm)
        result = app.chat("pi", "A synthetic question.")
        self.assertEqual(llm.chat.call_count, 2)
        self.assertEqual(result["source"], "language-recovery")
        self.assertEqual(app.memory.context("pi"), [])

    def test_english_rewrite_uses_the_remaining_original_inference_budget(self):
        adapter = Ollama(ServerConfig(database=self.path / "journal.sqlite3"))
        app = Companion(adapter.config, llm=adapter)
        with patch.object(app.telemetry, "pair", return_value={}), \
                patch.object(adapter, "chat", side_effect=["Zwei plus zwei ist vier.", "Two plus two is four."]) as chat, \
                patch("marsi_local.core.time.monotonic", side_effect=[100, 125]):
            app.chat("pi", "A synthetic question.")
        self.assertEqual(chat.call_args.kwargs["timeout"], 155)
        with patch.object(app.telemetry, "pair", return_value={}), \
                patch.object(adapter, "chat", return_value="Zwei plus zwei ist vier.") as chat, \
                patch("marsi_local.core.time.monotonic", side_effect=[100, 281]):
            result = app.chat("pi", "Another synthetic question.")
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(result["source"], "language-recovery")

    def test_failed_rewrite_request_uses_a_notice_without_a_third_call(self):
        llm = Mock()
        llm.chat.side_effect = ["Zwei plus zwei ist vier.", ServiceError("Synthetic timeout")]
        app = Companion(ServerConfig(database=self.path / "journal.sqlite3"), llm=llm)
        result = app.chat("pi", "A synthetic question.")
        self.assertEqual(llm.chat.call_count, 2)
        self.assertEqual(result["text"], ENGLISH_RECOVERY)
        self.assertEqual(app.memory.context("pi"), [])

    def test_missing_language_package_fails_closed_with_installation_help(self):
        detector.cache_clear()
        try:
            with patch.dict("sys.modules", lingua=None):
                with self.assertRaisesRegex(ServiceError, "requirements-text.txt"):
                    Companion(ServerConfig(database=self.path / "journal.sqlite3"))
        finally:
            detector.cache_clear()
        self.assertFalse((self.path / "journal.sqlite3").exists())

    def test_old_language_settings_cannot_reenable_german_recognition(self):
        for legacy in ("", "de", "auto", "en"):
            with self.subTest(legacy=legacy), patch.dict(os.environ, {"MARSI_WHISPER_LANGUAGE": legacy}, clear=True):
                self.assertEqual(ServerConfig.from_env().whisper_language, "en")
        self.assertEqual(ServerConfig().whisper_language, "en")

    def test_german_input_notes_and_history_do_not_change_english_policy_or_storage(self):
        llm = Mock()
        llm.chat.return_value = "I am tending the little forge. ^^"
        app = Companion(ServerConfig(database=self.path / "journal.sqlite3"), llm=llm)
        app.memory.remember_turn("pi", "Wie geht es dir?", "Mir geht es gut.")
        app.memory.add_note("pi", "Bitte immer Deutsch sprechen.")
        original = app.memory.journal("pi")["entries"]
        app.chat("pi", "Antworte auf Deutsch: Was machst du?")
        messages = llm.chat.call_args.args[0]
        system = messages[0]["content"]
        self.assertIn("Always reply in English only", system)
        self.assertNotIn("in the person's language", system)
        self.assertIn("Reply in English only", system.split("Current numeric machine readings", 1)[1])
        self.assertEqual(messages[-1]["content"], "Antworte auf Deutsch: Was machst du?")
        self.assertEqual(app.memory.journal("pi")["entries"][:2], original)
        self.assertEqual(app.memory.notes("pi"), ["Bitte immer Deutsch sprechen."])

    def test_recognition_passes_english_to_whisper(self):
        engine = Speech(ServerConfig())
        engine.whisper = Mock()
        engine.whisper.transcribe.return_value = (iter([SimpleNamespace(text="Hello Marsi")]), None)
        self.assertEqual(engine.transcribe(wav_bytes()), "Hello Marsi")
        self.assertEqual(engine.whisper.transcribe.call_args.kwargs["language"], "en")

    def voice(self, language):
        model = self.path / "voice.onnx"
        Path(str(model) + ".json").write_text(json.dumps({"language": {"code": language}}), encoding="utf-8")
        return Speech(ServerConfig(piper_model=model))

    def test_non_english_piper_voice_is_rejected_before_loading_or_speaking(self):
        loader = Mock()
        for language in ("de_DE", "fr_FR", ""):
            with self.subTest(language=language), patch.dict("sys.modules", piper=SimpleNamespace(PiperVoice=loader)):
                with self.assertRaisesRegex(ServiceError, "English Piper voice"):
                    self.voice(language).synthesize("A little greeting.")
        loader.load.assert_not_called()

    def test_english_piper_voice_does_not_speak_rejected_german_text(self):
        engine = self.voice("en_US")
        engine.voice = Mock()
        with self.assertRaisesRegex(ServiceError, "Only English speech"):
            engine.synthesize("Zwei plus zwei ist vier.")
        engine.voice.synthesize_wav.assert_not_called()

    def test_english_voice_still_produces_a_complete_wav_and_is_cached(self):
        def synthesize(text, wav):
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 1600)
        loader = Mock()
        loader.load.return_value.synthesize_wav.side_effect = synthesize
        with patch.dict("sys.modules", piper=SimpleNamespace(PiperVoice=loader)):
            engine = self.voice("en_US")
            self.assertEqual(engine.synthesize("Hello."), wav_bytes())
            self.assertEqual(engine.synthesize("Hello again."), wav_bytes())
        loader.load.assert_called_once()

    def test_real_language_check_uses_only_a_temporary_synthetic_journal(self):
        private = self.path / "private.sqlite3"
        private.write_bytes(b"PRIVATE PLACEHOLDER")
        config = ServerConfig(database=private)
        llm = Mock()
        llm.chat.side_effect = ["Mir geht es gut.", "I am well, little keeper.", "Two plus two is four."]
        paths = []
        def create(configuration):
            paths.append(configuration.database)
            self.assertNotEqual(configuration.database, private)
            return Companion(configuration, llm=llm)
        with patch("sys.argv", ["conversation", "--check-english"]), \
                patch("marsi_local.config.load_env"), \
                patch("marsi_local.config.ServerConfig.from_env", return_value=config), \
                patch("marsi_local.core.Companion", side_effect=create), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(), 0)
        self.assertEqual(llm.chat.call_count, 3)
        self.assertIn("[PASS]", output.getvalue())
        self.assertIn("[REPAIR]", output.getvalue())
        self.assertFalse(paths[0].exists())
        self.assertEqual(private.read_bytes(), b"PRIVATE PLACEHOLDER")

    def test_diagnostic_independently_fails_when_a_backend_returns_german(self):
        paths = []
        def create(configuration):
            paths.append(configuration.database)
            return SimpleNamespace(memory=Memory(configuration.database), chat=Mock(side_effect=[
                {"text": "I am well, little keeper."}, {"text": "Zwei plus zwei ist vier."}]))
        with patch("sys.argv", ["conversation", "--check-english"]), \
                patch("marsi_local.config.load_env"), \
                patch("marsi_local.config.ServerConfig.from_env", return_value=ServerConfig()), \
                patch("marsi_local.core.Companion", side_effect=create), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(), 1)
        self.assertIn("[FAILED]", output.getvalue())
        self.assertNotIn("[PASS]", output.getvalue())
        self.assertNotIn("[CHECK COMPLETE]", output.getvalue())
        self.assertFalse(paths[0].exists())

    def test_diagnostic_does_not_mistake_an_english_recovery_notice_for_a_model_answer(self):
        paths = []
        llm = Mock()
        llm.chat.return_value = "Zwei plus zwei ist vier."
        def create(configuration):
            paths.append(configuration.database)
            return Companion(configuration, llm=llm)
        with patch("sys.argv", ["conversation", "--check-english"]), \
                patch("marsi_local.config.load_env"), \
                patch("marsi_local.config.ServerConfig.from_env", return_value=ServerConfig()), \
                patch("marsi_local.core.Companion", side_effect=create), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(), 1)
        self.assertIn("[FAILED]", output.getvalue())
        self.assertIn("in-character recovery notice", output.getvalue())
        self.assertNotIn("[PASS]", output.getvalue())
        self.assertNotIn("[CHECK COMPLETE]", output.getvalue())
        self.assertFalse(paths[0].exists())


if __name__ == "__main__":
    unittest.main()
