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


# --- notion_token_for: per-WS токен с fallback на глобальный ---


def test_notion_token_for_uses_per_ws(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN_WORK", "work-tok")
    s = _make(NOTION_TOKEN="global-tok")
    assert s.notion_token_for("work") == "work-tok"


def test_notion_token_for_falls_back_to_global(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN_PERSONAL", raising=False)
    s = _make(NOTION_TOKEN="global-tok")
    assert s.notion_token_for("personal") == "global-tok"


def test_notion_token_for_returns_none_when_neither(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN_PERSONAL", raising=False)
    s = _make()
    assert s.notion_token_for("personal") is None


# --- notion_enabled: per-WS токенов достаточно без глобального ---


def test_notion_enabled_per_ws_token_only(monkeypatch):
    # Никаких NOTION_TOKEN, только per-WS + parent-page.
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.setenv("NOTION_TOKEN_AI_PATH", "ai-tok")
    monkeypatch.setenv("NOTION_PARENT_PAGE_AI_PATH", "page-id")
    s = _make()
    assert s.notion_enabled is True


def test_notion_enabled_false_without_any_token(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    for ws in ("PERSONAL", "WORK", "FAMILY", "GROWTH", "AI_PATH"):
        monkeypatch.delenv(f"NOTION_TOKEN_{ws}", raising=False)
    s = _make(NOTION_DATABASE_ID="db")  # есть DB, но нет токена
    assert s.notion_enabled is False


# --- NOTES_PROVIDER default ---


def test_notes_provider_defaults_to_notion(monkeypatch):
    monkeypatch.delenv("NOTES_PROVIDER", raising=False)
    s = _make()
    assert s.NOTES_PROVIDER == "notion"
