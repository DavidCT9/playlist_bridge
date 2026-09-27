"""Thin, explicit wrapper around the parts of the Spotify Web API this
app needs. Written directly against the REST endpoints (rather than a
third-party SDK) so pagination, batching and rate-limit handling are
all visible in one place.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Callable, Optional

import requests

from app.models import PlaylistRef, Track

API_BASE = "https://api.spotify.com/v1"
log = logging.getLogger(__name__)


class SpotifyAPIError(Exception):
    pass


class SpotifyClient:
    def __init__(self, get_token: Callable[[], Optional[str]]):
        self._get_token = get_token

    def _request(self, method: str, path: str, **kwargs) -> dict:
        token = self._get_token()
        if not token:
            raise SpotifyAPIError("Not connected to Spotify.")
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        url = path if path.startswith("http") else f"{API_BASE}{path}"

        for attempt in range(4):
            resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
            log.info("Spotify %s %s -> %s (attempt %d)", method, path, resp.status_code, attempt + 1)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "1")) + 1
                log.warning("Spotify rate-limited us on %s, waiting %ds", path, wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                log.error("Spotify %s %s failed: %s", method, path, resp.text[:300])
                raise SpotifyAPIError(f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
            return resp.json() if resp.text else {}
        raise SpotifyAPIError(f"Rate limited too many times on {path}")

    def get_current_user(self) -> dict:
        return self._request("GET", "/me")

    def list_playlists(self) -> list[PlaylistRef]:
        playlists: list[PlaylistRef] = []
        url = "/me/playlists?limit=50"
        while url:
            data = self._request("GET", url)
            for item in data.get("items", []):
                count_obj = item.get("items") or item.get("tracks") or {}
                playlists.append(
                    PlaylistRef(
                        id=item["id"],
                        provider="spotify",
                        name=item["name"],
                        track_count=count_obj.get("total", 0),
                        owner=(item.get("owner") or {}).get("display_name"),
                    )
                )
            url = data.get("next")
            if url:
                url = url.replace(API_BASE, "")
        log.info("Spotify: found %d playlists", len(playlists))
        return playlists

    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        tracks: list[Track] = []
        skipped = 0
        logged_shape = False
        # NOTE: deliberately no `fields` filter here. Spotify's fields
        # filter can silently return {} for a whole nested object when
        # asked for a sub-key it no longer serves, instead of erroring --
        # which looks identical to "playlist has 0 tracks" downstream.
        # Fetching full objects and parsing defensively (item first, then
        # track) in Python avoids that failure mode entirely.
        url = f"/playlists/{playlist_id}/items?limit=100"
        while url:
            data = self._request("GET", url)
            entries = data.get("items", [])
            for entry in entries:
                if not logged_shape:
                    log.info(
                        "Spotify playlist %s: first raw entry keys=%s, item-or-track keys=%s",
                        playlist_id, list(entry.keys()),
                        list((entry.get("item") or entry.get("track") or {}).keys()),
                    )
                    logged_shape = True
                t = entry.get("item") or entry.get("track")
                is_local = entry.get("is_local") or (t.get("is_local") if t else False)
                if not t or is_local or not t.get("id"):
                    skipped += 1
                    continue
                tracks.append(
                    Track(
                        id=t["id"],
                        provider="spotify",
                        title=t.get("name", ""),
                        artists=[a.get("name", "") for a in t.get("artists", [])],
                        duration_ms=t.get("duration_ms", 0),
                        isrc=(t.get("external_ids") or {}).get("isrc"),
                        uri=t.get("uri"),
                    )
                )
            url = data.get("next")
            if url:
                url = url.replace(API_BASE, "")
        log.info(
            "Spotify playlist %s: got %d usable tracks (%d skipped as local/unavailable)",
            playlist_id, len(tracks), skipped,
        )
        return tracks

    def get_playlist_tracks_with_position(self, playlist_id: str) -> list[tuple[int, Track]]:
        """Same data as get_playlist_tracks, paired with each track's
        0-based position in the playlist. Needed to remove specific
        duplicate occurrences rather than every copy of a track."""
        result: list[tuple[int, Track]] = []
        position = 0
        url = f"/playlists/{playlist_id}/items?limit=100"
        while url:
            data = self._request("GET", url)
            for entry in data.get("items", []):
                t = entry.get("item") or entry.get("track")
                is_local = entry.get("is_local") or (t.get("is_local") if t else False)
                if t and not is_local and t.get("id"):
                    result.append((
                        position,
                        Track(
                            id=t["id"],
                            provider="spotify",
                            title=t.get("name", ""),
                            artists=[a.get("name", "") for a in t.get("artists", [])],
                            duration_ms=t.get("duration_ms", 0),
                            isrc=(t.get("external_ids") or {}).get("isrc"),
                            uri=t.get("uri"),
                        ),
                    ))
                position += 1  # every slot counts, including skipped/local ones
            url = data.get("next")
            if url:
                url = url.replace(API_BASE, "")
        return result

    def remove_tracks_at_positions(self, playlist_id: str, uri_positions: list[tuple[str, int]]) -> None:
        """Removes exact occurrences (uri, position) rather than every
        copy of a uri. Batches from the highest position down to the
        lowest -- since positions are computed from the state *before*
        any removal, working top-down means positions from later
        batches are never invalidated by earlier ones."""
        pairs_sorted = sorted(uri_positions, key=lambda p: p[1], reverse=True)
        for i in range(0, len(pairs_sorted), 100):
            chunk = pairs_sorted[i : i + 100]
            by_uri: dict[str, list[int]] = {}
            for uri, pos in chunk:
                by_uri.setdefault(uri, []).append(pos)
            body = {"items": [{"uri": u, "positions": ps} for u, ps in by_uri.items()]}
            self._request("DELETE", f"/playlists/{playlist_id}/items", json=body)
        log.info("Spotify playlist %s: removed %d duplicate occurrence(s)", playlist_id, len(pairs_sorted))

    def create_playlist(self, name: str, description: str = "") -> PlaylistRef:
        data = self._request(
            "POST",
            "/me/playlists",
            json={"name": name, "description": description, "public": False},
        )
        log.info("Spotify: created playlist %r (id=%s)", name, data.get("id"))
        return PlaylistRef(id=data["id"], provider="spotify", name=data["name"])

    def add_tracks(self, playlist_id: str, uris: list[str]) -> None:
        for i in range(0, len(uris), 100):
            chunk = uris[i : i + 100]
            self._request("POST", f"/playlists/{playlist_id}/items", json={"uris": chunk})
        log.info("Spotify playlist %s: added %d track(s)", playlist_id, len(uris))

    def remove_tracks(self, playlist_id: str, uris: list[str]) -> None:
        for i in range(0, len(uris), 100):
            chunk = uris[i : i + 100]
            body = {"items": [{"uri": u} for u in chunk]}
            self._request("DELETE", f"/playlists/{playlist_id}/items", json=body)
        log.info("Spotify playlist %s: removed %d track(s)", playlist_id, len(uris))

    def search_track(self, title: str, artist: str, isrc: Optional[str] = None) -> list[Track]:
        query = f"isrc:{isrc}" if isrc else f"track:{title} artist:{artist}"
        data = self._request("GET", f"/search?type=track&limit=5&q={urllib.parse.quote(query)}")
        results = []
        for t in data.get("tracks", {}).get("items", []):
            results.append(
                Track(
                    id=t["id"],
                    provider="spotify",
                    title=t.get("name", ""),
                    artists=[a.get("name", "") for a in t.get("artists", [])],
                    duration_ms=t.get("duration_ms", 0),
                    isrc=(t.get("external_ids") or {}).get("isrc"),
                    uri=t.get("uri"),
                )
            )
        log.info("Spotify search %r -> %d candidate(s)", query, len(results))
        return results
