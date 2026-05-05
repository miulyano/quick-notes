"""LLM classify + format pipeline (stub for Increment 1).

Increment 3 swaps this for one OpenAI call with structured output:
{type, title, properties, markdown_body}.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.domain.note_types import DEFAULT_TYPE


@dataclass
class ProcessedNote:
    note_type: str
    title: str
    formatted: str
    properties: dict = field(default_factory=dict)


async def process(raw_text: str) -> ProcessedNote:
    """Stub: derive title from first line, body = raw text, type = note."""
    text = raw_text.strip()
    first_line = text.split("\n", 1)[0]
    title = first_line[:80] if first_line else "Без названия"
    return ProcessedNote(
        note_type=DEFAULT_TYPE,
        title=title,
        formatted=text,
    )
