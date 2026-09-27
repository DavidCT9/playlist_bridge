"""The `Api` class is exposed to the webview's JavaScript side via
`window.pywebview.api.<method>(...)`. Every method takes/returns plain
JSON-safe values (dicts, lists, strings, numbers) since that is all
that can cross the JS bridge.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import webbrowser

from app import config, db
from app.auth.spotify_auth import SpotifyAuth
from app.auth.tidal_auth import TidalAuth
from app.services.spotify_client import SpotifyClient
from app.services.tidal_client import TidalClient
from app.sync.engine import SyncEngine

log = logging.getLogger(__name__)


def _plain(obj):
    """Recursively convert dataclasses/lists into JSON-safe structures."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_plain(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    return obj


class Api:
    def __init__(self):
        self.settings = config.load_settings()
        self.spotify_auth = SpotifyAuth(
            self.settings["spotify_client_id"], self.settings["spotify_redirect_port"]
        )
        self.tidal_auth = TidalAuth()
        self.spotify_client = SpotifyClient(self.spotify_auth.get_valid_access_token)
        self.tidal_client = TidalClient(self.tidal_auth.get_session)
        self.engine = SyncEngine(self.spotify_client, self.tidal_client)
        self.scheduler = None  # wired up by main.py after construction
        self._busy_lock = threading.Lock()

    # ---- status / settings --------------------------------------------

    def get_status(self):
        return {
            "spotify_connected": self.spotify_auth.is_connected(),
            "tidal_connected": self.tidal_auth.is_connected(),
            "settings": self.settings,
            "paused": bool(self.scheduler.paused) if self.scheduler else False,
        }

    def save_settings(self, settings: dict):
        self.settings.update(settings)
        config.save_settings(self.settings)
        # Client ID / port may have changed -- rebuild the Spotify auth
        # helper and repoint the client at its (possibly refreshed) token getter.
        self.spotify_auth = SpotifyAuth(
            self.settings["spotify_client_id"], self.settings["spotify_redirect_port"]
        )
        self.spotify_client._get_token = self.spotify_auth.get_valid_access_token
        return {"ok": True}

    # ---- auth -----------------------------------------------------------

    def connect_spotify(self):
        log.info("connect_spotify() called")
        ok, message = self.spotify_auth.login()
        log.info("connect_spotify result: ok=%s message=%s", ok, message)
        return {"ok": ok, "message": message}

    def disconnect_spotify(self):
        log.info("disconnect_spotify() called")
        self.spotify_auth.logout()
        return {"ok": True}

    def connect_tidal(self):
        log.info("connect_tidal() called")
        holder: dict = {}

        def on_url(url: str) -> None:
            log.info("TIDAL login URL ready, opening browser: %s", url)
            holder["url"] = url
            webbrowser.open(url)

        ok, message = self.tidal_auth.login(on_url)
        log.info("connect_tidal result: ok=%s message=%s", ok, message)
        return {"ok": ok, "message": message, "url": holder.get("url")}

    def disconnect_tidal(self):
        log.info("disconnect_tidal() called")
        self.tidal_auth.logout()
        return {"ok": True}

    # ---- playlists / pairs -----------------------------------------------

    def get_dashboard(self):
        if not (self.spotify_auth.is_connected() and self.tidal_auth.is_connected()):
            log.info("get_dashboard: not both connected, skipping")
            return {"error": "Connect both Spotify and TIDAL first."}
        try:
            data = self.engine.suggest_pairs()
        except Exception as exc:
            log.exception("get_dashboard failed")
            return {"error": str(exc)}
        return {
            "linked": _plain(data["linked"]),
            "suggestions": [
                {"spotify": _plain(s["spotify"]), "tidal": _plain(s["tidal"])}
                for s in data["suggestions"]
            ],
            "unmatched_spotify": _plain(data["unmatched_spotify"]),
            "unmatched_tidal": _plain(data["unmatched_tidal"]),
        }

    def create_pair(self, spotify_playlist: dict, tidal_playlist: dict, direction: str = "spotify_to_tidal"):
        log.info(
            "create_pair: %r <-> %r (direction=%s)",
            spotify_playlist.get("name"), tidal_playlist.get("name"), direction,
        )
        pair_id = db.create_pair(
            spotify_playlist_id=spotify_playlist.get("id"),
            spotify_playlist_name=spotify_playlist.get("name"),
            tidal_playlist_id=tidal_playlist.get("id"),
            tidal_playlist_name=tidal_playlist.get("name"),
            direction=direction,
        )
        return {"ok": True, "pair_id": pair_id}

    def create_playlist_and_pair(self, source_provider: str, playlist: dict, direction: str = ""):
        """Creates a new playlist on the *other* service (matching name)
        and links it to `playlist` as a pair."""
        try:
            if source_provider == "spotify":
                created = self.tidal_client.create_playlist(playlist["name"])
                return self.create_pair(playlist, _plain(created), direction or "spotify_to_tidal")
            else:
                created = self.spotify_client.create_playlist(playlist["name"])
                return self.create_pair(_plain(created), playlist, direction or "tidal_to_spotify")
        except Exception as exc:
            log.exception("create_playlist_and_pair failed")
            return {"ok": False, "error": str(exc)}

    def update_pair(self, pair_id: int, fields: dict):
        db.update_pair(pair_id, **fields)
        return {"ok": True}

    def delete_pair(self, pair_id: int):
        db.delete_pair(pair_id)
        return {"ok": True}

    def get_history(self, limit: int = 50):
        return db.get_history(limit)

    # ---- sync -------------------------------------------------------------

    def sync_pair_now(self, pair_id: int, dry_run: bool = False):
        log.info("sync_pair_now(pair_id=%s, dry_run=%s) called", pair_id, dry_run)
        pair = db.get_pair(pair_id)
        if not pair:
            log.warning("sync_pair_now: pair %s not found", pair_id)
            return {"error": "Pair not found."}
        with self._busy_lock:
            result = self.engine.sync_pair(pair, dry_run=dry_run)
        return _plain(result)

    def sync_all_now(self, dry_run: bool = False):
        log.info("sync_all_now(dry_run=%s) called", dry_run)
        with self._busy_lock:
            results = self.engine.sync_all(dry_run=dry_run)
        return [_plain(r) for r in results]

    def toggle_pause(self):
        if self.scheduler:
            self.scheduler.paused = not self.scheduler.paused
        return {"paused": bool(self.scheduler.paused) if self.scheduler else False}

    # ---- duplicate removal ------------------------------------------------

    def deduplicate_playlist(self, provider: str, playlist_id: str, dry_run: bool = False):
        log.info("deduplicate_playlist(provider=%s, playlist_id=%s, dry_run=%s) called", provider, playlist_id, dry_run)
        try:
            result = self.engine.deduplicate_playlist(provider, playlist_id, dry_run=dry_run)
            return {"ok": True, **result}
        except Exception as exc:
            log.exception("deduplicate_playlist failed")
            return {"ok": False, "error": str(exc)}
