import pytest

from bot.services import transcriber
from bot.services.transcriber import Utterance


def test_render_single_speaker():
    utts = [
        Utterance("A", "first sentence", 0, 1000),
        Utterance("A", "second sentence", 1000, 2000),
    ]
    text = transcriber._render_with_speakers(utts)
    assert text == "first sentence\n\nsecond sentence"


def test_render_multi_speaker_labels():
    utts = [
        Utterance("A", "Привет", 0, 100),
        Utterance("B", "Здарова", 100, 200),
        Utterance("A", "Как ты?", 200, 300),
    ]
    text = transcriber._render_with_speakers(utts)
    assert "A: Привет" in text
    assert "B: Здарова" in text
    assert "A: Как ты?" in text


def test_render_empty():
    assert transcriber._render_with_speakers([]) == ""


def test_render_skips_empty_text():
    utts = [
        Utterance("A", "ok", 0, 100),
        Utterance("A", "   ", 100, 200),
        Utterance("A", "next", 200, 300),
    ]
    text = transcriber._render_with_speakers(utts)
    assert text == "ok\n\nnext"


async def test_transcribe_disabled_raises(monkeypatch):
    monkeypatch.setattr("bot.services.transcriber.settings.ASSEMBLYAI_API_KEY", None)
    with pytest.raises(RuntimeError, match="not configured"):
        await transcriber.transcribe("/tmp/x.ogg")


class _FakeRaw:
    def __init__(self, status, text=""):
        self.status = status
        self.text = text


async def test_poll_returns_on_completed():
    raws = [_FakeRaw("queued"), _FakeRaw("processing"), _FakeRaw("completed", "ok")]

    async def fetch():
        return raws.pop(0)

    async def sleep_fn(_):
        return

    result = await transcriber._poll_for_completion(
        fetch=fetch,
        on_fraction=None,
        completed_statuses=("completed", "error"),
        queued_status="queued",
        processing_status="processing",
        now_fn=lambda: 0.0,
        sleep_fn=sleep_fn,
    )
    assert result.status == "completed"


async def test_poll_raises_on_timeout():
    """Бесконечный processing → RuntimeError по истечении max_poll_seconds."""
    async def fetch():
        return _FakeRaw("processing")

    async def sleep_fn(_):
        return

    clock = {"t": 0.0}

    def now_fn():
        clock["t"] += 100.0
        return clock["t"]

    with pytest.raises(RuntimeError, match="timeout"):
        await transcriber._poll_for_completion(
            fetch=fetch,
            on_fraction=None,
            completed_statuses=("completed", "error"),
            queued_status="queued",
            processing_status="processing",
            now_fn=now_fn,
            sleep_fn=sleep_fn,
            max_poll_seconds=300.0,
        )
