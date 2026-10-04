"""Lightweight Tk display + push-to-talk interface for the Raspberry Pi 3 B+."""
from __future__ import annotations

import argparse
import io
import os
import signal
import subprocess
import tempfile
import threading
import wave

from .client import Client
from .config import load_env


def record(stop: threading.Event, seconds=15) -> bytes:
    # RawInputStream needs no NumPy and keeps audio in memory only.
    import sounddevice as sd
    rate = int(os.getenv("MARSI_MIC_RATE", "16000"))
    if rate not in (16000, 22050, 44100, 48000):
        raise ValueError("MARSI_MIC_RATE must be 16000, 22050, 44100 or 48000")
    device = os.getenv("MARSI_MIC_DEVICE") or None
    if device and device.isdecimal():
        device = int(device)
    chunks, sample_bytes = [], 0

    def callback(data, frames, timing, status):
        nonlocal sample_bytes
        if not stop.is_set() and sample_bytes < rate * seconds * 2:
            block = bytes(data)[:rate * seconds * 2 - sample_bytes]
            chunks.append(block)
            sample_bytes += len(block)
        if sample_bytes >= rate * seconds * 2:
            stop.set()

    with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16", device=device, callback=callback):
        stop.wait(seconds)
        stop.set()
    if sample_bytes < rate // 5:
        raise ValueError("Recording was too short. Press Talk, speak, then press Finish.")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(chunks))
    return output.getvalue()


def play(audio: bytes, on_process=lambda process: None):
    # aplay receives only a local filename, never model-generated command text.
    device = os.getenv("MARSI_SPEAKER_DEVICE")
    with tempfile.TemporaryDirectory(prefix="marsi-") as folder:
        path = os.path.join(folder, "reply.wav")
        with open(path, "wb") as file:
            file.write(audio)
        command = ["aplay", "-q"] + (["-D", device] if device else []) + [path]
        with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
            on_process(process)
            try:
                if process.wait(timeout=120) != 0:
                    raise subprocess.CalledProcessError(process.returncode, command)
            except subprocess.TimeoutExpired:
                process.kill()
                raise
            finally:
                on_process(None)


# Preserve the public Display import used by existing callers.
from .display import Display


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env.pi")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--list-audio", action="store_true")
    args = parser.parse_args()
    load_env(args.env)
    if args.list_audio:
        import sounddevice
        print(sounddevice.query_devices())
        return
    import tkinter as tk
    root = tk.Tk()
    try:
        display = Display(root, Client.from_env(), windowed=args.windowed)
        signal.signal(signal.SIGTERM, lambda *_: root.after(0, display.close))
        root.mainloop()
    except (ValueError, tk.TclError) as error:
        root.destroy()
        parser.exit(1, f"Cannot open Marsi: {error}\n")
    except KeyboardInterrupt:
        display.close()


if __name__ == "__main__":
    main()
