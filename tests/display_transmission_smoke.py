"""Real Tk event-loop checks with delayed replies; no models, audio or network."""
from datetime import datetime
import os
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from marsi_local.client import ClientError
from marsi_local.display import Display


class DisplayTransmissionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        env = patch.dict(os.environ, {"MARSI_PI_STATE_DIR": self.folder.name,
                                      "MARSI_RITUALS": "false", "MARSI_SPEAK": "false"})
        env.start()
        self.addCleanup(env.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.client = SimpleNamespace(session="synthetic-display", chat=Mock(), journal=Mock(),
                                      telemetry=Mock(return_value={"pi": None, "server": None}),
                                      art=Mock(), sermon=Mock(), ritual=Mock())
        self.display = Display(self.root, self.client, windowed=True)
        self.display.polling = self.display.restored = True
        def close():
            if not self.display.closed:
                self.root.update_idletasks()
                for callback in self.root.tk.call("after", "info"):
                    self.root.after_cancel(callback)
                self.display.close()
        self.addCleanup(close)
        self.question = "A synthetic question from Terra."
        at = datetime.now().astimezone().isoformat()
        self.entries = [{"id": 10, "at": at, "kind": "chat", "role": "human", "text": self.question},
                        {"id": 11, "at": at, "kind": "chat", "role": "marsi", "text": "A little answer from Mars."}]
        self.result = {"text": self.entries[-1]["text"], "source": "qwen", "entries": self.entries}

    def content(self):
        return self.display.reply.get("1.0", "end")

    def pump_until(self, condition):
        deadline = time.monotonic() + 4
        while not condition():
            self.root.update()
            if time.monotonic() >= deadline:
                self.fail("Display did not finish the synthetic request")
            time.sleep(0.005)

    def delayed_send(self):
        release = threading.Event()
        self.addCleanup(release.set)
        def answer(*args):
            if not release.wait(4):
                raise ClientError("Synthetic test release timed out")
            return self.result
        self.client.chat.side_effect = answer
        self.display.input.insert(0, self.question)
        self.display.send_text()
        return release

    def test_send_echoes_before_server_reply_and_reconciles_a_page_already_in_flight(self):
        release = self.delayed_send()
        self.assertIn(self.question, self.content(), "Do not wait for a Tk tick or an HTTP reply")
        self.assertIn("ESTIMATE", self.content())
        self.assertTrue(self.display.busy)
        self.display.events.put(("archive", (self.display.generation,
                                            {"entries": self.entries, "has_more": False}, False, True)))
        self.display.tick()
        self.assertEqual(self.content().count(self.question), 1)
        self.assertNotIn(self.result["text"], self.content())
        self.display.input.insert(0, "Do not double-send.")
        self.display.send_text()
        release.set()
        self.pump_until(lambda: not self.display.busy)
        self.assertEqual(self.client.chat.call_count, 1)
        self.assertEqual(self.content().count(self.question), 1)
        self.assertEqual(self.content().count(self.result["text"]), 1)
        self.assertNotIn("ESTIMATE", self.content())
        self.assertEqual(self.display.cursor, 11)
        self.assertEqual(sorted(self.display.entries), [10, 11])
        # Subsequent polls cannot introduce another copy either.
        self.display.receive_entries(self.entries)
        self.assertEqual(self.content().count(self.question), 1)

    def test_latest_and_bounded_older_redraw_keep_the_pending_message_and_progress(self):
        release = self.delayed_send()
        self.display.jump_latest()
        self.assertEqual(self.content().count(self.question), 1)
        self.assertIn("ESTIMATE", self.content())
        at = self.entries[0]["at"]
        self.display.entries = {i: {"id": i, "at": at, "role": "marsi", "kind": "ritual", "text": "An old cog."}
                                for i in range(100, 701)}
        self.display.receive_entries([{"id": 99, "at": at, "role": "marsi", "kind": "ritual", "text": "An older cog."}], older=True)
        self.assertEqual(len(self.display.entries), 500)
        self.assertEqual(self.content().count(self.question), 1)
        self.assertEqual(self.content().count("ESTIMATE"), 1)
        self.display.update_progress(self.display.pending.started + 1000)
        self.assertIn("a longer thought", self.content())
        self.assertNotIn("100%", self.content())
        release.set()
        self.pump_until(lambda: not self.display.busy)
        self.assertNotIn("ESTIMATE", self.content())

    def test_failed_request_keeps_local_words_but_removes_progress_and_does_not_resend(self):
        self.client.chat.side_effect = ClientError("Synthetic unreachable forge")
        self.display.input.insert(0, self.question)
        self.display.send_text()
        self.pump_until(lambda: not self.display.busy)
        self.assertEqual(self.content().count(self.question), 1)
        self.assertIn("UNSEALED", self.content())
        self.assertNotIn("ESTIMATE", self.content())
        self.assertEqual(self.client.chat.call_count, 1)
        self.assertFalse(self.display.response_times.samples["chat"])

    def test_voice_placeholder_is_replaced_by_the_recognized_human_words(self):
        self.display.set_busy(True)
        self.display.events.put(("recorded", None))
        self.display.tick()
        self.assertIn("awaiting transcription", self.content())
        self.assertIn("ESTIMATE", self.content())
        self.display.events.put(("reply", dict(self.result, heard=self.question)))
        self.display.events.put(("done", None))
        self.display.tick()
        self.assertNotIn("awaiting transcription", self.content())
        self.assertNotIn("ESTIMATE", self.content())
        self.assertEqual(self.content().count(self.question), 1)

    def test_progress_finishes_when_the_reply_arrives_before_audio_playback_finishes(self):
        self.display.begin_transmission(self.question, "chat-voice")
        self.display.set_busy(True)
        self.display.events.put(("reply", self.result))
        self.display.events.put(("speaking", None))
        self.display.tick()
        self.assertTrue(self.display.busy)
        self.assertEqual(self.display.mode, "speaking")
        self.assertIsNone(self.display.pending)
        self.assertNotIn("ESTIMATE", self.content())
        self.assertEqual(len(self.display.response_times.samples["chat-voice"]), 1)

    def test_telemetry_still_refreshes_but_journal_fetches_wait_for_the_pending_request(self):
        self.display.begin_transmission(self.question, "chat")
        self.display.polling = False
        self.display.last_poll = time.monotonic()
        with patch.object(self.display.local, "snapshot", return_value={}):
            self.display.poll()
            self.pump_until(lambda: not self.display.polling)
        self.client.telemetry.assert_called_once_with({})
        self.client.journal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
