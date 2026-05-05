"""Note type registry — single source of truth for the LLM classifier and Notion sink.

Each type defines:
- `key`         — canonical id stored in `drafts.note_type` and exchanged with the LLM.
- `label`       — human-friendly RU label shown in TG buttons.
- `description` — guidance for the LLM on when to pick this type.
- `db_env`      — env var name for the per-type Notion database id.
                  Empty / unset → falls back to `NOTION_DATABASE_ID`.
- `properties`  — list of NotionProperty objects describing what the LLM should
                  extract and how to map it onto Notion DB columns.
- `template_id` — key used by `domain.templates.render` to format the markdown body.

Adding a new type:
  1. Append a `NoteType(...)` to TYPES below.
  2. Add a matching template branch in `domain.templates`.
  3. (If multi-DB setup) create the Notion database, share with integration,
     populate `<TYPE_KEY>_DB` env var.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PropertyKind = Literal["title", "rich_text", "select", "multi_select", "date", "checkbox"]


@dataclass(frozen=True)
class NotionProperty:
    name: str               # Notion DB column name (case-sensitive).
    kind: PropertyKind
    llm_hint: str = ""      # What this property means — fed into the LLM prompt.


@dataclass(frozen=True)
class NoteType:
    key: str
    label: str
    description: str
    db_env: str
    template_id: str
    properties: tuple[NotionProperty, ...] = field(default_factory=tuple)


TYPES: tuple[NoteType, ...] = (
    NoteType(
        key="note",
        label="📝 Заметка",
        description=(
            "Свободная заметка / запись. Используй когда нет более подходящего типа. "
            "Дефолтный fallback."
        ),
        db_env="NOTION_DB_NOTE",
        template_id="note",
        properties=(
            NotionProperty("Name", "title", "Краткий заголовок одной строкой."),
            NotionProperty(
                "Tags",
                "multi_select",
                "1-3 коротких тега по теме (ru), без хэштегов. Может быть пустым.",
            ),
        ),
    ),
    NoteType(
        key="task",
        label="✅ Задача",
        description=(
            "Что-то нужно сделать. Включает дедлайны, действия, обязательства. "
            "Признаки: 'надо', 'сделать', 'до пятницы', 'не забыть', чек-лист."
        ),
        db_env="NOTION_DB_TASK",
        template_id="task",
        properties=(
            NotionProperty("Name", "title", "Императив: что сделать (1 строка)."),
            NotionProperty(
                "Status",
                "select",
                "Одно из: Todo, In Progress, Done. По умолчанию Todo.",
            ),
            NotionProperty(
                "Priority",
                "select",
                "Одно из: Low, Medium, High. Если не ясно — Medium.",
            ),
            NotionProperty(
                "DueDate",
                "date",
                "ISO-дата дедлайна, если упомянут. Иначе пусто.",
            ),
        ),
    ),
    NoteType(
        key="idea",
        label="💡 Идея",
        description=(
            "Гипотеза, замысел, предположение, фича на потом. Не задача (без обязательства)."
        ),
        db_env="NOTION_DB_IDEA",
        template_id="idea",
        properties=(
            NotionProperty("Name", "title", "Суть идеи одной строкой."),
            NotionProperty(
                "Tags",
                "multi_select",
                "1-3 тега по области (например: bot, notion, ux).",
            ),
        ),
    ),
    NoteType(
        key="meeting",
        label="🤝 Митинг",
        description=(
            "Заметки со встречи / звонка с несколькими участниками. Признаки: упомянуты "
            "имена нескольких людей, обсуждение, agenda, decisions."
        ),
        db_env="NOTION_DB_MEETING",
        template_id="meeting",
        properties=(
            NotionProperty("Name", "title", "Тема встречи."),
            NotionProperty(
                "Attendees",
                "multi_select",
                "Список имён участников встречи (как в тексте).",
            ),
            NotionProperty(
                "Date",
                "date",
                "ISO-дата встречи если ясна, иначе сегодня.",
            ),
        ),
    ),
    NoteType(
        key="1on1",
        label="👥 1:1",
        description=(
            "Личная встреча 1-на-1 с конкретным человеком (типично сотрудник/менеджер). "
            "Один основной собеседник."
        ),
        db_env="NOTION_DB_1ON1",
        template_id="1on1",
        properties=(
            NotionProperty("Name", "title", "Имя собеседника или короткий subject."),
            NotionProperty(
                "With",
                "rich_text",
                "Имя человека с которым 1:1.",
            ),
            NotionProperty(
                "Date",
                "date",
                "ISO-дата встречи если ясна, иначе сегодня.",
            ),
        ),
    ),
    NoteType(
        key="work",
        label="💼 Рабочее",
        description=(
            "Рабочая заметка не подходящая под task/meeting/1on1: контекст проекта, "
            "статус, инсайт по работе."
        ),
        db_env="NOTION_DB_WORK",
        template_id="default",
        properties=(
            NotionProperty("Name", "title", "Краткий заголовок."),
            NotionProperty(
                "Tags",
                "multi_select",
                "1-3 рабочих тега (например: project, team).",
            ),
        ),
    ),
    NoteType(
        key="personal",
        label="🌱 Личное",
        description=(
            "Личная заметка: здоровье, семья, мысли, дневник, планы вне работы."
        ),
        db_env="NOTION_DB_PERSONAL",
        template_id="default",
        properties=(
            NotionProperty("Name", "title", "Краткий заголовок."),
            NotionProperty(
                "Tags",
                "multi_select",
                "1-3 личных тега (например: family, health).",
            ),
        ),
    ),
)


_BY_KEY: dict[str, NoteType] = {t.key: t for t in TYPES}
DEFAULT_TYPE = "note"


def get(key: str) -> NoteType:
    return _BY_KEY.get(key) or _BY_KEY[DEFAULT_TYPE]


def all_keys() -> tuple[str, ...]:
    return tuple(t.key for t in TYPES)
