"""Общая сборка properties-payload для Notion и Buildin sink'ов.

Notion и Buildin отличаются только wire-форматом property-значения:
- Notion:  `{"<kind>": <body>}` — ключ-как-тип.
- Buildin: `{"type": "<kind>", "<kind>": <body>}` — явный дискриминатор.

Тело (`<body>`) одинаковое: title/rich_text — массив `_rich_text(...)`,
select — `{"name": ...}` и т.д. Раньше это было продублировано в notion.py
и buildin.py — теперь один источник правды.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from typing import Any, Literal, Optional

from bot.domain.note_types import NoteType
from bot.storage.drafts import Draft

logger = logging.getLogger(__name__)

Shape = Literal["notion", "buildin"]

_DATE_IN_TITLE_RE = re.compile(r"\((\d{2})\.(\d{2})\.(\d{4})\)")


def _rich_text(value: str) -> list[dict]:
    return [{"type": "text", "text": {"content": value}}]


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _extract_date_from_title(title: Optional[str]) -> Optional[str]:
    """Найти `(DD.MM.YYYY)` в title и вернуть ISO `YYYY-MM-DD`.

    LLM по промту дописывает дату в title в формате `«Тема (DD.MM.YYYY)»`
    для meeting/1on1. Берём её как источник истины для property `Date`,
    чтобы заголовок и property не разъезжались (особенно после ручного
    редактирования title в web-editor). Невалидные даты (30.02.2026)
    отбрасываются — fallback на extracted-значение.
    """
    if not title:
        return None
    match = None
    for m in _DATE_IN_TITLE_RE.finditer(title):
        match = m  # берём последнее вхождение — по промту дата в конце
    if match is None:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return _dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def _wrap(shape: Shape, kind: str, body: dict | bool) -> dict:
    """Завернуть готовое body в нужный shape."""
    if shape == "buildin":
        return {"type": kind, kind: body}
    # notion
    return {kind: body}


def wrap_property(
    kind: str,
    value: Any,
    *,
    shape: Shape,
) -> Optional[dict]:
    """Сборка property-значения. Возвращает None — пропустить property."""
    if value is None:
        return None
    if kind == "title":
        return _wrap(shape, "title", _rich_text(str(value)))
    if kind == "rich_text":
        return _wrap(shape, "rich_text", _rich_text(str(value)))
    if kind == "select":
        return _wrap(shape, "select", {"name": str(value)})
    if kind == "multi_select":
        if not isinstance(value, list):
            value = [value]
        return _wrap(shape, "multi_select", [{"name": str(v)} for v in value if v])
    if kind == "date":
        return _wrap(shape, "date", {"start": str(value)})
    if kind == "checkbox":
        return _wrap(shape, "checkbox", bool(value))
    logger.warning("unknown property kind=%s value=%r", kind, value)
    return None


def build_properties(
    note_type: NoteType,
    draft: Draft,
    *,
    shape: Shape,
) -> dict[str, dict]:
    """Сборка properties-payload из draft.properties JSON + title fallback +
    серверный CreatedAt timestamp."""
    extracted: dict[str, Any] = {}
    if draft.properties:
        try:
            extracted = json.loads(draft.properties)
        except Exception:
            logger.warning("draft.properties not valid JSON: %r", draft.properties)
            extracted = {}

    out: dict[str, dict] = {}
    has_title = False
    title_date = _extract_date_from_title(draft.title)
    for prop in note_type.properties:
        value = extracted.get(prop.name)
        if prop.kind == "title":
            has_title = True
            # title-property всегда берём из draft.title — LLM может отдельно
            # положить «голую» тему в properties.<Name> (без даты-в-скобках,
            # которую инструктирован добавить именно в `title`). Источник
            # истины для заголовка страницы — draft.title.
            value = draft.title or "Без названия"
        elif prop.kind == "date" and prop.name == "Date" and title_date:
            # Date property синхронизируется с датой в title (meeting/1on1).
            # Иначе при редактировании title в web-editor Date уезжает.
            value = title_date
        wrapped = wrap_property(prop.kind, value, shape=shape)
        if wrapped is not None:
            out[prop.name] = wrapped

    if not has_title:
        out["Name"] = wrap_property("title", draft.title or "Без названия", shape=shape)

    out["CreatedAt"] = _wrap(shape, "date", {"start": _now_iso()})
    return out
