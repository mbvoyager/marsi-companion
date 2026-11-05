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
from marsi_local.pi import main as pi_main


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
        self.display.link_online = True
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
        with patch.object(self.display.local, "snapshot", return_value={}):
            self.display.poll()
            self.pump_until(lambda: not self.display.polling)
        self.client.telemetry.assert_called_once_with({})
        self.client.journal.assert_not_called()

    def test_boot_retries_until_the_server_is_ready_and_preserves_the_draft(self):
        self.display.polling = self.display.restored = self.display.link_online = False
        self.client.telemetry.side_effect = [ClientError("Synthetic server booting"), {"pi": None, "server": None}]
        self.client.journal.return_value = {"entries": self.entries, "has_more": False}
        with patch.object(self.display.local, "snapshot", return_value={}):
            self.display.tick()
            self.assertEqual(self.display.link_status.get(), "[LINK] Connecting #1")
            self.pump_until(lambda: not self.display.polling)
            self.assertIn("Retry in", self.display.link_status.get())
            self.display.input.insert(0, "Draft during boot.")
            self.display.send_text()
            self.assertEqual(self.display.input.get(), "Draft during boot.")
            self.assertFalse(self.display.busy)
            self.pump_until(lambda: self.display.link_online)
        self.assertEqual(self.display.link_status.get(), "[LINK] Online")
        self.assertTrue(self.display.restored)
        self.assertIn(self.result["text"], self.content())
        self.assertEqual(self.client.telemetry.call_count, 2)
        self.client.chat.assert_not_called()
        self.assertEqual(self.display.input.get(), "Draft during boot.")

    def test_lost_link_keeps_the_archive_and_distinguishes_token_rejection(self):
        self.display.receive_entries(self.entries)
        self.display.polling = False
        self.client.telemetry.side_effect = ClientError("Synthetic rejected token", status=401)
        with patch.object(self.display.local, "snapshot", return_value={}):
            self.display.poll()
            self.pump_until(lambda: not self.display.polling)
        self.assertFalse(self.display.link_online)
        self.assertIn("Token rejected", self.display.link_status.get())
        self.assertIn(self.result["text"], self.content())
        self.assertGreater(self.display.next_poll_at - time.monotonic(), 8)
        self.client.journal.assert_not_called()


class DisplayStartupTests(unittest.TestCase):
    def test_reticle_is_reasserted_when_the_fullscreen_window_becomes_mapped(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"MARSI_PI_STATE_DIR": folder, "MARSI_RITUALS": "false"}):
            root = tk.Tk()
            root.withdraw()
            app = None
            mapped = []
            def simulate_map_reset(event):
                if event.widget is root:
                    mapped.append(True)
                    for widget in (root, app.input, app.reply, app.canvas, app.send, app.talk):
                        widget.configure(cursor="none")
            # A preceding mapping handler models the cursor being cleared
            # while the graphical session maps the initial fullscreen window.
            root.bind("<Map>", simulate_map_reset, add="+")
            app = Display(root, SimpleNamespace(session="synthetic-map"), windowed=True)
            app.polling = True
            root.geometry("800x480-20000+0")
            try:
                root.deiconify()
                root.update()
                self.assertTrue(mapped)
                for widget in (root, app.input, app.reply, app.canvas, app.send, app.talk):
                    self.assertEqual(widget.cget("cursor"), app.pointer_cursor)
                # The event binding coexists with existing root bindings.
                self.assertTrue(root.bind("<Configure>"))
            finally:
                for callback in root.tk.call("after", "info"):
                    root.after_cancel(callback)
                app.close()

    def test_reticle_is_installed_after_screen_preparation_can_reset_the_pointer(self):
        # Model a display wake-up that clears its cursor. This is a startup
        # regression test, not a claim to emulate a particular Pi GPU driver.
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"MARSI_PI_STATE_DIR": folder, "MARSI_RITUALS": "false",
                                        "MARSI_CURSOR": "native"}):
            root = tk.Tk()
            root.withdraw()
            screen = Mock()
            def wake(backend):
                root.configure(cursor="none")
                return None
            screen.start.side_effect = wake
            cursors = []
            def create(window, client, **kwargs):
                app = Display(window, client, **kwargs)
                app.polling = True
                root.geometry("800x480-20000+0")
                root.deiconify()
                def inspect():
                    for widget in (root, app.input, app.reply, app.canvas, app.send, app.talk):
                        cursors.append((str(widget.cget("cursor")), str(app.pointer_cursor)))
                    for callback in root.tk.call("after", "info"):
                        root.after_cancel(callback)
                    app.close()
                root.after(30, inspect)
                return app
            with patch("sys.argv", ["marsi_local.pi", "--windowed"]), \
                    patch("marsi_local.pi.load_env"), \
                    patch("tkinter.Tk", return_value=root), \
                    patch("marsi_local.pi.ScreenAwake", return_value=screen), \
                    patch("marsi_local.pi.Client.from_env", return_value=SimpleNamespace(session="synthetic-startup")), \
                    patch("marsi_local.pi.Display", side_effect=create), \
                    patch("marsi_local.pi.inspect_audio", return_value=SimpleNamespace(issues=[])), \
                    patch("marsi_local.pi.signal.signal"):
                pi_main()
            self.assertEqual(len(cursors), 6)
            for actual, expected in cursors:
                self.assertNotEqual(actual, "none")
                self.assertEqual(actual, expected)
            screen.start.assert_called_once()
            screen.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
