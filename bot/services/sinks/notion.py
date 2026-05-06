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

import logging
import uuid
from typing import Any, Optional

from bot.config import settings
from bot.domain.note_types import get as get_note_type
from bot.services.sinks import FailureInjector
from bot.services.sinks._properties import build_properties as _build_properties
from bot.storage.drafts import Draft
from bot.utils.md_blocks import markdown_to_blocks

logger = logging.getLogger(__name__)

MAX_BLOCKS_PER_PAGE = 100  # Notion API: pages.create accepts up to 100 children.


def build_properties(note_type, draft):
    """Backwards-compatible wrapper. Используется тестами; новый код зовёт
    `_properties.build_properties` напрямую с shape="notion"."""
    return _build_properties(note_type, draft, shape="notion")


class NotionSink:
    def __init__(self) -> None:
        self._failure_injector: Optional[FailureInjector] = None
        self._client_override: Any = None
        self._client_real: Any = None

    def set_failure_injector(self, fn: Optional[FailureInjector]) -> None:
        self._failure_injector = fn

    def set_client(self, client: Any) -> None:
        """Test hook: inject a stand-in for `notion_client.AsyncClient`."""
        self._client_override = client

    async def close(self) -> None:
        """Закрыть notion_client.AsyncClient при graceful shutdown."""
        if self._client_real is not None:
            try:
                await self._client_real.aclose()
            except Exception:
                logger.exception("notion client close failed")
            self._client_real = None

    def _get_client(self) -> Any:
        if self._client_override is not None:
            return self._client_override
        if self._client_real is None:
            from notion_client import AsyncClient

            self._client_real = AsyncClient(auth=settings.NOTION_TOKEN)
        return self._client_real

    async def _create_page_stub(self, draft: Draft) -> str:
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

    async def _create_page_real(self, draft: Draft) -> str:
        note_type = get_note_type(draft.note_type or "")
        database_id = settings.database_id_for(note_type.db_env, provider="notion")
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

        client = self._get_client()
        response = await client.pages.create(
            parent={"database_id": database_id},
            properties=properties,
            children=blocks,
        )
        return response["id"]

    async def create_page(self, draft: Draft) -> str:
        if self._failure_injector is not None:
            await self._failure_injector(draft)
        if settings.notion_enabled:
            return await self._create_page_real(draft)
        return await self._create_page_stub(draft)


# Один процесс — один sink. Не singleton-pattern, просто модульный объект.
_sink = NotionSink()


# Обратно-совместимые модульные функции (старый импорт-сурфейс — используется
# тестами и старым outbox_worker до миграции на factory).
def set_failure_injector(fn: Optional[FailureInjector]) -> None:
    _sink.set_failure_injector(fn)


def set_client(client: Any) -> None:
    _sink.set_client(client)


async def create_page(draft: Draft) -> str:
    return await _sink.create_page(draft)


async def close() -> None:
    await _sink.close()


def get_sink_instance() -> NotionSink:
    return _sink
