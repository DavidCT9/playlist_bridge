"""Application-wide paths, defaults and constants.

Nothing in this module touches the network. All paths point at a
per-OS, per-user application-data directory so no files are ever
written next to the source code.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

APP_NAME = "PlaylistBridge"


def get_app_dir() -> Path:
    """Return (and create) the per-OS application data directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    app_dir = base / APP_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


APP_DIR = get_app_dir()
DB_PATH = APP_DIR / "playlistbridge.db"
SETTINGS_PATH = APP_DIR / "settings.json"
LOG_PATH = APP_DIR / "playlistbridge.log"
TIDAL_SESSION_PATH = APP_DIR / "tidal_session.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "spotify_client_id": "",
    "spotify_redirect_port": 8765,
    "sync_interval_minutes": 30,
    "auto_sync_enabled": True,
    "dry_run_default": False,
}

# Minimum scopes needed to read/create/modify the user's own playlists.
SPOTIFY_SCOPES = (
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-public playlist-modify-private user-read-private"
)

KEYRING_SERVICE = "PlaylistBridge"


def load_settings() -> dict[str, Any]:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return {**DEFAULT_SETTINGS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
