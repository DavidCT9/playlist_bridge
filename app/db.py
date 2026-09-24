"""SQLite storage for playlist-sync pairs and sync history.

This database holds only playlist ids/names and non-secret sync
settings -- never credentials or tokens (those live in the OS
keyring, see secure_store.py).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from typing import Optional

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_playlist_id TEXT,
    spotify_playlist_name TEXT,
    tidal_playlist_id TEXT,
    tidal_playlist_name TEXT,
    direction TEXT NOT NULL DEFAULT 'spotify_to_tidal',
    auto_sync INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    added_count INTEGER DEFAULT 0,
    removed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    status TEXT,
    message TEXT
);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def create_pair(**fields) -> int:
    fields.setdefault("direction", "spotify_to_tidal")
    fields.setdefault("auto_sync", 1)
    fields["created_at"] = dt.datetime.utcnow().isoformat()
    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO sync_pairs ({columns}) VALUES ({placeholders})",
            list(fields.values()),
        )
        return cur.lastrowid


def list_pairs() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM sync_pairs ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_pair(pair_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sync_pairs WHERE id = ?", (pair_id,)).fetchone()
        return dict(row) if row else None


def update_pair(pair_id: int, **fields) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(
            f"UPDATE sync_pairs SET {assignments} WHERE id = ?",
            [*fields.values(), pair_id],
        )


def delete_pair(pair_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sync_pairs WHERE id = ?", (pair_id,))
        conn.execute("DELETE FROM sync_history WHERE pair_id = ?", (pair_id,))


def record_sync(
    pair_id: Optional[int],
    started_at: str,
    finished_at: str,
    added: int,
    removed: int,
    skipped: int,
    status: str,
    message: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sync_history (pair_id, started_at, finished_at, added_count, "
            "removed_count, skipped_count, status, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pair_id, started_at, finished_at, added, removed, skipped, status, message),
        )


def get_history(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sync_history.*, sync_pairs.spotify_playlist_name, sync_pairs.tidal_playlist_name "
            "FROM sync_history LEFT JOIN sync_pairs ON sync_history.pair_id = sync_pairs.id "
            "ORDER BY sync_history.started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
