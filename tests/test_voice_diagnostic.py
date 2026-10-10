"""A source-WAV diagnostic must not need Whisper, Qwen or the normal journal."""
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from marsi_local.audio import tone
from marsi_local import speech


class VoiceDiagnosticTests(unittest.TestCase):
    def test_synthesis_saves_private_pcm_without_loading_recognition(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data" / "voice-check.wav"
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(sys, "argv", ["speech", "--synthesize", str(path), "--text", "A test sentence."]), \
                    patch.object(speech, "Speech") as factory, \
                    patch("sys.stdout", new_callable=io.StringIO) as output:
                factory.return_value.synthesize.return_value = tone()
                speech.main()
            self.assertEqual(path.read_bytes(), tone())
            factory.return_value.synthesize.assert_called_once_with("A test sentence.")
            factory.return_value.load_whisper.assert_not_called()
            self.assertIn("No Qwen request or journal entry", output.getvalue())
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_diagnostic_refuses_to_overwrite_an_existing_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.wav"
            path.write_bytes(b"existing private sample")
            with patch.object(sys, "argv", ["speech", "--synthesize", str(path)]), \
                    patch.object(speech, "Speech") as factory:
                factory.return_value.synthesize.return_value = tone()
                with self.assertRaises(FileExistsError):
                    speech.main()
            self.assertEqual(path.read_bytes(), b"existing private sample")


if __name__ == "__main__":
    unittest.main()
