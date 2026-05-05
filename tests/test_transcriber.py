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
