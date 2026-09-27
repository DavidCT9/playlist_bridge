import importlib
import unittest

import tests  # noqa: F401

MODULES = [
    "app.config", "app.secure_store", "app.db", "app.models",
    "app.auth.pkce", "app.auth.spotify_auth", "app.auth.tidal_auth",
    "app.services.spotify_client", "app.services.tidal_client",
    "app.sync.matcher", "app.sync.engine", "app.scheduler",
    "app.tray", "app.api", "app.main",
]


class TestEveryModuleImports(unittest.TestCase):
    def test_all_modules_import_without_error(self):
        for name in MODULES:
            with self.subTest(module=name):
                importlib.import_module(name)


if __name__ == "__main__":
    unittest.main()
