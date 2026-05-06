"""SQLite layer: shared async connection + idempotent migrations.

One process writes, so a single shared aiosqlite connection is safe and avoids
the lock thrash you'd get with a connection-per-call pattern. Tests replace it
with `:memory:` via `init_db`.
"""

from __future__ import annotations

import logging

import aiosqlite

logger = logging.getLogger(__name__)

_conn: aiosqlite.Connection | None = None

_MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS drafts (
        id              TEXT PRIMARY KEY,
        user_id         INTEGER NOT NULL,
        chat_id         INTEGER NOT NULL,
        message_id      INTEGER,
        preview_msg_id  INTEGER,
        status          TEXT NOT NULL,
        kind            TEXT NOT NULL,
        raw_payload     TEXT NOT NULL,
        transcribed     TEXT,
        note_type       TEXT,
        formatted       TEXT,
        title           TEXT,
        properties      TEXT,
        error           TEXT,
        created_at      INTEGER NOT NULL,
        updated_at      INTEGER NOT NULL,
        workspace       TEXT NOT NULL DEFAULT 'personal'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status)",
    "CREATE INDEX IF NOT EXISTS idx_drafts_user ON drafts(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS outbox (
        draft_id        TEXT PRIMARY KEY REFERENCES drafts(id) ON DELETE CASCADE,
        attempts        INTEGER NOT NULL DEFAULT 0,
        next_attempt_at INTEGER NOT NULL,
        last_error      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_outbox_due ON outbox(next_attempt_at)",
    """
    CREATE TABLE IF NOT EXISTS idempotency (
        draft_id        TEXT PRIMARY KEY,
        page_id         TEXT NOT NULL,
        saved_at        INTEGER NOT NULL
    )
    """,
]


async def init_db(path: str) -> aiosqlite.Connection:
    """Open shared connection, enable WAL, apply migrations.

    Safe to call multiple times — it closes any existing handle first so tests
    can swap databases between cases.
    """
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None

    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row

    # WAL only makes sense for file-backed DBs; :memory: ignores it.
    if path != ":memory:":
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA synchronous = NORMAL")
    await conn.execute("PRAGMA foreign_keys = ON")

    for stmt in _MIGRATIONS:
        await conn.execute(stmt)

    # Lightweight ALTER для существующих БД, у которых ещё нет колонки workspace.
    # IF NOT EXISTS для ADD COLUMN поддержан только в SQLite 3.35+, поэтому
    # точечный catch на "duplicate column name" — это норм, любая другая
    # OperationalError (disk full, corruption) должна сорвать старт, а не
    # молча пройти.
    try:
        await conn.execute(
            "ALTER TABLE drafts ADD COLUMN workspace TEXT NOT NULL DEFAULT 'personal'"
        )
    except aiosqlite.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
        logger.debug("workspace column already present, skipping ADD COLUMN")

    await conn.commit()

    _conn = conn
    return conn


def get_conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("DB not initialized. Call init_db() first.")
    return _conn


async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
