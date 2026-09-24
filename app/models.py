"""Provider-agnostic data models shared by the Spotify/TIDAL clients
and the sync engine, so the engine never has to know which provider a
track came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Track:
    id: str
    provider: str  # "spotify" | "tidal"
    title: str
    artists: list[str]
    duration_ms: int
    isrc: Optional[str] = None
    uri: Optional[str] = None  # what gets passed back to add/remove calls


@dataclass
class PlaylistRef:
    id: str
    provider: str
    name: str
    track_count: int = 0
    owner: Optional[str] = None


@dataclass
class DiffResult:
    to_add: list[Track] = field(default_factory=list)
    to_remove: list[Track] = field(default_factory=list)


@dataclass
class SyncResult:
    pair_id: int
    added: int = 0
    removed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False
