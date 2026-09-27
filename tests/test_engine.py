import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401
from app.models import PlaylistRef, Track
from app.sync.engine import DIRECTIONS, SyncEngine


def t(id_, title, artists=("Artist",), isrc=None, ms=200000):
    return Track(id=id_, provider="x", title=title, artists=list(artists), duration_ms=ms, isrc=isrc, uri=id_)


class FakeClient:
    """Implements the same interface SpotifyClient/TidalClient expose to
    SyncEngine, entirely in-memory and network-free."""
    def __init__(self, name):
        self.name = name
        self.playlists: dict[str, list[Track]] = {}
        self.created = []
        self.search_results: dict[str, list[Track]] = {}
        self.add_calls = []
        self.remove_calls = []

    def get_playlist_tracks(self, playlist_id):
        return list(self.playlists.get(playlist_id, []))

    def add_tracks(self, playlist_id, uris):
        self.add_calls.append((playlist_id, list(uris)))
        self.playlists.setdefault(playlist_id, [])

    def remove_tracks(self, playlist_id, uris):
        self.remove_calls.append((playlist_id, list(uris)))

    def create_playlist(self, name, description=""):
        ref = PlaylistRef(id=f"created-{len(self.created)}", provider=self.name, name=name)
        self.created.append(ref)
        return ref

    def search_track(self, title, artist, isrc=None):
        key = f"{title}|{artist}"
        return self.search_results.get(key, [])

    def list_playlists(self):
        return [PlaylistRef(id=pid, provider=self.name, name=pid) for pid in self.playlists]


class EngineTestBase(unittest.TestCase):
    def setUp(self):
        import app.config as config
        import app.db as db
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DB_PATH = Path(self._tmpdir.name) / "test.db"
        db.DB_PATH = config.DB_PATH
        db.init_db()
        self.db = db
        self.spotify = FakeClient("spotify")
        self.tidal = FakeClient("tidal")
        self.engine = SyncEngine(self.spotify, self.tidal)

    def tearDown(self):
        self._tmpdir.cleanup()

    def make_pair(self, direction="spotify_to_tidal", spotify_id="sp1", tidal_id="td1"):
        pair_id = self.db.create_pair(
            spotify_playlist_id=spotify_id, spotify_playlist_name="Src",
            tidal_playlist_id=tidal_id, tidal_playlist_name="Dst",
            direction=direction,
        )
        return self.db.get_pair(pair_id)


class TestComputeDiff(EngineTestBase):
    def test_add_and_remove_both_directions(self):
        source = [t("a", "Song A", isrc="I1"), t("b", "Song B", isrc="I2")]
        dest = [t("b2", "Song B", isrc="I2"), t("c", "Song C", isrc="I3")]
        diff = self.engine.compute_diff(source, dest)
        self.assertEqual([x.id for x in diff.to_add], ["a"])
        self.assertEqual([x.id for x in diff.to_remove], ["c"])

    def test_identical_lists_yield_empty_diff(self):
        source = [t("a", "Song A", isrc="I1")]
        dest = [t("a2", "Song A", isrc="I1")]
        diff = self.engine.compute_diff(source, dest)
        self.assertEqual(diff.to_add, [])
        self.assertEqual(diff.to_remove, [])


