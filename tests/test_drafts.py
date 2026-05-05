from bot.storage import drafts


async def test_create_then_get(fresh_db):
    draft_id = await drafts.create(
        user_id=111, chat_id=999, message_id=42, kind="text", raw_payload="hello"
    )
    d = await drafts.get(draft_id)
    assert d is not None
    assert d.user_id == 111
    assert d.chat_id == 999
    assert d.message_id == 42
    assert d.kind == "text"
    assert d.raw_payload == "hello"
    assert d.status == "raw"
    assert d.created_at > 0


async def test_update_fields(fresh_db):
    draft_id = await drafts.create(
        user_id=111, chat_id=999, message_id=1, kind="text", raw_payload="x"
    )
    await drafts.update(draft_id, status="awaiting_confirm", title="t", formatted="f")
    d = await drafts.get(draft_id)
    assert d.status == "awaiting_confirm"
    assert d.title == "t"
    assert d.formatted == "f"


async def test_delete(fresh_db):
    draft_id = await drafts.create(
        user_id=111, chat_id=999, message_id=1, kind="text", raw_payload="x"
    )
    await drafts.delete(draft_id)
    assert await drafts.get(draft_id) is None


async def test_list_for_user(fresh_db):
    a = await drafts.create(user_id=111, chat_id=1, message_id=1, kind="text", raw_payload="a")
    b = await drafts.create(user_id=111, chat_id=1, message_id=2, kind="text", raw_payload="b")
    await drafts.create(user_id=222, chat_id=2, message_id=3, kind="text", raw_payload="c")
    items = await drafts.list_for_user(111)
    ids = {d.id for d in items}
    assert ids == {a, b}


async def test_find_stale_saving(fresh_db):
    import time
    from bot.storage.db import get_conn

    draft_id = await drafts.create(
        user_id=111, chat_id=1, message_id=1, kind="text", raw_payload="x"
    )
    # Push updated_at into the past so threshold matches.
    past = int(time.time()) - 10_000
    conn = get_conn()
    await conn.execute(
        "UPDATE drafts SET status = 'saving', updated_at = ? WHERE id = ?",
        (past, draft_id),
    )
    await conn.commit()

    stale = await drafts.find_stale_saving(older_than_secs=300)
    assert {d.id for d in stale} == {draft_id}

    # Recent saving — not stale.
    fresh_id = await drafts.create(
        user_id=111, chat_id=1, message_id=2, kind="text", raw_payload="y"
    )
    await drafts.update(fresh_id, status="saving")
    stale_again = await drafts.find_stale_saving(older_than_secs=300)
    assert {d.id for d in stale_again} == {draft_id}
