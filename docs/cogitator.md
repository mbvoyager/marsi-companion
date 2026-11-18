# Cogitator update: install, check and adjust

This update changes the Pi display and local website, adds six silent local-data
interludes, and replaces the old daily diagrams with one authored sermon per day.
The ten approved examples are included in a pool of 42. No new models, Python
packages, Docker containers or Internet access are needed for these features.
Your existing microphone, speaker, token, TLS and climate settings remain in use.

## 1. Ubuntu: inspect the checkout and take a backup

Run on **Ubuntu**, in the SSH terminal for the Marsi server:

```bash
cd ~/marsi-companion
git status --short
```

An empty result means no tracked files have local edits. Keep any listed edits;
resolve them before switching branches. Private `.env` and `data/` files are ignored.

Back up the configured database using SQLite's backup operation. This works while
Marsi is running and includes committed data even if SQLite uses a WAL file:

```bash
.venv-server/bin/python - <<'PY'
from datetime import datetime
from pathlib import Path
import sqlite3
from marsi_local.config import load_env, ServerConfig
load_env('.env.server')
source = ServerConfig.from_env().database.resolve()
folder = source.parent / 'backups'
folder.mkdir(exist_ok=True)
target = folder / ('before-cogitator-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
    with sqlite3.connect(target) as backup:
        original.backup(backup)
print('Backup created:', target)
PY
```

Success prints the private backup's path. The command never prints a token.

## 2. Ubuntu: fetch the release branch and restart Marsi

Run each line separately and stop if a command fails:

```bash
git fetch origin
git switch codex/cogitator
git pull --ff-only
systemctl --user restart marsi-server
systemctl --user is-active marsi-server
curl -fsS --max-time 5 http://127.0.0.1:8765/health
```

`git switch` works both when the local branch already exists and when Git can
create it from the single matching `origin/codex/cogitator` branch. Avoid `-c` on
repeat updates. Success ends with `active` and health JSON containing `"status": "ok"`.
The journal and climate data stay in the configured SQLite database. The first
start adds sermon calendar/selection tables and retires the old diagram timer.
It keeps old journal entries readable and playable.

For a startup problem, inspect this before trying another change:

```bash
journalctl --user -u marsi-server -n 40 --no-pager
```

Do not paste `.env.server`, `.env.pi` or a bearer/admin token into a report.

## 3. Pi: update the display

Close the display with **Ctrl+Q**, then run on **the Pi**, locally or through SSH:

```bash
cd ~/marsi-companion
git status --short
git fetch origin
git switch codex/cogitator
git pull --ff-only
```

Keep the working `.env.pi`. New settings have defaults; copying an example over
the file would replace your audio and server settings.

On the Pi's **physical console** with Raspberry Pi OS Lite, open Marsi with:

```bash
startx "$HOME/marsi-companion/deploy/marsi-xsession.sh"
```

The existing autostart loads the updated script and code on the next Pi boot.
If needed, `sudo reboot` on the Pi verifies that existing startup arrangement.
SSH can update the files; `startx` belongs on the physical console.

## 4. Browser: reload and check

Open your existing trusted local **HTTPS** address on port **8766**. Use **Ctrl+F5**
to reload the updated browser files, then sign in with the usual Marsi token.
Sanctum still requires its separate admin token over HTTPS. Port 8765 continues
to serve the Pi API and `/health`; the HTTPS listener shares the same backend.

Check, in order:

1. Send a typed message. Your words appear immediately, followed by estimated
   progress and a moving-block reveal of Marsi's reply. F8/Talk and Voice still work.
2. Open Climate. Each sensor has a colour and shape. The same identity appears
   in its chart legend and end marker; line patterns distinguish overlapping
   curves. Custom colours set in Sanctum take precedence. Toggle a legend entry
   or tap a curve to inspect readings.
3. Type `/auspex`, `/vox`, `/servitor`, `/hololith`, `/codex`, then `/noosphere`.
   Each opens a temporary scene. A key or touch closes it immediately; it also
   closes after 15–30 seconds. The Pi retains its original figure; the web has
   a small original cog-and-skull seal instead of a portrait.
