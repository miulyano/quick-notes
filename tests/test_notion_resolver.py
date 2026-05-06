"""bot/services/sinks/_notion_resolver: cache → env → two-step auto-create."""

import pytest

from bot.domain.note_types import get as get_note_type
from bot.services.sinks._notion_resolver import resolve_or_create
from bot.storage import notion_dbs


class _StubPages:
    def __init__(self, response: dict | Exception):
        self.response = response
        self.calls: list[dict] = []

    async def create(self, **payload):
        self.calls.append(payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _StubDatabases:
    def __init__(self, response: dict | Exception):
        self.response = response
        self.calls: list[dict] = []

    async def create(self, **payload):
        self.calls.append(payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


_UNSET = object()


class _StubClient:
    def __init__(self, *, page_response=_UNSET, db_response=_UNSET):
        self.pages = _StubPages(
            {"id": "wrapper-page-uuid"} if page_response is _UNSET else page_response
        )
        self.databases = _StubDatabases(
            {"id": "auto-created-uuid"} if db_response is _UNSET else db_response
        )


@pytest.fixture(autouse=True)
def _clean_envs(monkeypatch):
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
    assert client.pages.calls == []
    assert client.databases.calls == []


@pytest.mark.asyncio
async def test_returns_per_workspace_env_when_no_cache(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_DB_WORK_TASK", "ws-task-env")
    client = _StubClient()

    got = await resolve_or_create("work", get_note_type("task"), client)

    assert got == "ws-task-env"
    assert client.pages.calls == []
    assert client.databases.calls == []


@pytest.mark.asyncio
async def test_falls_back_to_per_type_env(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.config.settings.NOTION_DB_TASK", "per-type-env")
    client = _StubClient()

    got = await resolve_or_create("personal", get_note_type("task"), client)

    assert got == "per-type-env"
    assert client.pages.calls == []
    assert client.databases.calls == []


@pytest.mark.asyncio
async def test_falls_back_to_default_database_id(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.config.settings.NOTION_DATABASE_ID", "default-uuid")
    client = _StubClient()

    got = await resolve_or_create("personal", get_note_type("task"), client)

    assert got == "default-uuid"
    assert client.pages.calls == []
    assert client.databases.calls == []


@pytest.mark.asyncio
async def test_two_step_create_when_only_parent_page_set(fresh_db, monkeypatch):
    """Lazy: pages.create (wrapper) → databases.create (внутри wrapper)."""
    monkeypatch.setenv("NOTION_PARENT_PAGE_WORK", "parent-page-uuid")
    client = _StubClient(
        page_response={"id": "wrapper-uuid"},
        db_response={"id": "new-db-uuid"},
    )

    got = await resolve_or_create("work", get_note_type("task"), client)

    assert got == "new-db-uuid"

    # Step 1: wrapper-page внутри parent-page воркспейса.
    assert len(client.pages.calls) == 1
    page_payload = client.pages.calls[0]
    assert page_payload["parent"] == {"type": "page_id", "page_id": "parent-page-uuid"}
    page_title = page_payload["properties"]["title"]["title"][0]["text"]["content"]
    assert "Задачи" in page_title

    # Step 2: full-page DB внутри wrapper.
    assert len(client.databases.calls) == 1
    db_payload = client.databases.calls[0]
    assert db_payload["parent"] == {"type": "page_id", "page_id": "wrapper-uuid"}
    assert "Status" in db_payload["properties"]
    assert "Priority" in db_payload["properties"]
    assert "DueDate" in db_payload["properties"]
    assert "CreatedAt" in db_payload["properties"]
    db_title_text = db_payload["title"][0]["text"]["content"]
    assert "Задачи" in db_title_text


@pytest.mark.asyncio
async def test_caches_after_auto_create(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_PERSONAL", "parent-uuid")
    client = _StubClient(
        page_response={"id": "wrapper-uuid"},
        db_response={"id": "new-uuid"},
    )

    first = await resolve_or_create("personal", get_note_type("note"), client)
    second = await resolve_or_create("personal", get_note_type("note"), client)

    assert first == second == "new-uuid"
    # Второй вызов из кэша — повторных create нет.
    assert len(client.pages.calls) == 1
    assert len(client.databases.calls) == 1


@pytest.mark.asyncio
async def test_returns_none_when_nothing_configured(fresh_db, monkeypatch):
    client = _StubClient()
    got = await resolve_or_create("personal", get_note_type("task"), client)
    assert got is None
    assert client.pages.calls == []
    assert client.databases.calls == []


@pytest.mark.asyncio
async def test_create_payload_uses_plural_title(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_PERSONAL", "p")
    client = _StubClient(
        page_response={"id": "wrapper"},
        db_response={"id": "x"},
    )

    await resolve_or_create("personal", get_note_type("idea"), client)

    page_title = client.pages.calls[0]["properties"]["title"]["title"][0]["text"]["content"]
    db_title = client.databases.calls[0]["title"][0]["text"]["content"]
    # plural form, согласовано с setup_buildin_dbs.
    assert "Идеи" in page_title
    assert "Идеи" in db_title


@pytest.mark.asyncio
async def test_select_options_propagated(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_WORK", "p")
    client = _StubClient(
        page_response={"id": "wrapper"},
        db_response={"id": "x"},
    )

    await resolve_or_create("work", get_note_type("task"), client)

    status_options = client.databases.calls[0]["properties"]["Status"]["select"]["options"]
    assert {o["name"] for o in status_options} == {"Todo", "In Progress", "Done"}


@pytest.mark.asyncio
async def test_db_create_failure_leaves_orphan_page_and_no_cache(
    fresh_db, monkeypatch, caplog
):
    """databases.create падает после успешного pages.create — wrapper id в логах,
    исключение пробрасывается, кэш не обновлён."""
    monkeypatch.setenv("NOTION_PARENT_PAGE_WORK", "parent")
    client = _StubClient(
        page_response={"id": "wrapper-orphan-uuid"},
        db_response=RuntimeError("notion API down"),
    )

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError, match="notion API down"):
            await resolve_or_create("work", get_note_type("task"), client)

    # wrapper id фиксируется в логах для ручной чистки.
    assert any("wrapper-orphan-uuid" in rec.message for rec in caplog.records)

    # Кэш не обновлён — повторный hit снова попытается создать.
    cached = await notion_dbs.get("work", "task")
    assert cached is None


@pytest.mark.asyncio
async def test_pages_create_missing_id_raises(fresh_db, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_WORK", "parent")
    client = _StubClient(
        page_response={},  # no "id"
        db_response={"id": "x"},
    )

    with pytest.raises(RuntimeError, match="pages.create response missing id"):
        await resolve_or_create("work", get_note_type("task"), client)

    # databases.create не должен вызываться, если wrapper не создан.
    assert client.databases.calls == []
