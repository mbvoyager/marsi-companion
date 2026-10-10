"""Pi audio adapters and a local, interactive check; no server or display needed."""
from __future__ import annotations

import argparse
from array import array
from dataclasses import dataclass, field
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

from .config import load_env

CHECK_COMMAND = ".venv-pi/bin/python -m marsi_local.audio --check"
MAX_PLAYBACK_BYTES = 8_000_000


class AudioError(ValueError):
    """An input or playback failure that is safe to display locally."""


def microphone_settings():
    rate = int(os.getenv("MARSI_MIC_RATE", "16000"))
    if rate not in (16000, 22050, 44100, 48000):
        raise ValueError("MARSI_MIC_RATE must be 16000, 22050, 44100 or 48000")
    device = os.getenv("MARSI_MIC_DEVICE") or None
    return (int(device) if device and device.isdecimal() else device), rate


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return output.getvalue()


def record(stop: threading.Event, seconds=15) -> bytes:
    # RawInputStream needs no NumPy; microphone data stays in memory.
    try:
        import sounddevice as sd
        device, rate = microphone_settings()
        chunks, sample_bytes, overflow = [], 0, False
        limit = int(rate * seconds) * 2

        def callback(data, frames, timing, status):
            nonlocal sample_bytes, overflow
            overflow |= bool(status.input_overflow)
            if not stop.is_set() and sample_bytes < limit:
                block = bytes(data)[:limit - sample_bytes]
                chunks.append(block)
                sample_bytes += len(block)
            if sample_bytes >= limit:
                stop.set()

        with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16", device=device, callback=callback):
            stop.wait(seconds)
            stop.set()
        if overflow:
            raise AudioError("Microphone lost audio samples. Close other recording apps and run the audio check.")
        if sample_bytes < rate // 5:
            raise AudioError("Recording was too short. Press Talk, speak, then press Finish.")
        return wav_bytes(b"".join(chunks), rate)
    except AudioError:
        raise
    except (ImportError, OSError, ValueError) as error:
        raise AudioError(f"Microphone could not open: {error}. Run {CHECK_COMMAND}") from error
    except Exception as error:
        # PortAudioError is imported only on machines with sounddevice installed.
        raise AudioError(f"Microphone recording failed: {error}. Run {CHECK_COMMAND}") from error


def playback_settings():
    try:
        buffer = int(os.getenv("MARSI_PLAYBACK_BUFFER_MS", "1000"))
        period = int(os.getenv("MARSI_PLAYBACK_PERIOD_MS", "100"))
    except ValueError as error:
        raise AudioError("Playback buffer and period must be whole milliseconds.") from error
    if not 100 <= buffer <= 2000 or not 10 <= period <= buffer // 2:
        raise AudioError("Playback buffer must be 100..2000 ms; period must be 10 ms..half the buffer.")
    return buffer, period


def play(audio: bytes, on_process=lambda process: None):
    device = os.getenv("MARSI_SPEAKER_DEVICE")
    buffer, period = playback_settings()
    # A private temporary directory is removed after playback, including on failure.
    try:
        with tempfile.TemporaryDirectory(prefix="marsi-") as folder:
            path = os.path.join(folder, "reply.wav")
            with open(path, "wb") as file:
                file.write(audio)
            command = ["aplay", "-q"] + (["-D", device] if device else []) + [
                f"--buffer-time={buffer * 1000}", f"--period-time={period * 1000}", path,
            ]
            # A file avoids deadlock on a full stderr pipe while keeping ALSA's error.
            with tempfile.TemporaryFile() as errors:
                with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors,
                                      env={**os.environ, "LC_ALL": "C"}) as process:
                    on_process(process)
                    try:
                        code = process.wait(timeout=120)
                    except subprocess.TimeoutExpired as error:
                        process.kill()
                        process.wait()
                        raise AudioError("Speaker playback timed out. Check the receiver's connection.") from error
                    finally:
                        on_process(None)
                    errors.seek(0)
                    detail = errors.read(8192).decode("utf-8", errors="replace").strip()
                    if code != 0:
                        raise AudioError(f"Speaker playback failed: {detail or 'aplay exit ' + str(code)}")
                    # ALSA can recover an underrun and still exit successfully.
                    # Surface those lost samples instead of reporting clean audio.
                    if re.search(r"\b(?:underrun|xrun)\b", detail, re.IGNORECASE):
                        raise AudioError("Speaker playback had buffer underruns (lost audio samples). "
                                         "Run the continuous playback check; see docs/audio-check.md.")
    except OSError as error:
        raise AudioError(f"Speaker could not open: {error}. Check alsa-utils and the audio device.") from error


