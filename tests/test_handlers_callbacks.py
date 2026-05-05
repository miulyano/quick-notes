from unittest.mock import AsyncMock, MagicMock

from bot.handlers.callbacks import on_cancel, on_save
from bot.storage import drafts, outbox


async def _mk_draft() -> str:
    draft_id = await drafts.create(
        user_id=111, chat_id=1, message_id=1, kind="text", raw_payload="x"
    )
    await drafts.update(draft_id, status="awaiting_confirm")
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
    cb.answer.assert_awaited()


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
