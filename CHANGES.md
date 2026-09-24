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
