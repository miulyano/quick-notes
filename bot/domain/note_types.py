"""Note type registry — пример из реф-сетапа автора. Отредактируй под свой workflow.

Это **личный пример** того, как один человек разложил свой поток заметок:
свободные note, задачи, идеи, митинги, 1:1, рабочее/личное. Бот рассчитан
на то, что форкер заменит набор на свой — типы захардкожены здесь, чтобы
LLM знала, во что классифицировать, и чтобы setup_buildin_dbs знал, какие
DB и с какими колонками создавать.

NoteType описывает один тип заметки:
- `key`         — canonical id в `drafts.note_type` и в LLM-ответе.
- `label`       — UI-строка для TG-кнопок (RU/EN/любой).
- `description` — подсказка для LLM, когда выбрать этот тип.
- `db_env`      — имя env-переменной для per-type Notion DB id (например
                  `NOTION_DB_TASK`). Пусто/unset → fallback на
                  `NOTION_DATABASE_ID`. Для Buildin берётся суффикс
                  (`NOTION_DB_TASK` → `BUILDIN_DB_<WS>_TASK`).
- `template_id` — ключ ветки в `domain.templates.render`.
- `properties`  — список колонок DB и hint'ов, что LLM туда кладёт.

NotionProperty:
- `name`           — case-sensitive имя колонки DB. Используется и при
                     записи в Buildin/Notion, и при автосоздании DB
                     setup-скриптом.
- `kind`           — title | rich_text | select | multi_select | date | checkbox.
- `llm_hint`       — что LLM кладёт в это поле (попадает в prompt).
- `select_options` — для kind=select|multi_select фиксированный список
                     значений; setup_buildin_dbs использует его для
                     PropertySchemaSelect.options. Бот всегда дописывает
                     колонку `CreatedAt` (date) — её не нужно объявлять здесь.

Как адаптировать:
  1. Добавить/удалить/переименовать `NoteType(...)` в `TYPES`.
  2. Если меняется `template_id` — добавить ветку в `domain.templates`.
  3. Если меняется список properties — пересоздать DB через
     `python -m scripts.setup_buildin_dbs` (или вручную для Notion и положить
     id в `NOTION_DB_<TYPE>` / `BUILDIN_DB_<WS>_<TYPE>`).
  4. Адаптировать `tests/test_note_types.py` и (при изменении templates)
     `tests/test_templates.py` — это разрешённое исключение (см. CLAUDE.md).

Подробнее — раздел «Под себя» в README.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PropertyKind = Literal["title", "rich_text", "select", "multi_select", "date", "checkbox"]


@dataclass(frozen=True)
class NotionProperty:
    name: str               # DB column name (case-sensitive). Применимо и к Notion, и к Buildin.
    kind: PropertyKind
    llm_hint: str = ""      # What this property means — fed into the LLM prompt.
    select_options: tuple[str, ...] = ()  # Для kind=select/multi_select — фиксированный список опций
                                          # (используется setup_buildin_dbs для PropertySchemaSelect.options).


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
                select_options=("Todo", "In Progress", "Done"),
            ),
            NotionProperty(
                "Priority",
                "select",
                "Одно из: Low, Medium, High. Если не ясно — Medium.",
                select_options=("Low", "Medium", "High"),
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
    NoteType(
        key="book",
        label="📚 Книга",
        description=(
            "Заметка о книге: впечатления, конспект, выписки, обзор. "
            "Признаки: название книги + автор, упоминание чтения, "
            "цитат, рекомендаций."
        ),
        db_env="NOTION_DB_BOOK",
        template_id="default",
        properties=(
            NotionProperty("Name", "title", "Название книги."),
            NotionProperty(
                "Author",
                "rich_text",
                "Имя автора книги (одно или несколько через запятую).",
            ),
            NotionProperty(
                "Rating",
                "select",
                "Оценка от 1 до 10 звёзд: ⭐ (1) … ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐ (10). "
                "Если оценка не упомянута — пусто.",
                select_options=(
                    "⭐",
                    "⭐⭐",
                    "⭐⭐⭐",
                    "⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐",
                ),
            ),
        ),
    ),
    NoteType(
        key="film",
        label="🎥 Фильм",
        description=(
            "Заметка о фильме / сериале: впечатления, рецензия, разбор. "
            "Признаки: название фильма + режиссёр или год выхода, "
            "упоминание просмотра, актёров, сцен, оценки."
        ),
        db_env="NOTION_DB_FILM",
        template_id="default",
        properties=(
            NotionProperty("Name", "title", "Название фильма."),
            NotionProperty(
                "Director",
                "rich_text",
                "Имя режиссёра (одного или нескольких через запятую). "
                "Может быть пустым.",
            ),
            NotionProperty(
                "Year",
                "rich_text",
                "Год выхода фильма (4 цифры, например '1999'). Может быть пустым.",
            ),
            NotionProperty(
                "Genre",
                "multi_select",
                "1-3 жанра (ru или en, например: drama, comedy, sci-fi). "
                "Может быть пустым.",
            ),
            NotionProperty(
                "Rating",
                "select",
                "Оценка от 1 до 10 звёзд: ⭐ (1) … ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐ (10). "
                "Если оценка не упомянута — пусто.",
                select_options=(
                    "⭐",
                    "⭐⭐",
                    "⭐⭐⭐",
                    "⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐⭐⭐⭐",
                    "⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐",
                ),
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
