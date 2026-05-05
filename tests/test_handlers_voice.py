"""Voice handler durability + happy-path with mocked download/transcribe/LLM."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.voice import handle_media
from bot.services import llm_processor
from bot.services.transcriber import TranscriptionResult, Utterance
from bot.storage import drafts


class _FakeProgress:
    """Drop-in for ProgressReporter that skips Telegram I/O."""

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


def _voice_message(file_id="vid-1"):
    msg = MagicMock()
    msg.from_user.id = 111
    msg.chat.id = 999
    msg.message_id = 42
    msg.voice = MagicMock(file_id=file_id, duration=12, mime_type="audio/ogg")
    msg.audio = None
    msg.video = None
    msg.video_note = None
    sent = MagicMock(message_id=4242)
    msg.answer = AsyncMock(return_value=sent)
    return msg


@pytest.fixture
def patch_progress(monkeypatch):
    monkeypatch.setattr("bot.handlers.voice.ProgressReporter", lambda *a, **kw: _FakeProgress())


@pytest.fixture(autouse=True)
def _reset():
    llm_processor.set_client(None)
    yield
    llm_processor.set_client(None)


async def test_disabled_assemblyai_short_circuits(fresh_db, monkeypatch, patch_progress):
    monkeypatch.setattr("bot.handlers.voice.settings.ASSEMBLYAI_API_KEY", None)
    bot = MagicMock()
    msg = _voice_message()

    await handle_media(msg, bot)

    msg.answer.assert_awaited()
    # No draft created — feature is off.
    assert await drafts.list_for_user(111) == []


async def test_happy_path(fresh_db, monkeypatch, patch_progress, tmp_path):
    monkeypatch.setattr("bot.handlers.voice.settings.ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr("bot.handlers.voice.settings.TEMP_DIR", str(tmp_path))

    async def fake_transcribe(path, *, on_fraction=None):
        return TranscriptionResult(
            text="Hello world",
            utterances=[Utterance("A", "Hello world", 0, 1000)],
            speaker_count=1,
            language="en",
        )

    monkeypatch.setattr("bot.handlers.voice.transcriber.transcribe", fake_transcribe)
    # llm_processor stub kicks in if OPENAI_API_KEY is empty.
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", None)

    bot = MagicMock()
    bot.download = AsyncMock()

    msg = _voice_message()
    await handle_media(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.kind == "voice"
    assert d.status == "awaiting_confirm"
    assert d.transcribed == "Hello world"
    assert d.title == "Hello world"
    assert d.preview_msg_id == 4242
    bot.download.assert_awaited_once()


async def test_download_failure_keeps_draft_with_file_id(
    fresh_db, monkeypatch, patch_progress, tmp_path
):
    monkeypatch.setattr("bot.handlers.voice.settings.ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr("bot.handlers.voice.settings.TEMP_DIR", str(tmp_path))

    bot = MagicMock()
    bot.download = AsyncMock(side_effect=RuntimeError("network"))

    msg = _voice_message(file_id="VID-LOST")
    await handle_media(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    # File_id preserved in raw_payload — content not lost despite download fail.
    assert "VID-LOST" in (d.raw_payload or "")
    assert d.status == "raw"
    assert d.error and "network" in d.error


async def test_transcribe_failure_keeps_file_id_for_retry(
    fresh_db, monkeypatch, patch_progress, tmp_path
):
    monkeypatch.setattr("bot.handlers.voice.settings.ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr("bot.handlers.voice.settings.TEMP_DIR", str(tmp_path))

    async def boom(*_a, **_kw):
        raise RuntimeError("AssemblyAI down")

    monkeypatch.setattr("bot.handlers.voice.transcriber.transcribe", boom)

    bot = MagicMock()
    bot.download = AsyncMock()

    msg = _voice_message()
    await handle_media(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.status == "raw"
    assert d.error and "AssemblyAI" in d.error
    assert d.kind == "voice"
