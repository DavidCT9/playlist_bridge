import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401


class TestDb(unittest.TestCase):
    def setUp(self):
        import app.config as config
        import app.db as db
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DB_PATH = Path(self._tmpdir.name) / "test.db"
        db.DB_PATH = config.DB_PATH
        db.init_db()
        self.db = db

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_create_and_get_pair(self):
        pair_id = self.db.create_pair(
            spotify_playlist_id="sp1", spotify_playlist_name="Runs",
            tidal_playlist_id="td1", tidal_playlist_name="Runs (TIDAL)",
            direction="spotify_to_tidal",
        )
        pair = self.db.get_pair(pair_id)
        self.assertIsNotNone(pair)
        self.assertEqual(pair["spotify_playlist_name"], "Runs")
        self.assertEqual(pair["auto_sync"], 1)

    def test_list_pairs_ordering_and_count(self):
        self.db.create_pair(spotify_playlist_id="a", spotify_playlist_name="A", tidal_playlist_id="a", tidal_playlist_name="A")
        self.db.create_pair(spotify_playlist_id="b", spotify_playlist_name="B", tidal_playlist_id="b", tidal_playlist_name="B")
        pairs = self.db.list_pairs()
        self.assertEqual(len(pairs), 2)

    def test_update_pair(self):
        pair_id = self.db.create_pair(spotify_playlist_id="a", spotify_playlist_name="A", tidal_playlist_id="a", tidal_playlist_name="A")
        self.db.update_pair(pair_id, direction="tidal_to_spotify", auto_sync=0)
        pair = self.db.get_pair(pair_id)
        self.assertEqual(pair["direction"], "tidal_to_spotify")
        self.assertEqual(pair["auto_sync"], 0)

    def test_update_pair_with_no_fields_is_a_noop_not_a_crash(self):
        pair_id = self.db.create_pair(spotify_playlist_id="a", spotify_playlist_name="A", tidal_playlist_id="a", tidal_playlist_name="A")
        self.db.update_pair(pair_id)
        self.assertIsNotNone(self.db.get_pair(pair_id))

    def test_delete_pair_also_clears_its_history(self):
        pair_id = self.db.create_pair(spotify_playlist_id="a", spotify_playlist_name="A", tidal_playlist_id="a", tidal_playlist_name="A")
        self.db.record_sync(pair_id, "t1", "t2", 5, 1, 0, "success", "")
        self.db.delete_pair(pair_id)
        self.assertIsNone(self.db.get_pair(pair_id))
        history = self.db.get_history(50)
        self.assertEqual([h for h in history if h["pair_id"] == pair_id], [])

    def test_history_includes_playlist_names_via_join(self):
        pair_id = self.db.create_pair(spotify_playlist_id="a", spotify_playlist_name="Alpha", tidal_playlist_id="a", tidal_playlist_name="Alpha TD")
        self.db.record_sync(pair_id, "t1", "t2", 3, 2, 1, "success", "")
        history = self.db.get_history(10)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["spotify_playlist_name"], "Alpha")
        self.assertEqual(history[0]["added_count"], 3)

    def test_history_survives_deleted_pair_via_left_join(self):
        self.db.record_sync(None, "t1", "t2", 0, 0, 0, "error", "boom")
        history = self.db.get_history(10)
        self.assertEqual(len(history), 1)
        self.assertIsNone(history[0]["spotify_playlist_name"])

    def test_get_history_limit(self):
        pair_id = self.db.create_pair(spotify_playlist_id="a", spotify_playlist_name="A", tidal_playlist_id="a", tidal_playlist_name="A")
        for i in range(5):
            self.db.record_sync(pair_id, f"t{i}", f"t{i}", 1, 0, 0, "success", "")
        self.assertEqual(len(self.db.get_history(3)), 3)


if __name__ == "__main__":
    unittest.main()
