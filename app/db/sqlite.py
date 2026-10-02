"""
App database on SQLite.

  admins         user accounts (scrypt password hashes)
  sessions       login sessions (only a SHA-256 of each token is stored)
  sources        registry of uploaded files: name, type, size, chunks, who uploaded it and when,
                 and processing status (files are indexed in the background)
  site_settings  controls for the main website (maintenance mode, features, announcement)
  events         visits, searches and chat questions reported by the main website

Events store an anonymous visitor hash and the question text only —
no IP addresses or other personal data.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    username              TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash         TEXT    NOT NULL,
    -- 1 while the user still has the default password; the dashboard asks them to change it
    must_change_password  INTEGER NOT NULL DEFAULT 0,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT    PRIMARY KEY,
    admin_id    INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    expires_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT    NOT NULL UNIQUE,
    kind         TEXT    NOT NULL,
    size_bytes   INTEGER NOT NULL,
    chunks       INTEGER NOT NULL,
    characters   INTEGER NOT NULL,
    ocr_pages    INTEGER NOT NULL DEFAULT 0,
    uploaded_by  TEXT,
    uploaded_at  TEXT    NOT NULL,
    -- 'processing' → 'ready', or 'failed'; progress is a short status line while processing
    status       TEXT    NOT NULL DEFAULT 'ready',
    progress     TEXT,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS site_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT    NOT NULL CHECK (type IN ('visit', 'search', 'chat')),
    visitor_hash  TEXT,
    query         TEXT,
    result        TEXT,
    latency_ms    INTEGER,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS events_created_at ON events (created_at);
CREATE INDEX IF NOT EXISTS events_type_created_at ON events (type, created_at);

-- Text of every indexed passage (app/services/text_index.py): `text` as shown to visitors,
-- and in passages_fts (same rowid) its normalized form for exact-quote search. The vector
-- store keeps only vectors and metadata, so each text is stored once.
CREATE TABLE IF NOT EXISTS passages (
    rowid    INTEGER PRIMARY KEY,
    item_id  TEXT    NOT NULL UNIQUE,
    source   TEXT    NOT NULL,
    text     TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS passages_source ON passages (source);
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    body,
    tokenize = 'unicode61 remove_diacritics 0'
);
"""


BUSY_TIMEOUT = 30  # seconds


@contextmanager
def connection():
    """Managed connection to the app database.

    The background indexer writes while the dashboard and the website read; a writer waits
    up to BUSY_TIMEOUT seconds for another to finish instead of failing at once.
    """
    conn = sqlite3.connect(get_settings().sqlite_path, timeout=BUSY_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added to the admins table after its first version: column name → SQL type.
# (bandit B105 reads the "password" in the column name as a hard-coded secret.)
_ADMIN_COLUMNS_ADDED = {"must_change_password": "INTEGER NOT NULL DEFAULT 0"}  # nosec B105


def vacuum() -> None:
    """Rewrite the database file without its free pages (deleted rows), so it shrinks."""
    conn = sqlite3.connect(get_settings().sqlite_path, timeout=BUSY_TIMEOUT, isolation_level=None)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


def init_db() -> None:
    """Create the database file and tables if missing. Called on application startup."""
    Path(get_settings().sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        # Write-ahead logging: readers never wait for a writer (and vice versa). Persistent.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        # Databases created by earlier versions get the newer columns added.
        _add_missing_columns(conn, "admins", _ADMIN_COLUMNS_ADDED)
        _add_missing_columns(conn, "passages", {"text": "TEXT NOT NULL DEFAULT ''"})
        _add_missing_columns(conn, "sources", {
            "status": "TEXT NOT NULL DEFAULT 'ready'",
            "progress": "TEXT",
            "error": "TEXT",
        })


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
