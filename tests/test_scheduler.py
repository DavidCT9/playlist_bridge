import threading
import time
import unittest

import tests  # noqa: F401
from app.scheduler import Scheduler


class TestScheduler(unittest.TestCase):
    def test_trigger_now_runs_the_callback(self):
        called = threading.Event()
        sched = Scheduler(run_sync=lambda: called.set(), get_interval_minutes=lambda: 60)
        sched.trigger_now()
        self.assertTrue(called.wait(timeout=2), "trigger_now() should invoke run_sync promptly")

    def test_exception_in_run_sync_does_not_propagate(self):
        def boom():
            raise RuntimeError("sync exploded")
        sched = Scheduler(run_sync=boom, get_interval_minutes=lambda: 60)
        sched.trigger_now()
        time.sleep(0.2)

    def test_paused_scheduler_still_allows_manual_trigger(self):
        calls = []
        sched = Scheduler(run_sync=lambda: calls.append(1), get_interval_minutes=lambda: 0.01)
        sched.paused = True
        sched.trigger_now()
        time.sleep(0.2)
        self.assertEqual(calls, [1], "trigger_now() should run even while paused (manual sync still works)")

    def test_interval_minutes_has_a_floor_of_5_seconds(self):
        sched = Scheduler(run_sync=lambda: None, get_interval_minutes=lambda: 0)
        interval_seconds = max(5, sched._get_interval_minutes()) * 60
        self.assertEqual(interval_seconds, 300)

    def test_start_is_idempotent(self):
        sched = Scheduler(run_sync=lambda: None, get_interval_minutes=lambda: 60)
        sched.start()
        t1 = sched._thread
        sched.start()
        t2 = sched._thread
        self.assertIs(t1, t2)
        sched.stop()

    def test_stop_signals_the_loop_to_exit(self):
        sched = Scheduler(run_sync=lambda: None, get_interval_minutes=lambda: 60)
        sched.start()
        self.assertTrue(sched._thread.is_alive())
        sched.stop()
        sched._thread.join(timeout=2)
        self.assertFalse(sched._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
