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
sudo apt install -y git nano python3 python3-venv python3-tk libportaudio2 alsa-utils x11-xserver-utils
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
startx "$HOME/marsi-companion/deploy/marsi-xsession.sh"
```

Run this on the physical console; `startx` over a normal SSH connection is not
the same as launching a local graphical session.

Marsi uses a green/red mechanical crosshair pointer on X11. If an older
installation hides the pointer, [refresh the Lite startup block and reboot](quickstart.md#3-start-the-display-manually)
to remove the old `-nocursor` option. The pointer uses the window system, with
no extra animation or mouse polling; typing, text selection and clicks are
unchanged. Windows/macOS development uses a standard visible crosshair.
At startup, screen power settings are prepared before the interface, and the
reticle is reapplied after the window becomes visible. If it is missing only
after automatic boot, see [startup cursor diagnosis](troubleshooting.md#pi-display-and-boot).

On an existing desktop, open a terminal in the project directory and run:

```bash
.venv-pi/bin/python -m marsi_local.pi
```

The default display is fullscreen: black, Mars red, green phosphor, a small ASCII
Marsi and machine readings. Escape makes it a window; Ctrl+Q or typed `exit` closes
it. Use `--windowed` during development. Both sides of conversations remain in
the scrollable journal; OLDER TRANSMISSIONS loads earlier pages. The display
supports 800×480 and 480×320, with smaller lettering on the smaller screen.

Your typed message appears immediately, with an ASCII progress bar underneath.
`ESTIMATE` means a timing guess, not measured model progress. The first guess is
rough; Marsi adjusts it using the last five completed requests of each kind in
this display session. Voice and text have separate timings. If a reply takes
longer, the bar waits below 100% and says `a longer thought`. It disappears as
soon as the response arrives, before speaker playback finishes. The confirmed
server entry replaces your provisional line without repeating it in the chat.

After F8/FINISH, a sealed-recording notice appears with the same estimated
progress. The recognized words replace that notice when Ubuntu returns them.
If the connection fails, your typed words remain locally marked `UNSEALED`;
there is no automatic resend. The server journal remains the durable archive.

Startup silently checks audio settings and PipeWire/PulseAudio routes and adds
any warnings to the local terminal view; typed conversation remains available.
It does not probe the microphone hardware, play a test tone or record you.
Enable Voice, type a sentence and press Enter or SEND. Hear Marsi's spoken reply
before trying speech recognition.

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

### Keep the screen awake

On the recommended Lite/X11 setup, Marsi disables X11's screen saver and display
power timeout while the app runs. This also applies when starting the Python
app directly in an X11 desktop. Normal exit restores the earlier settings;
no permanent OS setting is edited and no keep-awake polling process is added.
The `xset` utility comes from `x11-xserver-utils`, installed in step 1.
These are the [X.Org screen-saver and DPMS controls](https://xorg.freedesktop.org/releases/X11R7.5/doc/man/man1/xset.1.html).

For an existing Pi installation, update **on the Pi**:

```bash
cd ~/marsi-companion
git pull --ff-only
sudo apt update
sudo apt install -y x11-xserver-utils
sudo reboot
```

With autostart already installed, Marsi opens with these changes after the
reboot. Alternatively, close Marsi and open it again. This display update does
not require changes on Ubuntu.

To check from SSH while Marsi is open, log in as the same Pi user and run:

```bash
DISPLAY=:0 xset q
```

`Screen Saver` should show `timeout: 0`. `DPMS` should be disabled if the X server
supports it; a report that the extension is unavailable is also normal. If the
session uses a different display number, use that number instead of `:0`.
If access is denied, run `xset q` in a terminal inside the graphical session.

A full Wayland desktop manages its own idle policy; Marsi shows a `LUMEN`
notice there rather than claiming Xwayland can hold the monitor awake. Disable
Screen Blanking in the desktop's display settings, as described in the
[official Raspberry Pi guide](https://www.raspberrypi.com/documentation/computers/configuration.html#configure-screen-blanking).
If an X11 screen still turns off with timeout zero and DPMS disabled, check the
monitor's own sleep/eco timer or any separately installed screen-locking utility.

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

The top-right link indicator shows `Connecting #1` as soon as Marsi starts.
After a failed attempt, `Retry in` counts down until the next try. The pauses
between attempts are 1, 2, 4 and then 8 seconds. Each background HTTP request
has a five-second socket timeout. `Token rejected` identifies a rejected login
and retries after ten seconds. Correct the Pi's `.env.pi` and reopen Marsi if
you need to change its token or server address.

`Online` appears when the server accepts the background request. The loaded
journal remains visible during a disconnect. You can keep typing during startup
or a disconnect. Your draft stays in the input field until you send it while
online. Scheduled speech and idle rites resume when the link returns. An already
submitted chat may take up to the normal 240-second request timeout.

Open `http://YOUR_SERVER_IP:8765/health` from the Pi or another device in the
same LAN or Wi-Fi. Use the Ubuntu address from `MARSI_SERVER_URL` and append
`/health`. See the [LAN health check and firewall setup](ubuntu-server.md#check-health-from-lan-or-wi-fi).

[Useful troubleshooting commands](troubleshooting.md) cover the display process,
boot launcher, audio services, server and logs. Lite startup logs go to
`~/marsi-companion/data/pi-display.log`; these are private and excluded from Git.