4. Check missing data: no exterior sensor or an old reading must produce
   `NO SIGNAL`, never a made-up temperature. Radar positions are schematic,
   not measured room positions. Scenes show a snapshot taken when requested.
5. Type `sermon` with Voice on. It retrieves today's sermon. Repeating the command
   replays the same entry rather than creating another. The next day draws a
   new eligible text; the eligible pool is exhausted before repeating.

A sermon saved earlier on the upgrade day still counts as that day's entry.
It remains replayable; the following day draws from the new pool. Temperature
references belong to the entry's creation time, shown in the journal timestamp.

Automatic interludes require Idle enabled, two minutes without interaction,
no active recording/reply/playback, and a time outside quiet hours. Their random
interval is 30–90 minutes. They never interrupt web administration. Manual
commands make immediate testing possible without changing the system clock.

## 5. Optional Pi settings

Edit **the Pi's `.env.pi`**, then restart the display to apply changes:

| Setting | Default | Meaning |
| --- | --- | --- |
| `MARSI_INTERLUDE_MIN_SECONDS` | `1800` | Minimum interval; supported timer range 30–86400 seconds |
| `MARSI_INTERLUDE_MAX_SECONDS` | `5400` | Maximum interval, at least the minimum |
| `MARSI_INTERLUDE_IDLE_SECONDS` | `120` | Required idle time, at least 120 seconds |
| `MARSI_INTERLUDE_MIN_DURATION` | `15` | Minimum scene duration |
| `MARSI_INTERLUDE_MAX_DURATION` | `30` | Maximum duration; both duration settings must be within 15–30 seconds |
| `MARSI_INTERLUDE_CHIRP` | `false` | Optional 0.18-second, locally generated servitor chirp |
| `MARSI_TYPEWRITER` | `true` | Reveal new Marsi text with a moving block cursor |
| `MARSI_REDUCED_MOTION` | `false` | Stop motion and show complete replies immediately |
| `MARSI_QUIET_START`, `MARSI_QUIET_END` | `22`, `8` | Pi quiet interval; equal hours disable it |

The web uses the same default interlude intervals and respects the operating
system/browser **reduced motion** preference. Its Idle checkbox is independent
of the Pi. Browser interludes are silent. Older loaded history is never typed
again on either surface. A new interaction finishes the current text reveal.

On **Ubuntu's `.env.server`**, `MARSI_MORNING_HOUR=7` and
`MARSI_QUIET_START=22` / `MARSI_QUIET_END=8` determine the daily sermon window.
Keep the quiet hours in agreement with the Pi. With these defaults the sermon
falls between 08:00 and 22:00, after the morning hour. The 07:00 spoken greeting
retains its existing quiet-hour override. A late startup can deliver one sermon
for the current waking day; missed days are not replayed.

## Design and verification

`marsi_local/web/cogitator.json` is the shared source for palette, typography,
spacing, frame sizes and default sensor styles. Python loads it directly; the
server derives `/web/theme.css` from it. Climate responses carry the same
colour/shape/dash identity to both clients. Ordinary hiding/renaming preserves
registry rows and therefore sensor identities.
When more than four sensors are added, the same palette combines with different
line patterns and shapes rather than immediately repeating an identical style.

The decorative Imperial date is a documented display convention:
`0.FFFYYY.M42`, where `FFF` is the UTC fraction of the real calendar year
(000–999), and `YYY` its last three digits. Leap years use their actual length.
`M42` is fictional presentation, not a claim about the real year or setting canon.
Journal timestamps retain their normal calendar dates and local display.

Scenes and replies do not train Qwen. Interludes use no model or Internet and
create no journal rows. Brief logs record type and duration only. Real readings
are kept separate from decorative hex, redactions and header glitches. Tk
reuses its scene items; animation is capped at 15 fps. Verify final smoothness
and voice on the physical Pi 3 B+ after updating.

See the [before/after captures](../artifacts/cogitator/README.md) and the
[development checks](development.md#verification). All captures use test data.
