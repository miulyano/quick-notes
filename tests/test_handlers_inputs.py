"""Verify the durability contract: text in → draft persisted BEFORE LLM/preview."""

from unittest.mock import AsyncMock, MagicMock

from bot.handlers.inputs import handle_text
from bot.storage import drafts


def _make_message(text: str, user_id: int = 111, chat_id: int = 999):
    msg = MagicMock()
    msg.from_user.id = user_id
    msg.chat.id = chat_id
    msg.message_id = 42
    msg.text = text

    sent = MagicMock()
    sent.message_id = 4242
    msg.answer = AsyncMock(return_value=sent)
    return msg


async def test_text_creates_draft_and_preview(fresh_db):
    msg = _make_message("Hello world\nMore body")

    await handle_text(msg)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.kind == "text"
    assert d.raw_payload == "Hello world\nMore body"
    assert d.status == "awaiting_confirm"
    assert d.note_type == "note"
    assert d.title == "Hello world"
    assert d.formatted == "Hello world\nMore body"
    assert d.preview_msg_id == 4242
    msg.answer.assert_awaited()


async def test_blank_text_ignored(fresh_db):
    msg = _make_message("   ")
    await handle_text(msg)
    assert await drafts.list_for_user(111) == []
    msg.answer.assert_not_called()


async def test_llm_failure_marks_draft_failed_but_keeps_payload(fresh_db, monkeypatch):
    async def boom(_text):
        raise RuntimeError("llm down")

    monkeypatch.setattr("bot.handlers.inputs.llm_processor.process", boom)

    msg = _make_message("important content")
    await handle_text(msg)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.status == "failed"
    assert d.raw_payload == "important content"  # not lost
    assert d.error == "llm down"
