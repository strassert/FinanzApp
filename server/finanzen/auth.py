"""API tokens. Only a SHA-256 hash is stored; the token is shown once."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from typing import Optional

from .core.db import utcnow

SCOPES = ("app", "home", "wallet")   # wallet: only POST /api/wallet (iOS Shortcut)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(conn: sqlite3.Connection, name: str, scope: str = "app") -> str:
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope}")
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO api_tokens (name, token_hash, scope, created_at) VALUES (?,?,?,?)",
                 (name, _hash(token), scope, utcnow()))
    return token


def check_token(conn: sqlite3.Connection, token: Optional[str]) -> Optional[str]:
    """Return the scope of a valid token, else None."""
    if not token:
        return None
    row = conn.execute("SELECT id, scope FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL",
                       (_hash(token),)).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?", (utcnow(), row["id"]))
    return row["scope"]


def list_tokens(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, name, scope, created_at, last_used_at, revoked_at FROM api_tokens ORDER BY id")]


def revoke_token(conn: sqlite3.Connection, token_id: int) -> bool:
    cur = conn.execute("UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                       (utcnow(), token_id))
    return cur.rowcount == 1
