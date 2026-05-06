"""Edit-flow: подменю, переход в awaiting_edit_*, запись нового значения, /cancel."""

import json
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.callbacks import on_edit, on_edit_field
from bot.handlers.commands import cmd_cancel
from bot.handlers.edit import _is_editing, handle_edit_input
from bot.storage import drafts


async def _mk_draft(note_type: str = "note", user_id: int = 111) -> str:
    draft_id = await drafts.create(
        user_id=user_id, chat_id=42, message_id=1, kind="text", raw_payload="x"
    )
    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type=note_type,
        title="старый заголовок",
        formatted="старое тело",
        preview_msg_id=4242,
    )
    return draft_id


def _cb(data: str):
    cb = MagicMock()
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


def _make_message(text: str, user_id: int = 111, chat_id: int = 42):
    msg = MagicMock()
    msg.from_user.id = user_id
    msg.chat.id = chat_id
    msg.message_id = 7
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _make_bot():
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()
    return bot


async def test_on_edit_shows_submenu(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"edit:{draft_id}")

    await on_edit(cb)

    cb.message.edit_reply_markup.assert_awaited()
    rows = cb.message.edit_reply_markup.await_args.kwargs["reply_markup"].inline_keyboard
    callback_data = [b.callback_data for row in rows for b in row]
    assert any(c == f"editfld:{draft_id}:title" for c in callback_data)
    assert any(c == f"editfld:{draft_id}:body" for c in callback_data)
    assert any(c == f"back:{draft_id}" for c in callback_data)


async def test_on_edit_unknown_draft(fresh_db):
    cb = _cb("edit:missing")
    await on_edit(cb)
    cb.answer.assert_awaited_with("Черновик не найден", show_alert=True)


async def test_on_edit_field_title_sets_status_and_prompts(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"editfld:{draft_id}:title")

    await on_edit_field(cb)

    d = await drafts.get(draft_id)
    assert d.status == "awaiting_edit_title"
    cb.message.edit_reply_markup.assert_awaited_with(reply_markup=None)
    cb.message.answer.assert_awaited()
    prompt = cb.message.answer.await_args.args[0]
    assert "заголовок" in prompt.lower()


async def test_on_edit_field_body_sets_status_and_prompts(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"editfld:{draft_id}:body")

    await on_edit_field(cb)

    d = await drafts.get(draft_id)
    assert d.status == "awaiting_edit_body"
    cb.message.answer.assert_awaited()
    prompt = cb.message.answer.await_args.args[0]
    assert "тело" in prompt.lower()


async def test_on_edit_field_unknown_field(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"editfld:{draft_id}:wat")
    await on_edit_field(cb)
    cb.answer.assert_awaited_with("Неизвестное поле", show_alert=True)


async def test_handle_edit_input_writes_title_and_refreshes_preview(fresh_db):
    draft_id = await _mk_draft()
    await drafts.update(draft_id, status="awaiting_edit_title")
    msg = _make_message("Новый заголовок")
    bot = _make_bot()

    await handle_edit_input(msg, bot)

    d = await drafts.get(draft_id)
    assert d.title == "Новый заголовок"
    assert d.status == "awaiting_confirm"
    bot.edit_message_text.assert_awaited()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 42
    assert kwargs["message_id"] == 4242
    assert "Новый заголовок" in bot.edit_message_text.await_args.args[0]
    msg.answer.assert_awaited_with("✅ Обновлено")


async def test_handle_edit_input_writes_body(fresh_db):
    draft_id = await _mk_draft()
    await drafts.update(draft_id, status="awaiting_edit_body")
    msg = _make_message("Новое тело\nс несколькими строками")
    bot = _make_bot()

    await handle_edit_input(msg, bot)

    d = await drafts.get(draft_id)
    assert d.formatted == "Новое тело\nс несколькими строками"
    assert d.status == "awaiting_confirm"
    bot.edit_message_text.assert_awaited()


async def test_is_editing_false_when_no_active_edit(fresh_db):
    await _mk_draft()  # status=awaiting_confirm
    msg = _make_message("hi")
    assert await _is_editing(msg) is False


async def test_is_editing_true_only_for_edit_status(fresh_db):
    draft_id = await _mk_draft()
    await drafts.update(draft_id, status="awaiting_edit_body")
    msg = _make_message("hi")
    assert await _is_editing(msg) is True


async def test_find_awaiting_edit_isolates_by_user(fresh_db):
    other = await drafts.create(
        user_id=222, chat_id=1, message_id=1, kind="text", raw_payload="y"
    )
    await drafts.update(other, status="awaiting_edit_title")

    mine = await _mk_draft(user_id=111)
    await drafts.update(mine, status="awaiting_edit_body")

    found = await drafts.find_awaiting_edit(111)
    assert found is not None
    assert found.id == mine
    assert found.status == "awaiting_edit_body"


async def test_find_awaiting_edit_returns_most_recent(fresh_db):
    older = await _mk_draft()
    await drafts.update(older, status="awaiting_edit_title")
    newer = await _mk_draft()
    await drafts.update(newer, status="awaiting_edit_body")

    found = await drafts.find_awaiting_edit(111)
    assert found is not None
    assert found.id == newer


async def test_cancel_in_edit_mode_restores_preview(fresh_db):
    draft_id = await _mk_draft()
    await drafts.update(draft_id, status="awaiting_edit_title")
    msg = _make_message("/cancel")
    bot = _make_bot()

    await cmd_cancel(msg, bot)

    d = await drafts.get(draft_id)
    assert d.status == "awaiting_confirm"
    bot.edit_message_text.assert_awaited()
    msg.answer.assert_awaited_with("↩️ Правка отменена.")


async def test_cancel_without_active_edit(fresh_db):
    await _mk_draft()  # awaiting_confirm
    msg = _make_message("/cancel")
    bot = _make_bot()

    await cmd_cancel(msg, bot)

    msg.answer.assert_awaited_with("Нечего отменять.")
    bot.edit_message_text.assert_not_called()


async def test_handle_edit_input_meeting_keeps_kind_toggle(fresh_db):
    draft_id = await _mk_draft(note_type="meeting")
    await drafts.update(
        draft_id,
        status="awaiting_edit_title",
        extras_json=json.dumps({"kind": "sync"}),
    )
    msg = _make_message("Митинг с Алисой")
    bot = _make_bot()

    await handle_edit_input(msg, bot)

    rm = bot.edit_message_text.await_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in rm.inline_keyboard for b in row]
    assert any(c.startswith("togglekind:") for c in callbacks)
