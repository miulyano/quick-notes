"""Workspace registry — куда (в какой Buildin space) сохранять заметку.

Каждый workspace соответствует отдельному Buildin space. Type определяет
schema/template, workspace — место. DB IDs хранятся в env как
`BUILDIN_DB_<WS>_<TYPE>` (см. config.database_id_for).

Реестр захардкожен — добавление нового workspace требует ровно 1 строки + env.
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
)


_BY_KEY: dict[str, Workspace] = {w.key: w for w in WORKSPACES}
DEFAULT_WORKSPACE = "personal"


def get(key: str) -> Workspace:
    return _BY_KEY.get(key) or _BY_KEY[DEFAULT_WORKSPACE]


def all_keys() -> tuple[str, ...]:
    return tuple(w.key for w in WORKSPACES)
