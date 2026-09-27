"""Minimal stand-in for `tidalapi` so app code can be imported without
the real dependency installed. Tests patch Session's methods directly
(or substitute a hand-built fake session object entirely) to control
behavior and assert on exact calls made.
"""


class Track:
    """Used only as a type marker (e.g. `models=[tidalapi.Track]`)."""
    pass


class Session:
    def __init__(self):
        self.user = None

    def login_oauth(self):
        raise NotImplementedError("stub - patch this in tests")

    def login_session_file(self, session_file, do_pkce=False, fn_print=print):
        raise NotImplementedError("stub - patch this in tests")

    def check_login(self):
        return False

    def search(self, query, models=None):
        return {}

    def playlist(self, playlist_id):
        raise NotImplementedError("stub - patch this in tests")
