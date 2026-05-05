from unittest.mock import AsyncMock, MagicMock

from bot.handlers.callbacks import on_back, on_cancel, on_change_type, on_save, on_set_type
from bot.storage import drafts, outbox


async def _mk_draft(note_type="note") -> str:
    draft_id = await drafts.create(
        user_id=111, chat_id=1, message_id=1, kind="text", raw_payload="x"
    )
    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type=note_type,
        title="t",
        formatted="body",
    )
    return draft_id


def _cb(data: str):
    cb = MagicMock()
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.edit_text = AsyncMock()
    return cb


async def test_save_enqueues_and_marks_saving(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"save:{draft_id}")

    await on_save(cb)

    d = await drafts.get(draft_id)
    assert d.status == "saving"
    assert await outbox.get_attempts(draft_id) == 0


async def test_save_unknown_draft(fresh_db):
    cb = _cb("save:missing")
    await on_save(cb)
    cb.answer.assert_awaited_with("Черновик не найден", show_alert=True)


async def test_cancel_deletes_draft(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"cancel:{draft_id}")

    await on_cancel(cb)

    assert await drafts.get(draft_id) is None
    cb.message.edit_text.assert_awaited()


async def test_change_type_shows_picker(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"chtype:{draft_id}")

    await on_change_type(cb)

    cb.message.edit_reply_markup.assert_awaited()
    # Confirm the keyboard sent contains type buttons.
    kwargs = cb.message.edit_reply_markup.await_args.kwargs
    rows = kwargs["reply_markup"].inline_keyboard
    callback_data = [b.callback_data for row in rows for b in row]
    assert any(c.startswith("settype:") for c in callback_data)
    assert any(c.startswith("back:") for c in callback_data)


async def test_set_type_updates_and_renders_preview(fresh_db):
    draft_id = await _mk_draft(note_type="note")
    cb = _cb(f"settype:{draft_id}:task")

    await on_set_type(cb)

    d = await drafts.get(draft_id)
    assert d.note_type == "task"
    cb.message.edit_text.assert_awaited()


async def test_back_restores_main_keyboard(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"back:{draft_id}")

    await on_back(cb)

    cb.message.edit_reply_markup.assert_awaited()
