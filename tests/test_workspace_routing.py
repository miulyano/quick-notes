"""settings.database_id_for: приоритет per-(ws,type) → per-type → default."""

import pytest

from bot.config import settings


@pytest.fixture(autouse=True)
def _clear_buildin_envs(monkeypatch):
    for key in (
        "BUILDIN_DB_WORK_TASK",
        "BUILDIN_DB_PERSONAL_TASK",
        "BUILDIN_DB_TASK",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("bot.config.settings.BUILDIN_DB_DEFAULT", None)


def test_per_workspace_per_type_wins(monkeypatch):
    monkeypatch.setenv("BUILDIN_DB_WORK_TASK", "ws-task-uuid")
    monkeypatch.setenv("BUILDIN_DB_TASK", "type-task-uuid")
    monkeypatch.setattr("bot.config.settings.BUILDIN_DB_DEFAULT", "default-uuid")

    got = settings.database_id_for("NOTION_DB_TASK", provider="buildin", workspace_key="work")
    assert got == "ws-task-uuid"


def test_per_type_fallback_when_no_workspace_match(monkeypatch):
    monkeypatch.setenv("BUILDIN_DB_TASK", "type-task-uuid")
    monkeypatch.setattr("bot.config.settings.BUILDIN_DB_DEFAULT", "default-uuid")

    got = settings.database_id_for("NOTION_DB_TASK", provider="buildin", workspace_key="personal")
    assert got == "type-task-uuid"


def test_default_when_neither(monkeypatch):
    monkeypatch.setattr("bot.config.settings.BUILDIN_DB_DEFAULT", "default-uuid")

    got = settings.database_id_for("NOTION_DB_TASK", provider="buildin", workspace_key="work")
    assert got == "default-uuid"


def test_returns_none_when_unconfigured():
    got = settings.database_id_for("NOTION_DB_TASK", provider="buildin", workspace_key="work")
    assert got is None


def test_notion_provider_ignores_workspace(monkeypatch):
    monkeypatch.setattr("bot.config.settings.NOTION_DB_TASK", "notion-task-uuid")
    monkeypatch.setattr("bot.config.settings.NOTION_DATABASE_ID", "notion-default")
    got = settings.database_id_for("NOTION_DB_TASK", provider="notion", workspace_key="work")
    assert got == "notion-task-uuid"


def test_notion_falls_back_to_default_db_id(monkeypatch):
    monkeypatch.setattr("bot.config.settings.NOTION_DB_TASK", None)
    monkeypatch.setattr("bot.config.settings.NOTION_DATABASE_ID", "notion-default")
    got = settings.database_id_for("NOTION_DB_TASK", provider="notion")
    assert got == "notion-default"
