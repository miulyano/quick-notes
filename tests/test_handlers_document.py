"""Document handler durability + happy-path with mocked download/extract/LLM."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.documents import MAX_DOCUMENT_BYTES, handle_document
from bot.services import llm_processor
from bot.services.doc_extractor import EmptyDocumentError
from bot.storage import drafts


class _FakeProgress:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def set_phase(self, _label):
        pass

    async def set_progress_fraction(self, _frac):
        pass

    async def fail(self, _text):
        pass

    async def finish(self):
        pass


def _doc_message(
    *,
    file_name: str = "agenda.txt",
    mime_type: str | None = "text/plain",
    file_size: int = 1024,
    forward_origin=None,
):
    msg = MagicMock()
    msg.from_user.id = 111
    msg.chat.id = 999
    msg.message_id = 42
    msg.document = MagicMock(
        file_id="DOC-1",
        file_name=file_name,
        mime_type=mime_type,
        file_size=file_size,
    )
    msg.forward_origin = forward_origin
    sent = MagicMock(message_id=4242)
    msg.answer = AsyncMock(return_value=sent)
    return msg


@pytest.fixture
def patch_progress(monkeypatch):
    monkeypatch.setattr(
        "bot.handlers.documents.ProgressReporter", lambda *a, **kw: _FakeProgress()
    )


@pytest.fixture(autouse=True)
def _reset():
    llm_processor.set_client(None)
    yield
    llm_processor.set_client(None)


async def test_oversized_rejected(fresh_db, patch_progress):
    bot = MagicMock()
    msg = _doc_message(file_size=MAX_DOCUMENT_BYTES + 1)
    await handle_document(msg, bot)
    msg.answer.assert_awaited()
    args, _ = msg.answer.call_args
    assert "больше" in args[0].lower() or "мб" in args[0].lower()
    assert await drafts.list_for_user(111) == []


async def test_audio_as_document_rejected(fresh_db, patch_progress):
    bot = MagicMock()
    msg = _doc_message(file_name="song.mp3", mime_type="audio/mpeg")
    await handle_document(msg, bot)
    msg.answer.assert_awaited()
    assert await drafts.list_for_user(111) == []


async def test_video_as_document_rejected(fresh_db, patch_progress):
    bot = MagicMock()
    msg = _doc_message(file_name="clip.mp4", mime_type="video/mp4")
    await handle_document(msg, bot)
    msg.answer.assert_awaited()
    assert await drafts.list_for_user(111) == []


async def test_unsupported_extension_rejected(fresh_db, patch_progress):
    bot = MagicMock()
    msg = _doc_message(file_name="installer.exe", mime_type="application/x-msdownload")
    await handle_document(msg, bot)
    msg.answer.assert_awaited()
    assert await drafts.list_for_user(111) == []


async def test_happy_path_txt(fresh_db, monkeypatch, patch_progress, tmp_path):
    monkeypatch.setattr("bot.handlers.documents.settings.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", None)

    captured: dict[str, str] = {}

    def fake_extract(path, mime, name):
        captured["path"] = path
        captured["mime"] = mime
        captured["name"] = name
        return "Hello"

    monkeypatch.setattr("bot.handlers.documents.doc_extractor.extract", fake_extract)

    async def fake_download(file_id, destination):
        with open(destination, "wb") as f:
            f.write(b"hello bytes")

    bot = MagicMock()
    bot.download = AsyncMock(side_effect=fake_download)

    msg = _doc_message(file_name="agenda.txt", mime_type="text/plain")
    await handle_document(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.kind == "document"
    assert d.status == "awaiting_confirm"
    assert d.transcribed == "Hello"
    assert d.title == "Hello"
    assert d.preview_msg_id == 4242
    bot.download.assert_awaited_once()
    assert captured["name"] == "agenda.txt"
    # temp file cleaned up
    assert not os.path.exists(captured["path"])


async def test_extract_failure_marks_draft_failed(
    fresh_db, monkeypatch, patch_progress, tmp_path
):
    monkeypatch.setattr("bot.handlers.documents.settings.TEMP_DIR", str(tmp_path))

    def boom(_path, _mime, _name):
        raise EmptyDocumentError("no extractable text")

    monkeypatch.setattr("bot.handlers.documents.doc_extractor.extract", boom)

    async def fake_download(file_id, destination):
        with open(destination, "wb") as f:
            f.write(b"x")

    bot = MagicMock()
    bot.download = AsyncMock(side_effect=fake_download)

    msg = _doc_message(file_name="scan.pdf", mime_type="application/pdf")
    await handle_document(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.status == "failed"
    assert d.error and "no extractable text" in d.error
    assert d.kind == "document"
    # cleanup happened
    assert not list(tmp_path.iterdir()) or all(
        not p.name.startswith(d.id) for p in tmp_path.iterdir()
    )


async def test_download_failure_keeps_draft_raw(
    fresh_db, monkeypatch, patch_progress, tmp_path
):
    monkeypatch.setattr("bot.handlers.documents.settings.TEMP_DIR", str(tmp_path))

    bot = MagicMock()
    bot.download = AsyncMock(side_effect=RuntimeError("network"))

    msg = _doc_message(file_name="agenda.txt", mime_type="text/plain")
    await handle_document(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.status == "raw"
    assert "DOC-1" in (d.raw_payload or "")
    assert d.error and "network" in d.error


async def test_forwarded_uses_kind_forward(
    fresh_db, monkeypatch, patch_progress, tmp_path
):
    from aiogram.types import MessageOriginUser, User

    monkeypatch.setattr("bot.handlers.documents.settings.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", None)

    captured_input: dict[str, str] = {}

    async def fake_process_long(text, *, on_fraction=None):
        captured_input["text"] = text
        if on_fraction:
            await on_fraction(1.0)
        from bot.services.llm_processor import ProcessedNote
        return ProcessedNote(
            note_type="note",
            title="Forwarded",
            formatted=text,
            workspace="personal",
        )

    monkeypatch.setattr(
        "bot.handlers.documents.llm_processor.process_long", fake_process_long
    )
    monkeypatch.setattr(
        "bot.handlers.documents.doc_extractor.extract",
        lambda _p, _m, _n: "shared agenda body",
    )

    async def fake_download(file_id, destination):
        with open(destination, "wb") as f:
            f.write(b"x")

    bot = MagicMock()
    bot.download = AsyncMock(side_effect=fake_download)

    user = User(id=555, is_bot=False, first_name="Alice", username="alice")
    origin = MessageOriginUser(
        type="user",
        date=__import__("datetime").datetime(2026, 5, 6, 12, 0, 0),
        sender_user=user,
    )
    msg = _doc_message(
        file_name="agenda.txt", mime_type="text/plain", forward_origin=origin
    )
    await handle_document(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.kind == "forward"
    assert "[Forwarded]" in captured_input["text"]
    assert "От:" in captured_input["text"]
    assert "shared agenda body" in captured_input["text"]


async def test_unknown_mime_with_supported_ext_works(
    fresh_db, monkeypatch, patch_progress, tmp_path
):
    """Telegram often sends application/octet-stream — extension must rescue."""
    monkeypatch.setattr("bot.handlers.documents.settings.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", None)
    monkeypatch.setattr(
        "bot.handlers.documents.doc_extractor.extract",
        lambda _p, _m, _n: "body",
    )

    async def fake_download(file_id, destination):
        with open(destination, "wb") as f:
            f.write(b"x")

    bot = MagicMock()
    bot.download = AsyncMock(side_effect=fake_download)

    msg = _doc_message(file_name="meeting.docx", mime_type="application/octet-stream")
    await handle_document(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    assert items[0].status == "awaiting_confirm"
