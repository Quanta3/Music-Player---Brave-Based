#!/usr/bin/env bash
set -euo pipefail
rm -f "$HOME/.local/share/applications/brave-music-panel.desktop"
rm -f "$HOME/.config/autostart/brave-music-panel.desktop"
rm -rf "$HOME/.local/share/brave-music-panel"
echo "Removed Brave Music Panel files and autostart entry."
echo "The app's log file was left in ~/.local/state/brave-music-panel."
echo "The dedicated Brave profile is removed with the app directory above."
