"""Check the installed speech decoder without downloading a Whisper model.

Run explicitly after installing requirements-server.txt; the ordinary stdlib
test suite does not require the optional speech packages.
"""
import io
import math
import struct
import unittest
import wave

import numpy as np
from faster_whisper.audio import decode_audio

from marsi_local.speech import validate_wav


class SpeechDecoderSmoke(unittest.TestCase):
    def test_pi_wav_decodes_to_whisper_samples(self):
        for rate in (16000, 48000):
            with self.subTest(rate=rate):
                samples = [int(8192 * math.sin(2 * math.pi * 440 * n / rate))
                           for n in range(rate)]
                output = io.BytesIO()
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    wav.writeframes(struct.pack(f"<{rate}h", *samples))
                data = output.getvalue()
                validate_wav(data)
                # This is the same BytesIO decoder path used by transcribe().
                audio = decode_audio(io.BytesIO(data), sampling_rate=16000)
                self.assertEqual(audio.dtype, np.float32)
                self.assertEqual(audio.shape, (16000,))
                self.assertTrue(np.isfinite(audio).all())
                self.assertGreater(float(np.sqrt(np.mean(audio ** 2))), 0.1)
                self.assertLess(float(np.max(np.abs(audio))), 0.3)


if __name__ == "__main__":
    unittest.main()
