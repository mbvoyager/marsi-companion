#!/usr/bin/env bash
set -euo pipefail
cd -- "$HOME/marsi-companion"
openbox &
exec .venv-pi/bin/python -m marsi_local.pi
