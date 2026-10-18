"""Linux real aplay check against ALSA's silent null device, not a speaker."""
import os
import shutil
import sys
import unittest
from unittest.mock import patch

from marsi_local.audio import play, wav_bytes
from marsi_local.audio_transfer import attach_audio, reply_audio


@unittest.skipUnless(sys.platform == "linux" and shutil.which("aplay"), "Needs Linux and alsa-utils")
class AlsaPlaybackSmoke(unittest.TestCase):
    def test_transferred_pcm_plays_from_ram_at_speech_and_device_rates(self):
        for rate in (16000, 22050, 48000):
            with self.subTest(rate=rate):
                sample = wav_bytes(b"\0\0" * rate, rate)
                result = {}
                attach_audio(result, sample)
                decoded = reply_audio(result, require_checksum=True)
                with patch.dict(os.environ, {"MARSI_SPEAKER_DEVICE": "null"}), \
                        patch("marsi_local.audio.tempfile.TemporaryDirectory",
                              side_effect=AssertionError("Audio must not use a disk WAV")):
                    play(decoded)


if __name__ == "__main__":
    unittest.main()
