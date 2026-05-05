"""Preview button handler: Save → enqueue, Cancel → delete draft."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.storage import drafts, outbox

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("save:"))
async def on_save(cb: CallbackQuery) -> None:
    draft_id = cb.data.split(":", 1)[1]
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    await drafts.update(draft_id, status="saving")
    await outbox.enqueue(draft_id)
    await cb.answer("⏳ Сохраняю…")
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel(cb: CallbackQuery) -> None:
    draft_id = cb.data.split(":", 1)[1]
    await drafts.delete(draft_id)
    await cb.answer("Отменено")
    if cb.message is not None:
        try:
            await cb.message.edit_text("✖️ Отменено")
        except Exception:
            pass
