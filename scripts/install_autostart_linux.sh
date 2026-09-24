#!/usr/bin/env bash
# Adds PlaylistBridge to your desktop environment's autostart (XDG
# autostart spec -- works on GNOME, KDE, XFCE, etc.) so it starts
# (minimized to the tray) whenever you log in.
#
# Run from inside the project folder:
#   bash scripts/install_autostart_linux.sh

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$(command -v python3)"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
DESKTOP_FILE="$AUTOSTART_DIR/playlistbridge.desktop"

mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=PlaylistBridge
Comment=Sync playlists between Spotify and TIDAL
Exec=${PYTHON_BIN} ${PROJECT_DIR}/main.py
Path=${PROJECT_DIR}
X-GNOME-Autostart-enabled=true
NoDisplay=false
EOF

chmod +x "$DESKTOP_FILE"
echo "Installed: $DESKTOP_FILE"
echo "Remove any time by deleting that file."
