"""Cross-provider track matching: ISRC first (the same recording has
the same ISRC on every service that carries it), then a fuzzy fallback
on normalized title/artist/duration for the common case where one side
is missing ISRC metadata.
"""
from __future__ import annotations

import difflib
import re
from typing import Optional

from app.models import Track

_NOISE_RE = re.compile(
    r"[\(\[][^)\]]*(feat\.?|ft\.?|with|remaster\w*|version|edit|mono|stereo)[^)\]]*[\)\]]",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]")

TITLE_MATCH_THRESHOLD = 0.82
ARTIST_MATCH_THRESHOLD = 0.80
PLAYLIST_NAME_THRESHOLD = 0.70
DURATION_TOLERANCE_MS = 4000


def normalize(text: str) -> str:
    text = text.lower()
    text = _NOISE_RE.sub("", text)
    text = _PUNCT_RE.sub("", text)
    return " ".join(text.split())


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def tracks_match(a: Track, b: Track) -> bool:
    if a.isrc and b.isrc:
        return a.isrc.strip().upper() == b.isrc.strip().upper()

    if _ratio(normalize(a.title), normalize(b.title)) < TITLE_MATCH_THRESHOLD:
        return False

    a_artists = {normalize(x) for x in a.artists if x}
    b_artists = {normalize(x) for x in b.artists if x}
    if a_artists and b_artists and not (a_artists & b_artists):
        primary_a = normalize(a.artists[0]) if a.artists else ""
        primary_b = normalize(b.artists[0]) if b.artists else ""
        if _ratio(primary_a, primary_b) < ARTIST_MATCH_THRESHOLD:
            return False

    if a.duration_ms and b.duration_ms:
        if abs(a.duration_ms - b.duration_ms) > DURATION_TOLERANCE_MS:
            return False

    return True


def find_match(track: Track, candidates: list[Track]) -> Optional[Track]:
    for candidate in candidates:
        if tracks_match(track, candidate):
            return candidate
    return None


def find_best_playlist_name_match(name: str, candidates: list[str]) -> Optional[str]:
    """Used only to *suggest* pairs the user still has to confirm --
    never to silently link playlists."""
    norm = normalize(name)
    best, best_ratio = None, 0.0
    for candidate in candidates:
        ratio = _ratio(norm, normalize(candidate))
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    return best if best_ratio >= PLAYLIST_NAME_THRESHOLD else None
