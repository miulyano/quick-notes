"""Test stub vs real-mode switch + payload structure for the real path."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.services import notion_client
from bot.storage.drafts import Draft


def _draft(title="My Note", body="line 1\n\nline 2", note_type="note") -> Draft:
    return Draft(
        id="d1",
        user_id=111,
        chat_id=1,
        message_id=1,
        preview_msg_id=None,
        status="awaiting_confirm",
        kind="text",
        raw_payload=body,
        transcribed=None,
        note_type=note_type,
        formatted=body,
        title=title,
        properties=None,
        error=None,
        created_at=0,
        updated_at=0,
    )


@pytest.fixture(autouse=True)
def _reset_module_state():
    notion_client.set_failure_injector(None)
    notion_client.set_client(None)
    yield
    notion_client.set_failure_injector(None)
    notion_client.set_client(None)


async def test_stub_mode_when_no_token(monkeypatch):
    """Without NOTION_TOKEN → stub path returns fake page_id."""
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", None)
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)

    page_id = await notion_client.create_page(_draft())

    assert page_id.startswith("stub-page-")


async def test_real_mode_calls_pages_create(monkeypatch):
    """With creds set → injected client receives a payload with the right shape."""
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "secret")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db123")

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "page-real-42"})
    notion_client.set_client(fake)

    page_id = await notion_client.create_page(_draft(title="Hello", body="# H1\n\nBody"))

    assert page_id == "page-real-42"
    fake.pages.create.assert_awaited_once()
    call_kwargs = fake.pages.create.await_args.kwargs

    assert call_kwargs["parent"] == {"database_id": "db123"}
    props = call_kwargs["properties"]
    assert props["Name"]["title"][0]["text"]["content"] == "Hello"
    assert props["Type"]["select"]["name"] == "note"
    assert "start" in props["CreatedAt"]["date"]

    blocks = call_kwargs["children"]
    assert blocks[0]["type"] == "heading_1"
    assert blocks[1]["type"] == "paragraph"


async def test_real_mode_truncates_excess_blocks(monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "secret")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db123")
    monkeypatch.setattr("bot.services.notion_client.MAX_BLOCKS_PER_PAGE", 5)

    fake = MagicMock()
    fake.pages = MagicMock()
    fake.pages.create = AsyncMock(return_value={"id": "p"})
    notion_client.set_client(fake)

    body = "\n\n".join(f"para {i}" for i in range(10))
    await notion_client.create_page(_draft(body=body))

    blocks = fake.pages.create.await_args.kwargs["children"]
    assert len(blocks) == 5


async def test_failure_injector_runs_in_real_mode(monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", "secret")
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", "db123")

    async def boom(_d):
        raise RuntimeError("transient")

    notion_client.set_failure_injector(boom)

    with pytest.raises(RuntimeError, match="transient"):
        await notion_client.create_page(_draft())


async def test_failure_injector_runs_in_stub_mode(monkeypatch):
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_TOKEN", None)
    monkeypatch.setattr("bot.services.notion_client.settings.NOTION_DATABASE_ID", None)

    async def boom(_d):
        raise RuntimeError("stub-fail")

    notion_client.set_failure_injector(boom)

    with pytest.raises(RuntimeError, match="stub-fail"):
        await notion_client.create_page(_draft())
