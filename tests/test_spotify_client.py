import unittest
from unittest.mock import patch

import tests  # noqa: F401
from app.services.spotify_client import SpotifyAPIError, SpotifyClient
import requests as fake_requests


def resp(status=200, json_data=None, headers=None):
    return fake_requests.Response(status_code=status, json_data=json_data, headers=headers)


class TestSpotifyClientBasics(unittest.TestCase):
    def setUp(self):
        self.client = SpotifyClient(get_token=lambda: "fake-token")

    def test_no_token_raises_clear_error(self):
        client = SpotifyClient(get_token=lambda: None)
        with self.assertRaises(SpotifyAPIError):
            client.get_current_user()

    @patch("app.services.spotify_client.requests.request")
    def test_request_sends_bearer_header(self, mock_request):
        mock_request.return_value = resp(200, {"id": "u1"})
        self.client.get_current_user()
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-token")

    @patch("app.services.spotify_client.requests.request")
    def test_429_retries_with_backoff_then_succeeds(self, mock_request):
        mock_request.side_effect = [
            resp(429, headers={"Retry-After": "0"}),
            resp(200, {"id": "u1"}),
        ]
        with patch("app.services.spotify_client.time.sleep"):
            data = self.client.get_current_user()
        self.assertEqual(data["id"], "u1")
        self.assertEqual(mock_request.call_count, 2)

    @patch("app.services.spotify_client.requests.request")
    def test_4xx_raises_spotify_api_error(self, mock_request):
        mock_request.return_value = resp(404, {})
        mock_request.return_value.text = '{"error": "not found"}'
        with self.assertRaises(SpotifyAPIError):
            self.client.get_current_user()


class TestListPlaylists(unittest.TestCase):
    def setUp(self):
        self.client = SpotifyClient(get_token=lambda: "tok")

    @patch("app.services.spotify_client.requests.request")
    def test_pagination_follows_next_until_none(self, mock_request):
        page1 = {
            "items": [{"id": "p1", "name": "One", "items": {"total": 3}, "owner": {"display_name": "me"}}],
            "next": "https://api.spotify.com/v1/me/playlists?offset=50&limit=50",
        }
        page2 = {
            "items": [{"id": "p2", "name": "Two", "items": {"total": 1}, "owner": {"display_name": "me"}}],
            "next": None,
        }
        mock_request.side_effect = [resp(200, page1), resp(200, page2)]
        playlists = self.client.list_playlists()
        self.assertEqual([p.id for p in playlists], ["p1", "p2"])
        self.assertEqual(mock_request.call_count, 2)

    @patch("app.services.spotify_client.requests.request")
    def test_track_count_reads_new_items_field_with_tracks_fallback(self, mock_request):
        page_new = {"items": [{"id": "p1", "name": "New", "items": {"total": 7}}], "next": None}
        mock_request.side_effect = [resp(200, page_new)]
        playlists = self.client.list_playlists()
        self.assertEqual(playlists[0].track_count, 7)

        page_old = {"items": [{"id": "p2", "name": "Old", "tracks": {"total": 4}}], "next": None}
        mock_request.side_effect = [resp(200, page_old)]
        playlists = self.client.list_playlists()
        self.assertEqual(playlists[0].track_count, 4)


