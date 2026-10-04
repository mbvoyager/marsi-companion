# Useful Ubuntu and Raspberry Pi commands

Run each command on the machine named below. Commands using `systemctl --user`
must run as the same user who installed Marsi, without sudo. Replace uppercase
placeholders before running commands. Keep tokens, addresses and private journal
text out of public issues and screenshots; redact diagnostic output before sharing.

## Ubuntu: service and models

| Command | What it tells you or does |
| --- | --- |
| `systemctl --user status marsi-server --no-pager` | Is Marsi's server running? |
| `systemctl --user is-enabled marsi-server` | Will the user service start automatically? |
| `journalctl --user -u marsi-server -n 60 --no-pager` | Recent server diagnostics |
| `systemctl --user restart marsi-server` | Load updated code/settings |
| `systemctl --user stop marsi-server` | Stop it before replacing packages or copying the database |
| `systemctl --user start marsi-server` | Start it again |
| `systemctl status ollama --no-pager` | Is the model runner running? |
| `ollama list` | Which models are downloaded? |
| `ollama ps` | Which model is loaded and where does it run? |
| `curl http://127.0.0.1:8765/health` | Is the API process responding? This does not test Qwen or speech |
| `ss -ltnp '( sport = :8765 )'` | Which process owns Marsi's port? |
| `loginctl show-user "$USER" -p Linger` | Can user services run without a login? |
| `free -h` / `df -h` / `top` | RAM, storage and active CPU use |
| `timedatectl` | Timezone and clock synchronization |
| `systemctl status ssh --no-pager` | Is remote SSH access running? |

If port 8765 is already in use, inspect its owner. A manually started Marsi and
the systemd service cannot both own the port. Stop the manual instance with
Ctrl+C in its terminal before starting the service; do not kill an unidentified
process. An old failure line in the journal does not mean the current service
is failing—check the current status and latest timestamps.

For speech, run from `~/marsi-companion`:

```bash
.venv-server/bin/python -m pip check
.venv-server/bin/python -m unittest tests.speech_decoder_smoke -v
.venv-server/bin/python -m marsi_local.speech --check-recognition
```

If a check fails, preserve the complete traceback. See
[speech diagnostics and the PyAV compatibility fix](ubuntu-server.md#speech-recognition-fails-after-the-microphone-test-passes).

To enable Ubuntu SSH from its local console:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
hostname -I
```

If UFW is already enabled, allow SSH before relying on remote access with
`sudo ufw allow OpenSSH`. Do not enable a firewall remotely without an SSH rule.
From another machine: `ssh YOUR_UBUNTU_USER@YOUR_SERVER_IP`.
These steps follow [Ubuntu's OpenSSH guide](https://ubuntu.com/server/docs/how-to/security/openssh-server/).

## Pi: display and boot

| Command | What it tells you or does |
| --- | --- |
| `pgrep -af 'marsi_local.pi'` | Is the display process running? |
| `pgrep -af 'Xorg|openbox'` | Is the Lite graphical session running? |
| `tail -n 60 ~/marsi-companion/data/pi-display.log` | Recent Lite display startup diagnostics |
| `systemctl status getty@tty1 --no-pager` | Is the local console/autologin service available? |
| `grep -A 5 '# BEGIN MARSI DISPLAY' ~/.profile` | Is the installed Lite startup block present? |
| `ls -l ~/.config/autostart/marsi.desktop` | Is Desktop startup installed? Only for Desktop |
| `sudo raspi-config` | Configure console autologin and other Pi settings |
| `vcgencmd measure_temp` | Pi temperature, where the Pi utility is installed |
| `vcgencmd get_throttled` | Pi power/thermal flags; preserve the value for diagnosis |
| `free -h` / `df -h` / `top` / `timedatectl` | RAM, storage, CPU, clock |

Use Ctrl+Q or type `exit` in Marsi to close the display. To stop it from SSH,
first find the exact process ID with `pgrep -af 'marsi_local.pi'`, then use
`kill YOUR_DISPLAY_PID`. Do not use a broad command that also kills unrelated
Python processes. An ordinary TERM signal closes the app gracefully; the Lite
launcher restarts crashes. A reboot is
the straightforward way to reopen an installed automatic display from SSH.
To stop it persistently, remove the managed startup block as described in
[quickstart](quickstart.md#4-make-the-lite-pi-start-automatically).

## Pi: audio and Bluetooth

Run these as Marsi's Pi user:

```bash
systemctl --user status pipewire pipewire-pulse wireplumber --no-pager
pactl info
pactl list short sinks
pactl list short sources
pactl list cards
bluetoothctl devices
rfkill list
```

A sink is an output; a source is an input. A `.monitor` source records speaker
output, not the microphone. For a receiver, use its actual address from
`bluetoothctl devices` in `bluetoothctl info YOUR_RECEIVER_ADDRESS` or
`bluetoothctl connect YOUR_RECEIVER_ADDRESS`. Keep its USB power connected.
Unplugging a power-only USB lead also interrupts Bluetooth.

Test through PipeWire after choosing the intended sink and microphone source:

```bash
speaker-test -D pipewire -t sine -c 1 -l 1
arecord -D pipewire -f S16_LE -r 16000 -c 1 -d 5 /tmp/marsi-mic-test.wav
aplay -D pipewire /tmp/marsi-mic-test.wav
```

Delete the private test recording when done: `rm /tmp/marsi-mic-test.wav`.
The [Bluetooth guide](bluetooth-audio.md) covers pairing, hands-free profiles,
default input/output selection and the WirePlumber SSH configuration.

## Either machine: Git and settings

```bash
cd ~/marsi-companion
git status --short
git log -1 --oneline
git pull --ff-only
```

If pulling reports local changes, inspect them before continuing; do not reset
or overwrite work blindly. `.env.server` is on Ubuntu, `.env.pi` is on the Pi.
They are hidden local files: `ls -la` shows them; `nano .env.server` or
`nano .env.pi` edits them. Never paste their complete contents into a public issue.
Restart the appropriate application after changing code or settings.
