"""SQLite access. Migrations in `migrations/NNN_*.sql` run at startup."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = Path(__file__).with_name("migrations")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] or 0
    applied = 0
    for file in sorted(MIGRATIONS.glob("*.sql")):
        version = int(file.name.split("_", 1)[0])
        if version <= current:
            continue
        with transaction(conn):
            for statement in _split(file.read_text(encoding="utf-8")):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        applied += 1
    return applied


def _split(script: str) -> list[str]:
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


class transaction:
    """`with transaction(conn):` – BEGIN IMMEDIATE / COMMIT / ROLLBACK; nests safely."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.outer = False

    def __enter__(self):
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
            self.outer = True
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if self.outer:
            self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