class TestSyncPairMirrorMode(EngineTestBase):
    def test_adds_resolved_tracks_and_removes_extras(self):
        pair = self.make_pair(direction="spotify_to_tidal")
        self.spotify.playlists["sp1"] = [t("a", "Song A", isrc="I1")]
        self.tidal.playlists["td1"] = [t("old", "Old Song", isrc="I9")]
        self.tidal.search_results["Song A|Artist"] = [t("a-tidal", "Song A", isrc="I1")]

        result = self.engine.sync_pair(pair)

        self.assertEqual(result.added, 1)
        self.assertEqual(result.removed, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(self.tidal.add_calls, [("td1", ["a-tidal"])])
        self.assertEqual(self.tidal.remove_calls, [("td1", ["old"])])
        self.assertEqual(self.spotify.add_calls, [])
        self.assertEqual(self.spotify.remove_calls, [])

    def test_unresolvable_track_is_skipped_not_crashed(self):
        pair = self.make_pair(direction="spotify_to_tidal")
        self.spotify.playlists["sp1"] = [t("a", "Song A", isrc="I1")]
        self.tidal.playlists["td1"] = []
        result = self.engine.sync_pair(pair)
        self.assertEqual(result.added, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.errors, [])

    def test_direction_reversed(self):
        pair = self.make_pair(direction="tidal_to_spotify")
        self.tidal.playlists["td1"] = [t("a", "Song A", isrc="I1")]
        self.spotify.playlists["sp1"] = []
        self.spotify.search_results["Song A|Artist"] = [t("a-sp", "Song A", isrc="I1")]
        result = self.engine.sync_pair(pair)
        self.assertEqual(self.spotify.add_calls, [("sp1", ["a-sp"])])
        self.assertEqual(self.tidal.add_calls, [])

    def test_unknown_direction_falls_back_to_spotify_to_tidal_default(self):
        pair = self.make_pair(direction="not_a_real_direction")
        self.spotify.playlists["sp1"] = [t("a", "Song A", isrc="I1")]
        self.tidal.search_results["Song A|Artist"] = [t("a-tidal", "Song A", isrc="I1")]
        result = self.engine.sync_pair(pair)
        self.assertEqual(self.tidal.add_calls, [("td1", ["a-tidal"])])


class TestSyncPairAdditiveMode(EngineTestBase):
    def test_never_deletes(self):
        pair = self.make_pair(direction="spotify_to_tidal_additive")
        self.spotify.playlists["sp1"] = [t("a", "Song A", isrc="I1")]
        self.tidal.playlists["td1"] = [t("old", "Old Song", isrc="I9")]
        self.tidal.search_results["Song A|Artist"] = [t("a-tidal", "Song A", isrc="I1")]
        result = self.engine.sync_pair(pair)
        self.assertEqual(result.added, 1)
        self.assertEqual(result.removed, 0)
        self.assertEqual(self.tidal.remove_calls, [])


class TestSyncPairDryRun(EngineTestBase):
    def test_dry_run_never_calls_add_or_remove(self):
        pair = self.make_pair(direction="spotify_to_tidal")
        self.spotify.playlists["sp1"] = [t("a", "Song A", isrc="I1")]
        self.tidal.playlists["td1"] = [t("old", "Old Song", isrc="I9")]
        self.tidal.search_results["Song A|Artist"] = [t("a-tidal", "Song A", isrc="I1")]
        result = self.engine.sync_pair(pair, dry_run=True)
        self.assertEqual(result.added, 1)
        self.assertEqual(result.removed, 1)
        self.assertEqual(self.tidal.add_calls, [])
        self.assertEqual(self.tidal.remove_calls, [])

    def test_dry_run_does_not_update_last_synced_at(self):
        pair = self.make_pair(direction="spotify_to_tidal")
        self.engine.sync_pair(pair, dry_run=True)
        refreshed = self.db.get_pair(pair["id"])
        self.assertIsNone(refreshed["last_synced_at"])


class TestSyncPairErrors(EngineTestBase):
    def test_fetch_failure_is_caught_and_recorded(self):
        pair = self.make_pair(direction="spotify_to_tidal")

        def boom(playlist_id):
            raise RuntimeError("network exploded")
        self.spotify.get_playlist_tracks = boom

        result = self.engine.sync_pair(pair)
        self.assertEqual(len(result.errors), 1)
        history = self.db.get_history(1)
        self.assertEqual(history[0]["status"], "error")


class TestSyncAll(EngineTestBase):
    def test_only_syncs_pairs_with_auto_sync_enabled(self):
        p1 = self.make_pair(spotify_id="sp1", tidal_id="td1")
        self.db.create_pair(
            spotify_playlist_id="sp2", spotify_playlist_name="S2",
            tidal_playlist_id="td2", tidal_playlist_name="T2",
            direction="spotify_to_tidal", auto_sync=0,
        )
        results = self.engine.sync_all()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].pair_id, p1["id"])

    def test_no_pairs_returns_empty_list_not_error(self):
        results = self.engine.sync_all()
        self.assertEqual(results, [])


