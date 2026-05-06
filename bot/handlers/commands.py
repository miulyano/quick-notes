"""/start, /help, /list, /retry, /cancel."""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.handlers.inputs import format_preview, preview_keyboard
from bot.storage import drafts, outbox

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Пришли мне текст — я подготовлю заметку и сохраню в Notion после "
        "подтверждения.\n\n"
        "Команды:\n"
        "/list — незавершённые черновики\n"
        "/retry — повторить сохранение упавших\n"
        "/cancel — выйти из режима правки черновика"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await cmd_start(message)


@router.message(Command("list"))
async def cmd_list(message: Message) -> None:
    items = await drafts.list_for_user(message.from_user.id)
    if not items:
        await message.answer("Нет незавершённых черновиков.")
        return
    lines = []
    for d in items:
        title = d.title or (d.raw_payload[:40] + ("…" if len(d.raw_payload) > 40 else ""))
        lines.append(f"• [{d.status}] {title}")
    await message.answer("\n".join(lines))


@router.message(Command("retry"))
async def cmd_retry(message: Message) -> None:
    items = await drafts.list_for_user(message.from_user.id)
    failed = [d for d in items if d.status == "failed"]
    if not failed:
        await message.answer("Нет упавших черновиков.")
        return
    for d in failed:
        await drafts.update(d.id, status="saving", error=None)
        await outbox.enqueue(d.id)
    await message.answer(f"Перезапущено: {len(failed)}")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, bot: Bot) -> None:
    """Выходит из режима правки draft и восстанавливает обычное превью."""
    draft = await drafts.find_awaiting_edit(message.from_user.id)
    if draft is None:
        await message.answer("Нечего отменять.")
        return
    await drafts.update(draft.id, status="awaiting_confirm")
    if draft.preview_msg_id is not None:
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
            logger.exception("failed to restore preview after /cancel for draft=%s", draft.id)
    await message.answer("↩️ Правка отменена.")
