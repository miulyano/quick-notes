"""Single GPT-4o call: classify type + extract properties + format body.

Real path requires OPENAI_API_KEY; without it the stub kicks in (one type
'note', body = raw input). One call instead of two saves ~half the tokens
since the model already sees the input when picking the type.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from bot.config import settings
from bot.domain.note_types import DEFAULT_TYPE, TYPES, all_keys
from bot.domain.workspaces import (
    DEFAULT_WORKSPACE,
    WORKSPACES,
    all_keys as all_workspace_keys,
)

logger = logging.getLogger(__name__)


@dataclass
class ProcessedNote:
    note_type: str
    title: str
    formatted: str                 # Markdown body (already template-rendered).
    workspace: str = DEFAULT_WORKSPACE
    properties: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)


_client_override: Any = None
_client_real: Any = None


def set_client(client: Any) -> None:
    """Test hook: inject a stand-in OpenAI client (must expose
    .chat.completions.create as AsyncMock returning the fake completion)."""
    global _client_override
    _client_override = client


def _get_client() -> Any:
    if _client_override is not None:
        return _client_override
    global _client_real
    if _client_real is None:
        from openai import AsyncOpenAI

        _client_real = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client_real


def _build_system_prompt() -> str:
    type_blocks = []
    for t in TYPES:
        prop_lines = "\n".join(
            f"  - {p.name} ({p.kind}): {p.llm_hint}" for p in t.properties
        )
        type_blocks.append(
            f"### {t.key}\n{t.description}\nProperties:\n{prop_lines or '  (none)'}"
        )
    types_section = "\n\n".join(type_blocks)

    workspace_lines = "\n".join(
        f"- `{w.key}` ({w.label}) — {w.description}" for w in WORKSPACES
    )

    return (
        "Ты помогаешь пользователю превращать сырые заметки (текст, транскрипт "
        "голосового, форвард) в структурированную страницу.\n\n"
        "Сделай за один проход:\n"
        "1. КЛАССИФИЦИРУЙ запись по одному из типов ниже.\n"
        "2. ВЫБЕРИ workspace, в который сохранять (см. список ниже).\n"
        "3. ИЗВЛЕКИ properties под выбранный тип.\n"
        "4. ОТФОРМАТИРУЙ тело заметки как чистый markdown (заголовки `##`, "
        "списки `-`, цитаты `>` где уместно). Не добавляй мета-информацию "
        "вроде «вот ваша заметка». Не цитируй prompt.\n\n"
        f"Типы:\n\n{types_section}\n\n"
        f"Workspaces:\n{workspace_lines}\n\n"
        f"Если не уверен в workspace — выбирай `{DEFAULT_WORKSPACE}`.\n\n"
        "Верни СТРОГО JSON со схемой:\n"
        "{\n"
        '  "type": "<один из ключей типов>",\n'
        '  "workspace": "<один из ключей workspaces>",\n'
        '  "title": "<строка ≤80 символов>",\n'
        '  "properties": { "<имя property>": <value>, ... },\n'
        '  "extras": {\n'
        '    "checklist": ["..."],     // для type=task\n'
        '    "agenda": ["..."],        // для type=meeting\n'
        '    "decisions": ["..."],     // для type=meeting\n'
        '    "action_items": ["..."],  // для type=meeting\n'
        '    "topics": ["..."],        // для type=1on1\n'
        '    "follow_ups": ["..."]     // для type=1on1\n'
        '  },\n'
        '  "markdown_body": "<основное тело заметки markdown>"\n'
        "}\n\n"
        "Все поля extras — опциональные, опускай если не применимы. "
        "Properties: используй формат значений соответствующий kind:\n"
        "- title/rich_text → строка\n"
        "- select → строка (одно значение)\n"
        "- multi_select → массив строк (1-3 элемента, может быть пустым)\n"
        "- date → ISO 8601 строка (YYYY-MM-DD), null если неизвестно\n"
        "- checkbox → bool"
    )


async def _process_real(raw_text: str) -> ProcessedNote:
    client = _get_client()
    system_prompt = _build_system_prompt()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        response_format={"type": "json_object"},
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ],
    )
    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)

    note_type = payload.get("type") or DEFAULT_TYPE
    if note_type not in all_keys():
        logger.warning("LLM returned unknown type=%r, falling back to %s", note_type, DEFAULT_TYPE)
        note_type = DEFAULT_TYPE

    workspace = payload.get("workspace") or DEFAULT_WORKSPACE
    if workspace not in all_workspace_keys():
        logger.warning(
            "LLM returned unknown workspace=%r, falling back to %s",
            workspace,
            DEFAULT_WORKSPACE,
        )
        workspace = DEFAULT_WORKSPACE

    title = (payload.get("title") or "Без названия").strip()[:80]
    properties = payload.get("properties") or {}
    extras = payload.get("extras") or {}
    body = (payload.get("markdown_body") or "").strip() or raw_text

    # Render template here so handlers stay dumb. Keeps LLM-output and
    # template logic close together.
    from bot.domain.templates import render

    formatted = render(note_type, body, extras)

    return ProcessedNote(
        note_type=note_type,
        title=title,
        formatted=formatted,
        workspace=workspace,
        properties=properties if isinstance(properties, dict) else {},
        extras=extras if isinstance(extras, dict) else {},
    )


async def _process_stub(raw_text: str) -> ProcessedNote:
    text = raw_text.strip()
    first_line = text.split("\n", 1)[0]
    title = first_line[:80] if first_line else "Без названия"
    return ProcessedNote(
        note_type=DEFAULT_TYPE,
        title=title,
        formatted=text,
        workspace=DEFAULT_WORKSPACE,
    )


async def process(raw_text: str) -> ProcessedNote:
    if settings.openai_enabled:
        try:
            return await _process_real(raw_text)
        except Exception:
            logger.exception("OpenAI process failed, falling back to stub")
            return await _process_stub(raw_text)
    return await _process_stub(raw_text)
