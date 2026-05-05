"""Outbox queue with exponential backoff.

next_attempt_at = now + min(BACKOFF_BASE * 2^attempts, BACKOFF_CAP).
Worker polls `claim_due(now)` periodically.
"""

from __future__ import annotations

import time

from bot.storage.db import get_conn

BACKOFF_BASE_SECS = 5
BACKOFF_CAP_SECS = 600  # 10 minutes


def _next_delay(attempts: int) -> int:
    return min(BACKOFF_BASE_SECS * (2**attempts), BACKOFF_CAP_SECS)


async def enqueue(draft_id: str, *, run_at: int | None = None) -> None:
    """Add draft to outbox (or reset if already there)."""
    if run_at is None:
        run_at = int(time.time())
    conn = get_conn()
    await conn.execute(
        """
        INSERT INTO outbox (draft_id, attempts, next_attempt_at, last_error)
        VALUES (?, 0, ?, NULL)
        ON CONFLICT(draft_id) DO UPDATE SET
            attempts = 0, next_attempt_at = excluded.next_attempt_at, last_error = NULL
        """,
        (draft_id, run_at),
    )
    await conn.commit()


async def claim_due(now: int | None = None) -> list[str]:
    """Return draft_ids whose retry window has arrived. No locking — worker is single."""
    if now is None:
        now = int(time.time())
    conn = get_conn()
    cur = await conn.execute(
        "SELECT draft_id FROM outbox WHERE next_attempt_at <= ? ORDER BY next_attempt_at",
        (now,),
    )
    rows = await cur.fetchall()
    await cur.close()
    return [r["draft_id"] for r in rows]


async def mark_failed(draft_id: str, error: str) -> int:
    """Bump attempts, schedule next try via exponential backoff. Returns new attempts count."""
    conn = get_conn()
    cur = await conn.execute(
        "SELECT attempts FROM outbox WHERE draft_id = ?", (draft_id,)
    )
    row = await cur.fetchone()
    await cur.close()
    if row is None:
        return 0
    attempts = row["attempts"] + 1
    next_attempt_at = int(time.time()) + _next_delay(attempts)
    await conn.execute(
        """
        UPDATE outbox SET attempts = ?, next_attempt_at = ?, last_error = ?
        WHERE draft_id = ?
        """,
        (attempts, next_attempt_at, error, draft_id),
    )
    await conn.commit()
    return attempts


async def delete(draft_id: str) -> None:
    conn = get_conn()
    await conn.execute("DELETE FROM outbox WHERE draft_id = ?", (draft_id,))
    await conn.commit()


async def get_attempts(draft_id: str) -> int | None:
    """Test helper. Returns None if not in outbox."""
    conn = get_conn()
    cur = await conn.execute(
        "SELECT attempts FROM outbox WHERE draft_id = ?", (draft_id,)
    )
    row = await cur.fetchone()
    await cur.close()
    return row["attempts"] if row else None
