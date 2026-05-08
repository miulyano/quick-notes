"""Verify the durability contract: text in → draft persisted BEFORE LLM/preview."""

import json
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.inputs import (
    PREVIEW_BODY_LIMIT,
    PREVIEW_TRUNCATE_MARKER,
    format_preview,
    handle_text,
    preview_keyboard,
)
from bot.storage import drafts


def _make_message(text: str, user_id: int = 111, chat_id: int = 999):
    msg = MagicMock()
    msg.from_user.id = user_id
    msg.chat.id = chat_id
    msg.message_id = 42
    msg.text = text
    msg.forward_origin = None  # default: not a forward

    sent = MagicMock()
    sent.message_id = 4242
    msg.answer = AsyncMock(return_value=sent)

    # ProgressReporter создаёт status-сообщение через message.reply и затем
    # дёргает bot.edit_message_text / delete_message по его id.
    status = MagicMock()
    status.chat.id = chat_id
    status.message_id = 7777
    status.text = ""
    msg.reply = AsyncMock(return_value=status)
    msg.bot = MagicMock()
    msg.bot.edit_message_text = AsyncMock()
    msg.bot.delete_message = AsyncMock()
    msg.bot.send_message = AsyncMock(return_value=status)
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


async def test_forward_text_marked_as_forward_kind(fresh_db, monkeypatch):
    seen_inputs: list[str] = []

    async def fake_llm(text):
        seen_inputs.append(text)
        from bot.services.llm_processor import ProcessedNote

        return ProcessedNote(note_type="note", title="t", formatted=text)

    monkeypatch.setattr("bot.handlers.inputs.llm_processor.process", fake_llm)

    fake_meta = {
        "source_kind": "channel",
        "chat_title": "Channel X",
        "chat_username": "chan_x",
        "date": "2026-05-04T10:00",
    }
    monkeypatch.setattr("bot.handlers.inputs.forward_utils.extract", lambda _m: fake_meta)

    msg = _make_message("forwarded text body")
    await handle_text(msg)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.kind == "forward"
    # raw_payload = JSON with text + forward meta.
    import json

    parsed = json.loads(d.raw_payload)
    assert parsed["text"] == "forwarded text body"
    assert parsed["forward"]["source_kind"] == "channel"

    # LLM saw the enriched text with the prefix, not the raw body.
    assert seen_inputs and seen_inputs[0].startswith("[Forwarded]")
    assert "forwarded text body" in seen_inputs[0]


def test_preview_truncate_uses_explicit_marker():
    body = "x" * (PREVIEW_BODY_LIMIT + 100)
    out = format_preview("title", body, "note", "personal", None)
    assert PREVIEW_TRUNCATE_MARKER in out
    # Тело отрезано ровно по PREVIEW_BODY_LIMIT.
    assert out.count("x") == PREVIEW_BODY_LIMIT


def test_preview_no_truncate_when_under_limit():
    body = "y" * 100
    out = format_preview("title", body, "note", "personal", None)
    assert PREVIEW_TRUNCATE_MARKER not in out


def test_preview_meeting_kind_sync_label():
    out = format_preview(
        "Тема", "body", "meeting", "personal", json.dumps({"kind": "sync"})
    )
    assert "(sync)" in out


def test_preview_meeting_default_no_kind_label():
    out = format_preview(
        "Тема", "body", "meeting", "personal", json.dumps({"kind": "meeting"})
    )
    assert "(sync)" not in out


def test_preview_non_meeting_ignores_kind():
    out = format_preview(
        "Тема", "body", "note", "personal", json.dumps({"kind": "sync"})
    )
    assert "(sync)" not in out


def test_preview_keyboard_meeting_has_kind_toggle():
    kb = preview_keyboard("d1", show_kind_toggle=True)
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert any(c.startswith("togglekind:") for c in callbacks)


def test_preview_keyboard_default_no_kind_toggle():
    kb = preview_keyboard("d1")
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert not any(c.startswith("togglekind:") for c in callbacks)
