# Raspberry Pi 3 B+: Marsi's little body

Use Raspberry Pi OS Lite **64-bit** for the smallest practical installation.
The [official OS page](https://www.raspberrypi.com/software/operating-systems/)
lists the 3 B+ as compatible. A minimal X11 session will display the Tkinter app.
A desktop edition also works, but consumes more of the Pi's 1 GB RAM.

Use Raspberry Pi Imager to configure your username, Wi-Fi, and SSH while writing
the card. The display's connection type may need its manufacturer's setup; an
HDMI display is the simplest initial test. Custom firmware is unnecessary.

Before testing a conversation from the Pi, complete steps 1–4 of the
**[Ubuntu server guide](ubuntu-server.md)** and its server preparation in step 5.
Leave Marsi running on Ubuntu with `--host 0.0.0.0`, and have the server's LAN
address and `MARSI_TOKEN` ready. You can install the Pi's operating system and
interface before that, but the connection test needs the server to be ready.

## 1. Install the interface

On the Pi, through SSH or its console:

```bash
sudo apt update
sudo apt install -y git nano python3 python3-venv python3-tk libportaudio2 alsa-utils
# For Lite only: add a small graphical session.
sudo apt install -y xserver-xorg xinit openbox
cd ~
git clone https://github.com/mbvoyager/marsi-companion.git
cd marsi-companion
bash scripts/setup-pi.sh
```

The Pi installs only a small microphone library; all model inference stays on Ubuntu.
Git is included in the package installation above so the Pi can download and
update its copy of the project.

The setup script creates **`~/marsi-companion/.env.pi` on the Pi**. This is a
hidden file because its name starts with a dot. Open it on the Pi:

```bash
nano ~/marsi-companion/.env.pi
```

Set `MARSI_SERVER_URL` to the Ubuntu machine's actual LAN address and copy the
`MARSI_TOKEN` value from **`~/marsi-companion/.env.server` on Ubuntu**. Replace
the existing values in these two fields; keep the other settings:

```text
MARSI_SERVER_URL=http://YOUR_SERVER_IP:8765
MARSI_TOKEN=THE_TOKEN_FROM_UBUNTU
```

Use the real address and token in place of the placeholders. In nano, Ctrl+O
followed by Enter saves; Ctrl+X exits. Both devices must be on a reachable LAN.
If Ubuntu's firewall is enabled, allow the Pi's address as described in step 5
of the Ubuntu guide before testing the connection.

First verify the connection without a display:

```bash
.venv-pi/bin/python -m marsi_local.client
```

Type a message and receive a Qwen answer. If this fails, fix the address, token,
server process, or firewall before troubleshooting audio. `/quit` exits.

## 2. Test the microphone and speaker before opening Marsi

For a **Bluetooth receiver or headset**, follow the
[Bluetooth audio guide](bluetooth-audio.md) first. Lite needs audio services to
bridge Bluetooth to Marsi's recording and playback. A receiver may support
speaker output without exposing a microphone; test those separately. Return
here once the local playback and, if available, recording tests succeed.

Attach a microphone and speaker/headphones. The Pi 3 B+ has no built-in microphone.
A USB microphone or USB sound card is a straightforward starting point.

```bash
.venv-pi/bin/python -m marsi_local.pi --list-audio
arecord -l
aplay -l
```

Set `MARSI_MIC_DEVICE` to the input device's index or name if the default is wrong.
We request mono 16-bit input at 16 kHz. If the microphone does not support that
rate, try `MARSI_MIC_RATE=48000`; the server also accepts 22.05 and 44.1 kHz.

Set `MARSI_SPEAKER_DEVICE` to an ALSA playback name such as `plughw:1,0` when
needed. Use the number actually reported on your Pi. With Marsi closed, run:

```bash
.venv-pi/bin/python -m marsi_local.audio --check
```

This works through SSH as well as the local console and loads `.env.pi`. It plays
a short tone, records five seconds through Marsi's actual microphone code, then
plays your words back. Answer `y` to each question only if you heard the correct
sound. The sample is removed after testing and is not sent to Ubuntu. If it
fails, use [audio check and recovery](audio-check.md) before proceeding.
`--status` instead of `--check` gives a silent readiness report.

## 3. Open the display and test conversation by voice

From the Pi's local console on Lite:

```bash
chmod +x deploy/marsi-xsession.sh
startx "$HOME/marsi-companion/deploy/marsi-xsession.sh" -- -nocursor
```

Run this on the physical console; `startx` over a normal SSH connection is not
the same as launching a local graphical session.

On an existing desktop, open a terminal in the project directory and run:

```bash
.venv-pi/bin/python -m marsi_local.pi
```

The default display is fullscreen: black, Mars red, green phosphor, a small ASCII
Marsi and machine readings. Escape makes it a window; Ctrl+Q or typed `exit` closes
it. Use `--windowed` during development. Both sides of conversations remain in
the scrollable journal; OLDER TRANSMISSIONS loads earlier pages. The display
supports 800×480 and 480×320, with smaller lettering on the smaller screen.

Startup checks audio readiness silently in the background and adds any warnings
to the local terminal view; typed conversation remains available. It does not
play a test tone or record you. Enable Voice, type a sentence and press Enter or
SEND. Hear Marsi's spoken reply before trying speech recognition.

Press **TALK** or **F8**, speak for a few seconds, then press **FINISH** or **F8**
again. F8 applies while Marsi has keyboard focus; holding it down does not start
repeated recordings. The recording stops
automatically after 15 seconds. Marsi shows what he heard and plays the reply if
Voice is enabled. Voice off skips synthesis as well as playback. The microphone
does not record in idle mode or during playback, which avoids most echo loops.

The recognizer can still mishear speech or noise. Start in a quiet room. A wake
word and continuous listening are later additions after this flow is reliable.

If the local recording test works but the display reports speech recognition
failed, follow [Ubuntu's recognition diagnostics](ubuntu-server.md#speech-recognition-fails-after-the-microphone-test-passes).
The recognizer runs on Ubuntu. A technical recognition failure does not require
re-pairing a Bluetooth device that already records and plays sound successfully.

Use the [feature test checklist](test-checklist.md) to work through conversation,
speech, notes, rituals, connection recovery and startup on your actual hardware.

## 4. Routines and automatic startup

The Idle rites switch controls spontaneous small rituals and scheduled speech.
**BLESS** requests an immediate ritual; **ART** makes a hardware-shaped ASCII
inscription. Typed `sermon` gives a tiny sermon. Manual requests use Voice.
Small automatic rituals are silent unless `MARSI_RITUAL_SPEECH=true`.
Ubuntu also schedules daily art, a sermon every 2–3 days and a 07:00 greeting.
The greeting speaks during quiet hours by default; other automatic speech does
not. See [behaviour and memory](behaviour.md) for every setting and timing rule.
Set both machines' timezone correctly; `timedatectl` shows the current setting.

To make Marsi open at every Lite boot, first verify display and audio manually.
Then run on the Pi:

```bash
cd ~/marsi-companion
bash scripts/install-pi-autostart.sh --lite --enable-autologin
```

Run as the same Pi user who runs Marsi, without `sudo` before `bash`. The option
configures Console Autologin through `raspi-config`, using sudo for that OS
setting only. Reboot when ready with `sudo reboot`. To configure OS autologin
manually instead, omit `--enable-autologin` and use the boot/autologin settings
in `sudo raspi-config`. The installer preserves your profile and adds a marked startup
block. SSH logins still get a normal shell. The display retries its server
connection during boot; it does not require Ubuntu to be ready first.
See [quickstart](quickstart.md#4-make-the-lite-pi-start-automatically) for Desktop
startup, rollback and what to expect after reboot. The installer replaces its
own marked block and the exact legacy block from this guide. It stops if it
finds a custom Marsi startup entry it cannot safely identify.

**FORGET** deletes this session's journal, working context, notes and schedule state from the server
after a confirmation. Copies and backups of the database remain separate.

## Connection loss

The Pi shows an error if the server is unavailable. It never silently switches
Qwen replies to fake AI answers. The ASCII character keeps blinking, and loaded
journal text remains visible. Archive/telemetry connections retry automatically;
server-backed rituals resume when reachable. Try another message once the server
is back. An in-progress
request can take up to 240 seconds to time out, while the screen remains responsive.

[Useful troubleshooting commands](troubleshooting.md) cover the display process,
boot launcher, audio services, server and logs. Lite startup logs go to
`~/marsi-companion/data/pi-display.log`; these are private and excluded from Git.
