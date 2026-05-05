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
def _reset():
    notion_client.set_failure_injector(None)
    notion_client.set_client(None)
    yield
    notion_client.set_failure_injector(None)
    notion_client.set_client(None)


async def test_stub_when_no_token(monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", None)
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)
    page_id = await notion_client.create_page(_draft())
    assert page_id.startswith("stub-page-")


async def test_real_uses_default_db_when_no_per_type(monkeypatch):
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


async def test_real_uses_per_type_db_when_set(monkeypatch):
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


async def test_properties_built_from_draft_json(monkeypatch):
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


async def test_multi_select_properties(monkeypatch):
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


async def test_title_falls_back_to_draft_title_when_missing(monkeypatch):
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


async def test_no_database_configured_raises(monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DB_TASK", None)

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock()
    notion_client.set_client(fake)

    # NOTION_TOKEN set but DATABASE_ID empty → notion_enabled is False, falls
    # back to stub mode. So no exception expected here. But if notion_enabled
    # AND the per-type DB resolves to None, we DO raise.
    # Force notion_enabled True via direct call to the real path:
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "")
    # Easiest: assert the resolver returns falsy and the real path raises.
    from bot.services.notion_client import _create_page_real

    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)
    with pytest.raises(RuntimeError, match="no Notion database configured"):
        await _create_page_real(_draft(note_type="task"))


async def test_failure_injector_runs(monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db")

    async def boom(_d):
        raise RuntimeError("transient")

    notion_client.set_failure_injector(boom)
    with pytest.raises(RuntimeError, match="transient"):
        await notion_client.create_page(_draft())


async def test_truncates_excess_blocks(monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "k")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db")
    monkeypatch.setattr("bot.services.notion_client.MAX_BLOCKS_PER_PAGE", 5)

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "p"})
    notion_client.set_client(fake)

    body = "\n\n".join(f"para {i}" for i in range(10))
    await notion_client.create_page(_draft(note_type="note", formatted=body))

    blocks = fake.pages.create.await_args.kwargs["children"]
    assert len(blocks) == 5
