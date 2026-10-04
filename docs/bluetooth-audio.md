# Bluetooth audio on Raspberry Pi OS Lite

Run this guide **on the Raspberry Pi**, as the same user who runs Marsi.
Ubuntu still handles Qwen, Whisper and Piper. The Pi handles the Bluetooth link,
microphone recording and speaker playback.

The instructions below target Raspberry Pi OS **Bookworm or Trixie**. Check with
`cat /etc/os-release`. If your release is older, capture its name before changing
the audio setup. Close Marsi with Ctrl+Q during setup; reopen him after testing.
Bluetooth audio access is normally associated with the active local login.
For setup over SSH, use the version-specific option in step 2 below. The GUI
still starts from the Pi's physical console as described in the Pi setup guide.

## 1. Understand the receiver

For a receiver connected to an old speaker system, the expected arrangement is:

```text
Pi -- Bluetooth --> receiver -- AUX cable --> powered speaker system
                         |
                    USB supplies power
```

A label such as `5V 300mA` describes power requirements. It does not identify the
model or prove that the USB port carries audio. Leave the receiver powered from
its current USB supply if convenient; it must pair with the Pi for this route.
Keep its analogue output connected to the speaker system.

Playback and microphone support are separate capabilities. Ordinary Bluetooth
music playback uses **A2DP**; a typical receiver's built-in microphone needs a
**hands-free profile, HFP/HSP**. Bluetooth version 5.0 alone does not establish
microphone support. An AUX output is not automatically a microphone input.
PipeWire supports these profiles, but the receiver must support the appropriate
one too. See [WirePlumber's Bluetooth profiles](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html#monitor-properties).

Turn off your phone's Bluetooth temporarily so it does not reclaim the receiver.
If the receiver has a TX/RX switch, select RX. Put it into pairing mode using its
own instructions; button combinations differ between SONRU models.

## 2. Add the Pi's audio services

```bash
sudo apt update
sudo apt install -y bluez pipewire-audio pulseaudio-utils alsa-utils
sudo systemctl enable --now bluetooth
systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
pactl info
```

`pipewire-audio` installs the audio service, Bluetooth support, the ALSA bridge
and WirePlumber, which manages connections. The package is available in
[Bookworm](https://packages.debian.org/bookworm/pipewire-audio) and
[Trixie](https://packages.debian.org/trixie/pipewire-audio).
`pactl` controls PipeWire's PulseAudio-compatible service; we do not need a second
audio server. Its server information should mention PipeWire.

Run the user-service command and audio tests **without sudo**. If a command fails,
keep its error and stop there. If `pactl info` reports connection refused, inspect:

```bash
systemctl --user status pipewire pipewire-pulse wireplumber
```

### SSH or unattended operation: WirePlumber 0.5

If pairing succeeds but connecting reports `br-connection-profile-unavailable`,
check the audio packages and services above before changing settings. With
services running and the Bluetooth plugin installed, SSH without a local seat
session can leave Bluetooth audio profiles unavailable. Inspect:

```bash
wireplumber --version
loginctl list-sessions
```

For **WirePlumber 0.5.x**, the dedicated Marsi user's audio service can be allowed
to use Bluetooth without an active local login. This is the upstream
[headless Bluetooth configuration](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html#logind-integration).
Run as the same user who runs Marsi, without sudo:

```bash
cd ~/marsi-companion
git pull --ff-only
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cp deploy/wireplumber/51-marsi-bluetooth.conf ~/.config/wireplumber/wireplumber.conf.d/
systemctl --user restart wireplumber
systemctl --user is-active wireplumber
```

The included fragment sets `monitor.bluez.seat-monitoring` to `disabled` within
the main profile. It augments the distribution's settings through the documented
[configuration-fragment mechanism](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/conf_file.html#fragments).
After the service reports `active`, retry the receiver connection in step 3 and
check `pactl list short sinks`. If it still fails, keep the connection error and:

```bash
journalctl --user -u wireplumber -b --no-pager -n 60
```

For WirePlumber **0.4.x**, this fragment does not apply; use an active physical
console session for the initial test, or obtain instructions for that version.
Do not mix the older Lua configuration format with WirePlumber 0.5.

For an unattended Pi, optionally keep this user's services running after SSH
logout with `sudo loginctl enable-linger "$USER"`. This does not start the GUI;
its startup is configured separately in [the Pi guide](raspberry-pi.md).
To undo the 0.5 Bluetooth setting, remove only the file installed above and
restart WirePlumber:

```bash
rm ~/.config/wireplumber/wireplumber.conf.d/51-marsi-bluetooth.conf
systemctl --user restart wireplumber
```

## 3. Pair the receiver

Start the Bluetooth controller:

```bash
bluetoothctl
```

Inside its prompt, enter these commands one at a time:

```text
power on
agent on
default-agent
scan on
```

Wait for the receiver's advertised name and address. Match the name you normally
see on your phone; do not pair an unrelated nearby device. Replace
`AA:BB:CC:DD:EE:FF` below with **your receiver's address**, then enter:

```text
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
info AA:BB:CC:DD:EE:FF
scan off
quit
```

Follow any authentication prompt. The device information should show paired,
trusted and connected. Its service list may include Audio Sink and Handsfree;
the next step checks what the audio service can actually expose.
These operations are documented in [BlueZ's controller manual](https://manpages.debian.org/trixie/bluez/bluetoothctl.1.en.html).

If the controller says it is blocked, inspect `rfkill list`; `sudo rfkill unblock
bluetooth` clears a software block. If it reports no controller, keep that error
instead of continuing with pairing commands. If audio services are unavailable,
first check step 2, including its SSH option when applicable.

## 4. Test the speaker before Marsi's voice

```bash
pactl list short sinks
pactl list cards
```

A **sink** is an audio output. Find the receiver's `bluez_output...` sink name
and set it as the default, using its exact name instead of `YOUR_SINK_NAME`:

```bash
pactl set-default-sink YOUR_SINK_NAME
speaker-test -D pipewire -t sine -c 2 -l 1
```

Start with the speaker system's volume low. Expect a short tone from each
channel. This test checks the Pi-to-speaker path without involving Qwen or Piper.
The `-D pipewire` option uses the ALSA bridge installed above. Bluetooth devices
are managed by the audio service and may not appear in the hardware-only
`aplay -l` list. Use `aplay -L` to check for the `pipewire` bridge.

Default-output commands are documented in [pactl's manual](https://manpages.debian.org/trixie/pulseaudio-utils/pactl.1.en.html),
and the tone test in [speaker-test's manual](https://manpages.debian.org/bookworm/alsa-utils/speaker-test.1.en.html).

## 5. Check whether the receiver has a usable microphone

In `pactl list cards`, find the receiver's card name and its `Profiles` section.
An A2DP playback profile alone does not provide the usual hands-free microphone.
Look for an available profile described as **HFP/HSP** or **Headset Head Unit**,
with both a sink and a source. The exact name varies; copy what your Pi lists.

If such a profile exists, select it using the actual card and profile names:

```bash
pactl set-card-profile YOUR_CARD_NAME YOUR_HANDSFREE_PROFILE
pactl list short sinks
pactl list short sources
```

Switching profiles can change the sink names, so select the receiver's new output
as in step 4. Find its microphone source and select it:

```bash
pactl set-default-source YOUR_MICROPHONE_SOURCE_NAME
arecord -D pipewire -f S16_LE -r 16000 -c 1 -d 5 /tmp/marsi-mic-test.wav
aplay -D pipewire /tmp/marsi-mic-test.wav
```

Speak during the five-second recording. You should hear your own speech back.
Choose a real microphone source, **not** one ending in `.monitor`: a monitor
captures speaker output. The test file remains in `/tmp` until removed or cleared
by the OS. Delete it when finished with `rm /tmp/marsi-mic-test.wav`.

Hands-free mode typically sounds more like a telephone than stereo music. That
can still be useful for testing conversation. If no hands-free profile is
available, capture the card/profile output: the receiver may be playback-only,
or its microphone profile may not have connected. Do not assume software can
create a microphone that the hardware does not expose. You can still test spoken
replies using typed input, and add a separate microphone later.

## 6. Point Marsi at the audio bridge

```bash
cd ~/marsi-companion
.venv-pi/bin/python -m marsi_local.pi --list-audio
nano .env.pi
```

Set the speaker field to:

```text
MARSI_SPEAKER_DEVICE=pipewire
```

If the list shows `pipewire` with input channels, and the microphone test worked,
also set:

```text
MARSI_MIC_DEVICE=pipewire
MARSI_MIC_RATE=16000
```

Use the exact input name shown by the list. If the bridge is absent or has no
input channels, keep that output for diagnosis rather than guessing an index.
Save with Ctrl+O, Enter; exit with Ctrl+X. Restart Marsi from the physical console:

```bash
startx "$HOME/marsi-companion/deploy/marsi-xsession.sh" -- -nocursor
```

First enable **Voice** and type a short message. Then test **BLESS**. Finally,
if recording worked, press **TALK** or F8, speak, and press **FINISH** or F8.

If tones work but Marsi reports a voice-synthesis error, check Piper on Ubuntu
using step 4 of [the server guide](ubuntu-server.md). If Marsi reports speaker
playback failed, check the Pi's selected output and Bluetooth connection.

## After a restart

Power on the receiver before starting Marsi. Check that it reconnects and repeat
a short playback test. Trust stores the pairing; it does not guarantee every
receiver reconnects automatically. If needed, reconnect with
`bluetoothctl connect AA:BB:CC:DD:EE:FF`, using its real address.

Default outputs and profiles can be restored by the audio manager, but verify
them on your device. Once audio works, use the [feature checklist](test-checklist.md)
to test the rest of Marsi. These instructions have been checked against the
upstream documentation; the SONRU/Pi hardware tests must be performed on your
actual devices.
