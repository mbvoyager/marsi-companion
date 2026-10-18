"""Verify whole-WAV transport and the real Linux descriptor hand-off."""
import base64
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from marsi_local import audio
from marsi_local.audio_transfer import attach_audio, reply_audio


class AudioTransferTests(unittest.TestCase):
    def test_whole_wav_survives_encoding_and_checked_decoding(self):
        sample = audio.tone()
        result = {}
        attach_audio(result, sample)
        self.assertEqual(reply_audio(result, require_checksum=True), sample)
        self.assertEqual(result["audio_info"]["bytes"], len(sample))
        for changed in (sample[:-2], sample[:-2] + b"xx"):
            damaged = dict(result, audio_base64=base64.b64encode(changed).decode("ascii"))
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                reply_audio(damaged)

    def test_older_server_is_compatible_but_not_a_verified_diagnostic(self):
        sample = audio.tone()
        old = {"audio_base64": base64.b64encode(sample).decode("ascii")}
        self.assertEqual(reply_audio(old), sample)
        with self.assertRaisesRegex(ValueError, "Update and restart"):
            reply_audio(old, require_checksum=True)
        for bad in ({}, {"audio_base64": "!!"}, {"audio_base64": ""}):
            with self.assertRaises(ValueError):
                reply_audio(bad)

    def test_voice_check_downloads_once_and_replays_identical_bytes_without_recording(self):
        result = {"text": "A synthetic voice test."}
        sample = audio.tone()
        attach_audio(result, sample)
        with patch("marsi_local.client.Client.from_env") as factory, \
                patch("builtins.input", side_effect=["", "", "yes"]), \
                patch.object(audio, "play") as player, patch.object(audio, "record") as recorder, \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            factory.return_value.check_voice.return_value = result
            self.assertTrue(audio.check_voice())
        factory.return_value.check_voice.assert_called_once_with(None)
        self.assertEqual(player.call_count, 2)
        self.assertEqual(player.call_args_list[0].args[0], sample)
        self.assertIs(player.call_args_list[0].args[0], player.call_args_list[1].args[0])
        recorder.assert_not_called()
        self.assertIn("SHA-256 matches", output.getvalue())

    def test_voice_error_never_reaches_playback(self):
        with patch("marsi_local.client.Client.from_env") as factory, \
                patch.object(audio, "play") as player, patch("sys.stdout", new_callable=io.StringIO):
            factory.return_value.check_voice.return_value = {"voice_error": "No voice configured"}
            with self.assertRaisesRegex(audio.AudioError, "No voice configured"):
                audio.check_voice()
            player.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux" and hasattr(os, "memfd_create"), "Needs Linux memfd")
    def test_ram_wav_is_inherited_by_real_child_and_closed_after_failure(self):
        sample = audio.tone()
        with patch.object(audio.tempfile, "TemporaryDirectory", side_effect=AssertionError("No disk WAV")):
            with self.assertRaisesRegex(RuntimeError, "test cleanup"):
                with audio.playback_source(sample) as (path, options):
                    self.assertEqual(Path(path).read_bytes(), sample)
                    descriptor = options["pass_fds"][0]
                    child = subprocess.run([sys.executable, "-c",
                                            "import pathlib,sys; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())",
                                            path], capture_output=True, check=True, **options)
                    self.assertEqual(child.stdout, sample)
                    raise RuntimeError("test cleanup")
        with self.assertRaises(OSError):
            os.fstat(descriptor)


if __name__ == "__main__":
    unittest.main()
