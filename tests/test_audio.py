"""Test the real adapters and diagnostic decisions without Pi hardware."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from marsi_local import audio


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def fake_input(self, pcm, overflow=False):
        @contextmanager
        def stream(**settings):
            self.input_settings = settings
            settings["callback"](pcm, len(pcm) // 2, None, SimpleNamespace(input_overflow=overflow))
            yield
        return SimpleNamespace(RawInputStream=stream)

    def test_record_uses_configured_device_rate_and_caps_audio(self):
        os.environ.update(MARSI_MIC_DEVICE="7", MARSI_MIC_RATE="48000")
        pcm = struct.pack("<h", 3000) * (48000 * 6)
        with patch.dict(sys.modules, sounddevice=self.fake_input(pcm)):
            captured = audio.record(threading.Event(), seconds=5)
        self.assertEqual(self.input_settings["device"], 7)
        self.assertEqual(self.input_settings["samplerate"], 48000)
        duration, peak, rms = audio.recording_levels(captured)
        self.assertEqual(duration, 5)
        self.assertAlmostEqual(peak, 3000 / 32768)
        self.assertAlmostEqual(rms, peak)

    def test_record_reports_portaudio_failure_and_overflow(self):
        device = SimpleNamespace(RawInputStream=Mock(side_effect=RuntimeError("Invalid sample rate")))
        with patch.dict(sys.modules, sounddevice=device):
            with self.assertRaisesRegex(audio.AudioError, "Invalid sample rate"):
                audio.record(threading.Event())
        with patch.dict(sys.modules, sounddevice=self.fake_input(b"\0\0" * 16000, overflow=True)):
            with self.assertRaisesRegex(audio.AudioError, "lost audio samples"):
                audio.record(threading.Event(), seconds=1)

    def test_play_reports_alsa_error_and_removes_private_sample(self):
        os.environ["MARSI_SPEAKER_DEVICE"] = "pipewire"
        sample = audio.tone()
        callback = Mock()
        paths = []
        @contextmanager
        def process(command, stdout, stderr, env):
            self.assertEqual(command[:4], ["aplay", "-q", "-D", "pipewire"])
            self.assertIn("--buffer-time=1000000", command)
            self.assertIn("--period-time=100000", command)
            self.assertEqual(env["LC_ALL"], "C")
            paths.append(Path(command[-1]))
            self.assertEqual(paths[-1].read_bytes(), sample)
            stderr.write(b"ALSA: Unknown PCM pipewire")
            stderr.flush()
            yield SimpleNamespace(wait=lambda timeout: 1)
        with patch.object(audio.subprocess, "Popen", process):
            with self.assertRaisesRegex(audio.AudioError, "Unknown PCM pipewire"):
                audio.play(sample, callback)
        self.assertFalse(paths[0].exists())
        self.assertIsNone(callback.call_args.args[0])

    def test_recovered_underrun_is_not_silently_treated_as_success(self):
        os.environ.update(MARSI_SPEAKER_DEVICE="plughw:CARD=Test,DEV=0",
                          MARSI_PLAYBACK_BUFFER_MS="800", MARSI_PLAYBACK_PERIOD_MS="80")
        paths = []
        @contextmanager
        def process(command, stdout, stderr, env):
            paths.append(Path(command[-1]))
            self.assertIn("--buffer-time=800000", command)
            self.assertIn("--period-time=80000", command)
            stderr.write(b"underrun!!! (at least 124.000 ms long)\n")
            stderr.flush()
            yield SimpleNamespace(wait=lambda timeout: 0)
        with patch.object(audio.subprocess, "Popen", process):
            with self.assertRaisesRegex(audio.AudioError, "lost audio samples"):
                audio.play(audio.tone())
        self.assertFalse(paths[0].exists())

    def test_invalid_playback_buffer_never_opens_a_device(self):
        for buffer, period in (("text", "100"), ("99", "10"), ("1000", "600")):
            os.environ.update(MARSI_PLAYBACK_BUFFER_MS=buffer, MARSI_PLAYBACK_PERIOD_MS=period)
            with patch.object(audio.subprocess, "Popen") as player:
                with self.assertRaises(audio.AudioError):
                    audio.play(audio.tone())
                player.assert_not_called()

    def test_wave_report_distinguishes_file_silence_from_continuous_audio(self):
        active = struct.pack("<h", 3000) * 16000
        sample = audio.wav_bytes(active + b"\0\0" * 16000 + active, 16000)
        info = audio.wav_report(sample)
        self.assertEqual(info["seconds"], 3)
        self.assertEqual(info["quiet_spans"], [(1, 2)])
        self.assertEqual(audio.wav_report(audio.tone(15))["quiet_spans"], [])
        with self.assertRaisesRegex(audio.AudioError, "truncated"):
            audio.wav_report(sample[:-100])

    def test_continuous_check_does_not_record_or_contact_the_server(self):
        with patch("builtins.input", side_effect=["", "yes"]), \
                patch.object(audio, "play") as player, patch.object(audio, "record") as recorder, \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertTrue(audio.check_playback())
        info = audio.wav_report(player.call_args.args[0])
        self.assertEqual(info["seconds"], 15)
        self.assertEqual(info["quiet_spans"], [])
        recorder.assert_not_called()

    def test_local_wav_cli_uses_the_same_playback_adapter(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.wav"
            path.write_bytes(audio.tone())
            with patch.object(sys, "argv", ["audio", "--play", str(path)]), \
                    patch.object(audio, "play") as player, patch.object(audio, "record") as recorder, \
                    patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(audio.main(), 0)
            player.assert_called_once_with(path.read_bytes())
            recorder.assert_not_called()

    def test_play_timeout_kills_process_and_clears_handle(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("aplay", 120), 0]
        callback = Mock()
        with patch.object(audio.subprocess, "Popen") as factory:
            factory.return_value.__enter__.return_value = process
            with self.assertRaisesRegex(audio.AudioError, "timed out"):
                audio.play(audio.tone(), callback)
        process.kill.assert_called_once()
        self.assertIsNone(callback.call_args.args[0])

    def routes(self, source="bluez_input.TEST", profile="headset-head-unit", mute=False):
        return ([{"name": "bluez_output.TEST", "description": "Test receiver", "state": "SUSPENDED", "mute": mute,
                  "volume": {"mono": {"value": 32768}}}],
                [{"name": source, "state": "SUSPENDED", "mute": False, "monitor_of_sink_name": None}],
                [{"name": "bluez_card.TEST", "active_profile": profile}])

    def test_idle_bluetooth_is_ready_but_muted_output_is_not(self):
        report = audio.AudioReport()
        audio.inspect_routes(report, *self.routes(), "bluez_output.TEST", "bluez_input.TEST")
        self.assertEqual(report.issues, [])
        audio.inspect_routes(report, *self.routes(mute=True), "bluez_output.TEST", "bluez_input.TEST")
        self.assertIn("Output is muted", report.issues[0])

    def test_monitor_and_missing_input_are_flagged(self):
        report = audio.AudioReport()
        audio.inspect_routes(report, *self.routes(source="bluez_output.TEST.monitor", profile="a2dp-sink"),
                             "bluez_output.TEST", "bluez_output.TEST.monitor")
        self.assertTrue(any("monitor, not a microphone" in issue for issue in report.issues))
        self.assertTrue(any("A2DP" in line for line in report.lines))
        report = audio.AudioReport()
        audio.inspect_routes(report, self.routes()[0], [], [], "bluez_output.TEST", "")
        self.assertTrue(any("No input route" in issue for issue in report.issues))

    def test_usb_input_does_not_warn_about_unused_monitor_route(self):
        report = audio.AudioReport()
        audio.inspect_routes(report, *self.routes(source="speaker.monitor"),
                             "bluez_output.TEST", "speaker.monitor", check_input=False)
        self.assertFalse(report.issues)

    def test_inspection_is_read_only_and_handles_missing_service(self):
        os.environ.update(MARSI_MIC_DEVICE="pipewire", MARSI_SPEAKER_DEVICE="pipewire")
        sd = SimpleNamespace(query_devices=Mock(return_value={"name": "pipewire", "max_input_channels": 64}),
                             check_input_settings=Mock())
        def query(command):
            if command == ["aplay", "-L"]:
                return "pipewire\n    PipeWire Sound Server"
            raise audio.AudioError("Connection refused")
        with patch.dict(sys.modules, sounddevice=sd), patch.object(audio.shutil, "which", return_value="pactl"), \
                patch.object(audio, "query", side_effect=query) as commands, patch.object(audio, "record") as record, \
                patch.object(audio, "play") as play:
            report = audio.inspect_audio()
        self.assertTrue(any("Connection refused" in issue for issue in report.issues))
        record.assert_not_called()
        play.assert_not_called()
        self.assertTrue(all("list" in call.args[0] or call.args[0][0] == "aplay" for call in commands.call_args_list))

    def test_inspection_reads_actual_default_routes(self):
        os.environ.update(MARSI_MIC_DEVICE="pipewire", MARSI_SPEAKER_DEVICE="pipewire")
        sinks, sources, cards = self.routes()
        replies = {"sinks": json.dumps(sinks), "sources": json.dumps(sources), "cards": json.dumps(cards),
                   "get-default-sink": "bluez_output.TEST", "get-default-source": "bluez_input.TEST", "-L": "pipewire"}
        sd = SimpleNamespace(query_devices=lambda *args: {"name": "pipewire", "max_input_channels": 1},
                             check_input_settings=Mock())
        with patch.dict(sys.modules, sounddevice=sd), patch.object(audio.shutil, "which", return_value="pactl"), \
                patch.object(audio, "query", side_effect=lambda command: replies[command[-1]]):
            report = audio.inspect_audio()
        self.assertFalse(report.issues)
        self.assertTrue(any("headset-head-unit" in line for line in report.lines))

    def interactive(self, responses, sample):
        with patch.object(audio, "inspect_audio", return_value=audio.AudioReport()), \
                patch.object(audio.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", side_effect=responses), patch.object(audio, "play") as play, \
                patch.object(audio, "record", return_value=sample) as record, \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            passed = audio.check_audio()
        return passed, output.getvalue(), play, record

    def test_check_requires_heard_tone_and_own_words(self):
        passed, output, play, record = self.interactive(["", "yes", "", "yes"], audio.tone())
        self.assertTrue(passed)
        self.assertEqual(play.call_count, 2)
        self.assertEqual(record.call_args.kwargs["seconds"], 5)
        self.assertIn("[PASS]", output)
        passed, output, _, _ = self.interactive(["", "no", "", "yes"], audio.tone())
        self.assertFalse(passed)
        self.assertNotIn("[PASS]", output)

    def test_silent_recording_does_not_pass_or_replay(self):
        passed, output, play, _ = self.interactive(["", "yes", ""], audio.wav_bytes(b"\0\0" * 80000, 16000))
        self.assertFalse(passed)
        self.assertEqual(play.call_count, 1)
        self.assertIn("almost silent", output)


if __name__ == "__main__":
    unittest.main()
