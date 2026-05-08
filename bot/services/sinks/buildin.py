"""Buildin sink (https://api.buildin.ai).

Buildin API структурно близок к Notion (`/v1/databases`, `/v1/pages`, `/v1/blocks`),
но отличается wire-форматом:
- Parent: `{"type": "database_id", "database_id": "..."}` (явный дискриминатор).
- Property value: `{"type": "title", "title": [...]}` (тип в теле).
- Block: `{"type": "paragraph", "data": {"rich_text": [...]}}` (контент под `data`).
- Auth: только Bearer (без Notion-Version header).

Без BUILDIN_TOKEN → stub-mode (как Notion).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

import httpx

from bot.config import settings
from bot.domain.note_types import get as get_note_type
from bot.domain.workspaces import DEFAULT_WORKSPACE
from bot.services.sinks import FailureInjector, PageRef
from bot.services.sinks._properties import build_properties as _build_properties
from bot.storage.drafts import Draft
from bot.utils.md_blocks import image_block_buildin, markdown_to_blocks_buildin

logger = logging.getLogger(__name__)

BASE_URL = "https://api.buildin.ai"
MAX_BLOCKS_PER_REQUEST = 100  # `maxItems` в openapi для children в pages.create / append.
DEFAULT_TIMEOUT = 30.0


def _extras_image_urls(draft: Draft) -> list[str]:
    """См. `bot.services.sinks.notion._extras_image_urls`."""
    if not draft.extras_json:
        return []
    try:
        extras = json.loads(draft.extras_json)
    except (TypeError, ValueError):
        return []
    urls = extras.get("image_urls") if isinstance(extras, dict) else None
    if not isinstance(urls, list):
        return []
    return [u for u in urls if isinstance(u, str) and u]


def build_properties(note_type, draft):
    """Backwards-compatible wrapper. Используется тестами; новый код зовёт
    `_properties.build_properties` напрямую с shape="buildin"."""
    return _build_properties(note_type, draft, shape="buildin")


class BuildinError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"buildin {status}: {message}")
        self.status = status
        self.message = message


class BuildinSink:
    def __init__(self) -> None:
        self._failure_injector: Optional[FailureInjector] = None
        self._client_override: Optional[httpx.AsyncClient] = None
        self._client_real: Optional[httpx.AsyncClient] = None

    def set_failure_injector(self, fn: Optional[FailureInjector]) -> None:
        self._failure_injector = fn

    def set_client(self, client: Optional[httpx.AsyncClient]) -> None:
        """Test hook: подмена httpx.AsyncClient (используется с MockTransport)."""
        self._client_override = client

    async def close(self) -> None:
        """Закрыть фоновую httpx-сессию при graceful shutdown."""
        if self._client_real is not None:
            try:
                await self._client_real.aclose()
            except Exception:
                logger.exception("buildin httpx client close failed")
            self._client_real = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client_override is not None:
            return self._client_override
        if self._client_real is None:
            self._client_real = httpx.AsyncClient(
                base_url=BASE_URL,
                headers={"Authorization": f"Bearer {settings.BUILDIN_TOKEN or ''}"},
                timeout=DEFAULT_TIMEOUT,
            )
        return self._client_real

    async def _request(self, method: str, path: str, *, json_body: Optional[dict] = None) -> dict:
        client = self._get_client()
        resp = await client.request(method, path, json=json_body)
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = {"raw": resp.text[:500]}
            raise BuildinError(resp.status_code, json.dumps(detail, ensure_ascii=False))
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    async def users_me(self) -> dict:
        """Health-check: validate token + получить инфу о боте."""
        return await self._request("GET", "/v1/users/me")

    async def _create_page_stub(self, draft: Draft) -> PageRef:
        page_id = f"stub-page-{uuid.uuid4().hex[:8]}"
        logger.info(
            "STUB buildin.create_page draft_id=%s type=%s ws=%s title=%r body_len=%d page_id=%s",
            draft.id,
            draft.note_type,
            draft.workspace,
            draft.title,
            len(draft.formatted or ""),
            page_id,
        )
        return PageRef(id=page_id, url=None)

    async def _append_children(self, page_id: str, blocks: list[dict]) -> None:
        """Дозалить блоки сверх первой сотни — чанками по 100 через PATCH."""
        for i in range(0, len(blocks), MAX_BLOCKS_PER_REQUEST):
            chunk = blocks[i : i + MAX_BLOCKS_PER_REQUEST]
            await self._request(
                "PATCH",
                f"/v1/blocks/{page_id}/children",
                json_body={"children": chunk},
            )

    async def _create_page_real(self, draft: Draft) -> PageRef:
        note_type = get_note_type(draft.note_type or "")
        workspace_key = draft.workspace or DEFAULT_WORKSPACE
        database_id = settings.database_id_for(
            note_type.db_env, provider="buildin", workspace_key=workspace_key
        )
        if not database_id:
            raise RuntimeError(
                f"no Buildin database configured for workspace={workspace_key} "
                f"type={note_type.key} (BUILDIN_DB_{workspace_key.upper()}_{note_type.key.upper()} "
                f"/ BUILDIN_DB_{note_type.key.upper()} / BUILDIN_DB_DEFAULT)"
            )

        body = draft.formatted or ""
        image_urls = _extras_image_urls(draft)
        blocks = [image_block_buildin(u) for u in image_urls] + markdown_to_blocks_buildin(body)
        first_chunk = blocks[:MAX_BLOCKS_PER_REQUEST]
        rest = blocks[MAX_BLOCKS_PER_REQUEST:]

        payload = {
            "parent": {"type": "database_id", "database_id": database_id},
            "properties": build_properties(note_type, draft),
            "children": first_chunk,
        }
        response = await self._request("POST", "/v1/pages", json_body=payload)
        page_id = response.get("id") or response.get("uuid")
        if not page_id:
            raise RuntimeError(f"buildin pages.create response missing id: {response!r}")

        if rest:
            await self._append_children(page_id, rest)

        return PageRef(id=page_id, url=response.get("url"))

    async def create_page(self, draft: Draft) -> PageRef:
        if self._failure_injector is not None:
            await self._failure_injector(draft)
        if settings.buildin_enabled:
            return await self._create_page_real(draft)
        return await self._create_page_stub(draft)


_sink = BuildinSink()


def set_failure_injector(fn: Optional[FailureInjector]) -> None:
    _sink.set_failure_injector(fn)


def set_client(client: Optional[httpx.AsyncClient]) -> None:
    _sink.set_client(client)


async def create_page(draft: Draft) -> PageRef:
    return await _sink.create_page(draft)


async def users_me() -> dict:
    return await _sink.users_me()


async def close() -> None:
    await _sink.close()


def get_sink_instance() -> BuildinSink:
    return _sink
