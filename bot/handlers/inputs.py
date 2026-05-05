"""Text-input handler: persist draft → run LLM → show preview with Save button.

The draft is created BEFORE any processing — that's the durability contract.
A crash anywhere downstream still leaves the user's content in SQLite,
recoverable via /list.
"""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.services import llm_processor
from bot.storage import drafts

router = Router()
logger = logging.getLogger(__name__)


def _preview_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💾 Save", callback_data=f"save:{draft_id}"),
                InlineKeyboardButton(text="✖️ Cancel", callback_data=f"cancel:{draft_id}"),
            ]
        ]
    )


def _format_preview(title: str, body: str, note_type: str) -> str:
    body_short = body if len(body) <= 1500 else body[:1500] + "…"
    return f"<b>{title}</b>\n<i>type: {note_type}</i>\n\n{body_short}"


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    user = message.from_user
    text = message.text or ""
    if not text.strip():
        return

    draft_id = await drafts.create(
        user_id=user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        kind="text",
        raw_payload=text,
    )

    try:
        processed = await llm_processor.process(text)
    except Exception as exc:
        logger.exception("llm_processor.process failed for draft=%s", draft_id)
        await drafts.update(draft_id, status="failed", error=str(exc))
        await message.answer(f"⚠️ Не получилось обработать. Доступно через /list.")
        return

    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type=processed.note_type,
        title=processed.title,
        formatted=processed.formatted,
        properties=json.dumps(processed.properties, ensure_ascii=False),
    )

    preview = _format_preview(processed.title, processed.formatted, processed.note_type)
    sent = await message.answer(preview, reply_markup=_preview_keyboard(draft_id))
    await drafts.update(draft_id, preview_msg_id=sent.message_id)
