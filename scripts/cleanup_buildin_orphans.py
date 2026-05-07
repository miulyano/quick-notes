"""One-shot чистка автосозданных wrapper-страниц + старых DB в Buildin.

Контекст: до этого фикса `scripts/setup_buildin_dbs` создавал на каждую пару
(workspace × type) wrapper-страницу в space + full-page DB внутри неё. Это
давало визуальное дублирование заголовка («📝 Заметки» → внутри «📝 Заметки» →
DB header). Скрипт архивирует старые wrapper-страницы (вместе с DB внутри)
по env-привязкам `BUILDIN_DB_<WS>_<TYPE>`.

Что трогает:
- Только пары `(workspace, note_type)` из реестров `WORKSPACES` × `TYPES`,
  для которых задан env `BUILDIN_DB_<WS>_<TYPE>`.

Что делает на каждой записи:
1. `GET /v1/databases/{db_id}` → достаёт `parent.page_id` (wrapper).
2. `PATCH /v1/pages/{wrapper_id}` с `{"archived": true}` — Buildin архивирует
   wrapper, DB внутри уезжает в trash вместе с ним.

После прогона надо вручную удалить из `.env` все строки `BUILDIN_DB_*` и
заново запустить `python -m scripts.setup_buildin_dbs >> .env` — он создаст
свежие full-page DB по новому one-step флоу.

Флаги:
- `--dry-run` — печатает что было бы архивировано, без сетевых вызовов.
- `--workspace=<key>` — только один workspace.
- `--type=<key>` — только один тип.

Запуск:
  source .venv/bin/activate
  python -m scripts.cleanup_buildin_orphans --dry-run
  python -m scripts.cleanup_buildin_orphans
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
from bot.domain.note_types import TYPES
from bot.domain.workspaces import WORKSPACES
from bot.services.sinks.buildin import BASE_URL

logger = logging.getLogger(__name__)


async def _archive_wrapper(client: httpx.AsyncClient, database_id: str) -> Optional[str]:
    resp = await client.get(f"/v1/databases/{database_id}")
    if resp.status_code >= 400:
        raise RuntimeError(f"buildin GET /v1/databases/{database_id} {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    parent = body.get("parent") or {}
    if parent.get("type") != "page_id":
        logger.warning(
            "buildin database %s parent type is %r, not page_id — пропускаю",
            database_id,
            parent.get("type"),
        )
        return None
    wrapper_id = parent.get("page_id")
    if not wrapper_id:
        logger.warning("buildin database %s parent.page_id отсутствует", database_id)
        return None

    resp = await client.patch(f"/v1/pages/{wrapper_id}", json={"archived": True})
    if resp.status_code >= 400:
        raise RuntimeError(
            f"buildin PATCH /v1/pages/{wrapper_id} {resp.status_code}: {resp.text[:300]}"
        )
    return wrapper_id


def _env_name(ws_key: str, type_key: str) -> str:
    return f"BUILDIN_DB_{ws_key.upper()}_{type_key.upper()}"


async def run(
    workspace_filter: Optional[str],
    type_filter: Optional[str],
    dry_run: bool,
    client_factory=None,
) -> int:
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

    pairs: list[tuple[str, str, str]] = []
    for ws in workspaces:
        for nt in note_types:
            env_name = _env_name(ws.key, nt.key)
            db_id = os.environ.get(env_name)
            if db_id:
                pairs.append((ws.key, nt.key, db_id))

    if not pairs:
        print("# нечего чистить — нет BUILDIN_DB_<WS>_<TYPE> env-переменных под фильтр")
        return 0

    if not dry_run and not settings.BUILDIN_TOKEN:
        sys.stderr.write("BUILDIN_TOKEN не задан — задайте в .env или export BUILDIN_TOKEN=...\n")
        return 2

    if dry_run:
        for ws_key, nt_key, db_id in pairs:
            print(f"# would archive wrapper of database {db_id} (ws={ws_key} type={nt_key})")
        print(f"# dry-run: ничего не изменено ({len(pairs)} пар)")
        return 0

    if client_factory is None:
        headers = {"Authorization": f"Bearer {settings.BUILDIN_TOKEN}"}

        def client_factory():
            return httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=30.0)

    archived = 0
    failed = 0
    archived_envs: list[str] = []
    async with client_factory() as client:
        for ws_key, nt_key, db_id in pairs:
            try:
                wrapper_id = await _archive_wrapper(client, db_id)
            except Exception as exc:
                logger.warning(
                    "archive failed for ws=%s type=%s db=%s: %s",
                    ws_key,
                    nt_key,
                    db_id,
                    exc,
                )
                failed += 1
                continue
            env_name = _env_name(ws_key, nt_key)
            if wrapper_id:
                print(
                    f"# archived wrapper {wrapper_id} (ws={ws_key} type={nt_key} db={db_id})"
                )
                archived += 1
                archived_envs.append(env_name)
            else:
                print(f"# skipped {db_id} (ws={ws_key} type={nt_key}) — нет wrapper-page")

    print(f"# done: archived={archived} failed={failed}")
    if archived_envs:
        print("# next steps:")
        print("#   1) удалите из .env эти строки:")
        for env_name in archived_envs:
            print(f"#      {env_name}=...")
        print("#   2) запустите:  python -m scripts.setup_buildin_dbs >> .env")
        print("#      (создаст свежие full-page DB по новому one-step флоу)")

    return 0 if failed == 0 else 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Buildin wrapper+DB cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Не делать сетевых вызовов")
    parser.add_argument("--workspace", help="ключ одного workspace")
    parser.add_argument("--type", dest="note_type", help="ключ одного note type")
    args = parser.parse_args()

    return asyncio.run(run(args.workspace, args.note_type, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
