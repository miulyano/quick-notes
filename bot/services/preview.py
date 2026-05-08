"""Helper для перерисовки preview-сообщения in-place.

Используется и из чат-хендлеров (settype/setws/togglekind), и из веб-эндпойнта
правки draft через Web App.
"""

from __future__ import annotations

import logging

from aiogram import Bot

from bot.handlers.inputs import format_preview, preview_keyboard
from bot.storage.drafts import Draft


logger = logging.getLogger(__name__)


async def refresh_preview(bot: Bot, draft: Draft) -> None:
    """Перерисовать preview-сообщение по сохранённому preview_msg_id.

    Если preview_msg_id отсутствует или edit_message_text упал — лог и тихо
    выходим: вызывающий код сам решит, нужен ли retry/alert.
    """
    if draft.preview_msg_id is None:
        return
    try:
        await bot.edit_message_text(
            format_preview(
                draft.title or "",
                draft.formatted or "",
                draft.note_type or "note",
                draft.workspace,
                draft.extras_json,
            ),
            chat_id=draft.chat_id,
            message_id=draft.preview_msg_id,
            reply_markup=preview_keyboard(
                draft.id,
                show_kind_toggle=(draft.note_type or "") == "meeting",
            ),
        )
    except Exception:
        logger.exception("refresh_preview failed for draft=%s", draft.id)
