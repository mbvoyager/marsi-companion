# Check the Pi's sound before opening Marsi

Use this page whenever the speaker or microphone stops working. Run the commands
**on the Pi, as the same user who runs Marsi, without sudo**. SSH works for this
check: sound comes from the Pi's attached speaker and microphone. Ubuntu does not
need to be running for these local tests.

## 1. Close Marsi and keep the receiver powered

Type `exit` or press Ctrl+Q in Marsi. From SSH, see
[how to stop the display](troubleshooting.md#pi-display-and-boot).
Keep the Bluetooth receiver's USB power connected and its speaker/headphones
connected. Temporarily turn off phone Bluetooth so the phone cannot reclaim it.
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

## 3. Restore Bluetooth audio if the check fails

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

## 4. Repeat the check, then start Marsi

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

Diagnostic output can contain device names and Bluetooth addresses. Review it
before posting publicly. Never post `.env.pi`, which also contains your token.
