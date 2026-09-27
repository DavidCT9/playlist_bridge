"""Core sync engine.

Two jobs:
1. Discovery -- look at both accounts' playlists, tell the caller which
   are already linked, which look like they should be linked (name
   matches) and which have no counterpart on the other side at all.
2. Sync -- for a linked pair, diff the source playlist against the
   destination playlist and apply the difference, honoring the pair's
   chosen mode. One side is always the source of truth for a given
   pair (true bidirectional merging is deliberately not offered: once
   both sides can both add *and* delete independently, conflicting
   edits have no single correct resolution, and guessing one would
   risk silently discarding a user's changes). The four modes are:
     - spotify_to_tidal: TIDAL mirrors Spotify (adds + deletes).
     - tidal_to_spotify: Spotify mirrors TIDAL (adds + deletes).
     - spotify_to_tidal_additive: same source, but never deletes --
       only ever adds tracks missing from the destination.
     - tidal_to_spotify_additive: same, mirrored.
"""
from __future__ import annotations

import datetime as dt
import logging

from app import db
from app.models import DiffResult, PlaylistRef, SyncResult, Track
from app.sync.matcher import find_best_playlist_name_match, find_duplicates, find_match

log = logging.getLogger(__name__)

# direction -> (source provider, destination provider, delete on destination?)
DIRECTIONS: dict[str, tuple[str, str, bool]] = {
    "spotify_to_tidal": ("spotify", "tidal", True),
    "tidal_to_spotify": ("tidal", "spotify", True),
    "spotify_to_tidal_additive": ("spotify", "tidal", False),
    "tidal_to_spotify_additive": ("tidal", "spotify", False),
}


