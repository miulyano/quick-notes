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

    processing_start: Optional[float] = None
    while True:
        raw = await asyncio.to_thread(aai_api.get_transcript, http_client, transcript_id)
        if raw.status == aai.TranscriptStatus.queued:
            frac = 0.05
        elif raw.status == aai.TranscriptStatus.processing:
            if processing_start is None:
                processing_start = asyncio.get_event_loop().time()
            elapsed = asyncio.get_event_loop().time() - processing_start
            frac = min(0.90, 0.10 + elapsed / 120.0)
        elif raw.status in (aai.TranscriptStatus.completed, aai.TranscriptStatus.error):
            break
        else:
            frac = 0.5

        if on_fraction:
            await on_fraction(frac)
        await asyncio.sleep(3.0)

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
