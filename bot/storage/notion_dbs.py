"""Кэш Notion-database id'ов под пары (workspace, note_type).

Lazy auto-create: при первом сохранении в (ws=X, type=Y) sink создаёт DB
в Notion под NOTION_PARENT_PAGE_<X> страницей и пишет id сюда. Дальше
резолв идёт из этого кэша, без обращения к API.

Резолв-цепочка целиком (см. bot/services/sinks/_notion_resolver.py):
    cache → NOTION_DB_<WS>_<TYPE> → NOTION_DB_<TYPE> → NOTION_DATABASE_ID
                                                  → создать новую DB.
"""

from __future__ import annotations

import time
from typing import Optional

from bot.storage.db import get_conn


async def get(workspace: str, note_type: str) -> Optional[str]:
    conn = get_conn()
    async with conn.execute(
        "SELECT database_id FROM notion_dbs WHERE workspace = ? AND note_type = ?",
        (workspace, note_type),
    ) as cur:
        row = await cur.fetchone()
        return row["database_id"] if row else None


async def put(workspace: str, note_type: str, database_id: str) -> None:
    conn = get_conn()
    await conn.execute(
        "INSERT OR REPLACE INTO notion_dbs (workspace, note_type, database_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (workspace, note_type, database_id, int(time.time())),
    )
    await conn.commit()


async def all_entries() -> list[dict]:
    conn = get_conn()
    async with conn.execute(
        "SELECT workspace, note_type, database_id, created_at FROM notion_dbs "
        "ORDER BY workspace, note_type"
    ) as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def delete(workspace: str, note_type: str) -> None:
    conn = get_conn()
    await conn.execute(
        "DELETE FROM notion_dbs WHERE workspace = ? AND note_type = ?",
        (workspace, note_type),
    )
    await conn.commit()


async def clear() -> None:
    """Полная очистка кэша. Используется one-shot скриптом cleanup_notion_orphans."""
    conn = get_conn()
    await conn.execute("DELETE FROM notion_dbs")
    await conn.commit()
