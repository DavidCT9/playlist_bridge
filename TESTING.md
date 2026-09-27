# Testing

This project has a real test suite, not just manual spot-checks. What it
covers and doesn't:

**Covered (network-free, runs anywhere):**
- Every pure-logic module: track/duplicate matching (`matcher.py`), the
  diff/apply engine (`engine.py`, all 4 sync modes + dry-run + dedup), the
  database layer (`db.py`), settings persistence (`config.py`), the
  background scheduler's threading behavior (`scheduler.py`), PKCE token
  generation, and Spotify's token-refresh logic.
- `SpotifyClient` and `TidalClient` against **mocked HTTP/API responses
  shaped exactly like Spotify's and TIDAL's real, documented schemas** --
  including a regression test that specifically asserts the `fields`
  filter bug (the one that caused "detects playlists but adds nothing")
  can't come back, and a test that verifies the duplicate-removal
  position math handles the >100-item batching edge case correctly.
- Every module in the app imports cleanly (`test_imports.py`) -- catches
  typos/missing names across the whole codebase, including `main.py`.
- The frontend's pure JavaScript (`esc()`, `relativeTime()`, every
  `render*()` template function, `DIRECTION_LABELS`) via a small Node
  harness that actually executes `frontend/app.js`, not a reimplementation
  of it. Includes a round-trip regression test for the quote-escaping bug
  fixed earlier (a playlist name containing `"` or `'` breaking the
  HTML-attribute-embedded JSON payload).

**Not covered, and can't be without your real accounts:** actually calling
the live Spotify/TIDAL APIs, the OAuth browser flows end-to-end, or the
GUI rendering itself (pywebview needs a real display). The mocked tests
prove the code *handles* realistic responses correctly; they can't prove
Spotify/TIDAL will keep sending exactly those shapes forever.

## Running the tests

```bash
# Python (98 tests, stdlib unittest only -- no extra install needed)
python3 -m unittest discover -s tests -p "test_*.py" -v

# JavaScript (25 tests, needs Node.js, no npm install needed)
node tests/js/run_js_tests.js
```

The Python tests use lightweight stand-ins for `requests`, `keyring`,
`tidalapi`, `pywebview`, `pystray`, and `PIL` (see `tests/_stubs/`) so the
suite runs without any of the app's real dependencies installed -- your
actual `requirements.txt` is unaffected, this is a test-only convenience.
`tests/` is not needed to run the app itself; delete it if you'd rather
not carry it around.