def tone(seconds: int = 1) -> bytes:
    rate = 16000
    length = rate * seconds
    samples = array("h", (int(2600 * math.sin(2 * math.pi * 660 * i / rate)
                              * min(1, i / 320, (length - i) / 320)) for i in range(length)))
    if sys.byteorder != "little":
        samples.byteswap()
    return wav_bytes(samples.tobytes(), rate)


def wav_report(audio: bytes):
    """Describe PCM and quiet spans; a quiet span is not proof of an audio fault."""
    with wave.open(io.BytesIO(audio), "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() not in (1, 2) or wav.getcomptype() != "NONE":
            raise AudioError("The WAV check needs mono/stereo 16-bit PCM audio.")
        rate, channels, frames = wav.getframerate(), wav.getnchannels(), wav.getnframes()
        if not 8000 <= rate <= 192000 or not 0 < frames <= rate * 120:
            raise AudioError("Test WAV must be 0..120 seconds at 8..192 kHz.")
        raw = wav.readframes(frames)
    if len(raw) != frames * channels * 2:
        raise AudioError("The WAV file is truncated.")
    samples = array("h", raw)
    if sys.byteorder != "little":
        samples.byteswap()
    block = max(1, round(rate * .02)) * channels
    quiet, start = [], None
    for offset in range(0, len(samples), block):
        window = samples[offset:offset + block]
        rms = math.sqrt(sum(value * value for value in window) / len(window)) / 32768
        if rms < .001:
            if start is None:
                start = offset
        elif start is not None:
            if (offset - start) / channels / rate >= .8:
                quiet.append((start / channels / rate, offset / channels / rate))
            start = None
    if start is not None and (len(samples) - start) / channels / rate >= .8:
        quiet.append((start / channels / rate, frames / rate))
    return {"seconds": frames / rate, "rate": rate, "channels": channels, "quiet_spans": quiet}


def describe_wav(audio: bytes):
    info = wav_report(audio)
    print(f"WAV: {info['seconds']:.2f}s; {info['rate']} Hz; {info['channels']} channel(s); 16-bit PCM.")
    if info["quiet_spans"]:
        print("Quiet spans >= 0.8s (RMS below 0.1%): " + ", ".join(
            f"{start:.2f}..{end:.2f}s" for start, end in info["quiet_spans"][:20]))
    else:
        print("No quiet spans >= 0.8s at this threshold.")
    print("Quiet spans may be normal pauses. This measures the file, not speaker performance.")


def read_playback_wav(path: Path):
    with path.open("rb") as file:
        audio = file.read(MAX_PLAYBACK_BYTES + 1)
    if len(audio) > MAX_PLAYBACK_BYTES:
        raise AudioError("Test WAV exceeds 8 MB.")
    wav_report(audio)
    return audio


def recording_levels(audio: bytes):
    with wave.open(io.BytesIO(audio), "rb") as wav:
        rate = wav.getframerate()
        samples = array("h", wav.readframes(wav.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max((abs(value) for value in samples), default=0) / 32768
    rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples))) / 32768
    return len(samples) / rate, peak, rms


