"""PKCE helpers (RFC 7636) used by the Spotify auth flow so no client
secret ever needs to be stored on disk.
"""
import base64
import hashlib
import secrets


def generate_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")


def generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
