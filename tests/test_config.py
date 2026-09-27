import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401
import app.config as config


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        config.SETTINGS_PATH = Path(self._tmpdir.name) / "settings.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_load_settings_returns_defaults_when_no_file(self):
        settings = config.load_settings()
        self.assertEqual(settings, config.DEFAULT_SETTINGS)

    def test_save_then_load_roundtrip(self):
        settings = dict(config.DEFAULT_SETTINGS)
        settings["spotify_client_id"] = "abc123"
        settings["sync_interval_minutes"] = 15
        config.save_settings(settings)
        loaded = config.load_settings()
        self.assertEqual(loaded["spotify_client_id"], "abc123")
        self.assertEqual(loaded["sync_interval_minutes"], 15)

    def test_load_merges_partial_file_with_defaults(self):
        config.SETTINGS_PATH.write_text('{"spotify_client_id": "xyz"}', encoding="utf-8")
        loaded = config.load_settings()
        self.assertEqual(loaded["spotify_client_id"], "xyz")
        self.assertIn("sync_interval_minutes", loaded)

    def test_load_survives_corrupt_json(self):
        config.SETTINGS_PATH.write_text("{not valid json", encoding="utf-8")
        loaded = config.load_settings()
        self.assertEqual(loaded, config.DEFAULT_SETTINGS)

    def test_app_dir_is_created(self):
        self.assertTrue(config.APP_DIR.exists())


if __name__ == "__main__":
    unittest.main()
