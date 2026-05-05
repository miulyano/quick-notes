"""Atomic 'save committed' transaction.

All three operations land or none — guards against the worker crashing between
'inserted into idempotency' and 'deleted draft', which would otherwise leak
ghost drafts.
"""

from __future__ import annotations

import time

from bot.storage.db import get_conn


async def commit_save(draft_id: str, page_id: str) -> None:
    conn = get_conn()
    await conn.execute("BEGIN IMMEDIATE")
    try:
        await conn.execute(
            """
            INSERT INTO idempotency (draft_id, page_id, saved_at) VALUES (?, ?, ?)
            ON CONFLICT(draft_id) DO NOTHING
            """,
            (draft_id, page_id, int(time.time())),
        )
        await conn.execute("DELETE FROM outbox WHERE draft_id = ?", (draft_id,))
        await conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
