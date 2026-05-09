"""Создание Buildin databases для каждой пары (workspace × note_type).

Скрипт читает `bot/domain/workspaces.py` и `bot/domain/note_types.py` —
если ты их отредактировал под свой setup, скрипт автоматически создаст DB
под обновлённый набор (см. раздел «Под себя» в README.md).

Логика (one-step):
1. Читает реестры (workspaces, note_types) и для каждой пары проверяет env
   `BUILDIN_DB_<WS>_<TYPE>`. Если задан — пропускает (мап на существующую DB).
2. Если пусто — создаёт full-page DB прямо в space с plural-title типа из
   `_PLURAL_TITLES` (например `📝 Заметки`). Buildin рендерит full-page DB
   как страницу-раздел с title и full-width таблицей; отдельная wrapper-page
   не нужна. Префикс воркспейса в title не нужен — он и так понятен из
   имени space'а.
3. Печатает в stdout строки `BUILDIN_DB_<WS>_<TYPE>=<uuid>` (для копи-пейста в .env).

Юзкейсы:
- Свежий запуск: все DB создаются.
- Повторный запуск: уже привязанные slot'ы пропускаются, создаются только новые
  (например, после добавления нового note type).

Флаги:
- `--dry-run` — не делать сетевых вызовов, печатать что было бы создано.
- `--workspace=<key>` — только один workspace (например `--workspace=work`).
- `--type=<key>` — только один тип (например `--type=task`).

Запуск:
  source .venv/bin/activate
  python -m scripts.setup_buildin_dbs >> .env
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Optional

import httpx

from bot.config import settings
from bot.domain.note_types import NoteType, NotionProperty, TYPES, get as get_type
from bot.domain.workspaces import WORKSPACES, Workspace, get as get_workspace
from bot.services.sinks.buildin import BASE_URL


logger = logging.getLogger(__name__)


def _property_schema(prop: NotionProperty) -> dict:
    """Сборка PropertySchema<Kind> для CreateDatabaseRequest."""
    base = {"name": prop.name, "type": prop.kind}
    if prop.kind == "title":
        base["title"] = {}
    elif prop.kind == "rich_text":
        base["rich_text"] = {}
    elif prop.kind == "select":
        base["select"] = {
            "options": [{"name": o} for o in prop.select_options] if prop.select_options else []
        }
    elif prop.kind == "multi_select":
        base["multi_select"] = {
            "options": [{"name": o} for o in prop.select_options] if prop.select_options else []
        }
    elif prop.kind == "date":
        base["date"] = {}
    elif prop.kind == "checkbox":
        base["checkbox"] = {}
    return base


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


def _section_title(ws: Workspace, note_type: NoteType) -> str:
    return _PLURAL_TITLES.get(note_type.key, note_type.label)


def _build_create_payload(ws: Workspace, note_type: NoteType, space_id: str) -> dict:
    """Full-page DB прямо в space — без промежуточной wrapper-page."""
    title = _section_title(ws, note_type)
    properties: dict[str, dict] = {p.name: _property_schema(p) for p in note_type.properties}

    # Title-property обязателен. Если в типе нет title — добавим Name.
    if not any(p.kind == "title" for p in note_type.properties):
        properties["Name"] = _property_schema(NotionProperty("Name", "title"))

    # CreatedAt автоматом — sink его пишет на каждой странице.
    properties["CreatedAt"] = _property_schema(NotionProperty("CreatedAt", "date"))

    return {
        "parent": {"type": "space_id", "space_id": space_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    }


def _env_name(ws: Workspace, note_type: NoteType) -> str:
    return f"BUILDIN_DB_{ws.key.upper()}_{note_type.key.upper()}"


async def _create_db(client: httpx.AsyncClient, payload: dict) -> str:
    resp = await client.post("/v1/databases", json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"buildin {resp.status_code}: {resp.text[:500]}")
    body = resp.json()
    db_id = body.get("id") or body.get("uuid")
    if not db_id:
        raise RuntimeError(f"databases.create response missing id: {body!r}")
    return db_id


async def run(workspace_filter: Optional[str], type_filter: Optional[str], dry_run: bool) -> int:
    workspaces = [
        w for w in WORKSPACES if workspace_filter is None or w.key == workspace_filter
    ]
    note_types = [t for t in TYPES if type_filter is None or t.key == type_filter]

    if workspace_filter and not workspaces:
        sys.stderr.write(f"unknown workspace: {workspace_filter}\n")
        return 2
    if type_filter and not note_types:
        sys.stderr.write(f"unknown note type: {type_filter}\n")
        return 2

    if not dry_run and not settings.BUILDIN_TOKEN:
        sys.stderr.write("BUILDIN_TOKEN не задан — задайте в .env или export BUILDIN_TOKEN=...\n")
        return 2

    headers = {"Authorization": f"Bearer {settings.BUILDIN_TOKEN}"} if settings.BUILDIN_TOKEN else {}
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=30.0) as client:
        for ws in workspaces:
            space_id = settings.buildin_space_id(ws.key)
            for note_type in note_types:
                env_name = _env_name(ws, note_type)
                existing = os.environ.get(env_name)
                if existing:
                    print(f"# already mapped: {env_name}={existing}")
                    continue

                if not space_id:
                    sys.stderr.write(
                        f"# skip {env_name}: {ws.space_env} не задан\n"
                    )
                    continue

                section_title = _section_title(ws, note_type)
                if dry_run:
                    print(
                        f"# would create full-page DB {section_title!r} in space={space_id} "
                        f"→ {env_name}"
                    )
                    continue

                payload = _build_create_payload(ws, note_type, space_id)
                try:
                    db_id = await _create_db(client, payload)
                except Exception as exc:
                    sys.stderr.write(f"# failed db for {env_name}: {exc}\n")
                    continue
                print(f"{env_name}={db_id}  # {section_title}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Buildin DB setup script")
    parser.add_argument("--dry-run", action="store_true", help="Не делать сетевых вызовов")
    parser.add_argument("--workspace", help="ключ одного workspace (см. workspaces.py)")
    parser.add_argument("--type", dest="note_type", help="ключ одного note type")
    args = parser.parse_args()

    return asyncio.run(run(args.workspace, args.note_type, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
