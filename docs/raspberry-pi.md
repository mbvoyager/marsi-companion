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

## 2. Open the display

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

The default display is fullscreen. Escape makes it a window; Ctrl+Q exits.
Use `--windowed` during development. Type a message and press Send before testing
the microphone. Replies can be scrolled in the text area, even on a 480×320 screen.

## 3. Test the microphone and speaker

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
needed. Use the number actually reported on your Pi. Test the output with:

```bash
speaker-test -t sine -c 1 -l 1
```

Press **Talk**, speak for a few seconds, then press **Finish**. The recording stops
automatically after 15 seconds. Marsi shows what he heard and plays the reply if
Voice is enabled. Voice off skips synthesis as well as playback. The microphone
does not record in idle mode or during playback, which avoids most echo loops.

The recognizer can still mishear speech or noise. Start in a quiet room. A wake
word and continuous listening are later additions after this flow is reliable.

## 4. Tiny rituals and startup

The Rituals switch controls occasional visual blessings. **Bless!** requests an
immediate ritual and uses the Voice switch. Automatic rituals are silent unless
`MARSI_RITUAL_SPEECH=true`. Quiet hours apply to automatic rituals. Set the Pi's
timezone correctly, for example `sudo timedatectl set-timezone Europe/Berlin`.

For optional Lite boot startup, first verify display and audio manually. In
`sudo raspi-config`, select console autologin for the local user. Then append
this to that user's `~/.profile`:

```bash
if [ -z "$DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
    startx "$HOME/marsi-companion/deploy/marsi-xsession.sh" -- -nocursor
fi
```

SSH logins will still get a normal shell. Remove that block to undo automatic
display startup. This template assumes the checkout is in the user's home folder.

**Forget** deletes this session's saved conversation and notes from the server
after a confirmation. Copies and backups of the database remain separate.

## Connection loss

The Pi shows an error if the server is unavailable. It never silently switches
Qwen replies to fake AI answers. Its local animation and silent ritual timer
continue working; try another message once the server is back. An in-progress
request can take up to 240 seconds to time out, while the screen remains responsive.
