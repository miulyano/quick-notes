"""Audio → transcript via OpenAI Speech-to-Text.

Default model: gpt-4o-mini-transcribe (дешевле, ~6% WER на русском по
бенчмаркам OpenAI). Для шумных записей переопределить
OPENAI_TRANSCRIBE_MODEL=gpt-4o-transcribe (~5% WER, та же цена что у whisper-1).

Возвращает плоский TranscriptionResult(text, language). Диаризация удалена —
все входы это короткие голосовые/кружки/мелкое видео с одним спикером.
Title generation / форматирование происходит дальше в services/llm_processor.process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from bot.config import settings

logger = logging.getLogger(__name__)

FractionCallback = Callable[[float], Awaitable[None]]

_client_override: Any = None
_client_real: Any = None

OPENAI_TIMEOUT_SECS = 120.0
OPENAI_MAX_RETRIES = 2


def set_client(client: Any) -> None:
    """Test hook: inject a stand-in OpenAI client (must expose
    .audio.transcriptions.create as AsyncMock returning the fake response)."""
    global _client_override
    _client_override = client


def _get_client() -> Any:
    if _client_override is not None:
        return _client_override
    global _client_real
    if _client_real is None:
        from openai import AsyncOpenAI

        _client_real = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=OPENAI_TIMEOUT_SECS,
            max_retries=OPENAI_MAX_RETRIES,
        )
    return _client_real


async def close_client() -> None:
    """Закрыть httpx-сессию OpenAI при graceful shutdown. Idempotent."""
    global _client_real
    if _client_real is not None:
        try:
            await _client_real.close()
        except Exception:
            logger.exception("OpenAI transcribe client close failed")
        _client_real = None


@dataclass
class TranscriptionResult:
    text: str
    language: Optional[str]


async def transcribe(
    audio_path: str,
    *,
    on_fraction: Optional[FractionCallback] = None,
) -> TranscriptionResult:
    """Transcribe an audio file at `audio_path` and return the result."""
    if not settings.openai_enabled:
        raise RuntimeError("OpenAI is not configured (OPENAI_API_KEY empty)")

    if on_fraction:
        await on_fraction(0.1)

    client = _get_client()

    with open(audio_path, "rb") as f:
        response = await client.audio.transcriptions.create(
            model=settings.OPENAI_TRANSCRIBE_MODEL,
            file=f,
            language=settings.FORCE_LANGUAGE_CODE or None,
            response_format="json",
        )

    text = (getattr(response, "text", "") or "").strip()
    language = getattr(response, "language", None) or settings.FORCE_LANGUAGE_CODE

    if on_fraction:
        await on_fraction(1.0)

    return TranscriptionResult(text=text, language=language)
