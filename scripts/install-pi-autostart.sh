#!/usr/bin/env bash
# Install Marsi's startup entry; optionally configure OS autologin too.
set -euo pipefail
mode=--lite
autologin=false
for argument in "$@"; do
    case "$argument" in
        --lite|--desktop) mode="$argument" ;;
        --enable-autologin) autologin=true ;;
        *) printf '%s\n' 'Usage: bash scripts/install-pi-autostart.sh --lite|--desktop [--enable-autologin]' >&2; exit 2 ;;
    esac
done
if [[ "$EUID" -eq 0 ]]; then
    printf '%s\n' 'Run as the user who runs Marsi, without sudo. Only OS autologin uses sudo.' >&2
    exit 1
fi
if "$autologin" && ! command -v raspi-config >/dev/null; then
    printf '%s\n' 'raspi-config is missing. Install it on Raspberry Pi OS before enabling autologin.' >&2
    exit 1
fi
cd -- "$(dirname -- "$0")/.."
if [[ "$PWD" != "$HOME/marsi-companion" ]]; then
    printf '%s\n' 'This template expects the checkout at ~/marsi-companion.' >&2
    exit 1
fi
chmod +x deploy/marsi-xsession.sh
case "$mode" in
    --lite)
        python3 - <<'PY'
from pathlib import Path
import shutil
profile = Path.home() / '.profile'
begin, end = '# BEGIN MARSI DISPLAY', '# END MARSI DISPLAY'
original = profile.read_text() if profile.exists() else ''
if begin in original or end in original:
    if original.count(begin) != 1 or original.count(end) != 1 or original.index(end) < original.index(begin):
        raise SystemExit('Unexpected Marsi markers in ~/.profile; inspect the file first.')
    start = original.index(begin)
    stop = original.index(end) + len(end)
    original = original[:start] + original[stop:].lstrip('\n')
legacy = '''if [ -z "$DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
    startx "$HOME/marsi-companion/deploy/marsi-xsession.sh" -- -nocursor
fi
'''
original = original.replace(legacy, '')
if 'marsi-xsession.sh' in original and 'startx' in original:
    raise SystemExit('A custom Marsi startup entry remains in ~/.profile; inspect it before installing another.')
backup = profile.with_name('.profile.before-marsi')
if profile.exists() and not backup.exists():
    shutil.copy2(profile, backup)
block = '''# BEGIN MARSI DISPLAY
if [ -z "$DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
    startx "$HOME/marsi-companion/deploy/marsi-xsession.sh" -- -nocursor
fi
# END MARSI DISPLAY
'''
profile.write_text(original.rstrip() + '\n\n' + block)
PY
        if ! "$autologin"; then
            printf '%s\n' 'Startup entry installed. In sudo raspi-config choose Console Autologin, then reboot.'
        fi
        ;;
    --desktop)
        mkdir -p "$HOME/.config/autostart"
        cat > "$HOME/.config/autostart/marsi.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Marsi companion
Exec=sh -c "cd ~/marsi-companion && exec .venv-pi/bin/python -m marsi_local.pi"
Terminal=false
DESKTOP
        if ! "$autologin"; then
            printf '%s\n' 'Desktop startup installed. Enable desktop autologin in raspi-config if desired.'
        fi
        ;;
    *) printf '%s\n' 'Usage: bash scripts/install-pi-autostart.sh --lite|--desktop' >&2; exit 2 ;;
esac
if "$autologin"; then
    boot_mode=B2
    if [[ "$mode" == --desktop ]]; then boot_mode=B4; fi
    sudo raspi-config nonint do_boot_behaviour "$boot_mode"
    printf '%s\n' 'Marsi startup and OS autologin configured. Reboot with sudo reboot when ready.'
fi
