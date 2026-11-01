#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
LOG_DIR="$STATE_HOME/brave-music-panel"
mkdir -p "$LOG_DIR"

# GUI launchers usually have no terminal. Save stdout/stderr so failures are debuggable.
if [[ "${BRAVE_MUSIC_PANEL_CONSOLE:-0}" != "1" ]]; then
  exec >> "$LOG_DIR/launcher.log" 2>&1
fi

echo "===== Brave Music Panel launch: $(date --iso-8601=seconds) ====="
if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
  PYTHON="$APP_DIR/.venv/bin/python"
elif [[ -x "$DATA_HOME/brave-music-panel/.venv/bin/python" ]]; then
  PYTHON="$DATA_HOME/brave-music-panel/.venv/bin/python"
elif python3 -c 'import PySide6' >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "ERROR: PySide6 is unavailable. Re-run install.sh from the extracted project folder."
  exit 1
fi

echo "Python: $PYTHON"
"$PYTHON" -c 'import PySide6; print("PySide6:", PySide6.__version__)'
echo "App: $APP_DIR/app.py"
exec "$PYTHON" "$APP_DIR/app.py"
