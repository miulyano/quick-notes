from bot.domain.note_types import DEFAULT_TYPE, TYPES, all_keys, get


def test_default_type_is_note():
    assert DEFAULT_TYPE == "note"


def test_all_keys_match_types():
    assert all_keys() == tuple(t.key for t in TYPES)


def test_keys_are_unique():
    keys = [t.key for t in TYPES]
    assert len(keys) == len(set(keys))


def test_get_known_type():
    t = get("task")
    assert t.key == "task"
    assert t.db_env == "NOTION_DB_TASK"


def test_get_unknown_falls_back_to_default():
    t = get("nonexistent")
    assert t.key == DEFAULT_TYPE


def test_every_type_has_title_property():
    """Notion DB requires a title field. Every type config must declare one."""
    for t in TYPES:
        assert any(p.kind == "title" for p in t.properties), f"{t.key} missing title property"