class SyncEngine:
    def __init__(self, spotify_client, tidal_client):
        self.clients = {"spotify": spotify_client, "tidal": tidal_client}

    # ---- discovery ---------------------------------------------------

    def suggest_pairs(self) -> dict:
        """Returns already-linked pairs, name-based suggestions for
        unlinked playlists, and whatever is left over with no obvious
        counterpart on the other side."""
        log.info("Discovering playlists on both services...")
        spotify_playlists: list[PlaylistRef] = self.clients["spotify"].list_playlists()
        tidal_playlists: list[PlaylistRef] = self.clients["tidal"].list_playlists()

        linked = db.list_pairs()
        linked_spotify_ids = {p["spotify_playlist_id"] for p in linked if p["spotify_playlist_id"]}
        linked_tidal_ids = {p["tidal_playlist_id"] for p in linked if p["tidal_playlist_id"]}

        unmatched_spotify = [p for p in spotify_playlists if p.id not in linked_spotify_ids]
        unmatched_tidal = [p for p in tidal_playlists if p.id not in linked_tidal_ids]

        suggestions = []
        remaining_tidal_names = [p.name for p in unmatched_tidal]
        for sp in unmatched_spotify:
            match_name = find_best_playlist_name_match(sp.name, remaining_tidal_names)
            if match_name:
                tp = next(p for p in unmatched_tidal if p.name == match_name)
                suggestions.append({"spotify": sp, "tidal": tp})
                remaining_tidal_names.remove(match_name)

        suggested_spotify_ids = {s["spotify"].id for s in suggestions}
        suggested_tidal_ids = {s["tidal"].id for s in suggestions}

        log.info(
            "Discovery: %d linked pair(s), %d suggested match(es), %d Spotify-only, %d TIDAL-only",
            len(linked), len(suggestions),
            len(unmatched_spotify) - len(suggestions), len(unmatched_tidal) - len(suggestions),
        )

        return {
            "linked": linked,
            "suggestions": suggestions,
            "unmatched_spotify": [p for p in unmatched_spotify if p.id not in suggested_spotify_ids],
            "unmatched_tidal": [p for p in unmatched_tidal if p.id not in suggested_tidal_ids],
        }

    # ---- diff / apply --------------------------------------------------

    def compute_diff(self, source_tracks: list[Track], dest_tracks: list[Track]) -> DiffResult:
        to_add = [t for t in source_tracks if find_match(t, dest_tracks) is None]
        to_remove = [t for t in dest_tracks if find_match(t, source_tracks) is None]
        return DiffResult(to_add=to_add, to_remove=to_remove)

    def _resolve_on_destination(self, track: Track, dest_name: str) -> Track | None:
        candidates = self.clients[dest_name].search_track(
            track.title, track.artists[0] if track.artists else "", track.isrc
        )
        return find_match(track, candidates)

    def sync_pair(self, pair: dict, dry_run: bool = False) -> SyncResult:
        started = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat()
        result = SyncResult(pair_id=pair["id"], dry_run=dry_run)
        pair_label = f"{pair.get('spotify_playlist_name')!r} <-> {pair.get('tidal_playlist_name')!r}"

        source_name, dest_name, mirror_deletes = DIRECTIONS.get(
            pair["direction"], DIRECTIONS["spotify_to_tidal"]
        )
        additive_only = not mirror_deletes
        log.info(
            "=== Sync pair #%s: %s | direction=%s (source=%s, dest=%s, delete=%s) dry_run=%s ===",
            pair["id"], pair_label, pair["direction"], source_name, dest_name, mirror_deletes, dry_run,
        )

        source_playlist_id = pair[f"{source_name}_playlist_id"]
        dest_playlist_id = pair[f"{dest_name}_playlist_id"]

        try:
            log.info("Fetching tracks from %s playlist %s (source)...", source_name, source_playlist_id)
            source_tracks = self.clients[source_name].get_playlist_tracks(source_playlist_id)
            log.info("Fetching tracks from %s playlist %s (destination)...", dest_name, dest_playlist_id)
            dest_tracks = self.clients[dest_name].get_playlist_tracks(dest_playlist_id)
        except Exception as exc:
            log.exception("Pair #%s: failed to read playlists", pair["id"])
            result.errors.append(f"Could not read playlists: {exc}")
            db.record_sync(pair["id"], started, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(), 0, 0, 0, "error", str(exc))
            return result

        log.info(
            "Pair #%s: source has %d track(s), destination has %d track(s)",
            pair["id"], len(source_tracks), len(dest_tracks),
        )

        diff = self.compute_diff(source_tracks, dest_tracks)
        log.info(
            "Pair #%s: diff -> %d to add, %d to remove%s",
            pair["id"], len(diff.to_add), len(diff.to_remove),
            " (removal disabled, add-only mode)" if additive_only else "",
        )

        resolved_to_add: list[Track] = []
        for track in diff.to_add:
            match = self._resolve_on_destination(track, dest_name)
            if match:
                log.info("  + resolved on %s: %r by %s", dest_name, track.title, ", ".join(track.artists))
                resolved_to_add.append(match)
            else:
                log.warning(
                    "  ! could not find %r by %s on %s -- skipping (not available there, or metadata too different to match confidently)",
                    track.title, ", ".join(track.artists), dest_name,
                )
                result.skipped += 1

        planned_removed = 0 if additive_only else len(diff.to_remove)

        if dry_run:
            result.added = len(resolved_to_add)
            result.removed = planned_removed
            log.info(
                "Pair #%s: DRY RUN complete -- would add %d, remove %d, skip %d",
                pair["id"], result.added, result.removed, result.skipped,
            )
            db.record_sync(
                pair["id"], started, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(),
                result.added, result.removed, result.skipped, "dry_run", "",
            )
            return result

        try:
            if resolved_to_add:
                uris = [t.uri or t.id for t in resolved_to_add]
                log.info("Pair #%s: adding %d track(s) to %s...", pair["id"], len(uris), dest_name)
                self.clients[dest_name].add_tracks(dest_playlist_id, uris)
                result.added = len(resolved_to_add)

            if not additive_only and diff.to_remove:
                uris = [t.uri or t.id for t in diff.to_remove]
                log.info("Pair #%s: removing %d track(s) from %s...", pair["id"], len(uris), dest_name)
                self.clients[dest_name].remove_tracks(dest_playlist_id, uris)
                result.removed = len(diff.to_remove)

            db.update_pair(pair["id"], last_synced_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat())
            db.record_sync(
                pair["id"], started, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(),
                result.added, result.removed, result.skipped, "success", "",
            )
            log.info(
                "Pair #%s: DONE -- added %d, removed %d, skipped %d",
                pair["id"], result.added, result.removed, result.skipped,
            )
        except Exception as exc:
            log.exception("Pair #%s: applying changes failed", pair["id"])
            result.errors.append(str(exc))
            db.record_sync(
                pair["id"], started, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(),
                result.added, result.removed, result.skipped, "error", str(exc),
            )

        return result

    def sync_all(self, dry_run: bool = False) -> list[SyncResult]:
        pairs = [p for p in db.list_pairs() if p["auto_sync"]]
        if not pairs:
            log.info(
                "sync_all: no pairs with auto-sync enabled (check the 'auto' checkbox next to each "
                "linked pair, and that at least one pair is linked at all)."
            )
            return []
        log.info("sync_all: starting sync for %d pair(s) (dry_run=%s)", len(pairs), dry_run)
        results = [self.sync_pair(p, dry_run=dry_run) for p in pairs]
        total_added = sum(r.added for r in results)
        total_removed = sum(r.removed for r in results)
        total_errors = sum(len(r.errors) for r in results)
        log.info(
            "sync_all: finished -- %d added, %d removed, %d error(s) across %d pair(s)",
            total_added, total_removed, total_errors, len(pairs),
        )
        return results

    # ---- duplicate removal -----------------------------------------------

    def deduplicate_playlist(self, provider: str, playlist_id: str, dry_run: bool = False) -> dict:
        """Scans one playlist on one service for duplicate tracks (same
        ISRC, or a confident fuzzy title/artist/duration match) and
        removes every occurrence after the first. Never touches the
        other service."""
        client = self.clients[provider]
        log.info("Dedup: scanning %s playlist %s...", provider, playlist_id)
        tracks_with_pos = client.get_playlist_tracks_with_position(playlist_id)
        duplicates = find_duplicates(tracks_with_pos)
        log.info(
            "Dedup: %s playlist %s -- %d duplicate occurrence(s) out of %d total track(s)",
            provider, playlist_id, len(duplicates), len(tracks_with_pos),
        )

        if dry_run or not duplicates:
            return {
                "total_tracks": len(tracks_with_pos),
                "duplicates_found": len(duplicates),
                "removed": len(duplicates) if dry_run else 0,
                "dry_run": dry_run,
            }

        if provider == "spotify":
            pairs = [(t.uri or t.id, pos) for pos, t in duplicates]
            client.remove_tracks_at_positions(playlist_id, pairs)
        else:
            client.remove_tracks_at_positions(playlist_id, [pos for pos, _t in duplicates])

        return {
            "total_tracks": len(tracks_with_pos),
            "duplicates_found": len(duplicates),
            "removed": len(duplicates),
            "dry_run": dry_run,
        }
