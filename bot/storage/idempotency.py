"""Dedup: draft_id → page_id mapping that survives draft deletion.

No FK on drafts intentionally — a successful save deletes the draft but the
idempotency record stays so retries after crash won't double-create pages.
"""

from __future__ import annotations

import time

from bot.storage.db import get_conn


async def insert(draft_id: str, page_id: str) -> None:
    conn = get_conn()
    await conn.execute(
        """
        INSERT INTO idempotency (draft_id, page_id, saved_at) VALUES (?, ?, ?)
        ON CONFLICT(draft_id) DO NOTHING
        """,
        (draft_id, page_id, int(time.time())),
    )
    await conn.commit()


async def get_page_id(draft_id: str) -> str | None:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT page_id FROM idempotency WHERE draft_id = ?", (draft_id,)
    )
    row = await cur.fetchone()
    await cur.close()
    return row["page_id"] if row else None
