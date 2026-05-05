"""Text-input handler: persist draft → run LLM → show preview with action buttons."""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.domain.note_types import get as get_note_type
from bot.services import llm_processor
from bot.storage import drafts
from bot.utils import forward as forward_utils

router = Router()
logger = logging.getLogger(__name__)


def preview_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💾 Save", callback_data=f"save:{draft_id}"),
                InlineKeyboardButton(text="🔁 Type", callback_data=f"chtype:{draft_id}"),
                InlineKeyboardButton(text="✖️ Cancel", callback_data=f"cancel:{draft_id}"),
            ]
        ]
    )


def format_preview(title: str, body: str, note_type_key: str) -> str:
    note_type = get_note_type(note_type_key)
    body_short = body if len(body) <= 1500 else body[:1500] + "…"
    return f"<b>{title}</b>\n<i>{note_type.label}</i>\n\n{body_short}"


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    user = message.from_user
    text = message.text or ""
    if not text.strip():
        return

    forward_meta = forward_utils.extract(message)
    kind = "forward" if forward_meta else "text"
    payload = (
        json.dumps({"text": text, "forward": forward_meta}, ensure_ascii=False)
        if forward_meta
        else text
    )

    draft_id = await drafts.create(
        user_id=user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        kind=kind,
        raw_payload=payload,
    )

    llm_input = forward_utils.enrich(text, forward_meta) if forward_meta else text

    try:
        processed = await llm_processor.process(llm_input)
    except Exception as exc:
        logger.exception("llm_processor.process failed for draft=%s", draft_id)
        await drafts.update(draft_id, status="failed", error=str(exc))
        await message.answer("⚠️ Не получилось обработать. Доступно через /list.")
        return

    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type=processed.note_type,
        title=processed.title,
        formatted=processed.formatted,
        properties=json.dumps(processed.properties, ensure_ascii=False),
    )

    preview = format_preview(processed.title, processed.formatted, processed.note_type)
    sent = await message.answer(preview, reply_markup=preview_keyboard(draft_id))
    await drafts.update(draft_id, preview_msg_id=sent.message_id)
