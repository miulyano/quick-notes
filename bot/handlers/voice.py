"""Voice / audio / video / video_note handlers.

Pipeline mirrors the text path but adds two phases up front:
1. Persist draft (status=raw) with `file_id` payload — durability before any
   network I/O.
2. Download Telegram file → temp path. Status `raw` stays.
3. Transcribe via AssemblyAI → status `transcribed`, text saved.
4. LLM classify+format → status `awaiting_confirm`.
5. Show preview with the same Save/Type/Cancel keyboard as the text path.

A crash anywhere downstream still leaves the draft visible via /list with the
TG `file_id` so the user can re-send the audio (or — Increment 5+ — /retry
will pick it up).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.config import settings
from bot.handlers.inputs import format_preview, preview_keyboard
from bot.services import llm_processor, transcriber
from bot.storage import drafts
from bot.utils import forward as forward_utils
from bot.utils.progress import ProgressReporter

router = Router()
logger = logging.getLogger(__name__)

_KIND_BY_FIELD = {
    "voice": ("voice", ".ogg"),
    "audio": ("audio", ".mp3"),
    "video": ("video", ".mp4"),
    "video_note": ("video", ".mp4"),
}


@router.message(F.voice | F.audio | F.video | F.video_note)
async def handle_media(message: Message, bot: Bot) -> None:
    if message.voice:
        kind, ext = _KIND_BY_FIELD["voice"]
        media = message.voice
    elif message.audio:
        kind, ext = _KIND_BY_FIELD["audio"]
        media = message.audio
    elif message.video:
        kind, ext = _KIND_BY_FIELD["video"]
        media = message.video
    elif message.video_note:
        kind, ext = _KIND_BY_FIELD["video_note"]
        media = message.video_note
    else:
        return

    if not settings.assemblyai_enabled:
        await message.answer(
            "⚠️ Транскрибация выключена. Добавь `ASSEMBLYAI_API_KEY` в `.env`."
        )
        return

    forward_meta = forward_utils.extract(message)
    payload = json.dumps(
        {
            "file_id": media.file_id,
            "duration": getattr(media, "duration", None),
            "mime_type": getattr(media, "mime_type", None),
            "forward": forward_meta,
        },
        ensure_ascii=False,
    )
    draft_kind = "forward" if forward_meta else kind

    draft_id = await drafts.create(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        kind=draft_kind,
        raw_payload=payload,
    )

    os.makedirs(settings.TEMP_DIR, exist_ok=True)
    audio_path = os.path.join(settings.TEMP_DIR, f"{draft_id}{ext}")

    async with ProgressReporter(message, "Скачиваю…") as progress:
        try:
            await bot.download(media.file_id, destination=audio_path)
        except Exception as exc:
            logger.exception("download failed for draft=%s", draft_id)
            await drafts.update(draft_id, error=f"download: {exc}")
            await progress.fail(f"Не получилось скачать: {exc}")
            return

        await progress.set_phase("Транскрибирую…")
        try:
            result = await transcriber.transcribe(
                audio_path, on_fraction=progress.set_progress_fraction
            )
        except Exception as exc:
            logger.exception("transcribe failed for draft=%s", draft_id)
            await drafts.update(draft_id, error=f"transcribe: {exc}")
            _cleanup(audio_path)
            await progress.fail(f"Транскрибация упала: {exc}")
            return

        await drafts.update(draft_id, status="transcribed", transcribed=result.text)
        _cleanup(audio_path)

        await progress.set_phase("Готовлю заметку…")
        llm_input = (
            forward_utils.enrich(result.text, forward_meta) if forward_meta else result.text
        )
        try:
            processed = await llm_processor.process(llm_input)
        except Exception as exc:
            logger.exception("llm_processor failed for draft=%s", draft_id)
            await drafts.update(draft_id, status="failed", error=f"llm: {exc}")
            await progress.fail(f"Не получилось обработать: {exc}")
            return

        await drafts.update(
            draft_id,
            status="awaiting_confirm",
            note_type=processed.note_type,
            title=processed.title,
            formatted=processed.formatted,
            properties=json.dumps(processed.properties, ensure_ascii=False),
        )
        await progress.finish()

    preview = format_preview(processed.title, processed.formatted, processed.note_type)
    sent = await message.answer(preview, reply_markup=preview_keyboard(draft_id))
    await drafts.update(draft_id, preview_msg_id=sent.message_id)


def _cleanup(path: str) -> None:
    with suppress(FileNotFoundError, OSError):
        os.remove(path)
