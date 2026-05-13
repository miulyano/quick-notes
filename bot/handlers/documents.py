"""Document handler: txt/md/csv/pdf/docx → extracted text → LLM → preview.

Mirrors `bot/handlers/voice.py` but swaps transcription for synchronous text
extraction (run in a thread). Long extracted texts go through
`llm_processor.process_long` (map-reduce).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.config import settings
from bot.handlers.inputs import format_preview, preview_keyboard
from bot.services import doc_extractor, llm_processor
from bot.services.doc_extractor import DocExtractError
from bot.storage import drafts
from bot.utils import forward as forward_utils
from bot.utils.progress import ProgressReporter

router = Router()
logger = logging.getLogger(__name__)

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024  # Telegram bot API download limit.

_SUPPORTED_EXTS = {".txt", ".md", ".markdown", ".csv", ".pdf", ".docx"}
_SUPPORTED_MIMES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/csv",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _is_supported(file_name: str | None, mime: str | None) -> bool:
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext in _SUPPORTED_EXTS:
        return True
    return (mime or "").lower() in _SUPPORTED_MIMES


@router.message(F.document)
async def handle_document(message: Message, bot: Bot) -> None:
    doc = message.document
    if doc is None:
        return

    mime = doc.mime_type or ""
    if mime.startswith("audio/") or mime.startswith("video/"):
        await message.answer(
            "⚠️ Это медиа — пришли как голосовое/аудио/видео, а не как файл."
        )
        return

    if not _is_supported(doc.file_name, doc.mime_type):
        await message.answer(
            "⚠️ Поддерживаются: txt, md, csv, pdf, docx."
        )
        return

    if (doc.file_size or 0) > MAX_DOCUMENT_BYTES:
        mb = MAX_DOCUMENT_BYTES // 1024 // 1024
        await message.answer(
            f"⚠️ Файл больше {mb} МБ — Telegram bot API не отдаст."
        )
        return

    forward_meta = forward_utils.extract(message)
    payload = json.dumps(
        {
            "file_id": doc.file_id,
            "mime_type": doc.mime_type,
            "file_name": doc.file_name,
            "file_size": doc.file_size,
            "forward": forward_meta,
        },
        ensure_ascii=False,
    )
    draft_kind = "forward" if forward_meta else "document"

    draft_id = await drafts.create(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        kind=draft_kind,
        raw_payload=payload,
    )

    os.makedirs(settings.TEMP_DIR, exist_ok=True)
    ext = os.path.splitext(doc.file_name or "")[1].lower() or ".bin"
    file_path = os.path.join(settings.TEMP_DIR, f"{draft_id}{ext}")

    async with ProgressReporter(message, "Скачиваю…") as progress:
        try:
            await bot.download(doc.file_id, destination=file_path)
        except Exception as exc:
            logger.exception("download failed for draft=%s", draft_id)
            await drafts.update(draft_id, error=f"download: {exc}")
            await progress.fail(f"Не получилось скачать: {exc}")
            return

        await progress.set_phase("Извлекаю текст…")
        try:
            text = await asyncio.to_thread(
                doc_extractor.extract, file_path, doc.mime_type, doc.file_name
            )
        except DocExtractError as exc:
            logger.warning("doc_extract failed for draft=%s: %s", draft_id, exc)
            await drafts.update(draft_id, status="failed", error=f"extract: {exc}")
            _cleanup(file_path)
            await progress.fail(f"Не получилось прочитать: {exc}")
            return
        except Exception as exc:
            logger.exception("doc_extract crashed for draft=%s", draft_id)
            await drafts.update(draft_id, status="failed", error=f"extract: {exc}")
            _cleanup(file_path)
            await progress.fail(f"Не получилось прочитать: {exc}")
            return
        finally:
            _cleanup(file_path)

        await drafts.update(draft_id, status="transcribed", transcribed=text)

        await progress.set_phase("Готовлю заметку…")
        llm_input = (
            forward_utils.enrich(text, forward_meta) if forward_meta else text
        )
        try:
            processed = await llm_processor.process_long(
                llm_input, on_fraction=progress.set_progress_fraction
            )
        except Exception as exc:
            logger.exception("llm_processor failed for draft=%s", draft_id)
            await drafts.update(draft_id, status="failed", error=f"llm: {exc}")
            await progress.fail(f"Не получилось обработать: {exc}")
            return

        properties_json = json.dumps(processed.properties, ensure_ascii=False)
        await drafts.update(
            draft_id,
            status="awaiting_confirm",
            note_type=processed.note_type,
            title=processed.title,
            formatted=processed.formatted,
            properties=properties_json,
            workspace=processed.workspace,
        )
        await progress.finish()

    preview = format_preview(
        processed.title,
        processed.formatted,
        processed.note_type,
        processed.workspace,
        None,
        properties_json,
    )
    sent = await message.answer(preview, reply_markup=preview_keyboard(draft_id))
    await drafts.update(draft_id, preview_msg_id=sent.message_id)


def _cleanup(path: str) -> None:
    with suppress(FileNotFoundError, OSError):
        os.remove(path)