class TestGetPlaylistTracks(unittest.TestCase):
    def setUp(self):
        self.client = SpotifyClient(get_token=lambda: "tok")

    def _track_obj(self, id_="t1", isrc="US1234567890"):
        return {
            "id": id_, "uri": f"spotify:track:{id_}", "name": "Song",
            "duration_ms": 200000, "artists": [{"name": "Artist"}],
            "external_ids": {"isrc": isrc}, "is_local": False,
        }

    @patch("app.services.spotify_client.requests.request")
    def test_parses_new_item_key(self, mock_request):
        page = {"items": [{"item": self._track_obj(), "is_local": False}], "next": None}
        mock_request.side_effect = [resp(200, page)]
        tracks = self.client.get_playlist_tracks("pl1")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].isrc, "US1234567890")

    @patch("app.services.spotify_client.requests.request")
    def test_parses_old_track_key_as_fallback(self, mock_request):
        page = {"items": [{"track": self._track_obj(), "is_local": False}], "next": None}
        mock_request.side_effect = [resp(200, page)]
        tracks = self.client.get_playlist_tracks("pl1")
        self.assertEqual(len(tracks), 1)

    @patch("app.services.spotify_client.requests.request")
    def test_regression_dual_field_request_is_gone(self, mock_request):
        """The actual production bug: a prior fix requested BOTH
        track(...) and item(...) via a `fields` filter, which could
        silently return {} for the whole nested object. Assert no
        `fields` param is sent at all -- full objects only."""
        page = {"items": [{"item": self._track_obj(), "is_local": False}], "next": None}
        mock_request.side_effect = [resp(200, page)]
        self.client.get_playlist_tracks("pl1")
        called_url = mock_request.call_args[0][1]
        self.assertNotIn("fields=", called_url, "fields filter should not be used for track fetching")

    @patch("app.services.spotify_client.requests.request")
    def test_skips_local_tracks(self, mock_request):
        page = {"items": [{"item": self._track_obj(), "is_local": True}], "next": None}
        mock_request.side_effect = [resp(200, page)]
        tracks = self.client.get_playlist_tracks("pl1")
        self.assertEqual(tracks, [])

    @patch("app.services.spotify_client.requests.request")
    def test_skips_entries_with_no_id_no_crash(self, mock_request):
        page = {"items": [{"item": None, "is_local": False}], "next": None}
        mock_request.side_effect = [resp(200, page)]
        tracks = self.client.get_playlist_tracks("pl1")
        self.assertEqual(tracks, [])

    @patch("app.services.spotify_client.requests.request")
    def test_positions_count_every_slot_including_skipped(self, mock_request):
        page = {
            "items": [
                {"item": self._track_obj("keep1"), "is_local": False},
                {"item": self._track_obj("local"), "is_local": True},
                {"item": self._track_obj("keep2"), "is_local": False},
            ],
            "next": None,
        }
        mock_request.side_effect = [resp(200, page)]
        result = self.client.get_playlist_tracks_with_position("pl1")
        positions = [pos for pos, _t in result]
        ids = [tr.id for _pos, tr in result]
        self.assertEqual(positions, [0, 2])
        self.assertEqual(ids, ["keep1", "keep2"])


class TestCreatePlaylist(unittest.TestCase):
    @patch("app.services.spotify_client.requests.request")
    def test_uses_me_playlists_not_removed_users_endpoint(self, mock_request):
        mock_request.return_value = resp(200, {"id": "new1", "name": "New List"})
        client = SpotifyClient(get_token=lambda: "tok")
        result = client.create_playlist("New List")
        called_url = mock_request.call_args[0][1]
        self.assertIn("/me/playlists", called_url)
        self.assertNotIn("/users/", called_url)
        self.assertEqual(result.id, "new1")


class TestRemoveTracksAtPositions(unittest.TestCase):
    @patch("app.services.spotify_client.requests.request")
    def test_sends_items_key_not_tracks_key(self, mock_request):
        mock_request.return_value = resp(200, {})
        client = SpotifyClient(get_token=lambda: "tok")
        client.remove_tracks_at_positions("pl1", [("spotify:track:a", 3)])
        _, kwargs = mock_request.call_args
        body = kwargs["json"]
        self.assertIn("items", body)
        self.assertNotIn("tracks", body)

    @patch("app.services.spotify_client.requests.request")
    def test_groups_same_uri_multiple_positions(self, mock_request):
        mock_request.return_value = resp(200, {})
        client = SpotifyClient(get_token=lambda: "tok")
        client.remove_tracks_at_positions("pl1", [("uri-a", 5), ("uri-a", 2), ("uri-b", 9)])
        body = mock_request.call_args[1]["json"]
        by_uri = {item["uri"]: item["positions"] for item in body["items"]}
        self.assertEqual(sorted(by_uri["uri-a"]), [2, 5])
        self.assertEqual(by_uri["uri-b"], [9])

    @patch("app.services.spotify_client.requests.request")
    def test_batches_over_100_highest_positions_first(self, mock_request):
        mock_request.return_value = resp(200, {})
        client = SpotifyClient(get_token=lambda: "tok")
        pairs = [(f"uri-{i}", i) for i in range(150)]
        client.remove_tracks_at_positions("pl1", pairs)
        self.assertEqual(mock_request.call_count, 2)
        first_call_positions = [p for item in mock_request.call_args_list[0][1]["json"]["items"] for p in item["positions"]]
        second_call_positions = [p for item in mock_request.call_args_list[1][1]["json"]["items"] for p in item["positions"]]
        self.assertEqual(min(first_call_positions), 50)
        self.assertEqual(max(second_call_positions), 49)


if __name__ == "__main__":
    unittest.main()
