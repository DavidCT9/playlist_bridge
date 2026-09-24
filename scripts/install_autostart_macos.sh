#!/usr/bin/env bash
# Adds PlaylistBridge as a macOS LaunchAgent so it starts (minimized to
# the menu-bar tray) whenever you log in.
#
# Run from inside the project folder:
#   bash scripts/install_autostart_macos.sh

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$(command -v python3)"
PLIST="$HOME/Library/LaunchAgents/com.playlistbridge.app.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.playlistbridge.app</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${PROJECT_DIR}/main.py</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_DIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed and loaded: $PLIST"
echo "Remove with: launchctl unload $PLIST && rm $PLIST"
