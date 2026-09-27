"""Minimal stand-in for `keyring`, structured as a real package because
secure_store.py does `import keyring.errors` (a submodule import, which
requires an actual package -- a single-file module with a nested class
of the same name would NOT satisfy that import statement).

Has real (in-memory) working behavior by default, since secure_store's
job is simple enough to fake accurately: a dict keyed by (service, key).
"""
from . import errors  # noqa: F401  (re-exported so `keyring.errors` works too)

_store: dict[tuple[str, str], str] = {}


def set_password(service, key, value):
    _store[(service, key)] = value


def get_password(service, key):
    return _store.get((service, key))


def delete_password(service, key):
    if (service, key) not in _store:
        raise errors.PasswordDeleteError("not found")
    del _store[(service, key)]


def _reset():
    """Test helper: clear all stored values between tests."""
    _store.clear()
