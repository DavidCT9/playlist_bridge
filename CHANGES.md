# QA pass — 2026-09-27 (round 3)

Added a real, executable test suite (123 tests: 98 Python + 25 JS -- see
`TESTING.md`) and used it to find and fix two more small issues that
manual review alone hadn't caught:

- **`datetime.utcnow()` is deprecated in Python 3.12+.** Still worked,
  but printed a `DeprecationWarning` on every sync. Replaced with the
  officially-recommended equivalent (`datetime.now(timezone.utc)`, then
  stripped back to naive UTC) in `db.py` and `engine.py` -- produces the
  *exact same* stored string format, so this doesn't touch your existing
  database rows or the frontend's date parsing.
- **Re-verified every `tidalapi` method actually used** (`session.playlist()`,
  `playlist.add()`, `.remove_by_id()`, `.remove_by_index()`,
  `.tracks()`, `user.create_playlist()`, `login_oauth_simple()`,
  `login_session_file()`) against real source/changelog evidence, not
  just search snippets as before -- all confirmed correct.
- No sync-breaking bugs found this round; the fixes above are
  robustness/hygiene, not behavior changes.

See `TESTING.md` for what's covered, what isn't (and can't be without
live accounts), and how to run it yourself.

---

# Fixes applied — 2026-09-24 (round 2)

## Root cause of "detects playlists but doesn't add songs"

My previous fix made `get_playlist_tracks()` request **both** `track(...)`
and `item(...)` in the same Spotify `fields` filter, as a defensive hedge.
That was the bug. Evidence: your pasted log's `INFO app.services.spotify_client`
lines only exist in that fix's code, and every sync in that log window
completed with status `success` and `+0 -0` -- no error, just an empty diff.
Spotify's `fields` filter can silently return `{}` for a whole nested object
when part of the filter no longer matches the schema, instead of erroring.
An empty list compared to an empty list looks like "already in sync" to the
diff engine -- which is exactly what you saw. Meanwhile `list_playlists()`
(used for discovery) never used a `fields` filter, which is why playlist
*discovery* kept working the whole time while track-level sync silently did
nothing.

**Fix:** `get_playlist_tracks()` now fetches full, unfiltered objects and
parses `item` (falling back to `track`) in Python, removing the fields-filter
guesswork entirely. It also logs the raw key shape of the first entry once
per call, so if this diagnosis is somehow still wrong, your next log capture
will show conclusively what Spotify is actually sending, rather than another
round of guessing.

## New: duplicate-track removal

Added a proper "Dedupe" action, available per-side on every linked pair and
on every unmatched playlist. It:
- Fetches the playlist with each track's exact position.
- Groups tracks by ISRC (or the same fuzzy title/artist/duration match used
  for cross-service sync) to find duplicates, always keeping the *first*
  occurrence of each song.
- Removes only the extra occurrences, **by exact position** -- not by track
  ID/URI. This matters: Spotify's/TIDAL's plain "remove track X" deletes
  *every* copy of X, which would be exactly wrong for deduping (it would
  wipe the song entirely instead of trimming it to one copy). Positions are
  removed highest-to-lowest so earlier positions stay valid mid-operation.

New methods: `get_playlist_tracks_with_position()` and
`remove_tracks_at_positions()` on both `SpotifyClient` and `TidalClient`;
`find_duplicates()` in `matcher.py`; `deduplicate_playlist()` in the sync
engine and exposed via `api.py`. UI: a "Dedupe" button next to each
playlist in the Linked and Not-yet-linked sections. It asks for confirmation
first (it's a real deletion) and reports how many duplicates it removed.

## Please re-run and re-check

1. Run `python3 main.py`, then click **Sync now** on a pair (or **Sync all
   now**) rather than just watching the dashboard -- the dashboard's
   auto-refresh every 25s only re-lists playlists, it never syncs by itself.
2. Watch for the new `first raw entry keys=...` log line for each playlist --
   paste that back to me if anything still looks wrong, it'll show exactly
   what Spotify is sending.
3. If you've made any other local edits, re-upload the project as a zip
   (I couldn't reach your GitHub repo directly -- see chat for why).

---

# Fixes applied — 2026-09-23

## Root cause

Spotify shipped a breaking Web API change in **February 2026** — after this
project was originally built — that renamed the playlist track-management
endpoints from `/tracks` to `/items`, along with related field/body renames.
Full details: https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide

Your edit to `spotify_client.py` (changing the URLs from `/tracks` to
`/items`) correctly identified this, but three related pieces still needed
updating:

## `app/services/spotify_client.py`
1. **`get_playlist_tracks()`** — the `fields` filter still asked for
   `items(track(...))` and the parser still read `entry["track"]`. Spotify
   renamed each entry's key from `track` to `item`. Fixed to request and
   parse **both** `item(...)` and `track(...)`, using whichever is present
   — safe during Spotify's deprecation window and after it ends.
2. **`remove_tracks()`** — the DELETE body still sent `{"tracks": [...]}`.
   Spotify's migration guide explicitly renamed this body parameter to
   `{"items": [...]}`. This alone would make every track removal fail.
3. **`create_playlist()`** — was still calling `POST /users/{id}/playlists`,
   which the Feb 2026 update **removed outright** (not renamed — gone).
   Replaced with `POST /me/playlists`, which no longer needs a separate
   "get current user" call first.
4. `list_playlists()` — the per-playlist track *count* (display only, not
   used by sync logic) had the same `tracks`→`items` rename applied.

## `app/tray.py`
`run_tray_in_background()` had `threading.Thread(target=icon.run_detached(),
daemon=True)` — the `()` calls `run_detached()` immediately while
*constructing* the Thread object, not when the thread starts, and
`run_detached()` already manages its own background thread internally.
Fixed to call `icon.run_detached()` directly with nothing wrapped around it.

## `frontend/style.css`
An input/select rule had `color: var(--bg)` instead of `var(--text)`,
making typed text (e.g. in Settings) nearly invisible against its own
background. Cosmetic, unrelated to sync, fixed anyway.

## `app/main.py`
The background scheduler was calling `api.engine.sync_all()` directly,
bypassing the lock `sync_pair_now`/`sync_all_now` use. That meant a manual
"Sync now" click and a scheduled sync could run concurrently against the
same playlist. Now routed through `api.sync_all_now()` so they're always
serialized.

## Logging (added throughout)
`app/services/spotify_client.py`, `app/services/tidal_client.py`,
`app/sync/engine.py`, `app/scheduler.py`, `app/api.py`,
`app/auth/spotify_auth.py`, `app/auth/tidal_auth.py`, `app/main.py` all now
log each meaningful step at INFO level (and warnings/errors where something
didn't work) instead of only logging on unhandled exceptions. Run
`python3 main.py` from a terminal and you'll now see, per sync: which pair,
which direction, how many tracks were fetched from each side, the computed
diff, each track resolved or skipped on the destination, and the final
added/removed/skipped counts.

## Removed
`app.py` at the project root — contained only the literal text "updated
code", not real code. Looked like an accidental stray save; deleted.
