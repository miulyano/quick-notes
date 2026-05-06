"""Draft CRUD. Status machine:
raw → transcribed → classified → awaiting_confirm → saving → [DELETE] | failed

Edit-ветки из awaiting_confirm:
awaiting_confirm ↔ awaiting_edit_title
awaiting_confirm ↔ awaiting_edit_body
После записи нового значения статус возвращается в awaiting_confirm.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

from bot.storage.db import get_conn


@dataclass
class Draft:
    id: str
    user_id: int
    chat_id: int
    message_id: Optional[int]
    preview_msg_id: Optional[int]
    status: str
    kind: str
    raw_payload: str
    transcribed: Optional[str]
    note_type: Optional[str]
    formatted: Optional[str]
    title: Optional[str]
    properties: Optional[str]
    error: Optional[str]
    created_at: int
    updated_at: int
    workspace: str = "personal"  # одно из workspaces.all_keys(); default = DEFAULT_WORKSPACE.
    extras_json: Optional[str] = None  # JSON-сериализованный extras от LLM (kind, action_items и т.п.).


def _row_to_draft(row) -> Draft:
    return Draft(**dict(row))


async def create(
    *,
    user_id: int,
    chat_id: int,
    message_id: Optional[int],
    kind: str,
    raw_payload: str,
    status: str = "raw",
) -> str:
    """Insert draft and commit. Returns draft_id (uuid4 hex)."""
    draft_id = uuid.uuid4().hex
    now = int(time.time())
    conn = get_conn()
    await conn.execute(
        """
        INSERT INTO drafts (
            id, user_id, chat_id, message_id, status, kind, raw_payload,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (draft_id, user_id, chat_id, message_id, status, kind, raw_payload, now, now),
    )
    await conn.commit()
    return draft_id


async def update(draft_id: str, **fields) -> None:
    """Update arbitrary mutable fields plus updated_at. Status transitions go here too."""
    if not fields:
        return
    fields["updated_at"] = int(time.time())
    columns = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [draft_id]
    conn = get_conn()
    await conn.execute(f"UPDATE drafts SET {columns} WHERE id = ?", values)
    await conn.commit()


async def get(draft_id: str) -> Optional[Draft]:
    conn = get_conn()
    cur = await conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
    row = await cur.fetchone()
    await cur.close()
    return _row_to_draft(row) if row else None


async def list_for_user(user_id: int, limit: int = 50) -> list[Draft]:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM drafts WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    rows = await cur.fetchall()
    await cur.close()
    return [_row_to_draft(r) for r in rows]


async def delete(draft_id: str) -> None:
    conn = get_conn()
    await conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
    await conn.commit()


async def find_awaiting_edit(user_id: int) -> Optional[Draft]:
    """Most recent draft of this user in awaiting_edit_title|awaiting_edit_body, или None."""
    conn = get_conn()
    cur = await conn.execute(
        """
        SELECT * FROM drafts
        WHERE user_id = ?
          AND status IN ('awaiting_edit_title', 'awaiting_edit_body')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    return _row_to_draft(row) if row else None


async def find_stale_saving(older_than_secs: int) -> list[Draft]:
    """Find drafts stuck in saving longer than the threshold (sec).

    Used on startup to recover from crashes mid-save.
    """
    cutoff = int(time.time()) - older_than_secs
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM drafts WHERE status = 'saving' AND updated_at < ?",
        (cutoff,),
    )
    rows = await cur.fetchall()
    await cur.close()
    return [_row_to_draft(r) for r in rows]
