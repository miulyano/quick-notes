"""Markdown → blocks (Notion + Buildin shapes).

Парсер dumb по дизайну: heading (#/##/###), bullet/numbered lists, quote,
code fences, paragraph. Inline markdown (bold/italic/links) НЕ парсится — текст
едет как plain rich_text. Если потребуется — менять отдельным PR с реальной
md-библиотекой.

Internal pipeline:
  raw markdown → parse_markdown() → list[ParsedBlock]  ── общий парсер
                                          │
                                          ├─ markdown_to_blocks() → Notion shape
                                          └─ markdown_to_blocks_buildin() → Buildin shape
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Лимит длины content в одном rich_text элементе. У Notion явный hard cap 2000;
# Buildin лимит в openapi не указан — оставляем то же, безопасно.
MAX_RICH_TEXT_LEN = 2000

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s+(.+)$")
_CODE_FENCE_RE = re.compile(r"^```(\w*)$")


@dataclass
class ParsedBlock:
    type: str                                # paragraph | heading_1 | … | code | quote
    content: str                             # текстовое тело
    extra: dict[str, Any] = field(default_factory=dict)  # language, …


def parse_markdown(text: str) -> list[ParsedBlock]:
    """Provider-neutral markdown parser. Возвращает список ParsedBlock.

    Не делает предположений о shape целевого блока (Notion/Buildin) — это
    задача обёрток ниже.
    """
    lines = text.split("\n")
    blocks: list[ParsedBlock] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        joined = "\n".join(paragraph).strip()
        if joined:
            blocks.append(ParsedBlock("paragraph", joined))
        paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        fence = _CODE_FENCE_RE.match(stripped)
        if fence:
            flush_paragraph()
            language = fence.group(1) or "plain text"
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not _CODE_FENCE_RE.match(lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            blocks.append(ParsedBlock("code", "\n".join(code_lines), {"language": language}))
            i += 1  # skip closing fence
            continue

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        h = _HEADING_RE.match(stripped)
        if h:
            flush_paragraph()
            level = len(h.group(1))
            block_type = {1: "heading_1", 2: "heading_2", 3: "heading_3"}[level]
            blocks.append(ParsedBlock(block_type, h.group(2)))
            i += 1
            continue

        bullet = _BULLET_RE.match(stripped)
        if bullet:
            flush_paragraph()
            blocks.append(ParsedBlock("bulleted_list_item", bullet.group(1)))
            i += 1
            continue

        numbered = _NUMBERED_RE.match(stripped)
        if numbered:
            flush_paragraph()
            blocks.append(ParsedBlock("numbered_list_item", numbered.group(1)))
            i += 1
            continue

        quote = _QUOTE_RE.match(stripped)
        if quote:
            flush_paragraph()
            blocks.append(ParsedBlock("quote", quote.group(1)))
            i += 1
            continue

        paragraph.append(line)
        i += 1

    flush_paragraph()
    return blocks


def _rich_text(content: str) -> list[dict]:
    """Сплит длинного content на чанки по MAX_RICH_TEXT_LEN."""
    if not content:
        return [{"type": "text", "text": {"content": ""}}]
    return [
        {"type": "text", "text": {"content": content[i : i + MAX_RICH_TEXT_LEN]}}
        for i in range(0, len(content), MAX_RICH_TEXT_LEN)
    ]


def markdown_to_blocks(text: str) -> list[dict]:
    """Notion shape: `{object: block, type: <t>, <t>: {rich_text: [...], **extra}}`."""
    out: list[dict] = []
    for pb in parse_markdown(text):
        payload = {"rich_text": _rich_text(pb.content), **pb.extra}
        out.append({"object": "block", "type": pb.type, pb.type: payload})
    return out


def markdown_to_blocks_buildin(text: str) -> list[dict]:
    """Buildin shape: `{type: <t>, data: {rich_text: [...], **extra}}`.

    Отличие от Notion: контент блока всегда живёт под ключом `data`, а не под
    именем типа. Это формат `BlockData` в openapi (см. план).
    """
    out: list[dict] = []
    for pb in parse_markdown(text):
        data = {"rich_text": _rich_text(pb.content), **pb.extra}
        out.append({"type": pb.type, "data": data})
    return out
