"""Notion sink. Per-(workspace × type) DB routing + lazy one-step auto-create.

Real path (хотя бы один токен + хотя бы один resolvable DB или parent-page)
создаёт страницу в DB-таргете для пары (draft.workspace, draft.note_type).
Резолв через `_notion_resolver.resolve_or_create`:

  cache (notion_dbs table) → NOTION_DB_<WS>_<TYPE> → NOTION_DB_<TYPE>
                          → NOTION_DATABASE_ID
                          → auto-create под NOTION_PARENT_PAGE_<WS>
                            (один POST databases.create — full-page DB)

Notion рендерит full-page DB как страницу с title и full-width таблицей,
поэтому отдельная wrapper-page не нужна.

Setup the user must do (see README):
- Internal Integration в Notion → token в NOTION_TOKEN.
  Если бот-воркспейсы лежат в разных Notion workspaces — задать
  NOTION_TOKEN_<WS> на каждый (имеет приоритет над глобальным NOTION_TOKEN).
- Один из:
  - NOTION_DATABASE_ID (минимум — все типы и workspace'ы упадут туда), либо
  - per-type / per-(ws×type) env ids, либо
  - NOTION_PARENT_PAGE_<WS> на каждый используемый workspace —
    бот создаст full-page DB при первом hit и закэширует.
- Каждая DB / parent-page должна быть расшарена с integration
  (Connections → Add). Auto-created DB наследует доступ от parent-page.

Без любого токена/DB → stub mode (logs only).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from bot.config import settings
from bot.domain.note_types import get as get_note_type
from bot.services.sinks import FailureInjector, PageRef
from bot.services.sinks._notion_resolver import resolve_or_create
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
        self._clients_real: dict[str, Any] = {}

    def set_failure_injector(self, fn: Optional[FailureInjector]) -> None:
        self._failure_injector = fn

    def set_client(self, client: Any) -> None:
        """Test hook: inject a stand-in for `notion_client.AsyncClient`.

        Один override-клиент покрывает все воркспейсы (тестам всё равно)."""
        self._client_override = client

    async def close(self) -> None:
        """Закрыть все notion_client.AsyncClient при graceful shutdown."""
        for ws, client in list(self._clients_real.items()):
            try:
                await client.aclose()
            except Exception:
                logger.exception("notion client close failed ws=%s", ws)
        self._clients_real.clear()

    def _get_client(self, workspace_key: str) -> Any:
        if self._client_override is not None:
            return self._client_override
        cached = self._clients_real.get(workspace_key)
        if cached is not None:
            return cached
        token = settings.notion_token_for(workspace_key)
        if not token:
            raise RuntimeError(
                f"no Notion token for ws={workspace_key}: "
                f"set NOTION_TOKEN_{workspace_key.upper()} or NOTION_TOKEN"
            )
        from notion_client import AsyncClient

        # Pin Notion-Version to 2022-06-28: SDK 2.7.0+ defaults to 2025-09-03,
        # which split databases→data_sources. Our auto-create payload still
        # uses the legacy shape (`properties` directly on database), so the
        # newer version drops them and creates a Name-only DB. See PR #20 /
        # CHANGELOG entry for details. Migration to data_sources is a future
        # feat task.
        client = AsyncClient(auth=token, notion_version="2022-06-28")
        self._clients_real[workspace_key] = client
        return client

    async def _create_page_stub(self, draft: Draft) -> PageRef:
        page_id = f"stub-page-{uuid.uuid4().hex[:8]}"
        logger.info(
            "STUB notion.create_page draft_id=%s type=%s title=%r body_len=%d page_id=%s",
            draft.id,
            draft.note_type,
            draft.title,
            len(draft.formatted or ""),
            page_id,
        )
        return PageRef(id=page_id, url=None)

    async def _create_page_real(self, draft: Draft) -> PageRef:
        note_type = get_note_type(draft.note_type or "")
        workspace_key = draft.workspace or "personal"
        client = self._get_client(workspace_key)

        database_id = await resolve_or_create(workspace_key, note_type, client)
        if not database_id:
            raise RuntimeError(
                f"no Notion database for ws={workspace_key} type={note_type.key} "
                f"and NOTION_PARENT_PAGE_{workspace_key.upper()} not set; "
                f"set NOTION_DATABASE_ID, NOTION_DB_{note_type.key.upper()}, "
                f"or NOTION_PARENT_PAGE_{workspace_key.upper()} to unblock"
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

        response = await client.pages.create(
            parent={"database_id": database_id},
            properties=properties,
            children=blocks,
        )
        return PageRef(id=response["id"], url=response.get("url"))

    async def create_page(self, draft: Draft) -> PageRef:
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


async def create_page(draft: Draft) -> PageRef:
    return await _sink.create_page(draft)


async def close() -> None:
    await _sink.close()


def get_sink_instance() -> NotionSink:
    return _sink
