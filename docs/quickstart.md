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
bash scripts/install-pi-autostart.sh --lite
sudo raspi-config
```

In raspi-config, choose **Console Autologin** in its boot/autologin settings,
then Finish. Names vary slightly by OS version; see the
[official configuration guide](https://www.raspberrypi.com/documentation/computers/configuration.html).
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
until the server is ready. Keep the Bluetooth receiver powered and verify its
reconnection separately using [Bluetooth audio](bluetooth-audio.md).

For a Desktop installation, use `bash scripts/install-pi-autostart.sh --desktop`
instead. It creates `~/.config/autostart/marsi.desktop`; do not install both
startup methods. Autologin must be enabled separately for an unattended boot.

To undo Lite display startup, edit `~/.profile` and remove only the block between
`# BEGIN MARSI DISPLAY` and `# END MARSI DISPLAY`. To undo Desktop startup, remove
only `~/.config/autostart/marsi.desktop`. A deliberate `exit` returns to the
console on Lite; it does not erase settings or memory.

## 5. Verify the new features

Try `art` and `sermon` immediately; no need to wait several days. Reopen the
display and check that conversations and inscriptions remain in the journal.
Review [behaviour and memory](behaviour.md) for schedules and
[troubleshooting commands](troubleshooting.md) if anything fails.
