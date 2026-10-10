# Check the Pi's sound before opening Marsi

Use this page whenever the speaker or microphone stops working. Run the commands
**on the Pi, as the same user who runs Marsi, without sudo**. SSH works for this
check: sound comes from the Pi's attached speaker and microphone. Ubuntu does not
need to be running for these local tests.

## 1. Close Marsi and keep the audio device connected

Type `exit` or press Ctrl+Q in Marsi. From SSH, see
[how to stop the display](troubleshooting.md#pi-display-and-boot).
For a USB speakerphone, keep its USB data cable connected to the Pi. For Bluetooth,
keep the receiver's power and speaker/headphones connected. Temporarily turn off
phone Bluetooth so the phone cannot reclaim the receiver.
Start with a low speaker volume.

Update the Pi's checkout, preserving your existing `.env.pi`:

```bash
cd ~/marsi-companion
git pull --ff-only
.venv-pi/bin/python -m marsi_local.audio --check
```

No new Python packages are needed if Marsi's Pi environment is already installed.
The check loads `.env.pi` and uses **the same recording and playback code as the
display**. If you use another settings file, add `--env PATH_TO_YOUR_SETTINGS`.
An exported `MARSI_...` setting takes precedence over the file, as it does in Marsi.

## 2. Follow the test prompts

The first part lists Marsi's device settings and, when using PipeWire, its actual
default output and input. It reports unavailable services, missing devices,
muting, zero volume, and an input that is a speaker monitor. `SUSPENDED` by itself
is normal while a device is idle.

1. Press Enter to play a one-second tone. Answer `y` only if you heard it through
   the speaker/headphones you intended to use.
2. Press Enter again, then speak for five seconds. The check prints the recorded
   duration and signal levels, then plays your recording back. Answer `y` only if
   you hear your own words clearly.
3. `[PASS]` means both local paths worked and the readiness check found no issues.
   `[NOT READY]` means a test or readiness warning needs attention. Keep the output
   to help identify the failing layer.

This test does not transcribe speech, contact Ubuntu, change audio settings or
pair devices. The microphone sample stays in memory except for a private
temporary playback file, which is removed after playback. It does not enter
Marsi's conversation archive.

For a silent report without recording or playback, run:

```bash
.venv-pi/bin/python -m marsi_local.audio --status
```

This reports readiness only; it cannot prove a speaker is audible or a microphone
contains speech. The display performs this silent check in the background at
startup and adds warnings to its local terminal view. It remains usable by typing
if audio is unavailable. Starting Marsi does not play a test tone or record you.

## 3. USB speakerphones

List the USB device on both playback and capture sides:

```bash
aplay -l
arecord -l
```

An AIRHUG 06 may appear as card `A06`, device `0`. Use your actual output. If
Marsi uses `pipewire` for both devices, check that its defaults point to the
USB speaker and real microphone, rather than HDMI or an old Bluetooth receiver:

```bash
pactl get-default-sink
pactl get-default-source
pactl list short sinks
pactl list short sources
```

An input ending in `.monitor` records speaker output. The real USB microphone
normally starts with `alsa_input.usb-`. Use the actual names from your output
with `pactl set-default-sink` and `pactl set-default-source` if needed. Do not
change working routes simply because their idle state says `SUSPENDED`.

For direct ALSA playback, use a **card ID** instead of a number that can change
after reboot. For example, `plughw:CARD=A06,DEV=0` selects this card and allows
ALSA to convert Piper's sample rate to a format the USB device supports. Direct
playback is also a useful comparison if the PipeWire route has breaks; see below.
Keep the microphone setting unchanged while testing the speaker.

## 4. Restore Bluetooth audio if the check fails

First inspect the services and receiver:

```bash
systemctl --user status pipewire pipewire-pulse wireplumber --no-pager
bluetoothctl devices
pactl list short sinks
pactl list short sources
pactl list cards
```

If the audio services are installed but failed, restart them, then reconnect the
receiver. Replace `YOUR_RECEIVER_ADDRESS` with the address from `bluetoothctl
devices`; do not type the placeholder literally:

```bash
systemctl --user restart pipewire pipewire-pulse wireplumber
bluetoothctl connect YOUR_RECEIVER_ADDRESS
bluetoothctl info YOUR_RECEIVER_ADDRESS
```

If connection fails with `br-connection-profile-unavailable`, follow
[the Bluetooth guide's audio-service and SSH setup](bluetooth-audio.md#2-add-the-pis-audio-services).
If the controller is blocked, inspect `rfkill list` before proceeding. A receiver
that loses USB power loses its Bluetooth connection too; start by restoring power.
Trusting/pairing does not guarantee reconnection after every power cycle.

If the receiver connects but its microphone is missing, inspect `pactl list cards`.
For a receiver with a built-in microphone, select an available **HFP/HSP / Headset
Head Unit** profile with both a sink and a source. An A2DP profile provides music
playback here; it does not provide the usual hands-free microphone. Copy the
actual card and profile names from your output:

```bash
pactl set-card-profile YOUR_CARD_NAME YOUR_HANDSFREE_PROFILE
pactl list short sinks
pactl list short sources
```

A profile change may create different output names. Choose the receiver's current
`bluez_output...` sink and its real `bluez_input...` microphone source. A source
ending in `.monitor` records speaker output. Replace the placeholders below with
the names shown by your Pi:

```bash
pactl set-default-sink YOUR_OUTPUT_NAME
pactl set-default-source YOUR_MICROPHONE_NAME
pactl set-sink-mute @DEFAULT_SINK@ 0
pactl set-source-mute @DEFAULT_SOURCE@ 0
pactl set-sink-volume @DEFAULT_SINK@ 50%
pactl set-source-volume @DEFAULT_SOURCE@ 100%
```

These commands select and unmute the routes for the current user; start low and
adjust speaker volume as needed. Names, profiles and volume controls are described
in [pactl's manual](https://manpages.debian.org/trixie/pulseaudio-utils/pactl.1.en.html).
For microphone profile and headless access details, see
[WirePlumber's Bluetooth configuration](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html).

For the PipeWire Bluetooth path, check the following fields in `.env.pi` with
`nano .env.pi`. Edit these fields only, preserving the server URL, token and
other settings:

```text
MARSI_SPEAKER_DEVICE=pipewire
MARSI_MIC_DEVICE=pipewire
MARSI_MIC_RATE=16000
```

Use `pipewire` for the microphone only if the Pi lists it as an input-capable
device. List devices with `.venv-pi/bin/python -m marsi_local.pi --list-audio`.
If the selected microphone rejects 16 kHz, try `MARSI_MIC_RATE=48000` and repeat
the check. USB microphones may use a different name or index. Device selection
and supported-rate checking use the
[sounddevice hardware API](https://python-sounddevice.readthedocs.io/en/0.5.3/api/checking-hardware.html).

## 5. Repeat the check, then start Marsi

```bash
.venv-pi/bin/python -m marsi_local.audio --check
```

After it passes, open the display using [quickstart](quickstart.md#3-start-the-display-manually).
Enable **Voice**, send a typed sentence, and listen to Marsi's reply. Then use
**F8 / Talk**, speak and press **F8 / Finish**.

If local audio passes but a typed Voice reply fails, preserve the display's
`[VOX]` error: voice generation runs on Ubuntu, while playback runs on the Pi.
If microphone replay passes but recognition fails, use
[Ubuntu's speech diagnostics](ubuntu-server.md#speech-recognition-fails-after-the-microphone-test-passes).
Those server failures do not require re-pairing a receiver that passes the local
test. Repeat the local check after reboot or a receiver power cycle if audio
stops working again.

## 6. Breaks or stuttering during speech

The server sends a complete WAV before the Pi starts playback. A slow Qwen
response or LAN transfer delays the start; it does not feed this player a word
at a time. Test the generated file and the local playback route separately.

### First, test continuous sound on the Pi

Close Marsi, lower the speaker volume, then run:

```bash
cd ~/marsi-companion
.venv-pi/bin/python -m marsi_local.audio --check-playback
```

This plays **15 seconds of one continuous tone**, with no intended gaps. It
uses Marsi's speaker settings and does not record, use Qwen or contact Ubuntu.
If this tone breaks, the interruption is in the Pi/audio path.

For a USB card listed as `A06`, compare direct USB playback without editing
`.env.pi`:

```bash
MARSI_SPEAKER_DEVICE=plughw:CARD=A06,DEV=0 .venv-pi/bin/python -m marsi_local.audio --check-playback
```

If it reports `Device or resource busy`, PipeWire or another application may
still own the USB device. Stop playback/recording applications and wait a few
seconds for idle devices to release. If needed, temporarily run the commands
below, test direct playback, then restore the audio services. Do this with Marsi
closed; it interrupts PipeWire audio for your user:

```bash
systemctl --user stop wireplumber pipewire-pulse.service pipewire-pulse.socket pipewire.service pipewire.socket
MARSI_SPEAKER_DEVICE=plughw:CARD=A06,DEV=0 .venv-pi/bin/python -m marsi_local.audio --check-playback
systemctl --user start pipewire.socket pipewire-pulse.socket wireplumber.service
```

Only use that service sequence when you installed PipeWire. If direct USB is
continuous while PipeWire breaks, either investigate PipeWire's scheduling or
set **only** `MARSI_SPEAKER_DEVICE=plughw:CARD=A06,DEV=0` in `.env.pi`. Keep the
working microphone route and repeat the full recording/replay check afterward.

Marsi now requests a 1000 ms playback buffer and 100 ms period. The device
negotiates the actual values, which can be smaller. Existing `.env.pi` files get
these defaults without editing. Override them only when comparing settings:

```text
MARSI_PLAYBACK_BUFFER_MS=1000
MARSI_PLAYBACK_PERIOD_MS=100
```

A larger buffer can tolerate scheduling delays and can add startup latency. It
cannot repair gaps already present in the WAV or a disconnecting USB device.
ALSA can recover from a buffer underrun and return success; Marsi now reports
that interruption instead of silently treating it as clean playback. The
[aplay manual](https://manpages.debian.org/trixie/alsa-utils/aplay.1.en.html)
documents buffering and recovery. No resampling is forcibly disabled.

If both playback routes break, inspect the Pi while testing:

```bash
vcgencmd get_throttled
top
journalctl -k -b --no-pager | tail -n 60
journalctl --user -u pipewire -u wireplumber -n 60 --no-pager
```

`throttled=0x0` means no power/thermal throttling flags are set at the time of
the check. USB disconnect/reset messages point to the USB connection, cable or
power path. Test another data cable/port if those messages occur. Preserve the
actual output before changing system-wide settings.

### Then, compare the original voice WAV

Run **on Ubuntu**, while not requesting another voiced reply:

```bash
cd ~/marsi-companion
git pull --ff-only
.venv-server/bin/python -m marsi_local.speech --synthesize data/voice-check.wav
```

This generates three short English sentences through your configured Piper
voice, saves the exact WAV, and reports its duration and quiet spans. It does
not run Whisper or Qwen and does not read/change your conversation journal.
Use `--text "YOUR TEST SENTENCE"` to test wording that showed the problem.
The output is private and excluded from Git. The command refuses to overwrite
an existing file; remove only `data/voice-check.wav` when deliberately repeating
the diagnostic. Use text in the installed voice's language for the baseline.

Copy that file from Ubuntu to **the Pi**. Replace the two placeholders below
with your Ubuntu login and reachable server address:

```bash
cd ~/marsi-companion
scp YOUR_UBUNTU_USER@YOUR_SERVER_IP:~/marsi-companion/data/voice-check.wav data/voice-check.wav
.venv-pi/bin/python -m marsi_local.audio --play data/voice-check.wav
```

Also listen to the same file on another computer/player if available. Quiet
spans measured in the file may be ordinary sentence pauses; they are not proof
of failure. If the same long breaks occur at the same points in another player,
inspect the wording, voice language and Piper output. If they occur only on the
Pi, continue investigating playback. This avoids guessing and cutting normal
pauses out of speech. Delete the diagnostic WAV on both machines when finished.

Diagnostic output can contain device names and Bluetooth addresses. Review it
before posting publicly. Never post `.env.pi`, which also contains your token.
