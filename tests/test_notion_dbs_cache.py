"""bot/storage/notion_dbs: get/put/all_entries поверх SQLite."""

import pytest

from bot.storage import notion_dbs


@pytest.mark.asyncio
async def test_get_returns_none_when_empty(fresh_db):
    assert await notion_dbs.get("personal", "task") is None


@pytest.mark.asyncio
async def test_put_then_get_roundtrip(fresh_db):
    await notion_dbs.put("personal", "task", "db-uuid-1")
    assert await notion_dbs.get("personal", "task") == "db-uuid-1"


@pytest.mark.asyncio
async def test_put_replaces_existing(fresh_db):
    await notion_dbs.put("work", "meeting", "old")
    await notion_dbs.put("work", "meeting", "new")
    assert await notion_dbs.get("work", "meeting") == "new"


@pytest.mark.asyncio
async def test_separate_keys_dont_collide(fresh_db):
    await notion_dbs.put("personal", "task", "p-task")
    await notion_dbs.put("work", "task", "w-task")
    await notion_dbs.put("personal", "note", "p-note")

    assert await notion_dbs.get("personal", "task") == "p-task"
    assert await notion_dbs.get("work", "task") == "w-task"
    assert await notion_dbs.get("personal", "note") == "p-note"


@pytest.mark.asyncio
async def test_all_entries_lists_all_rows(fresh_db):
    await notion_dbs.put("personal", "task", "p-task")
    await notion_dbs.put("work", "task", "w-task")

    rows = await notion_dbs.all_entries()
    keys = {(r["workspace"], r["note_type"]) for r in rows}
    assert keys == {("personal", "task"), ("work", "task")}
    assert all("database_id" in r and "created_at" in r for r in rows)
