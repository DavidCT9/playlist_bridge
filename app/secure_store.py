"""Thin wrapper around `keyring` for storing OAuth tokens in the OS
credential vault (Windows Credential Manager, macOS Keychain, or the
Secret Service/KWallet on Linux).

Tokens handled through this module are never written to a plain file
and this module never makes a network call itself.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import keyring
import keyring.errors

from app.config import KEYRING_SERVICE


def save_json(key: str, data: dict[str, Any]) -> None:
    keyring.set_password(KEYRING_SERVICE, key, json.dumps(data))


def load_json(key: str) -> Optional[dict[str, Any]]:
    raw = keyring.get_password(KEYRING_SERVICE, key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def delete(key: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        pass
