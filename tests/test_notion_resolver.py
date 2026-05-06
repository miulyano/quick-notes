"""bot/services/sinks/_notion_resolver: cache → env → auto-create."""

from types import SimpleNamespace

import pytest

from bot.domain.note_types import get as get_note_type
from bot.services.sinks._notion_resolver import resolve_or_create
from bot.storage import notion_dbs


class _StubDatabases:
    def __init__(self, response: dict):
        self.response = response
        self.calls: list[dict] = []

    async def create(self, **payload):
        self.calls.append(payload)
        return self.response


class _StubClient:
    def __init__(self, response: dict | None = None):
        self.databases = _StubDatabases(response or {"id": "auto-created-uuid"})


@pytest.fixture(autouse=True)
def _clean_envs(monkeypatch):
    for key in list(globals_envs := []):
        monkeypatch.delenv(key, raising=False)
    for key in (
        "NOTION_DB_PERSONAL_TASK",
        "NOTION_DB_WORK_TASK",
        "NOTION_DB_TASK",
        "NOTION_PARENT_PAGE_PERSONAL",
        "NOTION_PARENT_PAGE_WORK",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("bot.config.settings.NOTION_DB_TASK", None)
    monkeypatch.setattr("bot.config.settings.NOTION_DATABASE_ID", None)


@pytest.mark.asyncio
async def test_returns_cached_entry_without_api_call(fresh_db):
    await notion_dbs.put("personal", "task", "cached-uuid")
    client = _StubClient()

    got = await resolve_or_create("personal", get_note_type("task"), client)

    assert got == "cached-uuid"
    assert client.databases.calls == []


@pytest.mark.asyncio
async def test_returns_per_workspace_env_when_no_cache(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_DB_WORK_TASK", "ws-task-env")
    client = _StubClient()

    got = await resolve_or_create("work", get_note_type("task"), client)

    assert got == "ws-task-env"
    assert client.databases.calls == []


@pytest.mark.asyncio
async def test_falls_back_to_per_type_env(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.config.settings.NOTION_DB_TASK", "per-type-env")
    client = _StubClient()

    got = await resolve_or_create("personal", get_note_type("task"), client)

    assert got == "per-type-env"


@pytest.mark.asyncio
async def test_falls_back_to_default_database_id(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.config.settings.NOTION_DATABASE_ID", "default-uuid")
    client = _StubClient()

    got = await resolve_or_create("personal", get_note_type("task"), client)

    assert got == "default-uuid"


@pytest.mark.asyncio
async def test_creates_db_when_only_parent_page_set(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_WORK", "parent-page-uuid")
    client = _StubClient(response={"id": "new-db-uuid"})

    got = await resolve_or_create("work", get_note_type("task"), client)

    assert got == "new-db-uuid"
    assert len(client.databases.calls) == 1
    payload = client.databases.calls[0]
    assert payload["parent"] == {"type": "page_id", "page_id": "parent-page-uuid"}
    assert "Status" in payload["properties"]
    assert "Priority" in payload["properties"]
    assert "DueDate" in payload["properties"]
    # CreatedAt автодобавляется на любом типе.
    assert "CreatedAt" in payload["properties"]


@pytest.mark.asyncio
async def test_caches_after_auto_create(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_PERSONAL", "parent-uuid")
    client = _StubClient(response={"id": "new-uuid"})

    first = await resolve_or_create("personal", get_note_type("note"), client)
    second = await resolve_or_create("personal", get_note_type("note"), client)

    assert first == second == "new-uuid"
    # Второй вызов уже из кэша — без повторного create.
    assert len(client.databases.calls) == 1


@pytest.mark.asyncio
async def test_returns_none_when_nothing_configured(fresh_db, monkeypatch):
    client = _StubClient()
    got = await resolve_or_create("personal", get_note_type("task"), client)
    assert got is None
    assert client.databases.calls == []


@pytest.mark.asyncio
async def test_create_payload_uses_plural_title(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_PERSONAL", "p")
    client = _StubClient(response={"id": "x"})

    await resolve_or_create("personal", get_note_type("idea"), client)

    payload = client.databases.calls[0]
    title_text = payload["title"][0]["text"]["content"]
    assert "Идеи" in title_text  # plural form, согласовано с setup_buildin_dbs


@pytest.mark.asyncio
async def test_select_options_propagated(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_WORK", "p")
    client = _StubClient(response={"id": "x"})

    await resolve_or_create("work", get_note_type("task"), client)

    payload = client.databases.calls[0]
    status_options = payload["properties"]["Status"]["select"]["options"]
    assert {o["name"] for o in status_options} == {"Todo", "In Progress", "Done"}
