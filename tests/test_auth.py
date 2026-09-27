import time
import unittest
from unittest.mock import patch

import tests  # noqa: F401
from app.auth.pkce import generate_code_challenge, generate_code_verifier


class TestPkce(unittest.TestCase):
    def test_verifier_is_url_safe_and_reasonable_length(self):
        v = generate_code_verifier()
        self.assertGreaterEqual(len(v), 43)  # RFC 7636 minimum
        self.assertLessEqual(len(v), 128)     # RFC 7636 maximum
        self.assertTrue(all(c not in v for c in "+/="))

    def test_verifiers_are_unique(self):
        self.assertNotEqual(generate_code_verifier(), generate_code_verifier())

    def test_challenge_is_deterministic_for_same_verifier(self):
        v = generate_code_verifier()
        self.assertEqual(generate_code_challenge(v), generate_code_challenge(v))

    def test_challenge_differs_from_verifier(self):
        v = generate_code_verifier()
        self.assertNotEqual(generate_code_challenge(v), v)


class TestSpotifyTokenRefresh(unittest.TestCase):
    def setUp(self):
        import keyring
        keyring._reset()
        from app.auth.spotify_auth import SpotifyAuth
        self.auth = SpotifyAuth(client_id="testclient", redirect_port=8765)

    def test_no_stored_tokens_returns_none(self):
        self.assertIsNone(self.auth.get_valid_access_token())

    def test_unexpired_token_returned_without_refresh_call(self):
        from app.secure_store import save_json
        save_json("spotify_tokens", {
            "access_token": "still-good", "refresh_token": "r1",
            "expires_in": 3600, "obtained_at": time.time(),
        })
        with patch("app.auth.spotify_auth.requests.post") as mock_post:
            token = self.auth.get_valid_access_token()
        self.assertEqual(token, "still-good")
        mock_post.assert_not_called()

    def test_expired_token_triggers_refresh(self):
        from app.secure_store import save_json
        save_json("spotify_tokens", {
            "access_token": "stale", "refresh_token": "r1",
            "expires_in": 3600, "obtained_at": time.time() - 4000,  # well expired
        })
        import requests as fake_requests

        def fake_post(url, data=None, timeout=None):
            self.assertEqual(data["grant_type"], "refresh_token")
            self.assertEqual(data["refresh_token"], "r1")
            return fake_requests.Response(200, {"access_token": "fresh", "expires_in": 3600})

        with patch("app.auth.spotify_auth.requests.post", side_effect=fake_post):
            token = self.auth.get_valid_access_token()
        self.assertEqual(token, "fresh")

    def test_refresh_keeps_old_refresh_token_if_not_reissued(self):
        from app.secure_store import save_json, load_json
        save_json("spotify_tokens", {
            "access_token": "stale", "refresh_token": "original-refresh",
            "expires_in": 3600, "obtained_at": time.time() - 4000,
        })
        import requests as fake_requests
        with patch("app.auth.spotify_auth.requests.post",
                   return_value=fake_requests.Response(200, {"access_token": "fresh", "expires_in": 3600})):
            self.auth.get_valid_access_token()
        stored = load_json("spotify_tokens")
        self.assertEqual(stored["refresh_token"], "original-refresh")

    def test_refresh_failure_returns_none_not_exception(self):
        from app.secure_store import save_json
        import requests as fake_requests
        save_json("spotify_tokens", {
            "access_token": "stale", "refresh_token": "r1",
            "expires_in": 3600, "obtained_at": time.time() - 4000,
        })
        with patch("app.auth.spotify_auth.requests.post",
                   side_effect=fake_requests.RequestException("network down")):
            token = self.auth.get_valid_access_token()
        self.assertIsNone(token)

    def test_login_without_client_id_fails_fast_no_network_call(self):
        from app.auth.spotify_auth import SpotifyAuth
        auth = SpotifyAuth(client_id="", redirect_port=8765)
        ok, message = auth.login()
        self.assertFalse(ok)
        self.assertIn("Client ID", message)


if __name__ == "__main__":
    unittest.main()
