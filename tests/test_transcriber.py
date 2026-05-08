from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.services import transcriber


@pytest.fixture(autouse=True)
def _reset_client():
    transcriber.set_client(None)
    yield
    transcriber.set_client(None)


async def test_transcribe_disabled_raises(monkeypatch):
    monkeypatch.setattr("bot.services.transcriber.settings.OPENAI_API_KEY", None)
    with pytest.raises(RuntimeError, match="not configured"):
        await transcriber.transcribe("/tmp/x.ogg")


async def test_transcribe_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr("bot.services.transcriber.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "bot.services.transcriber.settings.OPENAI_TRANSCRIBE_MODEL",
        "gpt-4o-mini-transcribe",
    )
    monkeypatch.setattr("bot.services.transcriber.settings.FORCE_LANGUAGE_CODE", None)

    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"fake-bytes")

    fake_response = MagicMock(text="Привет мир", language="ru")
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create = AsyncMock(return_value=fake_response)
    transcriber.set_client(fake_client)

    fractions: list[float] = []

    async def on_fraction(f: float):
        fractions.append(f)

    result = await transcriber.transcribe(str(audio), on_fraction=on_fraction)

    assert result.text == "Привет мир"
    assert result.language == "ru"
    assert fractions[0] == 0.1 and fractions[-1] == 1.0
    fake_client.audio.transcriptions.create.assert_awaited_once()
    kwargs = fake_client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini-transcribe"
    assert kwargs["language"] is None
    assert kwargs["response_format"] == "json"


async def test_transcribe_passes_force_language(monkeypatch, tmp_path):
    monkeypatch.setattr("bot.services.transcriber.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("bot.services.transcriber.settings.FORCE_LANGUAGE_CODE", "ru")

    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"x")

    # Модели gpt-4o-*-transcribe не возвращают language в response — проверяем,
    # что результат подхватывает FORCE_LANGUAGE_CODE как fallback.
    fake_response = MagicMock(spec=["text"])
    fake_response.text = "ok"
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create = AsyncMock(return_value=fake_response)
    transcriber.set_client(fake_client)

    result = await transcriber.transcribe(str(audio))

    assert result.text == "ok"
    assert result.language == "ru"
    kwargs = fake_client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["language"] == "ru"


async def test_transcribe_strips_whitespace(monkeypatch, tmp_path):
    monkeypatch.setattr("bot.services.transcriber.settings.OPENAI_API_KEY", "sk-test")
    audio = tmp_path / "v.ogg"
    audio.write_bytes(b"x")

    fake_response = MagicMock(text="  hello  \n", language=None)
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create = AsyncMock(return_value=fake_response)
    transcriber.set_client(fake_client)

    result = await transcriber.transcribe(str(audio))
    assert result.text == "hello"
