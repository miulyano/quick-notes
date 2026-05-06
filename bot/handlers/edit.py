"""Edit-input handler: пишет новое значение title/body в draft, перерисовывает превью.

Активен только если у user_id есть draft в awaiting_edit_title|awaiting_edit_body.
Регистрируется в Dispatcher до inputs.router, иначе сообщение пойдёт в обычный
handle_text → новый LLM-цикл.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.handlers.inputs import format_preview, preview_keyboard
from bot.storage import drafts

router = Router()
logger = logging.getLogger(__name__)


async def _is_editing(message: Message) -> bool:
    if not message.from_user:
        return False
    draft = await drafts.find_awaiting_edit(message.from_user.id)
    return draft is not None


@router.message(F.text & ~F.text.startswith("/"), _is_editing)
async def handle_edit_input(message: Message, bot: Bot) -> None:
    draft = await drafts.find_awaiting_edit(message.from_user.id)
    if draft is None:
        return
    text = message.text or ""
    if draft.status == "awaiting_edit_title":
        await drafts.update(draft.id, title=text, status="awaiting_confirm")
    else:  # awaiting_edit_body
        await drafts.update(draft.id, formatted=text, status="awaiting_confirm")

    fresh = await drafts.get(draft.id)
    if fresh and fresh.preview_msg_id:
        try:
            await bot.edit_message_text(
                format_preview(
                    fresh.title or "",
                    fresh.formatted or "",
                    fresh.note_type or "note",
                    fresh.workspace,
                    fresh.extras_json,
                ),
                chat_id=fresh.chat_id,
                message_id=fresh.preview_msg_id,
                reply_markup=preview_keyboard(
                    fresh.id,
                    show_kind_toggle=(fresh.note_type or "") == "meeting",
                ),
            )
        except Exception:
            logger.exception("failed to refresh preview after edit for draft=%s", draft.id)
    await message.answer("✅ Обновлено")
