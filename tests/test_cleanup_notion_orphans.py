"""scripts/cleanup_notion_orphans: archive wrapper-pages + clear notion_dbs cache."""

import pytest

from bot.storage import notion_dbs
from scripts.cleanup_notion_orphans import run


class _StubDatabases:
    def __init__(self, parents: dict[str, dict]):
        # parents: db_id -> parent dict
        self._parents = parents
        self.retrieve_calls: list[str] = []

    async def retrieve(self, *, database_id: str):
        self.retrieve_calls.append(database_id)
        if database_id not in self._parents:
            raise RuntimeError(f"db {database_id} not found")
        return {"parent": self._parents[database_id]}


class _StubPages:
    def __init__(self):
        self.archived: list[str] = []

    async def update(self, *, page_id: str, archived: bool):
        assert archived is True
        self.archived.append(page_id)


class _StubClient:
    def __init__(self, parents: dict[str, dict]):
        self.databases = _StubDatabases(parents)
        self.pages = _StubPages()

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_archives_wrappers_and_clears_cache(fresh_db):
    await notion_dbs.put("personal", "note", "db-1")
    await notion_dbs.put("work", "task", "db-2")

    client = _StubClient(
        {
            "db-1": {"type": "page_id", "page_id": "wrap-1"},
            "db-2": {"type": "page_id", "page_id": "wrap-2"},
        }
    )

    code = await run(None, None, dry_run=False, client_factory=lambda ws: client)

    assert code == 0
    assert sorted(client.pages.archived) == ["wrap-1", "wrap-2"]
    assert sorted(client.databases.retrieve_calls) == ["db-1", "db-2"]
    assert await notion_dbs.all_entries() == []


@pytest.mark.asyncio
async def test_dry_run_does_not_touch_anything(fresh_db):
    await notion_dbs.put("personal", "note", "db-1")
    client = _StubClient({"db-1": {"type": "page_id", "page_id": "wrap-1"}})

    code = await run(None, None, dry_run=True, client_factory=lambda ws: client)

    assert code == 0
    assert client.pages.archived == []
    assert client.databases.retrieve_calls == []
    cached = await notion_dbs.get("personal", "note")
    assert cached == "db-1"


@pytest.mark.asyncio
async def test_per_workspace_filter(fresh_db):
    await notion_dbs.put("personal", "note", "db-personal")
    await notion_dbs.put("work", "task", "db-work")
    client = _StubClient(
        {
            "db-personal": {"type": "page_id", "page_id": "wrap-p"},
            "db-work": {"type": "page_id", "page_id": "wrap-w"},
        }
    )

    code = await run("personal", None, dry_run=False, client_factory=lambda ws: client)

    assert code == 0
    assert client.pages.archived == ["wrap-p"]
    # work-запись осталась, фильтр запретил полную очистку.
    assert await notion_dbs.get("work", "task") == "db-work"
    assert await notion_dbs.get("personal", "note") is None


@pytest.mark.asyncio
async def test_failure_on_one_pair_does_not_break_others(fresh_db):
    await notion_dbs.put("personal", "note", "db-ok")
    await notion_dbs.put("personal", "task", "db-missing")
    client = _StubClient(
        {
            "db-ok": {"type": "page_id", "page_id": "wrap-ok"},
            # "db-missing" отсутствует — retrieve бросит исключение.
        }
    )

    code = await run(None, None, dry_run=False, client_factory=lambda ws: client)

    assert code == 1  # failures > 0
    assert client.pages.archived == ["wrap-ok"]
    # Удачная запись удалена, проблемная осталась для повторного прогона.
    assert await notion_dbs.get("personal", "note") is None
    assert await notion_dbs.get("personal", "task") == "db-missing"


@pytest.mark.asyncio
async def test_skips_database_with_non_page_parent(fresh_db):
    """Если кто-то вручную перенёс DB в workspace root — parent.type != page_id."""
    await notion_dbs.put("personal", "note", "db-1")
    client = _StubClient({"db-1": {"type": "workspace"}})

    code = await run(None, None, dry_run=False, client_factory=lambda ws: client)

    assert code == 0
    assert client.pages.archived == []
    assert await notion_dbs.get("personal", "note") is None
