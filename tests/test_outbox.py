import time

from bot.storage import drafts, outbox


async def _mk_draft() -> str:
    return await drafts.create(
        user_id=111, chat_id=1, message_id=1, kind="text", raw_payload="x"
    )


async def test_enqueue_and_claim_due(fresh_db):
    draft_id = await _mk_draft()
    await outbox.enqueue(draft_id)
    due = await outbox.claim_due()
    assert due == [draft_id]


async def test_claim_due_skips_future(fresh_db):
    draft_id = await _mk_draft()
    await outbox.enqueue(draft_id, run_at=int(time.time()) + 3600)
    due = await outbox.claim_due()
    assert due == []


async def test_mark_failed_grows_backoff(fresh_db):
    draft_id = await _mk_draft()
    await outbox.enqueue(draft_id)
    a1 = await outbox.mark_failed(draft_id, "boom")
    a2 = await outbox.mark_failed(draft_id, "boom2")
    a3 = await outbox.mark_failed(draft_id, "boom3")
    assert (a1, a2, a3) == (1, 2, 3)
    # After failure, claim_due should not pick it up immediately.
    due_now = await outbox.claim_due(now=int(time.time()))
    assert due_now == []


async def test_delete_outbox_entry(fresh_db):
    draft_id = await _mk_draft()
    await outbox.enqueue(draft_id)
    await outbox.delete(draft_id)
    assert await outbox.get_attempts(draft_id) is None


async def test_enqueue_resets_attempts(fresh_db):
    draft_id = await _mk_draft()
    await outbox.enqueue(draft_id)
    await outbox.mark_failed(draft_id, "e")
    assert await outbox.get_attempts(draft_id) == 1
    await outbox.enqueue(draft_id)
    assert await outbox.get_attempts(draft_id) == 0
