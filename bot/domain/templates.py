"""Markdown templates per note type. Stub for Increment 1.

Increment 3 introduces real per-type formatting (meeting agenda layout,
1:1 structure, task fields, etc).
"""

from __future__ import annotations

from bot.domain.note_types import DEFAULT_TYPE


def render(note_type: str, title: str, body: str) -> str:
    """Apply markdown template for the given note type."""
    if note_type == DEFAULT_TYPE:
        return body
    raise ValueError(f"unknown note_type: {note_type}")
