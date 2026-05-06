"""Stub vs real-mode + per-type DB routing + properties payload."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.services import notion_client
from bot.storage.drafts import Draft


def _draft(**overrides) -> Draft:
    base = dict(
        id="d1",
        user_id=111,
        chat_id=1,
        message_id=1,
        preview_msg_id=None,
        status="awaiting_confirm",
        kind="text",
        raw_payload="raw",
        transcribed=None,
        note_type="note",
        formatted="line 1\n\nline 2",
        title="My Note",
        properties=None,
        error=None,
        created_at=0,
        updated_at=0,
    )
    base.update(overrides)
    return Draft(**base)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    notion_client.set_failure_injector(None)
    notion_client.set_client(None)
    # Per-(ws×type) env-переменные могут утечь из других тестов через os.environ —
    # явная очистка для всех ws×type комбинаций под test_real_*.
    for ws in ("PERSONAL", "WORK", "FAMILY", "GROWTH", "AI_PATH"):
        for t in ("NOTE", "TASK", "IDEA", "MEETING", "1ON1", "WORK", "PERSONAL"):
            monkeypatch.delenv(f"NOTION_DB_{ws}_{t}", raising=False)
        monkeypatch.delenv(f"NOTION_PARENT_PAGE_{ws}", raising=False)
    yield
    notion_client.set_failure_injector(None)
    notion_client.set_client(None)


async def test_stub_when_no_token(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", None)
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)
    # Per-WS токены тоже должны быть пусты для stub-режима.
    for ws in ("PERSONAL", "WORK", "FAMILY", "GROWTH", "AI_PATH"):
        monkeypatch.delenv(f"NOTION_TOKEN_{ws}", raising=False)
    page_id = await notion_client.create_page(_draft())
    assert page_id.startswith("stub-page-")


async def test_per_workspace_token_used(fresh_db, monkeypatch):
    """`_get_client(ws)` берёт NOTION_TOKEN_<WS>; разные ws → разные клиенты."""
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "global")
    monkeypatch.setenv("NOTION_TOKEN_WORK", "work-token")
    notion_client.set_client(None)  # снимаем override — используем настоящий путь
    sink = notion_client.get_sink_instance()

    captured: list[str] = []

    class _FakeAsyncClient:
        def __init__(self, *, auth):
            captured.append(auth)

        async def aclose(self):
            pass

    monkeypatch.setattr("notion_client.AsyncClient", _FakeAsyncClient)

    sink._get_client("work")
    sink._get_client("personal")
    sink._get_client("work")  # повтор — кэш hit, без нового клиента

    assert captured == ["work-token", "global"]
    assert set(sink._clients_real.keys()) == {"work", "personal"}

    await sink.close()
    assert sink._clients_real == {}


async def test_get_client_raises_when_no_token(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", None)
    notion_client.set_client(None)
    sink = notion_client.get_sink_instance()
    with pytest.raises(RuntimeError, match="no Notion token for ws=work"):
        sink._get_client("work")


async def test_close_closes_all_per_ws_clients(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "g")
    notion_client.set_client(None)
    sink = notion_client.get_sink_instance()
    closed: list[str] = []

    class _FakeAsyncClient:
        def __init__(self, *, auth):
            self.auth = auth

        async def aclose(self):
            closed.append(self.auth)

    monkeypatch.setattr("notion_client.AsyncClient", _FakeAsyncClient)
    sink._get_client("work")
    sink._get_client("personal")

    await sink.close()
    assert sorted(closed) == ["g", "g"]


async def test_real_uses_default_db_when_no_per_type(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "default-db")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DB_NOTE", None)

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "p"})
    notion_client.set_client(fake)

    await notion_client.create_page(_draft(note_type="note"))

    parent = fake.pages.create.await_args.kwargs["parent"]
    assert parent == {"database_id": "default-db"}


async def test_real_uses_per_type_db_when_set(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "default-db")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DB_TASK", "tasks-db")

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "p"})
    notion_client.set_client(fake)

    await notion_client.create_page(_draft(note_type="task"))

    parent = fake.pages.create.await_args.kwargs["parent"]
    assert parent == {"database_id": "tasks-db"}


async def test_properties_built_from_draft_json(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db")

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "p"})
    notion_client.set_client(fake)

    props_json = json.dumps(
        {
            "Name": "Bump version",
            "Status": "Todo",
            "Priority": "High",
            "DueDate": "2026-05-10",
        }
    )
    await notion_client.create_page(_draft(note_type="task", properties=props_json))

    sent = fake.pages.create.await_args.kwargs["properties"]
    assert sent["Name"]["title"][0]["text"]["content"] == "Bump version"
    assert sent["Status"]["select"]["name"] == "Todo"
    assert sent["Priority"]["select"]["name"] == "High"
    assert sent["DueDate"]["date"]["start"] == "2026-05-10"
    assert "CreatedAt" in sent  # always added


async def test_multi_select_properties(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db")

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "p"})
    notion_client.set_client(fake)

    props_json = json.dumps({"Name": "Idea", "Tags": ["bot", "notion"]})
    await notion_client.create_page(_draft(note_type="idea", properties=props_json))

    sent = fake.pages.create.await_args.kwargs["properties"]
    assert sent["Tags"]["multi_select"] == [{"name": "bot"}, {"name": "notion"}]


async def test_title_falls_back_to_draft_title_when_missing(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db")

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "p"})
    notion_client.set_client(fake)

    # No properties JSON — title comes from draft.title.
    await notion_client.create_page(_draft(note_type="note", title="Fallback title"))

    sent = fake.pages.create.await_args.kwargs["properties"]
    assert sent["Name"]["title"][0]["text"]["content"] == "Fallback title"


async def test_no_database_configured_raises(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DB_TASK", None)

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock()
    notion_client.set_client(fake)

    sink = notion_client.get_sink_instance()
    with pytest.raises(RuntimeError, match="no Notion database for ws=personal"):
        await sink._create_page_real(_draft(note_type="task"))


async def test_failure_injector_runs(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db")

    async def boom(_d):
        raise RuntimeError("transient")

    notion_client.set_failure_injector(boom)
    with pytest.raises(RuntimeError, match="transient"):
        await notion_client.create_page(_draft())


async def test_truncates_excess_blocks(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db")
    monkeypatch.setattr("bot.services.sinks.notion.MAX_BLOCKS_PER_PAGE", 5)

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "p"})
    notion_client.set_client(fake)

    body = "\n\n".join(f"para {i}" for i in range(10))
    await notion_client.create_page(_draft(note_type="note", formatted=body))

    blocks = fake.pages.create.await_args.kwargs["children"]
    assert len(blocks) == 5


async def test_lazy_two_step_create_when_only_parent_page_set(fresh_db, monkeypatch):
    """Lazy auto-create: pages.create wrapper → databases.create DB → pages.create note."""
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DB_TASK", None)
    monkeypatch.setenv("NOTION_PARENT_PAGE_WORK", "parent-uuid")

    fake = MagicMock()
    fake.pages = MagicMock()
    # 1-й вызов pages.create — wrapper-page; 2-й — note-page внутри DB.
    fake.pages.create = AsyncMock(side_effect=[{"id": "wrapper-uuid"}, {"id": "note-page-id"}])
    fake.databases = MagicMock()
    fake.databases.create = AsyncMock(return_value={"id": "auto-created-db"})
    notion_client.set_client(fake)

    await notion_client.create_page(_draft(note_type="task", workspace="work"))

    # Wrapper создался под parent-page воркспейса.
    wrapper_call = fake.pages.create.await_args_list[0]
    assert wrapper_call.kwargs["parent"] == {"type": "page_id", "page_id": "parent-uuid"}

    # DB создалась внутри wrapper.
    assert fake.databases.create.await_count == 1
    db_call = fake.databases.create.await_args
    assert db_call.kwargs["parent"] == {"type": "page_id", "page_id": "wrapper-uuid"}

    # Note-page легла в auto-created DB.
    note_call = fake.pages.create.await_args_list[1]
    assert note_call.kwargs["parent"] == {"database_id": "auto-created-db"}


async def test_lazy_create_caches_for_subsequent_calls(fresh_db, monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DB_NOTE", None)
    monkeypatch.setenv("NOTION_PARENT_PAGE_PERSONAL", "parent")

    fake = MagicMock()
    fake.pages = MagicMock()
    # 1-й — wrapper-page (создаётся раз); 2-й, 3-й — note-page.
    fake.pages.create = AsyncMock(
        side_effect=[{"id": "wrapper"}, {"id": "n1"}, {"id": "n2"}]
    )
    fake.databases = MagicMock()
    fake.databases.create = AsyncMock(return_value={"id": "cached-db"})
    notion_client.set_client(fake)

    await notion_client.create_page(_draft(id="d1", note_type="note"))
    await notion_client.create_page(_draft(id="d2", note_type="note"))

    # databases.create — только один раз; вторая заметка взяла DB из кэша,
    # wrapper-page тоже не создавалась повторно.
    assert fake.databases.create.await_count == 1
    # 1 wrapper + 2 note pages = 3 вызова pages.create.
    assert fake.pages.create.await_count == 3
