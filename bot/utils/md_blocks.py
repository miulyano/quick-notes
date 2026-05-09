"""Markdown → blocks (Notion + Buildin shapes).

Block-level parser распознаёт: heading (#/##/###), bullet (`- foo`), to_do
(`- [ ] foo` / `- [x] foo`), numbered list (`1. foo`), quote (`> foo`),
fenced code (` ```lang `), paragraph.

Inline-парсер на уровне `rich_text` поддерживает (без вложенности):
  - `**bold**` → annotations.bold
  - `*italic*` / `_italic_` → annotations.italic (с word-boundary защитой,
    чтобы не ломать `snake_case` и `2*3`)
  - `` `code` `` → annotations.code
  - `[text](url)` → text.link.url
Внутри fenced code (` ``` `) inline-парсинг отключён — содержимое едет как plain.

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
_TODO_RE = re.compile(r"^\[([ xX])\]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s+(.+)$")
_CODE_FENCE_RE = re.compile(r"^```(\w*)$")


@dataclass
class ParsedBlock:
    type: str                                # paragraph | heading_1 | … | code | quote | to_do
    content: str                             # текстовое тело
    extra: dict[str, Any] = field(default_factory=dict)  # language, checked, …


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
            bullet_text = bullet.group(1)
            todo = _TODO_RE.match(bullet_text)
            if todo:
                marker, todo_text = todo.group(1), todo.group(2)
                blocks.append(
                    ParsedBlock("to_do", todo_text, {"checked": marker in "xX"})
                )
            else:
                blocks.append(ParsedBlock("bulleted_list_item", bullet_text))
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


# --- Inline parser ---------------------------------------------------------


def _is_boundary(text: str, idx: int) -> bool:
    """True если позиция вне строки или символ не alphanumeric.

    Используется для word-boundary защиты `_italic_`, чтобы не ломать
    идентификаторы вида `snake_case`.
    """
    if idx < 0 or idx >= len(text):
        return True
    return not text[idx].isalnum()


def _tokenize_inline(text: str) -> list[tuple[str, dict, str | None]]:
    """Разбить inline-текст на токены `(content, annotations, link_url)`.

    Без поддержки вложенности (`**bold _italic_**` будет bold-only). Приоритет
    маркеров: code → link → bold → italic → plain. Внутри code другие маркеры
    игнорируются.
    """
    tokens: list[tuple[str, dict, str | None]] = []
    plain_buf: list[str] = []
    i = 0
    n = len(text)

    def flush_plain() -> None:
        if plain_buf:
            tokens.append(("".join(plain_buf), {}, None))
            plain_buf.clear()

    while i < n:
        ch = text[i]

        # Code: `text`
        if ch == "`":
            end = text.find("`", i + 1)
            if end != -1 and end > i + 1:
                flush_plain()
                tokens.append((text[i + 1 : end], {"code": True}, None))
                i = end + 1
                continue

        # Link: [text](url)
        if ch == "[":
            close = text.find("]", i + 1)
            if close != -1 and close + 1 < n and text[close + 1] == "(":
                paren = text.find(")", close + 2)
                if paren != -1:
                    label = text[i + 1 : close]
                    url = text[close + 2 : paren]
                    if label and url:
                        flush_plain()
                        tokens.append((label, {}, url))
                        i = paren + 1
                        continue

        # Bold: **text**
        if ch == "*" and i + 1 < n and text[i + 1] == "*":
            end = text.find("**", i + 2)
            if end != -1 and end > i + 2:
                inner = text[i + 2 : end]
                if inner and not inner[0].isspace() and not inner[-1].isspace() and "*" not in inner:
                    flush_plain()
                    tokens.append((inner, {"bold": True}, None))
                    i = end + 2
                    continue

        # Italic: *text* (single asterisk)
        if ch == "*":
            end = text.find("*", i + 1)
            if end != -1 and end > i + 1:
                inner = text[i + 1 : end]
                if (
                    inner
                    and not inner[0].isspace()
                    and not inner[-1].isspace()
                    and "*" not in inner
                ):
                    flush_plain()
                    tokens.append((inner, {"italic": True}, None))
                    i = end + 1
                    continue

        # Italic: _text_ (word-boundary safe → не ломает snake_case)
        if ch == "_" and _is_boundary(text, i - 1):
            end = text.find("_", i + 1)
            if end != -1 and end > i + 1 and _is_boundary(text, end + 1):
                inner = text[i + 1 : end]
                if (
                    inner
                    and not inner[0].isspace()
                    and not inner[-1].isspace()
                    and "_" not in inner
                ):
                    flush_plain()
                    tokens.append((inner, {"italic": True}, None))
                    i = end + 1
                    continue

        plain_buf.append(ch)
        i += 1

    flush_plain()
    return tokens


def _chunked(content: str) -> list[str]:
    return [content[i : i + MAX_RICH_TEXT_LEN] for i in range(0, len(content), MAX_RICH_TEXT_LEN)]


def _rich_text(content: str, parse_inline: bool = True) -> list[dict]:
    """Преобразовать строку в массив rich_text объектов с inline-аннотациями.

    Длинные токены чанкуются по `MAX_RICH_TEXT_LEN` (cap Notion на rich_text
    element). При `parse_inline=False` (например, внутри code-блока) inline
    маркеры игнорируются, всё едет plain.
    """
    if not content:
        return [{"type": "text", "text": {"content": ""}}]

    if parse_inline:
        tokens = _tokenize_inline(content)
    else:
        tokens = [(content, {}, None)]

    out: list[dict] = []
    for token_text, annotations, link in tokens:
        if not token_text:
            continue
        for chunk in _chunked(token_text):
            obj: dict[str, Any] = {"type": "text", "text": {"content": chunk}}
            if link:
                obj["text"]["link"] = {"url": link}
            if annotations:
                obj["annotations"] = dict(annotations)
            out.append(obj)

    if not out:
        return [{"type": "text", "text": {"content": ""}}]
    return out


# --- Shape wrappers --------------------------------------------------------


def markdown_to_blocks(text: str) -> list[dict]:
    """Notion shape: `{object: block, type: <t>, <t>: {rich_text: [...], **extra}}`."""
    out: list[dict] = []
    for pb in parse_markdown(text):
        rich = _rich_text(pb.content, parse_inline=pb.type != "code")
        payload = {"rich_text": rich, **pb.extra}
        out.append({"object": "block", "type": pb.type, pb.type: payload})
    return out


def markdown_to_blocks_buildin(text: str) -> list[dict]:
    """Buildin shape: `{type: <t>, data: {rich_text: [...], **extra}}`.

    Отличие от Notion: контент блока всегда живёт под ключом `data`, а не под
    именем типа. Это формат `BlockData` в openapi (см. план).
    """
    out: list[dict] = []
    for pb in parse_markdown(text):
        rich = _rich_text(pb.content, parse_inline=pb.type != "code")
        data = {"rich_text": rich, **pb.extra}
        out.append({"type": pb.type, "data": data})
    return out


def image_block_notion(url: str) -> dict:
    """Image-block с external URL для Notion pages.create children."""
    return {
        "object": "block",
        "type": "image",
        "image": {"type": "external", "external": {"url": url}},
    }


def image_block_buildin(url: str) -> dict:
    """Image-block с external URL для Buildin pages.create children.

    Shape mirror'ит Notion: контент типа `image` под `data` (как у paragraph).
    """
    return {
        "type": "image",
        "data": {"type": "external", "external": {"url": url}},
    }
