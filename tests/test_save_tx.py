from bot.storage import drafts, idempotency, outbox, save_tx


async def test_commit_save_clears_draft_and_outbox(fresh_db):
    draft_id = await drafts.create(
        user_id=111, chat_id=1, message_id=1, kind="text", raw_payload="x"
    )
    await outbox.enqueue(draft_id)

    await save_tx.commit_save(draft_id, "page-1")

    assert await drafts.get(draft_id) is None
    assert await outbox.get_attempts(draft_id) is None
    assert await idempotency.get_page_id(draft_id) == "page-1"


async def test_commit_save_idempotent(fresh_db):
    draft_id = await drafts.create(
        user_id=111, chat_id=1, message_id=1, kind="text", raw_payload="x"
    )
    await outbox.enqueue(draft_id)

    await save_tx.commit_save(draft_id, "page-1")
    # Second call (e.g. retry after partial crash) — must not change page_id.
    await save_tx.commit_save(draft_id, "page-2")
    assert await idempotency.get_page_id(draft_id) == "page-1"
