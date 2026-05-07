"""One-shot чистка автосозданных wrapper-страниц + старых full-page DB в Notion.

Контекст: до этого фикса резолвер `_notion_resolver` создавал на каждую пару
(workspace × type) wrapper-страницу + full-page DB внутри неё. Это давало
визуальное дублирование заголовка («📝 Заметки» → внутри «📝 Заметки» →
DB header). Скрипт архивирует старые wrapper-страницы (вместе с DB внутри)
и чистит SQLite-кэш `notion_dbs`. После прогона следующее сохранение заметки
создаст свежую full-page DB по новому one-step флоу.

Что трогает:
- Только записи в `notion_dbs` table — это всегда auto-created пары.
  Явно проставленные `NOTION_DB_*` env остаются нетронутыми (их и нет в кэше).

Что делает на каждой записи:
1. `databases.retrieve(database_id=...)` → достаёт `parent.page_id` (wrapper).
2. `pages.update(page_id=wrapper, archived=True)` → Notion архивирует wrapper,
   DB внутри уезжает в trash вместе с ним. Trash хранится 30 дней — можно
   восстановить через UI, если что.
3. После прохода всех записей — DELETE FROM notion_dbs.

Флаги:
- `--dry-run` — печатает что было бы архивировано, без сетевых вызовов и без
  чистки кэша.
- `--workspace=<key>` — только один workspace.
- `--type=<key>` — только один тип.

Запуск:
  source .venv/bin/activate
  python -m scripts.cleanup_notion_orphans --dry-run
  python -m scripts.cleanup_notion_orphans
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Optional

from bot.config import settings
from bot.storage import db as db_module
from bot.storage import notion_dbs

logger = logging.getLogger(__name__)


async def _archive_wrapper(client: Any, database_id: str) -> Optional[str]:
    """Возвращает id архивированной wrapper-page или None если уже отсутствует."""
    db_meta = await client.databases.retrieve(database_id=database_id)
    parent = db_meta.get("parent") or {}
    if parent.get("type") != "page_id":
        logger.warning(
            "database %s parent type is %r, not page_id — пропускаю архивацию",
            database_id,
            parent.get("type"),
        )
        return None
    wrapper_id = parent.get("page_id")
    if not wrapper_id:
        logger.warning("database %s parent.page_id отсутствует", database_id)
        return None
    await client.pages.update(page_id=wrapper_id, archived=True)
    return wrapper_id


def _make_client(workspace_key: str) -> Any:
    token = settings.notion_token_for(workspace_key)
    if not token:
        raise RuntimeError(
            f"no Notion token for ws={workspace_key}: "
            f"set NOTION_TOKEN_{workspace_key.upper()} or NOTION_TOKEN"
        )
    from notion_client import AsyncClient

    return AsyncClient(auth=token, notion_version="2022-06-28")


async def run(
    workspace_filter: Optional[str],
    type_filter: Optional[str],
    dry_run: bool,
    client_factory=_make_client,
    init_db_path: Optional[str] = None,
) -> int:
    if init_db_path is not None:
        await db_module.init_db(init_db_path)
    rows = await notion_dbs.all_entries()
    if workspace_filter:
        rows = [r for r in rows if r["workspace"] == workspace_filter]
    if type_filter:
        rows = [r for r in rows if r["note_type"] == type_filter]

    if not rows:
        print("# notion_dbs cache пуст — чистить нечего")
        return 0

    print(f"# собираюсь обработать {len(rows)} записей в notion_dbs")

    archived = 0
    failed = 0
    clients: dict[str, Any] = {}
    for row in rows:
        ws = row["workspace"]
        nt = row["note_type"]
        db_id = row["database_id"]

        if dry_run:
            print(f"# would archive wrapper of database {db_id} (ws={ws} type={nt})")
            continue

        if ws not in clients:
            try:
                clients[ws] = client_factory(ws)
            except Exception as exc:
                logger.warning("skip ws=%s: %s", ws, exc)
                failed += 1
                continue

        try:
            wrapper_id = await _archive_wrapper(clients[ws], db_id)
        except Exception as exc:
            logger.warning(
                "archive failed for ws=%s type=%s db=%s: %s", ws, nt, db_id, exc
            )
            failed += 1
            continue

        if wrapper_id:
            print(f"# archived wrapper {wrapper_id} (ws={ws} type={nt} db={db_id})")
            archived += 1
        else:
            print(f"# skipped {db_id} (ws={ws} type={nt}) — нет wrapper-page")

        await notion_dbs.delete(ws, nt)

    if dry_run:
        print(f"# dry-run: ничего не изменено ({len(rows)} записей в кэше)")
        return 0

    if not workspace_filter and not type_filter and failed == 0:
        await notion_dbs.clear()
        print("# notion_dbs cache очищен полностью")

    # Закрываем все созданные httpx-сессии notion_client.
    for ws, client in clients.items():
        try:
            await client.aclose()
        except Exception:
            logger.exception("notion client close failed ws=%s", ws)

    print(f"# done: archived={archived} failed={failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Notion wrapper+DB cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Не делать сетевых вызовов")
    parser.add_argument("--workspace", help="ключ одного workspace")
    parser.add_argument("--type", dest="note_type", help="ключ одного note type")
    args = parser.parse_args()

    return asyncio.run(
        run(
            args.workspace,
            args.note_type,
            args.dry_run,
            init_db_path=settings.DATABASE_PATH,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
