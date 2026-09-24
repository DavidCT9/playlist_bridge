"""System tray icon so PlaylistBridge can keep syncing in the
background after the main window is closed, similar to how a sync
client like Dropbox behaves.
"""
from __future__ import annotations

import pystray
from PIL import Image, ImageDraw


def _make_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(124, 156, 255, 255))
    draw.ellipse((22, 22, 42, 42), fill=(18, 19, 26, 255))
    return img


def build_tray(on_open, on_sync_now, on_toggle_pause, on_quit, is_paused) -> pystray.Icon:
    menu = pystray.Menu(
        pystray.MenuItem("Open PlaylistBridge", on_open, default=True),
        pystray.MenuItem("Sync now", on_sync_now),
        pystray.MenuItem("Pause auto-sync", on_toggle_pause, checked=lambda item: is_paused()),
        pystray.MenuItem("Quit", on_quit),
    )
    return pystray.Icon("PlaylistBridge", _make_icon_image(), "PlaylistBridge", menu)


def run_tray_in_background(icon: pystray.Icon) -> None:
    # icon.run_detached() spawns and manages the tray's own background
    # thread internally -- it must be *called*, not passed as `target=`
    # to a Thread (that would invoke it immediately, while the Thread
    # object is being constructed, before .start() ever runs, and then
    # start a second, pointless empty thread around its return value).
    icon.run_detached()
