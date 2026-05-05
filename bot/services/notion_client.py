"""Notion sink. Per-type DB routing + per-type properties.

Real path (NOTION_TOKEN + a database id) creates a page in the type-specific
database, with properties built from `draft.properties` JSON via the
NoteType registry.

Setup the user must do (see README):
- One Internal Integration in Notion → token in NOTION_TOKEN.
- For each type used: a database with the schema described in the type's
  NotionProperty list, shared with the integration.
- Per-type ids in env (NOTION_DB_TASK, NOTION_DB_IDEA, ...). Types without an
  override fall back to NOTION_DATABASE_ID.

Without NOTION_TOKEN/NOTION_DATABASE_ID → stub mode (logs only).
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import uuid
from typing import Any, Awaitable, Callable, Optional

from bot.config import settings
from bot.domain.note_types import NoteType, get as get_note_type
from bot.storage.drafts import Draft
from bot.utils.md_blocks import markdown_to_blocks

logger = logging.getLogger(__name__)

MAX_BLOCKS_PER_PAGE = 100  # Notion API: pages.create accepts up to 100 children.

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
        from notion_client import AsyncClient

        _client_real = AsyncClient(auth=settings.NOTION_TOKEN)
    return _client_real


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _wrap_property(kind: str, value: Any) -> Optional[dict]:
    """Notion's typed property payload. Returns None to omit the property."""
    if value is None:
        return None
    if kind == "title":
        return {"title": [{"text": {"content": str(value)}}]}
    if kind == "rich_text":
        return {"rich_text": [{"text": {"content": str(value)}}]}
    if kind == "select":
        return {"select": {"name": str(value)}}
    if kind == "multi_select":
        if not isinstance(value, list):
            value = [value]
        return {"multi_select": [{"name": str(v)} for v in value if v]}
    if kind == "date":
        return {"date": {"start": str(value)}}
    if kind == "checkbox":
        return {"checkbox": bool(value)}
    logger.warning("unknown property kind=%s value=%r", kind, value)
    return None


def build_properties(note_type: NoteType, draft: Draft) -> dict[str, dict]:
    """Construct Notion properties payload from draft.properties JSON.

    Title is filled from draft.title if the LLM didn't include it explicitly.
    `CreatedAt` is appended as a server-side timestamp regardless of type.
    """
    extracted: dict[str, Any] = {}
    if draft.properties:
        try:
            extracted = json.loads(draft.properties)
        except Exception:
            logger.warning("draft.properties not valid JSON: %r", draft.properties)
            extracted = {}

    out: dict[str, dict] = {}
    has_title = False
    for prop in note_type.properties:
        value = extracted.get(prop.name)
        if prop.kind == "title":
            has_title = True
            if not value:
                value = draft.title or "Без названия"
        wrapped = _wrap_property(prop.kind, value)
        if wrapped is not None:
            out[prop.name] = wrapped

    if not has_title:
        # Notion DB requires a title property. If the type config didn't
        # declare one, use draft.title under "Name" as a safe default.
        out["Name"] = _wrap_property("title", draft.title or "Без названия")

    out["CreatedAt"] = {"date": {"start": _now_iso()}}
    return out


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


async def _create_page_real(draft: Draft) -> str:
    note_type = get_note_type(draft.note_type or "")
    database_id = settings.database_id_for(note_type.db_env)
    if not database_id:
        raise RuntimeError(
            f"no Notion database configured for type={note_type.key} "
            f"(env={note_type.db_env} or NOTION_DATABASE_ID)"
        )

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

    properties = build_properties(note_type, draft)

    client = _get_client()
    response = await client.pages.create(
        parent={"database_id": database_id},
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
