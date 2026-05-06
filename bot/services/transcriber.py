"""Audio → transcript via AssemblyAI Universal-2.

Returns a flat string with optional speaker labels. Title generation /
formatting happens later in `services/llm_processor.process` — this module
stays dumb on purpose.

Multi-speaker recordings are rendered as
    A: ...

    B: ...
so the LLM downstream can reason about participants (useful for `meeting` /
`1on1` types).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from bot.config import settings

logger = logging.getLogger(__name__)

FractionCallback = Callable[[float], Awaitable[None]]
_client_override: object | None = None

# Жёсткий потолок на полный цикл poll. Реальная транскрипция аудио до часа
# укладывается в 5–10 минут; всё, что дольше — почти всегда залип AssemblyAI.
# Без этого таймаута while-True крутится бесконечно, ProgressReporter тоже.
MAX_POLL_SECONDS = 600.0
POLL_INTERVAL_SECS = 3.0


def set_client_override(client) -> None:
    """Test hook: replace the underlying SDK transcriber with a stand-in."""
    global _client_override
    _client_override = client


@dataclass
class Utterance:
    speaker: str
    text: str
    start_ms: int
    end_ms: int


@dataclass
class TranscriptionResult:
    text: str                       # Plain transcript with speaker labels (if multi).
    utterances: list[Utterance]
    speaker_count: int
    language: Optional[str]


def _render_with_speakers(utterances: list[Utterance]) -> str:
    if not utterances:
        return ""
    speakers = {u.speaker for u in utterances}
    if len(speakers) <= 1:
        return "\n\n".join(u.text.strip() for u in utterances if u.text.strip())
    parts: list[str] = []
    for u in utterances:
        text = u.text.strip()
        if not text:
            continue
        parts.append(f"{u.speaker}: {text}")
    return "\n\n".join(parts)


def _build_config():
    """Construct AssemblyAI TranscriptionConfig."""
    import assemblyai as aai

    cfg = aai.TranscriptionConfig(
        speech_models=[settings.ASSEMBLYAI_SPEECH_MODEL],
        speaker_labels=True,
        punctuate=True,
        format_text=True,
        disfluencies=False,
    )
    if settings.FORCE_LANGUAGE_CODE:
        cfg.language_code = settings.FORCE_LANGUAGE_CODE
    else:
        cfg.language_detection = True
    return cfg


def _utterances_from_response(transcript) -> list[Utterance]:
    out: list[Utterance] = []
    for u in transcript.utterances or []:
        out.append(
            Utterance(
                speaker=str(u.speaker),
                text=u.text or "",
                start_ms=int(getattr(u, "start", 0) or 0),
                end_ms=int(getattr(u, "end", 0) or 0),
            )
        )
    return out


async def _poll_for_completion(
    *,
    fetch,
    on_fraction: Optional[FractionCallback],
    completed_statuses: tuple,
    queued_status,
    processing_status,
    now_fn=None,
    sleep_fn=None,
    max_poll_seconds: float = MAX_POLL_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECS,
):
    """Чистый poll-цикл: вытащен из _run_assemblyai для тестируемости.

    fetch — корутина без аргументов, возвращает raw-объект со полем .status.
    Зависимости инжектируются (now_fn / sleep_fn), чтобы тест мог
    подменить часы и не спать реально.
    """
    loop = asyncio.get_event_loop()
    now_fn = now_fn or loop.time
    sleep_fn = sleep_fn or asyncio.sleep

    poll_start = now_fn()
    processing_start: Optional[float] = None
    while True:
        raw = await fetch()
        if raw.status == queued_status:
            frac = 0.05
        elif raw.status == processing_status:
            if processing_start is None:
                processing_start = now_fn()
            frac = min(0.90, 0.10 + (now_fn() - processing_start) / 120.0)
        elif raw.status in completed_statuses:
            return raw
        else:
            frac = 0.5

        if on_fraction:
            await on_fraction(frac)

        if now_fn() - poll_start > max_poll_seconds:
            raise RuntimeError(
                f"AssemblyAI timeout: status={raw.status} after {max_poll_seconds:.0f}s"
            )
        await sleep_fn(poll_interval)


async def _run_assemblyai(
    audio_path: str,
    on_fraction: Optional[FractionCallback] = None,
):
    """Submit audio, poll status until completed/error, return raw transcript."""
    import assemblyai as aai
    from assemblyai import api as aai_api

    aai.settings.api_key = settings.ASSEMBLYAI_API_KEY

    transcriber = _client_override or aai.Transcriber(config=_build_config())

    transcript = await asyncio.to_thread(transcriber.submit, audio_path)
    transcript_id = transcript._impl.transcript_id
    http_client = transcript._client.http_client

    async def fetch():
        return await asyncio.to_thread(aai_api.get_transcript, http_client, transcript_id)

    raw = await _poll_for_completion(
        fetch=fetch,
        on_fraction=on_fraction,
        completed_statuses=(aai.TranscriptStatus.completed, aai.TranscriptStatus.error),
        queued_status=aai.TranscriptStatus.queued,
        processing_status=aai.TranscriptStatus.processing,
    )

    if raw.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI error: {raw.error}")
    if on_fraction:
        await on_fraction(1.0)
    return raw


async def transcribe(
    audio_path: str,
    *,
    on_fraction: Optional[FractionCallback] = None,
) -> TranscriptionResult:
    """Transcribe an audio file at `audio_path` and return the result."""
    if not settings.assemblyai_enabled:
        raise RuntimeError("AssemblyAI is not configured (ASSEMBLYAI_API_KEY empty)")

    raw = await _run_assemblyai(audio_path, on_fraction)
    utterances = _utterances_from_response(raw)
    speaker_count = (
        len({u.speaker for u in utterances}) if utterances else (1 if (raw.text or "").strip() else 0)
    )
    text = _render_with_speakers(utterances) if utterances else (raw.text or "").strip()
    language = getattr(raw, "language_code", None) or settings.FORCE_LANGUAGE_CODE
    return TranscriptionResult(
        text=text,
        utterances=utterances,
        speaker_count=speaker_count,
        language=language,
    )
