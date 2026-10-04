#!/usr/bin/env bash
set -euo pipefail
cd -- "$HOME/marsi-companion"
umask 077
mkdir -p data
if [[ -f data/pi-display.log ]] && [[ $(wc -c < data/pi-display.log) -gt 1048576 ]]; then
    mv -f data/pi-display.log data/pi-display.previous.log
fi
exec >> data/pi-display.log 2>&1
openbox &
while true; do
    if .venv-pi/bin/python -m marsi_local.pi; then
        break  # A deliberate exit returns to the console.
    fi
    printf '%s\n' 'Display exited unexpectedly; retrying in five seconds.'
    sleep 5
done
