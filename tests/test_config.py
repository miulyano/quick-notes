from bot.config import Settings


def _make(user_ids: str = "111", **overrides) -> Settings:
    return Settings(
        BOT_TOKEN="t",
        ALLOWED_USER_IDS=user_ids,
        **overrides,
    )


def test_multiple_user_ids():
    assert _make("111,222,333").allowed_user_ids == [111, 222, 333]


def test_single_user_id():
    assert _make("555").allowed_user_ids == [555]


def test_user_ids_with_spaces():
    assert _make("111, 222 , 333").allowed_user_ids == [111, 222, 333]


def test_empty_entries_skipped():
    assert _make("111,,222").allowed_user_ids == [111, 222]


def test_trailing_comma_skipped():
    assert _make("111,222,").allowed_user_ids == [111, 222]


def test_default_database_path():
    s = _make("111")
    assert s.DATABASE_PATH == "data/notes.db"


# --- database_id_for: Notion provider ---


def test_database_id_notion_per_type_takes_priority():
    s = _make(
        NOTES_PROVIDER="notion",
        NOTION_TOKEN="t",
        NOTION_DATABASE_ID="default-db",
        NOTION_DB_TASK="task-db",
    )
    assert s.database_id_for("NOTION_DB_TASK", provider="notion") == "task-db"


def test_database_id_notion_falls_back_to_default():
    s = _make(
        NOTES_PROVIDER="notion",
        NOTION_TOKEN="t",
        NOTION_DATABASE_ID="default-db",
    )
    assert s.database_id_for("NOTION_DB_TASK", provider="notion") == "default-db"


def test_database_id_notion_returns_none_when_no_default():
    s = _make(NOTES_PROVIDER="notion", NOTION_TOKEN="t")
    assert s.database_id_for("NOTION_DB_TASK", provider="notion") is None


# --- database_id_for: Buildin provider ---


def test_database_id_buildin_workspace_specific(monkeypatch):
    monkeypatch.setenv("BUILDIN_DB_WORK_TASK", "ws-task-db")
    s = _make(BUILDIN_TOKEN="t", BUILDIN_DB_DEFAULT="default")
    assert (
        s.database_id_for("NOTION_DB_TASK", provider="buildin", workspace_key="work")
        == "ws-task-db"
    )


def test_database_id_buildin_falls_back_to_type_only(monkeypatch):
    monkeypatch.delenv("BUILDIN_DB_WORK_TASK", raising=False)
    monkeypatch.setenv("BUILDIN_DB_TASK", "type-task-db")
    s = _make(BUILDIN_TOKEN="t", BUILDIN_DB_DEFAULT="default")
    assert (
        s.database_id_for("NOTION_DB_TASK", provider="buildin", workspace_key="work")
        == "type-task-db"
    )


def test_database_id_buildin_falls_back_to_default(monkeypatch):
    for k in ("BUILDIN_DB_WORK_TASK", "BUILDIN_DB_TASK"):
        monkeypatch.delenv(k, raising=False)
    s = _make(BUILDIN_TOKEN="t", BUILDIN_DB_DEFAULT="default-db")
    assert (
        s.database_id_for("NOTION_DB_TASK", provider="buildin", workspace_key="work")
        == "default-db"
    )


def test_database_id_buildin_returns_none_when_unconfigured(monkeypatch):
    for k in ("BUILDIN_DB_WORK_TASK", "BUILDIN_DB_TASK"):
        monkeypatch.delenv(k, raising=False)
    s = _make(BUILDIN_TOKEN="t")  # no BUILDIN_DB_DEFAULT
    assert (
        s.database_id_for("NOTION_DB_TASK", provider="buildin", workspace_key="work")
        is None
    )
