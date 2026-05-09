"""Резолв Notion database id для пары (workspace, note_type) с lazy-create.

Цепочка:
1. SQLite-кэш `notion_dbs` (заполняется этим резолвером после auto-create).
2. `NOTION_DB_<WS>_<TYPE>` env (если форкер хочет руками задать конкретные DB).
3. `NOTION_DB_<TYPE>` env / `NOTION_DATABASE_ID` (классический per-type fallback).
4. Auto-create (one-step):
   если `NOTION_PARENT_PAGE_<WS>` задан — `databases.create` создаёт full-page DB
   прямо в parent-page воркспейса с plural-title типа («📝 Заметки», «✅ Задачи», ...)
   и схемой из `note_types.py`. Notion рендерит full-page DB как страницу с
   title и full-width таблицей — отдельная wrapper-page не нужна.
5. Если parent-page не задан — возвращает None (sink упадёт с понятной ошибкой).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from bot.config import settings
from bot.domain.note_types import NoteType, NotionProperty
from bot.storage import notion_dbs

logger = logging.getLogger(__name__)

# Plural-форма title'ов под full-page DB (совпадает с scripts/setup_buildin_dbs.py).
_PLURAL_TITLES: dict[str, str] = {
    "note": "📝 Заметки",
    "task": "✅ Задачи",
    "idea": "💡 Идеи",
    "meeting": "🤝 Митинги",
    "1on1": "👥 1:1",
    "work": "💼 Рабочее",
    "personal": "🌱 Личное",
    "book": "📚 Книги",
    "film": "🎥 Фильмы",
}


def _property_schema(prop: NotionProperty) -> dict:
    """Схема Notion property под `databases.create`."""
    base: dict[str, Any] = {prop.kind: {}}
    if prop.kind in ("select", "multi_select") and prop.select_options:
        base[prop.kind] = {"options": [{"name": o} for o in prop.select_options]}
    return base


def _section_title(note_type: NoteType) -> str:
    return _PLURAL_TITLES.get(note_type.key, note_type.label)


def _build_create_payload(parent_page_id: str, note_type: NoteType) -> dict:
    title = _section_title(note_type)
    properties: dict[str, dict] = {p.name: _property_schema(p) for p in note_type.properties}

    # Title-property обязателен. Если в типе нет title — добавим Name.
    if not any(p.kind == "title" for p in note_type.properties):
        properties["Name"] = _property_schema(NotionProperty("Name", "title"))

    # CreatedAt автоматом — sink его пишет на каждой странице.
    properties["CreatedAt"] = _property_schema(NotionProperty("CreatedAt", "date"))

    return {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    }


async def resolve_or_create(
    workspace_key: str,
    note_type: NoteType,
    client: Any,
) -> Optional[str]:
    """Возвращает database_id для пары (workspace, type).

    `client` — `notion_client.AsyncClient` или test-stub с тем же интерфейсом
    (метод `databases.create(**payload)` возвращающий dict с ключом "id").

    Возвращает None если ничего не задано и parent-page для workspace не
    сконфигурирован — caller должен это обработать (sink бросит RuntimeError
    с понятным сообщением).
    """
    # 1. cache
    cached = await notion_dbs.get(workspace_key, note_type.key)
    if cached:
        return cached

    # 2-3. env (per-(ws×type) → per-type → default)
    env_db = settings.database_id_for(
        note_type.db_env, provider="notion", workspace_key=workspace_key
    )
    if env_db:
        return env_db

    # 4. auto-create: one-step full-page DB прямо в parent-page воркспейса.
    parent_page_id = settings.notion_parent_page_id(workspace_key)
    if not parent_page_id:
        logger.warning(
            "no Notion DB for ws=%s type=%s and NOTION_PARENT_PAGE_%s not set; "
            "sink will fail until you set NOTION_DATABASE_ID, NOTION_DB_%s, "
            "or NOTION_PARENT_PAGE_%s",
            workspace_key,
            note_type.key,
            workspace_key.upper(),
            note_type.key.upper(),
            workspace_key.upper(),
        )
        return None

    db_payload = _build_create_payload(parent_page_id, note_type)
    logger.info(
        "creating Notion DB on demand: ws=%s type=%s parent=%s",
        workspace_key,
        note_type.key,
        parent_page_id,
    )
    db_response = await client.databases.create(**db_payload)
    db_id = db_response.get("id") if isinstance(db_response, dict) else None
    if not db_id:
        raise RuntimeError(
            f"databases.create response missing id for ws={workspace_key} "
            f"type={note_type.key}: {db_response!r}"
        )

    await notion_dbs.put(workspace_key, note_type.key, db_id)
    logger.info(
        "cached Notion DB ws=%s type=%s database_id=%s",
        workspace_key,
        note_type.key,
        db_id,
    )
    return db_id
