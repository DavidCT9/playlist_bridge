import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests  # noqa: F401


class TestApi(unittest.TestCase):
    def setUp(self):
        import app.config as config
        import app.db as db
        import keyring
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DB_PATH = Path(self._tmpdir.name) / "test.db"
        config.SETTINGS_PATH = Path(self._tmpdir.name) / "settings.json"
        db.DB_PATH = config.DB_PATH
        db.init_db()
        keyring._reset()
        from app.api import Api
        self.Api = Api
        self.api = Api()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_get_status_reports_disconnected_by_default(self):
        status = self.api.get_status()
        self.assertFalse(status["spotify_connected"])
        self.assertFalse(status["tidal_connected"])

    def test_save_settings_persists_and_rebuilds_spotify_auth(self):
        old_auth = self.api.spotify_auth
        res = self.api.save_settings({
            "spotify_client_id": "newid123",
            "spotify_redirect_port": 9999,
            "sync_interval_minutes": 10,
            "auto_sync_enabled": False,
        })
        self.assertTrue(res["ok"])
        self.assertEqual(self.api.settings["spotify_client_id"], "newid123")
        self.assertIsNot(self.api.spotify_auth, old_auth)  # rebuilt with new client id
        self.assertEqual(self.api.spotify_auth.client_id, "newid123")

    def test_get_dashboard_requires_both_connected(self):
        result = self.api.get_dashboard()
        self.assertIn("error", result)

    def test_create_pair_then_list_and_delete(self):
        r = self.api.create_pair(
            {"id": "sp1", "name": "Runs"}, {"id": "td1", "name": "Runs TD"}, "spotify_to_tidal"
        )
        self.assertTrue(r["ok"])
        pair_id = r["pair_id"]
        self.assertEqual(len(self.api.__dict__), len(self.api.__dict__))  # sanity no-op
        import app.db as db
        self.assertEqual(len(db.list_pairs()), 1)

        upd = self.api.update_pair(pair_id, {"auto_sync": 0})
        self.assertTrue(upd["ok"])
        self.assertEqual(db.get_pair(pair_id)["auto_sync"], 0)

        d = self.api.delete_pair(pair_id)
        self.assertTrue(d["ok"])
        self.assertIsNone(db.get_pair(pair_id))

    def test_sync_pair_now_reports_missing_pair_cleanly(self):
        result = self.api.sync_pair_now(99999)
        self.assertIn("error", result)

    def test_deduplicate_playlist_wraps_exceptions_as_ok_false(self):
        with patch.object(self.api.engine, "deduplicate_playlist", side_effect=RuntimeError("boom")):
            result = self.api.deduplicate_playlist("spotify", "pl1")
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])

    def test_toggle_pause_without_scheduler_wired_does_not_crash(self):
        # api.scheduler starts as None until main.py wires it up
        self.assertIsNone(self.api.scheduler)
        result = self.api.toggle_pause()
        self.assertFalse(result["paused"])


if __name__ == "__main__":
    unittest.main()
