#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"

# Prefer a project-local environment, then the environment created by install.sh.
if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$DATA_HOME/brave-music-panel/.venv/bin/python" ]]; then
  PYTHON="$DATA_HOME/brave-music-panel/.venv/bin/python"
elif python3 -c 'import PySide6' >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  cat >&2 <<MSG
PySide6 is not installed for this Python environment.

From this project directory, run:
  sudo apt install python3-venv playerctl wmctrl
  ./install.sh

Then run ./run.sh again. The installer puts its virtual environment in:
  $DATA_HOME/brave-music-panel/.venv
MSG
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/app.py" "$@"
