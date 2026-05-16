"""Workspace registry — пример из реф-сетапа автора. Отредактируй под свой workflow.

Это **личный пример**, а не «правильный» дефолт. Бот рассчитан на то, что
форкер заменит этот список на свой — workspace'ы захардкожены здесь, чтобы
LLM знала, куда классифицировать заметку, и чтобы скрипт setup_buildin_dbs
знал, какие DB создавать.

Каждый workspace соответствует отдельному Buildin space. Type определяет
schema/template, workspace — место. DB IDs хранятся в env как
`BUILDIN_DB_<WS>_<TYPE>` (см. config.database_id_for).

Поля Workspace:
- key:         ASCII-friendly id, попадает в env-имена и в LLM-ответ.
- label:       UI-строка (RU/EN/любой) для TG-кнопок и preview.
- description: подсказка для LLM, когда выбрать этот workspace.
- space_env:   имя env-var, в которой лежит UUID Buildin space'а.

Как адаптировать:
1. Добавить/удалить/переименовать записи в `WORKSPACES` ниже.
2. Прописать соответствующие BUILDIN_SPACE_<KEY.upper()> в `.env`.
3. Запустить `python -m scripts.setup_buildin_dbs >> .env` — создаст DB
   под обновлённый набор.
4. Адаптировать `tests/test_workspaces.py` (он проверяет конкретный набор
   ключей — это разрешённое исключение, см. CLAUDE.md).

Подробнее — раздел «Под себя» в README.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Workspace:
    key: str            # ASCII-friendly id для env-имён и LLM-ответа.
    label: str          # RU-строка для UI кнопок и preview.
    description: str    # Подсказка для LLM, когда выбрать этот workspace.
    space_env: str      # Env-имя для UUID space'а в Buildin.


WORKSPACES: tuple[Workspace, ...] = (
    Workspace(
        key="personal",
        label="Личное",
        description="Бытовое, хобби, дневник, размышления — не семья и не работа.",
        space_env="BUILDIN_SPACE_PERSONAL",
    ),
    Workspace(
        key="work",
        label="Работа",
        description="Текущий найм, проекты, коллеги, рабочие задачи и встречи.",
        space_env="BUILDIN_SPACE_WORK",
    ),
    Workspace(
        key="family",
        label="Семья",
        description="Жена/дети/родители, бытовые дела семьи, совместные планы.",
        space_env="BUILDIN_SPACE_FAMILY",
    ),
    Workspace(
        key="growth",
        label="Куда расти?",
        description="Карьерные раздумья, ориентиры, цели на год+, развитие.",
        space_env="BUILDIN_SPACE_GROWTH",
    ),
    Workspace(
        key="ai_path",
        label="Путь ИИ",
        description="AI/ML, эксперименты с ИИ, заметки по теме искусственного интеллекта.",
        space_env="BUILDIN_SPACE_AI_PATH",
    ),
    Workspace(
        key="blog",
        label="Блог",
        description="Идеи постов, черновики статей, публичные тексты и темы для блога.",
        space_env="BUILDIN_SPACE_BLOG",
    ),
)


_BY_KEY: dict[str, Workspace] = {w.key: w for w in WORKSPACES}
DEFAULT_WORKSPACE = "personal"


def get(key: str) -> Workspace:
    return _BY_KEY.get(key) or _BY_KEY[DEFAULT_WORKSPACE]


def all_keys() -> tuple[str, ...]:
    return tuple(w.key for w in WORKSPACES)