class TestSuggestPairs(EngineTestBase):
    def test_suggests_name_matches_and_lists_the_rest(self):
        self.spotify.list_playlists = lambda: [
            PlaylistRef(id="a", provider="spotify", name="Road Trip 2024"),
            PlaylistRef(id="b", provider="spotify", name="Morning Coffee"),
        ]
        self.tidal.list_playlists = lambda: [
            PlaylistRef(id="x", provider="tidal", name="Road Trip '24"),
            PlaylistRef(id="y", provider="tidal", name="Late Night Drive"),
        ]
        data = self.engine.suggest_pairs()
        self.assertEqual(len(data["suggestions"]), 1)
        self.assertEqual(data["suggestions"][0]["spotify"].id, "a")
        self.assertEqual(len(data["unmatched_spotify"]), 1)
        self.assertEqual(len(data["unmatched_tidal"]), 1)

    def test_already_linked_playlists_excluded_from_unmatched(self):
        self.make_pair(spotify_id="linked-sp", tidal_id="linked-td")
        self.spotify.list_playlists = lambda: [PlaylistRef(id="linked-sp", provider="spotify", name="X")]
        self.tidal.list_playlists = lambda: [PlaylistRef(id="linked-td", provider="tidal", name="X")]
        data = self.engine.suggest_pairs()
        self.assertEqual(data["unmatched_spotify"], [])
        self.assertEqual(data["unmatched_tidal"], [])
        self.assertEqual(len(data["linked"]), 1)


class TestDeduplicatePlaylist(EngineTestBase):
    def test_removes_duplicates_keeps_first(self):
        self.spotify.playlists["sp1"] = [
            t("a", "Song A", isrc="I1"),
            t("b", "Song B", isrc="I2"),
            t("a2", "Song A", isrc="I1"),
        ]
        self.spotify.get_playlist_tracks_with_position = lambda pid: list(enumerate(self.spotify.playlists[pid]))
        self.spotify.remove_tracks_at_positions = lambda pid, pairs: self.spotify.remove_calls.append((pid, pairs))

        result = self.engine.deduplicate_playlist("spotify", "sp1")
        self.assertEqual(result["total_tracks"], 3)
        self.assertEqual(result["duplicates_found"], 1)
        self.assertEqual(result["removed"], 1)
        self.assertEqual(self.spotify.remove_calls, [("sp1", [("a2", 2)])])

    def test_dry_run_reports_but_does_not_remove(self):
        self.spotify.playlists["sp1"] = [t("a", "Song A", isrc="I1"), t("a2", "Song A", isrc="I1")]
        self.spotify.get_playlist_tracks_with_position = lambda pid: list(enumerate(self.spotify.playlists[pid]))
        removed_called = []
        self.spotify.remove_tracks_at_positions = lambda pid, pairs: removed_called.append(1)

        result = self.engine.deduplicate_playlist("spotify", "sp1", dry_run=True)
        self.assertEqual(result["duplicates_found"], 1)
        self.assertEqual(result["dry_run"], True)
        self.assertEqual(removed_called, [])

    def test_no_duplicates_no_removal_call(self):
        self.spotify.playlists["sp1"] = [t("a", "Song A", isrc="I1"), t("b", "Song B", isrc="I2")]
        self.spotify.get_playlist_tracks_with_position = lambda pid: list(enumerate(self.spotify.playlists[pid]))
        called = []
        self.spotify.remove_tracks_at_positions = lambda pid, pairs: called.append(1)
        result = self.engine.deduplicate_playlist("spotify", "sp1")
        self.assertEqual(result["duplicates_found"], 0)
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
