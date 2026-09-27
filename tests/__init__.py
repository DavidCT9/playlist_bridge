"""Importing `tests` (which every test module does implicitly) puts the
stub packages (fake requests/keyring/tidalapi/webview/pystray/PIL --
see tests/_stubs/) ahead of anything else on sys.path, so `app.*` can be
imported and exercised without the real third-party dependencies
installed. This is only a testing convenience: the app's own
requirements.txt is unchanged and still lists the real packages.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_STUBS = _ROOT / "tests" / "_stubs"

for p in (str(_STUBS), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
