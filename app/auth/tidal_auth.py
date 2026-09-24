"""TIDAL authentication.

Important context: TIDAL does not run a public OAuth program for
third-party consumer apps the way Spotify does. This app talks to
TIDAL through `tidalapi`, an actively maintained open-source client
(https://github.com/EbbLabs/python-tidal) that performs the same
device-authorization flow (RFC 8628) TIDAL's own smart-TV and car apps
use, via a community-maintained OAuth client id bundled in the
library. You log in with your own TIDAL account, in your own browser,
on TIDAL's real login page -- your username and password never pass
through this app's code, only a short-lived link you approve.

Because this is unofficial, treat it the way you would any tool built
on a reverse-engineered API: it can break if TIDAL changes something
server-side, and it's on you to use it within TIDAL's terms for your
own account. It does not touch playback, downloads or DRM -- only
playlist metadata.

Session persistence: tidalapi owns the on-disk session file format
internally (login_session_file both restores and refreshes it), so
rather than re-implementing that schema ourselves we let the library
manage a single file inside our private app-data directory and lock
its permissions down to the current OS user only.
"""
from __future__ import annotations

import logging
import os
import stat
import threading
from typing import Callable, Optional

import tidalapi

from app.config import TIDAL_SESSION_PATH

log = logging.getLogger(__name__)


def _lock_down(path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


class TidalAuth:
    def __init__(self):
        self._session: Optional[tidalapi.Session] = None
        self._lock = threading.Lock()

    def is_connected(self) -> bool:
        return self.get_session() is not None

    def logout(self) -> None:
        with self._lock:
            self._session = None
        try:
            TIDAL_SESSION_PATH.unlink(missing_ok=True)
        except OSError:
            pass

    def get_session(self) -> Optional[tidalapi.Session]:
        """Returns a logged-in session, restoring/refreshing it from the
        local session file if needed. Never prompts for login."""
        with self._lock:
            if self._session is not None and self._session.check_login():
                return self._session
            if not TIDAL_SESSION_PATH.exists():
                log.warning("get_session: no TIDAL session file at %s -- not connected", TIDAL_SESSION_PATH)
                return None
            log.info("Loading TIDAL session from %s...", TIDAL_SESSION_PATH)
            session = tidalapi.Session()
            try:
                session.login_session_file(TIDAL_SESSION_PATH)
            except Exception as exc:
                log.error("TIDAL session restore failed (you may need to reconnect TIDAL): %s", exc)
                return None
            if session.check_login():
                log.info("TIDAL session restored OK")
                self._session = session
                _lock_down(TIDAL_SESSION_PATH)
                return session
            log.error("TIDAL session file loaded but check_login() returned False -- reconnect TIDAL")
            return None

    def login(self, url_callback: Callable[[str], None], timeout: int = 300) -> tuple[bool, str]:
        """Blocking call (safe to run off the UI thread -- pywebview
        already runs each js_api call on its own worker thread).
        `url_callback` is invoked with the TIDAL verification link the
        moment it is known, so the caller can open it in a browser."""
        session = tidalapi.Session()

        def relay(text: str) -> None:
            # tidalapi hands us a full sentence; pull out just the URL.
            for token in text.split():
                if token.startswith("http"):
                    url_callback(token)
                    return
            url_callback(text)

        try:
            session.login_session_file(TIDAL_SESSION_PATH, fn_print=relay)
        except Exception as exc:
            log.error("TIDAL login failed: %s", exc)
            return False, f"TIDAL login failed: {exc}"

        if not session.check_login():
            log.warning("TIDAL login: session file written but check_login() is False")
            return False, "TIDAL login was not completed in time."

        with self._lock:
            self._session = session
        _lock_down(TIDAL_SESSION_PATH)
        log.info("TIDAL login OK")
        return True, "TIDAL connected."
