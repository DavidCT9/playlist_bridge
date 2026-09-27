import unittest

import tests  # noqa: F401
from app.services.tidal_client import TidalAPIError, TidalClient


class FakeArtist:
    def __init__(self, name):
        self.name = name


class FakeTrack:
    def __init__(self, id_, name, artists=None, artist=None, duration=200, isrc=None, available=True):
        self.id = id_
        self.name = name
        self.artists = [FakeArtist(a) for a in artists] if artists else None
        self.artist = FakeArtist(artist) if artist else None
        self.duration = duration
        self.isrc = isrc
        self.available = available


class FakePlaylist:
    def __init__(self, id_, name, tracks=None, num_tracks=None):
        self.id = id_
        self.name = name
        self._tracks = tracks or []
        self.num_tracks = num_tracks if num_tracks is not None else len(self._tracks)
        self.added = []
        self.removed_ids = []
        self.removed_indices = []

    def tracks(self):
        return list(self._tracks)

    def add(self, ids):
        self.added.append(list(ids))

    def remove_by_id(self, track_id):
        self.removed_ids.append(track_id)

    def remove_by_index(self, index):
        self.removed_indices.append(index)
        del self._tracks[index]


class FakeUser:
    def __init__(self, playlists=None):
        self.id = "user1"
        self.username = "tester"
        self._playlists = playlists or []
        self.created = []

    def playlists(self):
        return list(self._playlists)

    def create_playlist(self, name, description=""):
        p = FakePlaylist("new1", name)
        self.created.append(p)
        return p


class FakeSession:
    def __init__(self, playlists_by_id=None, user_playlists=None):
        self.user = FakeUser(user_playlists or [])
        self._playlists_by_id = playlists_by_id or {}

    def playlist(self, playlist_id):
        return self._playlists_by_id[playlist_id]

    def search(self, query, models=None):
        return {"tracks": []}


class TestTidalClientBasics(unittest.TestCase):
    def test_no_session_raises_clear_error(self):
        client = TidalClient(get_session=lambda: None)
        with self.assertRaises(TidalAPIError):
            client.get_current_user()

    def test_list_playlists(self):
        session = FakeSession(user_playlists=[FakePlaylist("p1", "Runs", num_tracks=10)])
        client = TidalClient(get_session=lambda: session)
        playlists = client.list_playlists()
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0].track_count, 10)


class TestGetPlaylistTracks(unittest.TestCase):
    def test_artists_list_preferred_over_singular_artist(self):
        t = FakeTrack("t1", "Song", artists=["A", "B"], artist="A")
        session = FakeSession(playlists_by_id={"pl1": FakePlaylist("pl1", "X", tracks=[t])})
        client = TidalClient(get_session=lambda: session)
        tracks = client.get_playlist_tracks("pl1")
        self.assertEqual(tracks[0].artists, ["A", "B"])

    def test_falls_back_to_singular_artist(self):
        t = FakeTrack("t1", "Song", artists=None, artist="Solo Artist")
        session = FakeSession(playlists_by_id={"pl1": FakePlaylist("pl1", "X", tracks=[t])})
        client = TidalClient(get_session=lambda: session)
        tracks = client.get_playlist_tracks("pl1")
        self.assertEqual(tracks[0].artists, ["Solo Artist"])

    def test_duration_negative_one_sentinel_becomes_zero(self):
        """Regression test: tidalapi uses -1 as an 'unknown duration'
        sentinel, and -1 is truthy in Python, so `duration or 0` was
        letting -1 through as -1000ms and corrupting duration-based
        fuzzy matching."""
        t = FakeTrack("t1", "Song", artists=["A"], duration=-1)
        session = FakeSession(playlists_by_id={"pl1": FakePlaylist("pl1", "X", tracks=[t])})
        client = TidalClient(get_session=lambda: session)
        tracks = client.get_playlist_tracks("pl1")
        self.assertEqual(tracks[0].duration_ms, 0)

    def test_normal_duration_converts_seconds_to_ms(self):
        t = FakeTrack("t1", "Song", artists=["A"], duration=180)
        session = FakeSession(playlists_by_id={"pl1": FakePlaylist("pl1", "X", tracks=[t])})
        client = TidalClient(get_session=lambda: session)
        tracks = client.get_playlist_tracks("pl1")
        self.assertEqual(tracks[0].duration_ms, 180000)

    def test_unavailable_track_is_skipped(self):
        t = FakeTrack("t1", "Song", artists=["A"], available=False)
        session = FakeSession(playlists_by_id={"pl1": FakePlaylist("pl1", "X", tracks=[t])})
        client = TidalClient(get_session=lambda: session)
        tracks = client.get_playlist_tracks("pl1")
        self.assertEqual(tracks, [])

    def test_positions_track_original_index(self):
        tracks_in = [FakeTrack("a", "A", artists=["X"]), FakeTrack("b", "B", artists=["X"], available=False), FakeTrack("c", "C", artists=["X"])]
        session = FakeSession(playlists_by_id={"pl1": FakePlaylist("pl1", "X", tracks=tracks_in)})
        client = TidalClient(get_session=lambda: session)
        result = client.get_playlist_tracks_with_position("pl1")
        self.assertEqual([pos for pos, _t in result], [0, 2])


class TestAddRemoveTracks(unittest.TestCase):
    def test_add_tracks_batches_by_100_and_converts_to_int(self):
        playlist = FakePlaylist("pl1", "X")
        session = FakeSession(playlists_by_id={"pl1": playlist})
        client = TidalClient(get_session=lambda: session)
        ids = [str(i) for i in range(150)]
        client.add_tracks("pl1", ids)
        self.assertEqual(len(playlist.added), 2)
        self.assertEqual(len(playlist.added[0]), 100)
        self.assertIsInstance(playlist.added[0][0], int)

    def test_remove_tracks_at_positions_removes_highest_first(self):
        tracks_in = [FakeTrack(str(i), f"T{i}", artists=["X"]) for i in range(5)]
        playlist = FakePlaylist("pl1", "X", tracks=tracks_in)
        session = FakeSession(playlists_by_id={"pl1": playlist})
        client = TidalClient(get_session=lambda: session)
        client.remove_tracks_at_positions("pl1", [1, 3])
        self.assertEqual(playlist.removed_indices, [3, 1])

    def test_remove_by_index_missing_falls_back_gracefully(self):
        class NoIndexPlaylist(FakePlaylist):
            def remove_by_index(self, index):
                raise AttributeError("not supported in this version")
        playlist = NoIndexPlaylist("pl1", "X", tracks=[FakeTrack("a", "A", artists=["X"])])
        session = FakeSession(playlists_by_id={"pl1": playlist})
        client = TidalClient(get_session=lambda: session)
        client.remove_tracks_at_positions("pl1", [0])  # should not raise


if __name__ == "__main__":
    unittest.main()
