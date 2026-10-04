#!/usr/bin/env bash
# Install only Marsi's startup entry. OS console autologin is a separate choice.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
if [[ "$PWD" != "$HOME/marsi-companion" ]]; then
    printf '%s\n' 'This template expects the checkout at ~/marsi-companion.' >&2
    exit 1
fi
chmod +x deploy/marsi-xsession.sh
case "${1:---lite}" in
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
        printf '%s\n' 'Startup entry installed. In sudo raspi-config choose Console Autologin, then reboot.'
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
        printf '%s\n' 'Desktop startup installed. Enable desktop autologin in raspi-config if desired.'
        ;;
    *) printf '%s\n' 'Usage: bash scripts/install-pi-autostart.sh --lite|--desktop' >&2; exit 2 ;;
esac
