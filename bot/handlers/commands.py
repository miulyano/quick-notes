"""/start, /help, /list, /retry."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

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
        "/retry — повторить сохранение упавших"
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


