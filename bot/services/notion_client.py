"""Notion sink. Real implementation when NOTION_TOKEN set, stub otherwise.

Required Notion database schema (set up by the user, see README):
- "Name"      — title    (required by Notion for any database)
- "Type"      — select   (note types: note, …; values populated as you go)
- "CreatedAt" — date     (auto-set by the bot)

Failure-injector hook is preserved across the stub/real switch so tests can
simulate transient errors regardless of which path is active.
"""

from __future__ import annotations

import datetime as _dt
import logging
import uuid
from typing import Any, Awaitable, Callable, Optional

from bot.config import settings
from bot.storage.drafts import Draft
from bot.utils.md_blocks import markdown_to_blocks

logger = logging.getLogger(__name__)

# Notion limits children-per-pages.create to 100. Notes shouldn't get this big,
# but cap defensively rather than risk an API error.
MAX_BLOCKS_PER_PAGE = 100

FailureInjector = Callable[[Draft], Awaitable[None]]
_failure_injector: Optional[FailureInjector] = None
_client_override: Any = None
_client_real: Any = None


def set_failure_injector(fn: Optional[FailureInjector]) -> None:
    global _failure_injector
    _failure_injector = fn


def set_client(client: Any) -> None:
    """Test hook: inject a stand-in for `notion_client.AsyncClient`."""
    global _client_override
    _client_override = client


def _get_client() -> Any:
    if _client_override is not None:
        return _client_override
    global _client_real
    if _client_real is None:
        # Imported lazily so the stub path doesn't require notion-client
        # installed (helpful in lean test envs).
        from notion_client import AsyncClient

        _client_real = AsyncClient(auth=settings.NOTION_TOKEN)
    return _client_real


async def _create_page_stub(draft: Draft) -> str:
    page_id = f"stub-page-{uuid.uuid4().hex[:8]}"
    logger.info(
        "STUB notion.create_page draft_id=%s type=%s title=%r body_len=%d page_id=%s",
        draft.id,
        draft.note_type,
        draft.title,
        len(draft.formatted or ""),
        page_id,
    )
    return page_id


def _now_iso() -> str:
    # Notion accepts ISO-8601 with timezone offset.
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


async def _create_page_real(draft: Draft) -> str:
    title = draft.title or "Без названия"
    body = draft.formatted or ""
    blocks = markdown_to_blocks(body)
    if len(blocks) > MAX_BLOCKS_PER_PAGE:
        logger.warning(
            "draft=%s produced %d blocks (cap=%d), truncating",
            draft.id,
            len(blocks),
            MAX_BLOCKS_PER_PAGE,
        )
        blocks = blocks[:MAX_BLOCKS_PER_PAGE]

    properties = {
        "Name": {"title": [{"text": {"content": title}}]},
        "Type": {"select": {"name": draft.note_type or "note"}},
        "CreatedAt": {"date": {"start": _now_iso()}},
    }

    client = _get_client()
    response = await client.pages.create(
        parent={"database_id": settings.NOTION_DATABASE_ID},
        properties=properties,
        children=blocks,
    )
    return response["id"]


async def create_page(draft: Draft) -> str:
    if _failure_injector is not None:
        await _failure_injector(draft)
    if settings.notion_enabled:
        return await _create_page_real(draft)
    return await _create_page_stub(draft)
