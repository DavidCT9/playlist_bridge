"""Runs sync_all() on a background timer for as long as the app
process is alive, so syncing happens automatically -- not just when
the user clicks a button.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, run_sync: Callable[[], object], get_interval_minutes: Callable[[], int]):
        self._run_sync = run_sync
        self._get_interval_minutes = get_interval_minutes
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.paused = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            log.info("Scheduler already running, ignoring duplicate start()")
            return
        log.info("Scheduler starting (interval=%d min)", self._get_interval_minutes())
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        log.info("Scheduler stopping")
        self._stop_event.set()

    def trigger_now(self) -> None:
        log.info("Manual sync triggered")
        threading.Thread(target=self._safe_run, daemon=True).start()

    def _safe_run(self) -> None:
        try:
            self._run_sync()
        except Exception:
            log.exception("Background sync failed")

    def _loop(self) -> None:
        self._stop_event.wait(5)  # let the window finish opening first
        while not self._stop_event.is_set():
            if self.paused:
                log.info("Scheduler: auto-sync is paused, skipping this cycle")
            else:
                log.info("Scheduler: running scheduled sync")
                self._safe_run()
            interval_seconds = max(5, self._get_interval_minutes()) * 60
            log.info("Scheduler: sleeping %d min until next cycle", interval_seconds // 60)
            self._stop_event.wait(interval_seconds)
