# Quickstart: open Marsi and keep him running

Use this page if Ubuntu, Ollama, speech and the Pi are already installed. For a
fresh installation, follow [start here](start-here.md), then the
[Ubuntu guide](ubuntu-server.md) and [Pi guide](raspberry-pi.md).
Commands below assume both checkouts are `~/marsi-companion`.

## 1. Update Ubuntu first

Run on **Ubuntu**, locally or through SSH, as the user who installed Marsi:

```bash
cd ~/marsi-companion
git pull --ff-only
systemctl --user stop marsi-server
mkdir -p data/backups
if [ -f data/companion.sqlite3 ]; then
    cp -p data/companion.sqlite3 "data/backups/companion-$(date +%Y%m%d-%H%M%S).sqlite3"
fi
.venv-server/bin/python -m pip install -r requirements-server.txt
.venv-server/bin/python -m pip check
.venv-server/bin/python -m marsi_local.speech --check-recognition
systemctl --user start marsi-server
systemctl --user status marsi-server --no-pager
```

Run one command at a time; stop if it fails. The backup is private and stays out
of Git. If you configured `MARSI_DATABASE` to a different location, back up that
file instead. Stop all manual Marsi instances before copying an active database.
On first startup, the new journal imports the old retained conversation once.
Messages that the previous 30-exchange limit already deleted cannot be restored.

If you have not installed the service yet, use step 6 of the
[Ubuntu guide](ubuntu-server.md#6-start-the-server-automatically). Until then,
start `.venv-server/bin/python -m marsi_local.server --host 0.0.0.0` manually.

Check both machines' timezone with `timedatectl`. The morning greeting is due at
07:00 in **Ubuntu's local timezone**. Change a timezone only if it is wrong; an
example is `sudo timedatectl set-timezone Europe/Berlin`.

## 2. Update the Pi

First close the old display with Ctrl+Q, or type `exit` in the new display.
Then run on **the Pi**, locally or through SSH:

```bash
cd ~/marsi-companion
git pull --ff-only
```

This display update needs no new Pi Python packages. Keep `.env.pi`, including
your working microphone and speaker settings. New settings have defaults, so an
existing settings file does not need replacing. Never copy an example over it.

**Before opening the display, test the Pi's speaker and microphone:**

```bash
.venv-pi/bin/python -m marsi_local.audio --check
```

SSH works for this check. Follow its tone and five-second microphone replay
prompts. Keep the Bluetooth receiver powered; if it fails, use
[the audio check and recovery guide](audio-check.md) before proceeding.
For a silent inspection only, use `--status` instead of `--check`.

## 3. Start the display manually

On **the Pi's physical console** with Raspberry Pi OS Lite:

```bash
cd ~/marsi-companion
chmod +x deploy/marsi-xsession.sh
startx "$HOME/marsi-companion/deploy/marsi-xsession.sh" -- -nocursor
```

This opens Marsi on the attached screen. A normal SSH shell cannot substitute
for the physical console for this `startx` command. From an existing desktop's
terminal, use `.venv-pi/bin/python -m marsi_local.pi` instead.

Startup also runs a silent audio readiness check and displays any warnings. It
does not play a tone or record a microphone sample; use the manual check above
to verify actual sound. Typed conversation stays available if audio is missing.

- Type a sentence and press Enter or SEND.
- Press **F8** or TALK, speak, then press **F8** or FINISH. F8 works while the
  display has keyboard focus; it is not a system-wide shortcut.
- Type `art`, `sermon`, `bless`, `help`, or `exit`. A leading slash also works.
  These exact commands are handled by the app. Other sentences go to Qwen.
- Scroll the journal. **OLDER TRANSMISSIONS** loads an earlier page; `history`
  does the same in the display. **LATEST** returns to recent messages. The
  terminal client shows its latest page.
- Escape leaves fullscreen. Ctrl+Q or `exit` closes the display.

Both typed messages and recognized speech enter the server journal. Readings
refresh about every ten seconds. An unavailable temperature sensor shows `--`.
The first CPU percentage also shows `--` until two samples have been taken.

## 4. Make the Lite Pi start automatically

After the manual display and audio tests work, run **on the Pi**:

```bash
cd ~/marsi-companion
bash scripts/install-pi-autostart.sh --lite --enable-autologin
```

Run the script as your usual Pi user, **without sudo before `bash`**. The
`--enable-autologin` option uses sudo only to configure console autologin for
that user through `raspi-config`. It does not reboot immediately. The attached
console will log in automatically after boot; SSH keeps its normal login.
This uses the [official noninteractive boot setting](https://www.raspberrypi.com/documentation/computers/configuration.html).
To keep OS login settings unchanged, omit `--enable-autologin` and choose
Console Autologin separately in `sudo raspi-config`.
The installer adds a marked block to `~/.profile`, preserves the rest of it and
makes a first backup as `~/.profile.before-marsi`. It launches only on the local
console `/dev/tty1`, so SSH logins remain ordinary shells.
The installer also replaces the exact unmarked `startx` block from the earlier
guide. If it finds a custom Marsi startup entry instead, it stops and asks you
to inspect it; do not keep two launch entries.

Then reboot:

```bash
sudo reboot
```

The SSH session will disconnect. The display should open after the Pi boots.
The Ubuntu server also needs to be running; the display retries its connection
until the server is ready. Keep a USB speakerphone attached. For Bluetooth,
keep the receiver powered and verify reconnection separately using
[Bluetooth audio](bluetooth-audio.md).

If the Ubuntu service was already installed, ensure **on Ubuntu** that both
services are enabled and that Marsi's user services can start without a login:

```bash
systemctl --user enable --now marsi-server
sudo loginctl enable-linger "$USER"
sudo systemctl enable --now ollama
systemctl --user is-enabled marsi-server
systemctl --user is-active marsi-server
loginctl show-user "$USER" -p Linger
```

The last three checks should report `enabled`, `active` and `Linger=yes`.
After an Ubuntu reboot, check again through SSH; use a chat to verify Qwen
inference. If `marsi-server` is missing, install it using step 6 of the Ubuntu
guide before running these commands.

For a Desktop installation, use `bash scripts/install-pi-autostart.sh --desktop`
instead. It creates `~/.config/autostart/marsi.desktop`; do not install both
startup methods. Add `--enable-autologin` to enable desktop autologin too,
or configure it separately in raspi-config.

To undo Lite display startup, edit `~/.profile` and remove only the block between
`# BEGIN MARSI DISPLAY` and `# END MARSI DISPLAY`. To undo Desktop startup, remove
only `~/.config/autostart/marsi.desktop`. A deliberate `exit` returns to the
console on Lite; it does not erase settings or memory.
Console autologin can be disabled separately with
`sudo raspi-config nonint do_boot_behaviour B1`.

## 5. Verify the new features

Try `art` and `sermon` immediately; no need to wait several days. Reopen the
display and check that conversations and inscriptions remain in the journal.
Review [behaviour and memory](behaviour.md) for schedules and
[troubleshooting commands](troubleshooting.md) if anything fails.
