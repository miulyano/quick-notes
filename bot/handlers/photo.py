"""Photo handler. Forwarded posts с фото (одиночные + альбомы).

Поток:
1. Альбом агрегируется AlbumMiddleware → `data["album"] = [Message, …]`.
2. Для каждого фото берём `photo[-1]` (largest size) → `bot.get_file` →
   собираем URL `https://api.telegram.org/file/bot<TOKEN>/<file_path>`.
   URL живёт ~1 час, в течение этого времени Notion/Buildin закэшируют превью.
3. Caption (у первого сообщения альбома или одиночного фото) идёт в LLM как
   обычный текст (через `forward.enrich`). Title/body/note_type/workspace
   генерятся LLM как для текста.
4. Caption отсутствует → LLM пропускаем, title из forward-meta, body пуст.
5. URL'ы фото сохраняются в `extras_json.image_urls` — sink (Notion/Buildin)
   читает оттуда и вставляет image-блоки перед body.
"""

from __future__ import annotations

import json
import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.config import settings
from bot.handlers.inputs import format_preview, preview_keyboard
from bot.services import llm_processor
from bot.storage import drafts
from bot.utils import forward as forward_utils
from bot.utils.progress import ProgressReporter

router = Router()
logger = logging.getLogger(__name__)


def _photo_file_url(file_path: str) -> str:
    return f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file_path}"


def _photo_title_from_meta(forward_meta: dict | None) -> str:
    if not forward_meta:
        return "Photo"
    author = forward_meta.get("author") or forward_meta.get("chat_title")
    return f"Photo from {author}" if author else "Photo"


@router.message(F.photo)
async def handle_photo(
    message: Message, bot: Bot, album: list[Message] | None = None
) -> None:
    msgs = album if album else [message]
    primary = msgs[0]
    caption = (primary.caption or "").strip()
    forward_meta = forward_utils.extract(primary)

    image_urls: list[str] = []
    photos_meta: list[dict] = []
    for m in msgs:
        if not m.photo:
            continue
        ph = m.photo[-1]
        try:
            f = await bot.get_file(ph.file_id)
        except Exception:
            logger.exception("bot.get_file failed file_id=%s", ph.file_id)
            continue
        url = _photo_file_url(f.file_path)
        image_urls.append(url)
        photos_meta.append({"file_id": ph.file_id, "file_url": url})

    if not image_urls:
        await message.answer("Не получилось скачать фото из Telegram.")
        return

    raw_payload = json.dumps(
        {
            "caption": caption,
            "forward": forward_meta,
            "photos": photos_meta,
            "media_group_id": getattr(primary, "media_group_id", None),
        },
        ensure_ascii=False,
    )
    kind = "forward_photo" if forward_meta else "photo"

    draft_id = await drafts.create(
        user_id=primary.from_user.id,
        chat_id=primary.chat.id,
        message_id=primary.message_id,
        kind=kind,
        raw_payload=raw_payload,
    )

    if caption:
        llm_input = (
            forward_utils.enrich(caption, forward_meta) if forward_meta else caption
        )
        async with ProgressReporter(message, "Готовлю заметку…") as progress:
            try:
                processed = await llm_processor.process(llm_input)
            except Exception as exc:
                logger.exception("llm_processor.process failed for draft=%s", draft_id)
                await drafts.update(draft_id, status="failed", error=str(exc))
                await progress.fail("Не получилось обработать. Доступно через /list.")
                return
            await progress.finish()
        title = processed.title
        formatted = processed.formatted
        note_type = processed.note_type
        workspace = processed.workspace
        properties_json = json.dumps(processed.properties, ensure_ascii=False)
        extras = dict(processed.extras)
    else:
        title = _photo_title_from_meta(forward_meta)
        formatted = ""
        note_type = "note"
        workspace = "personal"
        properties_json = json.dumps({}, ensure_ascii=False)
        extras = {}

    extras["image_urls"] = image_urls
    extras_json = json.dumps(extras, ensure_ascii=False)

    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type=note_type,
        title=title,
        formatted=formatted,
        properties=properties_json,
        workspace=workspace,
        extras_json=extras_json,
    )

    preview = format_preview(title, formatted, note_type, workspace, extras_json)
    sent = await message.answer(
        preview,
        reply_markup=preview_keyboard(draft_id, show_kind_toggle=note_type == "meeting"),
    )
    await drafts.update(draft_id, preview_msg_id=sent.message_id)
