"""Spotify authentication using Authorization Code + PKCE.

Why PKCE: it is Spotify's recommended flow for apps that cannot keep a
secret safe (like a desktop app whose source the user can read), so
this app never stores -- or even asks for -- a client secret. Only a
Client ID (which is not sensitive) is needed.

How the redirect is caught: Spotify requires the redirect URI to be an
explicit loopback IP literal (http://127.0.0.1:PORT/callback -- Spotify
no longer accepts "localhost"). We start a one-shot HTTP server bound
only to 127.0.0.1, open the system browser for the actual login, and
shut the server down the instant it has captured the authorization
code. The server never binds 0.0.0.0, so it is never reachable from
outside this machine.

Tokens are stored via app.secure_store (the OS keychain), never in a
plain file.
"""
from __future__ import annotations

import http.server
import logging
import secrets
import threading
import time
import urllib.parse
import webbrowser
from typing import Optional

import requests

from app.auth.pkce import generate_code_challenge, generate_code_verifier
from app.config import SPOTIFY_SCOPES
from app.secure_store import delete, load_json, save_json

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
STORE_KEY = "spotify_tokens"

_CALLBACK_HTML = (
    "<html><body style='font-family:sans-serif;text-align:center;padding-top:4rem;"
    "background:#12131a;color:#edeef3'>"
    "<h2>PlaylistBridge</h2><p>Spotify connected. You can close this tab.</p>"
    "</body></html>"
)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures exactly one redirect and stores the query params on the
    server instance (not on the class), so concurrent logins never
    share state."""

    def do_GET(self):  # noqa: N802 -- required name for http.server
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            # e.g. a stray /favicon.ico request from the browser -- ignore
            # it so it can never be mistaken for the OAuth redirect.
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        self.server.oauth_result = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_CALLBACK_HTML.encode("utf-8"))
        self.server.oauth_done.set()

    def log_message(self, *args):  # silence default stderr access logs
        pass


class SpotifyAuth:
    def __init__(self, client_id: str, redirect_port: int):
        self.client_id = client_id
        self.redirect_port = redirect_port
        self.redirect_uri = f"http://127.0.0.1:{redirect_port}/callback"

    def is_connected(self) -> bool:
        return load_json(STORE_KEY) is not None

    def logout(self) -> None:
        delete(STORE_KEY)

    def login(self, timeout: int = 180) -> tuple[bool, str]:
        """Blocking call: opens the system browser, waits for the
        redirect, exchanges the code for tokens, and stores them.
        Returns (success, message)."""
        if not self.client_id.strip():
            return False, "Add your Spotify Client ID in Settings first."

        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        state = secrets.token_urlsafe(16)

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
            "scope": SPOTIFY_SCOPES,
        }
        auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

        try:
            server = http.server.HTTPServer(("127.0.0.1", self.redirect_port), _CallbackHandler)
        except OSError as exc:
            return False, (
                f"Could not bind 127.0.0.1:{self.redirect_port} ({exc}). "
                "Another app may be using that port -- change it in Settings."
            )
        server.oauth_result = {}
        server.oauth_done = threading.Event()

        server_thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
        )
        server_thread.start()

        webbrowser.open(auth_url)

        finished = server.oauth_done.wait(timeout)
        server.shutdown()  # stop the serve_forever loop (from this thread, not the server's)
        server_thread.join(timeout=5)
        try:
            server.server_close()
        except OSError:
            pass

        if not finished:
            return False, "Login timed out waiting for the browser redirect."

        result = server.oauth_result
        if "error" in result:
            return False, f"Spotify denied access: {result['error']}"
        if result.get("state") != state:
            return False, "Security check failed (state mismatch). Please try again."
        code = result.get("code")
        if not code:
            return False, "No authorization code received."

        try:
            token = self._exchange_code(code, verifier)
        except requests.RequestException as exc:
            return False, f"Token exchange failed: {exc}"

        save_json(STORE_KEY, token)
        return True, "Spotify connected."

    def _exchange_code(self, code: str, verifier: str) -> dict:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        resp = requests.post(TOKEN_URL, data=data, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        payload["obtained_at"] = time.time()
        return payload

    def get_valid_access_token(self) -> Optional[str]:
        """Returns a usable access token, transparently refreshing it
        if it has expired. Returns None if never connected or if the
        refresh itself fails (e.g. the user revoked access)."""
        tokens = load_json(STORE_KEY)
        if not tokens:
            log.warning("get_valid_access_token: no stored Spotify tokens -- not connected")
            return None

        expires_at = tokens.get("obtained_at", 0) + tokens.get("expires_in", 3600) - 60
        if time.time() < expires_at:
            return tokens["access_token"]

        log.info("Spotify access token expired, refreshing...")
        try:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": self.client_id,
            }
            resp = requests.post(TOKEN_URL, data=data, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            payload["obtained_at"] = time.time()
            payload.setdefault("refresh_token", tokens["refresh_token"])
            save_json(STORE_KEY, payload)
            log.info("Spotify token refreshed OK")
            return payload["access_token"]
        except requests.RequestException as exc:
            log.error("Spotify token refresh failed (you may need to reconnect Spotify): %s", exc)
            return None
