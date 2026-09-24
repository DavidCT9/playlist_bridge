"""Entry point: wires together the database, the JS<->Python bridge,
the pywebview window, the background scheduler and the tray icon.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import webview

from app import config, db
from app.api import Api
from app.scheduler import Scheduler
from app.tray import build_tray, run_tray_in_background

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(
        config.LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler(sys.stdout)],
    )


def run() -> None:
    _setup_logging()
    log = logging.getLogger(__name__)
    log.info("PlaylistBridge starting up. Config/DB dir: %s", config.APP_DIR)
    db.init_db()

    api = Api()
    log.info(
        "Startup status: spotify_connected=%s tidal_connected=%s",
        api.spotify_auth.is_connected(), api.tidal_auth.is_connected(),
    )

    window = webview.create_window(
        "PlaylistBridge",
        url=(FRONTEND_DIR / "index.html").as_uri(),
        js_api=api,
        width=1040,
        height=720,
        min_size=(780, 560),
        background_color="#12131a",
    )

    scheduler = Scheduler(
        # Goes through the same locked, logged path a manual "Sync now"
        # click uses, so a scheduled sync and a manual one can never run
        # concurrently against the same playlists.
        run_sync=lambda: api.sync_all_now(),
        get_interval_minutes=lambda: api.settings.get("sync_interval_minutes", 30),
    )
    api.scheduler = scheduler

    def on_open(icon=None, item=None):
        window.show()

    def on_sync_now(icon=None, item=None):
        scheduler.trigger_now()

    def on_toggle_pause(icon=None, item=None):
        scheduler.paused = not scheduler.paused

    def on_quit(icon=None, item=None):
        scheduler.stop()
        try:
            icon.stop()
        except Exception:
            pass
        window.destroy()

    tray_icon = build_tray(on_open, on_sync_now, on_toggle_pause, on_quit, lambda: scheduler.paused)

    def on_closing():
        # Minimize to tray instead of quitting, so background sync
        # keeps running. Use the tray menu's "Quit" to actually exit.
        # Note: cancelling close via `return False` is a documented
        # pywebview feature, but a couple of older renderer backends
        # have had quirks with it (see README > Troubleshooting). If
        # closing ever misbehaves on your platform, delete this
        # `window.events.closing += on_closing` line below and rely on
        # the login autostart script instead for background syncing.
        window.hide()
        return False

    window.events.closing += on_closing

    def on_shown():
        log.info("Window shown -- starting scheduler")
        scheduler.start()
        if api.settings.get("auto_sync_enabled", True):
            scheduler.trigger_now()
        else:
            log.info("auto_sync_enabled is off in Settings, not syncing on startup")

    window.events.shown += on_shown

    run_tray_in_background(tray_icon)
    log.info("Tray icon started, entering main event loop")
    webview.start(debug=False)


if __name__ == "__main__":
    run()
