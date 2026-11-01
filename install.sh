#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
INSTALL_DIR="$DATA_HOME/brave-music-panel"
APP_DIR="$DATA_HOME/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
INSTALL_LOG="$STATE_HOME/brave-music-panel/install.log"

mkdir -p "$INSTALL_DIR" "$APP_DIR" "$AUTOSTART_DIR" "$(dirname "$INSTALL_LOG")"
cp "$SCRIPT_DIR/app.py" "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/launch.sh" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/launch.sh"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install it with: sudo apt install python3"
  exit 1
fi
if ! command -v playerctl >/dev/null 2>&1; then
  echo "Install playerctl first: sudo apt install playerctl"
  exit 1
fi
if ! command -v wmctrl >/dev/null 2>&1; then
  echo "Note: wmctrl is needed to hide/restore the Brave window: sudo apt install wmctrl"
fi

if ! python3 -m venv "$INSTALL_DIR/.venv" >>"$INSTALL_LOG" 2>&1; then
  echo "Could not create the Python virtual environment. See $INSTALL_LOG"
  echo "On Linux Mint, install it with: sudo apt install python3-venv"
  exit 1
fi
if ! "$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip >>"$INSTALL_LOG" 2>&1; then
  echo "Could not upgrade pip. See $INSTALL_LOG"
  tail -n 30 "$INSTALL_LOG" || true
  exit 1
fi
if ! "$INSTALL_DIR/.venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt" >>"$INSTALL_LOG" 2>&1; then
  echo "Could not install Python requirements. See $INSTALL_LOG"
  tail -n 40 "$INSTALL_LOG" || true
  exit 1
fi
if ! "$INSTALL_DIR/.venv/bin/python" -c 'import PySide6; print(PySide6.__version__)'; then
  echo "PySide6 import test failed. See $INSTALL_LOG"
  exit 1
fi

cat > "$APP_DIR/brave-music-panel.desktop" <<EOF_DESKTOP
[Desktop Entry]
Type=Application
Name=Brave Music Panel
Comment=Edge-hover YouTube Music controller for Brave
Exec=$INSTALL_DIR/launch.sh
Icon=audio-headphones
Terminal=false
Categories=AudioVideo;Audio;Player;
StartupNotify=false
EOF_DESKTOP
chmod 644 "$APP_DIR/brave-music-panel.desktop"

read -r -p "Start Brave Music Panel automatically when you log in? [Y/n] " AUTOSTART
if [[ ! "$AUTOSTART" =~ ^[Nn]$ ]]; then
  cp "$APP_DIR/brave-music-panel.desktop" "$AUTOSTART_DIR/brave-music-panel.desktop"
  echo "Autostart enabled."
else
  rm -f "$AUTOSTART_DIR/brave-music-panel.desktop"
  echo "Autostart not enabled. You can launch it from the applications menu."
fi

echo
echo "Installed successfully. Launch 'Brave Music Panel' from the applications menu."
echo "Installed app: $INSTALL_DIR/app.py"
echo "Application log: $STATE_HOME/brave-music-panel/app.log"
echo "Launcher log: $STATE_HOME/brave-music-panel/launcher.log"
echo "Installer log: $INSTALL_LOG"
