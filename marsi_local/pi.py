"""Lightweight Tk display + push-to-talk interface for the Raspberry Pi 3 B+."""
from __future__ import annotations

import argparse
import signal
import threading

from .client import Client
from .config import load_env
from .audio import inspect_audio, play, record


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
        # Readiness is silent and runs off the UI thread. Explicit --check records.
        def readiness():
            report = inspect_audio()
            if report.issues:
                display.events.put(("audio_status", report.issues))
        threading.Thread(target=readiness, daemon=True).start()
        signal.signal(signal.SIGTERM, lambda *_: root.after(0, display.close))
        root.mainloop()
    except (ValueError, tk.TclError) as error:
        root.destroy()
        parser.exit(1, f"Cannot open Marsi: {error}\n")
    except KeyboardInterrupt:
        display.close()


if __name__ == "__main__":
    main()
