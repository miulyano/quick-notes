"""Markdown → Notion blocks. Just enough for MVP note formatting.

Supports: headings (#, ##, ###), bullet lists (-, *), numbered lists (1.),
quotes (>), code fences (```), paragraphs. Inline markdown (bold/italic/links)
is NOT parsed — content is shipped as plain rich_text. Keep this file dumb on
purpose; if we need rich inline rendering later, swap in a real markdown lib.
"""

from __future__ import annotations

import re

# Notion's hard limit on rich_text element content. Long paragraphs are split
# into multiple rich_text elements inside the same block.
MAX_RICH_TEXT_LEN = 2000

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s+(.+)$")
_CODE_FENCE_RE = re.compile(r"^```(\w*)$")


def _rich_text(content: str) -> list[dict]:
    """Split content into Notion-compliant rich_text chunks."""
    if not content:
        return [{"type": "text", "text": {"content": ""}}]
    return [
        {"type": "text", "text": {"content": content[i : i + MAX_RICH_TEXT_LEN]}}
        for i in range(0, len(content), MAX_RICH_TEXT_LEN)
    ]


def _block(block_type: str, content: str, **extra: dict) -> dict:
    payload = {"rich_text": _rich_text(content)}
    payload.update(extra)
    return {"object": "block", "type": block_type, block_type: payload}


def markdown_to_blocks(text: str) -> list[dict]:
    """Convert markdown into a list of Notion block payloads."""
    lines = text.split("\n")
    blocks: list[dict] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        joined = "\n".join(paragraph).strip()
        if joined:
            blocks.append(_block("paragraph", joined))
        paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Code fence (multi-line).
        fence = _CODE_FENCE_RE.match(stripped)
        if fence:
            flush_paragraph()
            language = fence.group(1) or "plain text"
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not _CODE_FENCE_RE.match(lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            blocks.append(_block("code", "\n".join(code_lines), language=language))
            i += 1  # skip closing fence
            continue

        # Blank line — paragraph boundary.
        if not stripped:
            flush_paragraph()
            i += 1
            continue

        # Heading.
        h = _HEADING_RE.match(stripped)
        if h:
            flush_paragraph()
            level = len(h.group(1))
            block_type = {1: "heading_1", 2: "heading_2", 3: "heading_3"}[level]
            blocks.append(_block(block_type, h.group(2)))
            i += 1
            continue

        # Bulleted list item.
        bullet = _BULLET_RE.match(stripped)
        if bullet:
            flush_paragraph()
            blocks.append(_block("bulleted_list_item", bullet.group(1)))
            i += 1
            continue

        # Numbered list item.
        numbered = _NUMBERED_RE.match(stripped)
        if numbered:
            flush_paragraph()
            blocks.append(_block("numbered_list_item", numbered.group(1)))
            i += 1
            continue

        # Quote.
        quote = _QUOTE_RE.match(stripped)
        if quote:
            flush_paragraph()
            blocks.append(_block("quote", quote.group(1)))
            i += 1
            continue

        paragraph.append(line)
        i += 1

    flush_paragraph()
    return blocks
