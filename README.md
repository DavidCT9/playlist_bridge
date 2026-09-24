# PlaylistBridge

A desktop app that keeps playlists in sync between **Spotify** and **TIDAL**:
it detects which of your playlists already have a counterpart on the other
service, links them, and then adds new tracks / removes deleted ones to keep
each pair matching -- automatically, in the background, for as long as the
app is running.

## How it works, in one paragraph

You sign into Spotify and TIDAL with your own accounts (nothing is typed
into this app itself -- both logins happen on the real Spotify/TIDAL pages in
your browser). PlaylistBridge then lists both accounts' playlists, suggests
pairs whose names match, and lets you confirm them or link others by hand.
For each linked pair it compares tracks by **ISRC** (the industry code that
identifies a specific recording across every streaming service) and falls
back to fuzzy title/artist/duration matching when a track is missing that
code. It then adds what's missing and -- unless you chose an "add-only" mode
-- removes what's no longer in the source playlist. A background scheduler
repeats this on a timer you control, and a tray icon keeps it running after
you close the window.

## Before you start: what to expect

This was built and syntax-checked in a sandboxed environment with no
internet access, so it could not be run end-to-end against the real Spotify
and TIDAL APIs before reaching you -- that final test can only happen on
your machine, with your accounts. The code follows both providers' documented
behavior closely and defensively (timeouts, retries, clear error messages),
but budget a few minutes for first-run troubleshooting; see
[Troubleshooting](#troubleshooting).

Two honesty notes worth reading before you invest time in this:

- **TIDAL has no public developer program for third-party apps** like
  Spotify does. This app talks to TIDAL through
  [`tidalapi`](https://github.com/EbbLabs/python-tidal), a well-maintained
  open-source library that uses the same device-login flow TIDAL's own TV
  and car apps use. It's the same approach tools like Soundiiz effectively
  rely on. It can break if TIDAL changes something server-side, and you're
  using it under TIDAL's terms for your own account -- it never touches
  playback, downloads, or DRM, only playlist metadata.
- **Matching isn't always perfect.** A track missing from one catalog,
  regional availability differences, or an unusual remaster can mean a track
  is skipped rather than wrongly matched. Skipped tracks are counted and
  logged rather than silently dropped -- see the Activity panel.

## Features

- Sign-in through Spotify's and TIDAL's own login pages (OAuth) -- this app
  never sees or stores your password.
- Auto-detects playlists that already exist on both sides by name, and lists
  the rest so you can link or create them with one click.
- ISRC-first track matching with a fuzzy fallback.
- Four sync modes per pair: mirror (add + remove) or add-only, in either
  direction.
- Dry-run mode to preview a sync before applying it.
- Background auto-sync on a timer, plus a tray icon so it keeps syncing
  after you close the window.
- Full sync history log (what was added/removed/skipped, and when).

## Security & privacy

- **No secrets are hardcoded or shipped.** Spotify login uses Authorization
  Code + PKCE, the flow designed for apps that can't safely keep a secret --
  so no client secret is ever needed or stored, only a non-secret Client ID
  you obtain yourself.
- **Tokens live in your OS's credential store** (Windows Credential Manager,
  macOS Keychain, or the Linux Secret Service/KWallet) via the `keyring`
  library -- never in a plain-text file. The one exception is the TIDAL
  session file, which `tidalapi` manages itself in a particular format;
  PlaylistBridge locks that file's permissions down to your OS user account
  only (`chmod 600`).
- **Nothing is exposed to the network.** The only server this app ever runs
  is a one-shot HTTP listener bound strictly to `127.0.0.1`, used only to
  catch the Spotify login redirect for a few seconds, then immediately shut
  down. It never binds `0.0.0.0` and is never reachable from another device.
- **OAuth `state` is validated** on the Spotify callback to prevent
  authorization-code injection.
- The local SQLite database only stores playlist names/IDs and sync history
  -- never credentials.

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux with a desktop environment
- A free Spotify account and a free or paid TIDAL account

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create your own Spotify app** (required -- Spotify requires every app
   to register its own Client ID):
   - Go to <https://developer.spotify.com/dashboard> and log in.
   - Click **Create app**. Name it anything (e.g. "PlaylistBridge").
   - Under **Redirect URIs**, add exactly:
     `http://127.0.0.1:8765/callback`
     (If you change the port in Settings later, update this to match.)
   - Save, then copy the **Client ID** shown on the app's page. You will
     *not* need the Client Secret -- PlaylistBridge uses the PKCE flow,
     which doesn't need one.

3. **Run the app**
   ```bash
   python main.py
   ```

4. On first launch, open **Settings** and paste in your Spotify Client ID
   (the redirect port defaults to `8765`, matching step 2). Save.

5. Click **Connect Spotify** and **Connect TIDAL** and approve access in the
   browser windows that open.

6. PlaylistBridge lists suggested playlist matches -- confirm the ones you
   want, and use **Create on TIDAL / Create on Spotify** for playlists that
   only exist on one side. Turn on **auto** per pair (on by default) and it
   will keep syncing on the interval set in Settings.

## Automatic syncing -- how it actually runs

There are two layers:

1. **While the app is open** (including minimized to the tray): a background
   thread syncs every N minutes (Settings, default 30), plus once right
   after startup.
2. **Start the app automatically at login**, so it's effectively always
   running in the background, using the helper script for your OS:
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts\install_autostart_windows.ps1`
   - macOS: `bash scripts/install_autostart_macos.sh`
   - Linux: `bash scripts/install_autostart_linux.sh`

   Each script only adds a per-user startup entry; nothing needs admin/root
   rights, and each is easy to remove (the script prints how).

Closing the main window hides it to the tray rather than quitting, so
auto-sync keeps running -- use the tray menu's **Quit** to actually exit.

## Building a standalone executable (optional)

Once you've confirmed the app runs with `python main.py`, you can package it
with PyInstaller so it doesn't need a Python install to launch:

```bash
pip install pyinstaller
pyinstaller --name PlaylistBridge --windowed --noconfirm \
  --add-data "frontend:frontend" main.py
```

(On Windows, use `--add-data "frontend;frontend"` -- semicolon, not colon.)
The executable will be in `dist/PlaylistBridge/`.

## Troubleshooting

- **"Could not bind 127.0.0.1:8765"** -- another process is using that port.
  Pick a different port in Settings, update the redirect URI on your Spotify
  app to match, and try again.
- **"Security check failed (state mismatch)"** -- the login took too long or
  was retried in another tab; just click Connect Spotify again.
- **TIDAL login times out** -- the device-login link expires after a few
  minutes; click Connect TIDAL again and approve it promptly.
- **A track is always skipped** -- it's likely unavailable in your region on
  the destination service, or its metadata differs enough that the matcher
  can't confirm it confidently. Check the Activity log's skipped count;
  nothing is guessed at silently.
- **Nothing syncs on schedule** -- check the "Pause auto-sync" checkbox is
  off, and that the app (or an autostart entry) is actually running.
- **Closing the window quits the app instead of minimizing to the tray** --
  a small number of pywebview/renderer combinations don't honor the
  "cancel close" hook `app/main.py` uses for this. It's cosmetic, not a
  data-safety issue: your linked pairs and history are saved regardless.
  Work around it by using the autostart script for your OS so the app is
  always running in the background rather than relying on it staying open
  after you close the window.

## Project layout

```
app/
  auth/            OAuth flows (Spotify PKCE, TIDAL device login)
  services/        Thin API clients (Spotify Web API, tidalapi)
  sync/            Matching (ISRC + fuzzy) and the diff/apply engine
  api.py           JS <-> Python bridge exposed to the UI
  db.py            SQLite storage for pairs and sync history
  scheduler.py     Background auto-sync timer
  tray.py          System tray icon
  main.py          App entry point (window, scheduler, tray wiring)
frontend/          HTML/CSS/JS UI (rendered in a pywebview window)
scripts/           Per-OS autostart-at-login helpers
```

## License

Use, modify, and share freely for your own personal projects.
