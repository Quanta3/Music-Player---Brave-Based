#!/usr/bin/env bash
set -u
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
INSTALL_DIR="$DATA_HOME/brave-music-panel"

printf '\n%s\n' '--- Session ---'
echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unknown}"
echo "DISPLAY=${DISPLAY:-unset}"
echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset}"

printf '\n%s\n' '--- System commands ---'
for cmd in python3 playerctl busctl wmctrl brave-browser brave; do
  printf '%-14s' "$cmd"
  command -v "$cmd" || true
done

printf '\n%s\n' '--- Installed application ---'
ls -ld "$INSTALL_DIR" "$INSTALL_DIR/.venv" 2>&1 || true
ls -l "$INSTALL_DIR/app.py" "$INSTALL_DIR/launch.sh" 2>&1 || true
if [[ -x "$INSTALL_DIR/.venv/bin/python" ]]; then
  "$INSTALL_DIR/.venv/bin/python" -c 'import sys; print("Python:", sys.executable); import PySide6; print("PySide6:", PySide6.__version__)' 2>&1 || true
else
  echo 'Installed virtualenv Python is missing.'
fi

printf '\n%s\n' '--- Desktop entry ---'
sed -n '1,120p' "$DATA_HOME/applications/brave-music-panel.desktop" 2>&1 || true

printf '\n%s\n' '--- MPRIS players ---'
playerctl -l 2>&1 || true

printf '\n%s\n' '--- Recent logs ---'
for file in "$STATE_HOME/brave-music-panel/install.log" "$STATE_HOME/brave-music-panel/launcher.log" "$STATE_HOME/brave-music-panel/app.log"; do
  echo "### $file"
  if [[ -f "$file" ]]; then tail -n 50 "$file"; else echo '(not created)'; fi
done
