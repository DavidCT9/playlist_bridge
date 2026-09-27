"""Wraps a logged-in `tidalapi.Session` behind the same interface as
SpotifyClient, so the sync engine can treat both providers uniformly
without knowing which one it's talking to.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import tidalapi

from app.models import PlaylistRef, Track

log = logging.getLogger(__name__)


class TidalAPIError(Exception):
    pass


def _to_track(t) -> Optional[Track]:
    if t is None or getattr(t, "available", True) is False:
        return None
    artists = []
    if getattr(t, "artists", None):
        artists = [a.name for a in t.artists if getattr(a, "name", None)]
    elif getattr(t, "artist", None) and getattr(t.artist, "name", None):
        artists = [t.artist.name]
    duration = getattr(t, "duration", None)
    duration_ms = int(duration * 1000) if duration and duration > 0 else 0
    return Track(
        id=str(t.id),
        provider="tidal",
        title=t.name or "",
        artists=artists,
        duration_ms=duration_ms,
        isrc=getattr(t, "isrc", None),
        uri=str(t.id),
    )


class TidalClient:
    def __init__(self, get_session: Callable[[], Optional["tidalapi.Session"]]):
        self._get_session = get_session

    def _session(self) -> "tidalapi.Session":
        session = self._get_session()
        if session is None:
            raise TidalAPIError("Not connected to TIDAL.")
        return session

    def get_current_user(self) -> dict:
        session = self._session()
        return {"id": session.user.id, "name": getattr(session.user, "username", "TIDAL user")}

    def list_playlists(self) -> list[PlaylistRef]:
        session = self._session()
        result = []
        for p in session.user.playlists():
            result.append(
                PlaylistRef(
                    id=str(p.id),
                    provider="tidal",
                    name=p.name,
                    track_count=getattr(p, "num_tracks", 0) or 0,
                )
            )
        log.info("TIDAL: found %d playlist(s)", len(result))
        return result

    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        session = self._session()
        playlist = session.playlist(playlist_id)
        tracks = []
        skipped = 0
        for t in playlist.tracks():
            track = _to_track(t)
            if track:
                tracks.append(track)
            else:
                skipped += 1
        log.info(
            "TIDAL playlist %s: got %d usable tracks (%d skipped as unavailable)",
            playlist_id, len(tracks), skipped,
        )
        return tracks

    def get_playlist_tracks_with_position(self, playlist_id: str) -> list[tuple[int, Track]]:
        """Same data as get_playlist_tracks, paired with each track's
        0-based position -- needed to remove specific duplicate
        occurrences rather than every copy of a track."""
        session = self._session()
        playlist = session.playlist(playlist_id)
        result = []
        for i, t in enumerate(playlist.tracks()):
            track = _to_track(t)
            if track:
                result.append((i, track))
        return result

    def remove_tracks_at_positions(self, playlist_id: str, positions: list[int]) -> None:
        """Removes tracks at exact 0-based indices, highest first, so
        removing one doesn't shift the index of another we still need
        to remove."""
        session = self._session()
        playlist = session.playlist(playlist_id)
        removed = 0
        for pos in sorted(set(positions), reverse=True):
            try:
                playlist.remove_by_index(pos)
                removed += 1
            except AttributeError:
                log.warning(
                    "TIDAL: remove_by_index() not available in this tidalapi version -- "
                    "skipping position %d (upgrade tidalapi to use duplicate removal on TIDAL)",
                    pos,
                )
            except Exception as exc:
                log.warning("TIDAL playlist %s: could not remove position %d: %s", playlist_id, pos, exc)
        log.info("TIDAL playlist %s: removed %d/%d duplicate occurrence(s)", playlist_id, removed, len(positions))

    def create_playlist(self, name: str, description: str = "") -> PlaylistRef:
        session = self._session()
        playlist = session.user.create_playlist(name, description)
        log.info("TIDAL: created playlist %r (id=%s)", name, playlist.id)
        return PlaylistRef(id=str(playlist.id), provider="tidal", name=playlist.name)

    def add_tracks(self, playlist_id: str, track_ids: list[str]) -> None:
        session = self._session()
        playlist = session.playlist(playlist_id)
        ids = [int(t) for t in track_ids]
        for i in range(0, len(ids), 100):
            playlist.add(ids[i : i + 100])
        log.info("TIDAL playlist %s: added %d track(s)", playlist_id, len(ids))

    def remove_tracks(self, playlist_id: str, track_ids: list[str]) -> None:
        session = self._session()
        playlist = session.playlist(playlist_id)
        removed = 0
        for tid in track_ids:
            try:
                playlist.remove_by_id(int(tid))
                removed += 1
            except Exception as exc:
                log.warning("TIDAL playlist %s: could not remove track %s: %s", playlist_id, tid, exc)
        log.info("TIDAL playlist %s: removed %d/%d track(s)", playlist_id, removed, len(track_ids))

    def search_track(self, title: str, artist: str, isrc: Optional[str] = None) -> list[Track]:
        session = self._session()
        query = f"{title} {artist}".strip()
        results = None
        try:
            results = session.search(query, models=[tidalapi.Track])
        except Exception as exc:
            log.info("TIDAL search with models=[Track] failed (%s), retrying without it", exc)
            try:
                results = session.search(query)
            except Exception as exc2:
                log.warning("TIDAL search %r failed entirely: %s", query, exc2)
                return []

        if isinstance(results, dict):
            raw_tracks = results.get("tracks", [])
        else:
            raw_tracks = getattr(results, "tracks", None) or []

        out = []
        for t in raw_tracks[:5]:
            track = _to_track(t)
            if track:
                out.append(track)
        log.info("TIDAL search %r -> %d candidate(s)", query, len(out))
        return out
