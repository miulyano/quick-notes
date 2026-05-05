from bot.storage import idempotency


async def test_insert_and_get(fresh_db):
    await idempotency.insert("draft-1", "page-abc")
    assert await idempotency.get_page_id("draft-1") == "page-abc"


async def test_get_unknown_returns_none(fresh_db):
    assert await idempotency.get_page_id("nope") is None


async def test_insert_is_idempotent(fresh_db):
    await idempotency.insert("draft-1", "page-abc")
    # Second insert with different page_id is a no-op (ON CONFLICT DO NOTHING).
    await idempotency.insert("draft-1", "page-xyz")
    assert await idempotency.get_page_id("draft-1") == "page-abc"
