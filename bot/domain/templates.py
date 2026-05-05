"""Markdown body templates per template_id.

Each template receives the LLM-formatted body plus optional structured fields
(extras) and returns the final markdown that gets shipped to Notion.
"""

from __future__ import annotations

from typing import Any

from bot.domain.note_types import get


def render(note_type_key: str, body: str, extras: dict[str, Any] | None = None) -> str:
    """Apply the markdown template for the given note type."""
    template_id = get(note_type_key).template_id
    extras = extras or {}
    body = (body or "").strip()
    renderer = _RENDERERS.get(template_id, _render_default)
    return renderer(body, extras)


def _render_default(body: str, _extras: dict) -> str:
    return body


def _render_note(body: str, _extras: dict) -> str:
    return body


def _render_task(body: str, extras: dict) -> str:
    parts: list[str] = [body] if body else []
    items = extras.get("checklist") or []
    if isinstance(items, list) and items:
        parts.append("")
        parts.append("## Чек-лист")
        for item in items:
            parts.append(f"- [ ] {item}")
    return "\n".join(parts).strip()


def _render_idea(body: str, _extras: dict) -> str:
    return body


def _render_meeting(body: str, extras: dict) -> str:
    agenda = extras.get("agenda") or []
    decisions = extras.get("decisions") or []
    actions = extras.get("action_items") or []

    # No structured extras → return body as-is. Headers add noise otherwise.
    if not (agenda or decisions or actions):
        return body

    parts: list[str] = []
    if agenda:
        parts.append("## Agenda")
        parts.extend(f"- {item}" for item in agenda)
        parts.append("")
    if body:
        parts.append("## Discussion")
        parts.append(body)
        parts.append("")
    if decisions:
        parts.append("## Decisions")
        parts.extend(f"- {item}" for item in decisions)
        parts.append("")
    if actions:
        parts.append("## Action items")
        parts.extend(f"- [ ] {item}" for item in actions)

    return "\n".join(parts).strip()


def _render_1on1(body: str, extras: dict) -> str:
    topics = extras.get("topics") or []
    follow_ups = extras.get("follow_ups") or []

    if not (topics or follow_ups):
        return body

    parts: list[str] = []
    if topics:
        parts.append("## Topics")
        parts.extend(f"- {item}" for item in topics)
        parts.append("")
    if body:
        parts.append("## Notes")
        parts.append(body)
        parts.append("")
    if follow_ups:
        parts.append("## Follow-ups")
        parts.extend(f"- [ ] {item}" for item in follow_ups)

    return "\n".join(parts).strip()


_RENDERERS = {
    "default": _render_default,
    "note": _render_note,
    "task": _render_task,
    "idea": _render_idea,
    "meeting": _render_meeting,
    "1on1": _render_1on1,
}