def query(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3,
                                encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AudioError(f"{command[0]} unavailable: {error}") from error
    if result.returncode:
        raise AudioError(f"{' '.join(command)}: {result.stderr.strip()[:500] or 'command failed'}")
    return result.stdout.strip()


@dataclass
class AudioReport:
    lines: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def inspect_routes(report: AudioReport, sinks, sources, cards, default_sink, default_source,
                   check_output=True, check_input=True):
    """Inspect only the selected bridge routes; SUSPENDED is normal while idle."""
    report.lines.append("Available outputs: " + (", ".join(node["name"] for node in sinks) or "(none)"))
    microphones = [node["name"] for node in sources if not node["name"].endswith(".monitor")
                   and node.get("monitor_of_sink_name") in (None, "", "n/a")]
    report.lines.append("Available microphones: " + (", ".join(microphones) or "(none)"))
    for kind, nodes, selected, enabled in (("Output", sinks, default_sink, check_output),
                                            ("Input", sources, default_source, check_input)):
        if not enabled:
            continue
        report.lines.append(f"{kind} route: {selected or '(none)'}")
        node = next((node for node in nodes if node.get("name") == selected), None)
        if not node:
            report.issues.append(f"No {kind.lower()} route is available. Connect the receiver or select the intended device.")
            continue
        report.lines.append(f"{kind}: {node.get('description', selected)}; state={node.get('state', '?')}; muted={node.get('mute', '?')}")
        if node.get("mute"):
            report.issues.append(f"{kind} is muted. Use pactl set-{'sink' if kind == 'Output' else 'source'}-mute @DEFAULT_{'SINK' if kind == 'Output' else 'SOURCE'}@ 0")
        volumes = [channel.get("value", 0) for channel in node.get("volume", {}).values()]
        if volumes and not any(volumes):
            report.issues.append(f"{kind} volume is zero. Raise the intended device's volume.")
        if kind == "Input" and (selected.endswith(".monitor") or node.get("monitor_of_sink_name") not in (None, "", "n/a")):
            report.issues.append("The selected input is a speaker monitor, not a microphone. Select a real input source.")
    bluez_cards = [card for card in cards if card.get("name", "").startswith("bluez_card.")]
    for card in bluez_cards:
        profile = card.get("active_profile", "?")
        report.lines.append(f"Bluetooth card: {card['name']}; profile={profile}")
        if check_input and str(profile).startswith("a2dp") and not any(
                source.get("name", "").startswith("bluez_input") for source in sources):
            report.lines.append("A2DP provides playback here; this receiver has no active Bluetooth microphone.")
    if bluez_cards and check_output and not default_sink.startswith("bluez_output"):
        report.lines.append("A Bluetooth device is present, but playback is routed elsewhere. Verify this is intentional.")
    if not bluez_cards:
        report.lines.append("No Bluetooth audio card is exposed. If using Bluetooth, check power, connection and WirePlumber.")


def inspect_audio() -> AudioReport:
    """Read-only readiness check: no recording, playback or configuration changes."""
    report = AudioReport()
    mic_name = ""
    mic_setting = os.getenv("MARSI_MIC_DEVICE", "")
    output = os.getenv("MARSI_SPEAKER_DEVICE", "")
    report.lines.append(f"Marsi settings: microphone={mic_setting or '(default)'}; speaker={output or '(default)'}; rate={os.getenv('MARSI_MIC_RATE', '16000')}")
    try:
        buffer, period = playback_settings()
        report.lines.append(f"Requested playback buffer={buffer} ms; period={period} ms (device negotiates actual values).")
    except AudioError as error:
        report.issues.append(str(error))
    try:
        import sounddevice as sd
        device, rate = microphone_settings()
        mic = sd.query_devices(device, "input")
        mic_name = mic["name"]
        report.lines.append(f"PortAudio input: {mic_name}; input channels={mic['max_input_channels']}")
        sd.check_input_settings(device=device, channels=1, dtype="int16", samplerate=rate)
    except Exception as error:
        report.issues.append(f"Microphone settings unavailable: {error}")
    try:
        devices = query(["aplay", "-L"])
        if output and output not in {line for line in devices.splitlines() if line and not line[0].isspace()}:
            # Explicit plughw/hw names are valid even when not individually listed.
            if not output.startswith(("plughw:", "hw:")):
                report.issues.append(f"ALSA playback device '{output}' is not listed by aplay -L.")
    except AudioError as error:
        report.issues.append(str(error))
    bridge_input = mic_name.casefold() in ("pipewire", "pulse", "default") or mic_setting in ("pipewire", "pulse")
    bridge_output = output in ("pipewire", "pulse", "default", "")
    if bridge_input or bridge_output:
        if shutil.which("pactl"):
            try:
                sinks = json.loads(query(["pactl", "--format=json", "list", "sinks"]))
                sources = json.loads(query(["pactl", "--format=json", "list", "sources"]))
                cards = json.loads(query(["pactl", "--format=json", "list", "cards"]))
                sink = query(["pactl", "get-default-sink"])
                source = query(["pactl", "get-default-source"])
                inspect_routes(report, sinks, sources, cards, sink, source, bridge_output, bridge_input)
            except (AudioError, ValueError, TypeError, KeyError) as error:
                report.issues.append(f"Audio service routes unavailable: {error}. Check pipewire, pipewire-pulse and wireplumber.")
        elif output in ("pipewire", "pulse") or mic_setting in ("pipewire", "pulse"):
            report.issues.append("pactl is missing. Install pulseaudio-utils to inspect PipeWire routes.")
    return report


def confirm(prompt):
    return input(prompt + " [y/N]: ").strip().casefold() in ("y", "yes")


def check_audio() -> bool:
    print("\n[VOX CHECK] Pi only; uses Marsi's audio settings. Close Marsi first. No Qwen or Whisper involved.")
    report = inspect_audio()
    for line in report.lines:
        print("  " + line)
    for issue in report.issues:
        print("[WARN] " + issue)
    if not sys.stdin.isatty():
        print("Run --check in an interactive terminal, or use --status for a silent report.")
        return False
    print("\n1. Speaker: set your speaker/headphone volume low. A one-second tone follows.")
    input("Press Enter when ready: ")
    output_ok = False
    try:
        play(tone())
        output_ok = confirm("Did you hear the tone on the intended speaker?")
        print("[OK] Speaker heard." if output_ok else "[FAIL] Tone was not heard. Check power, Bluetooth, route and volume.")
    except AudioError as error:
        print("[FAIL] " + str(error))
    print("\n2. Microphone: after Enter, say 'Marsi, the little machine is awake' for five seconds.")
    input("Press Enter to start recording: ")
    input_ok = False
    try:
        recording = record(threading.Event(), seconds=5)
        duration, peak, rms = recording_levels(recording)
        print(f"Captured {duration:.1f}s; peak={peak:.1%}; RMS={rms:.1%} (level, not speech recognition).")
        if peak < 0.002:
            print("[FAIL] Recording is almost silent. Check the selected source, mute and microphone power.")
        else:
            if peak > 0.98:
                print("[WARN] Recording may be clipping. Try reducing microphone volume.")
            print("Playing your recording back now...")
            play(recording)
            input_ok = confirm("Did you hear your own words clearly?")
            print("[OK] Microphone replay heard." if input_ok else "[FAIL] Replay did not contain clear speech. Check the real microphone source.")
    except AudioError as error:
        print("[FAIL] " + str(error))
    passed = output_ok and input_ok and not report.issues
    print("\n[PASS] Local audio works. Open Marsi and test a typed Voice reply, then F8." if passed else
          "\n[NOT READY] Fix the reported layer, then repeat this check. See docs/audio-check.md.")
    print("The sample was not sent to Ubuntu or retained; playback's temporary file was removed.")
    return passed


def check_playback():
    print("Continuous speaker test: 15 seconds, low-volume tone, no intended pauses.")
    print("Uses Marsi's configured speaker and buffer. No microphone, server or recording.")
    input("Lower the speaker volume, then press Enter: ")
    play(tone(15))
    heard = confirm("Did you hear one continuous tone without gaps?")
    print("[PASS] Continuous playback heard." if heard else
          "[NOT READY] Playback gaps are local to the Pi/audio path. See docs/audio-check.md.")
    return heard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env.pi")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="interactive tone, five-second recording and replay")
    mode.add_argument("--status", action="store_true", help="read-only routes and settings; no sound or recording")
    mode.add_argument("--check-playback", action="store_true", help="15-second continuous tone; no microphone or server")
    mode.add_argument("--play", type=Path, metavar="WAV", help="play a local PCM WAV using Marsi's actual speaker settings")
    mode.add_argument("--analyze", type=Path, metavar="WAV", help="inspect quiet spans in a local PCM WAV without playing it")
    args = parser.parse_args()
    try:
        load_env(args.env)
        if args.play or args.analyze:
            sample = read_playback_wav(args.play or args.analyze)
            describe_wav(sample)
            if args.play:
                play(sample)
            passed = True
        elif args.check_playback:
            passed = check_playback()
        elif args.check:
            passed = check_audio()
        else:
            report = inspect_audio()
            for line in report.lines:
                print(line)
            for issue in report.issues:
                print("[WARN] " + issue)
            print("Readiness only; use --check to verify audible sound and microphone replay.")
            passed = not report.issues
        return 0 if passed else 1
    except (EOFError, KeyboardInterrupt):
        print("\nAudio check cancelled.")
        return 1
    except ValueError as error:
        parser.exit(1, f"Audio settings error: {error}\n")
    except (OSError, wave.Error) as error:
        parser.exit(1, f"Audio file error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
