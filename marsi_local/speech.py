"""Optional CPU speech engines. Imports and model loading happen only when used."""
from __future__ import annotations

import argparse
import io
import logging
from pathlib import Path
import wave

from .config import ServerConfig, ROOT, load_env
from .core import ServiceError

MAX_AUDIO_BYTES = 2_000_000
MAX_AUDIO_SECONDS = 20
LOG = logging.getLogger("marsi.local.speech")


def validate_wav(data: bytes) -> None:
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("Recording exceeds 2 MB")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if (wav.getnchannels() != 1 or wav.getsampwidth() != 2
                    or wav.getframerate() not in (16000, 22050, 44100, 48000)
                    or wav.getcomptype() != "NONE"):
                raise ValueError("Use mono 16-bit PCM WAV at 16, 22.05, 44.1 or 48 kHz")
            frames = wav.getnframes()
            if not 0 < frames <= wav.getframerate() * MAX_AUDIO_SECONDS:
                raise ValueError("Recording must be 0..20 seconds long")
            if len(wav.readframes(frames)) != frames * 2:
                raise ValueError("Recording is truncated")
    except (wave.Error, EOFError) as error:
        raise ValueError("Invalid WAV recording") from error


class Speech:
    def __init__(self, config: ServerConfig):
        self.config = config
        self.whisper = None
        self.voice = None

    def load_whisper(self):
        if self.whisper is None:
            try:
                from faster_whisper import WhisperModel
                self.whisper = WhisperModel(
                    self.config.whisper_model, device="cpu", compute_type="int8",
                    cpu_threads=self.config.threads, num_workers=1,
                    download_root=str(ROOT / "models" / "whisper"),
                )
            except Exception as error:
                # Exception messages can contain private data; log only their type.
                LOG.error("Whisper model loading failed (%s)", type(error).__name__)
                raise ServiceError("Speech recognition unavailable. Install server speech packages and pre-download Whisper.") from error
        return self.whisper

    def transcribe(self, data: bytes, *, vad_filter: bool = True) -> str:
        validate_wav(data)
        try:
            segments, _ = self.load_whisper().transcribe(
                io.BytesIO(data), language=self.config.whisper_language,
                beam_size=1, vad_filter=vad_filter, condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except ServiceError:
            raise
        except Exception as error:
            LOG.error("Speech transcription failed (%s)", type(error).__name__)
            raise ServiceError("Speech recognition failed on Ubuntu. Check the server's speech diagnostics.") from error
        if not text:
            raise ServiceError("I did not catch any speech. Please try again.", 422)
        return text

    def check_recognition(self, *, no_vad: bool = False):
        """Exercise recognition with in-memory silence, without storing a turn."""
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 16000)
        audio = output.getvalue()
        stages = [(False, "Whisper transcription")]
        if not no_vad:
            stages.insert(0, (True, "WAV decoding and speech detection"))
        for vad_filter, label in stages:
            print(f"Checking {label.lower()}...", flush=True)
            try:
                self.transcribe(audio, vad_filter=vad_filter)
            except ServiceError as error:
                if error.status != 422:
                    raise
            # Silence can produce an empty result or a hallucinated transcript;
            # this tests engine execution, not recognition quality.
            print(f"{label} check passed.", flush=True)

    def synthesize(self, text: str) -> bytes:
        if not self.config.piper_model:
            raise ServiceError("No voice configured. Set MARSI_PIPER_MODEL to a downloaded .onnx voice.")
        try:
            if self.voice is None:
                from piper import PiperVoice
                self.voice = PiperVoice.load(str(self.config.piper_model))
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                self.voice.synthesize_wav(text, wav)
            audio = output.getvalue()
            if len(audio) > 8_000_000:
                raise ServiceError("Spoken reply was too long; the text is still available.")
            return audio
        except ServiceError:
            raise
        except Exception as error:
            raise ServiceError("Voice synthesis failed. Check Piper and its .onnx and .onnx.json files.") from error


def main():
    parser = argparse.ArgumentParser(description="Pre-load or diagnose Ubuntu's local speech engines")
    parser.add_argument("--env", default=".env.server")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-recognition", action="store_true",
                       help="Test decoding, speech detection and Whisper using in-memory silence")
    modes.add_argument("--transcribe", type=Path,
                       help="Transcribe a local test WAV and print the result; does not call Qwen")
    parser.add_argument("--no-vad", action="store_true",
                        help="Skip speech detection for a recognition diagnostic only")
    args = parser.parse_args()
    if args.no_vad and not (args.check_recognition or args.transcribe):
        parser.error("--no-vad requires --check-recognition or --transcribe")
    load_env(args.env)
    speech = Speech(ServerConfig.from_env())
    # Diagnostic failures retain their chained traceback in this explicitly
    # invoked terminal check. Routine server logs contain no exception text.
    if args.check_recognition:
        speech.check_recognition(no_vad=args.no_vad)
        return
    if args.transcribe:
        with args.transcribe.open("rb") as file:
            audio = file.read(MAX_AUDIO_BYTES + 1)
        print(speech.transcribe(audio, vad_filter=not args.no_vad))
        return
    speech.load_whisper()
    print("Whisper is cached locally.")
    if speech.config.piper_model:
        speech.synthesize("Beep boop. The tiny forge is ready.")
        print("Piper voice is ready.")


if __name__ == "__main__":
    main()
