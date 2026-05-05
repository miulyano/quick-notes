"""Worker behaviour: success path + flaky save + idempotent retry."""

import asyncio

import pytest

from bot.services import notion_client
from bot.storage import drafts, idempotency, outbox
from bot.workers import outbox_worker


async def _mk(payload: str = "x") -> str:
    return await drafts.create(
        user_id=111, chat_id=1, message_id=1, kind="text", raw_payload=payload
    )


@pytest.fixture(autouse=True)
def _clear_failure_injector():
    notion_client.set_failure_injector(None)
    yield
    notion_client.set_failure_injector(None)


async def test_process_one_happy_path(fresh_db):
    draft_id = await _mk()
    await outbox.enqueue(draft_id)

    saved = []

    async def on_saved(d, page_id):
        saved.append((d.id, page_id))

    await outbox_worker.process_one(draft_id, on_saved=on_saved)

    assert await drafts.get(draft_id) is None
    assert await outbox.get_attempts(draft_id) is None
    page_id = await idempotency.get_page_id(draft_id)
    assert page_id is not None
    assert saved == [(draft_id, page_id)]


async def test_process_one_retries_then_succeeds(fresh_db):
    draft_id = await _mk()
    await outbox.enqueue(draft_id)

    fail_count = {"n": 0}

    async def flaky(_draft):
        fail_count["n"] += 1
        if fail_count["n"] < 3:
            raise RuntimeError(f"transient {fail_count['n']}")

    notion_client.set_failure_injector(flaky)

    # First two calls fail, draft stays alive.
    await outbox_worker.process_one(draft_id)
    assert (await drafts.get(draft_id)) is not None
    assert await outbox.get_attempts(draft_id) == 1

    await outbox_worker.process_one(draft_id)
    assert await outbox.get_attempts(draft_id) == 2

    # Third call: failure injector lets it through, save commits.
    await outbox_worker.process_one(draft_id)
    assert await drafts.get(draft_id) is None
    assert await idempotency.get_page_id(draft_id) is not None


async def test_process_one_uses_cached_page_id_after_crash(fresh_db):
    draft_id = await _mk()
    await outbox.enqueue(draft_id)

    # Simulate "Notion succeeded but local commit crashed" — idempotency has
    # the page_id but draft and outbox row still exist.
    await idempotency.insert(draft_id, "previously-saved-page")

    calls = []

    async def should_not_be_called(_draft):
        calls.append("notion")

    notion_client.set_failure_injector(should_not_be_called)

    saved = []

    async def on_saved(d, page_id):
        saved.append(page_id)

    await outbox_worker.process_one(draft_id, on_saved=on_saved)

    # Notion was NOT re-hit; cached page_id was used.
    assert calls == []
    assert await drafts.get(draft_id) is None
    assert await outbox.get_attempts(draft_id) is None
    assert saved == ["previously-saved-page"]


async def test_max_attempts_marks_failed(fresh_db, monkeypatch):
    draft_id = await _mk()
    await outbox.enqueue(draft_id)

    monkeypatch.setattr(outbox_worker, "MAX_ATTEMPTS", 2)

    async def always_fail(_draft):
        raise RuntimeError("nope")

    notion_client.set_failure_injector(always_fail)

    failed = []

    async def on_failed(d, err):
        failed.append((d.id, err))

    # Two failures hit the cap.
    await outbox_worker.process_one(draft_id, on_failed=on_failed)
    await outbox_worker.process_one(draft_id, on_failed=on_failed)

    d = await drafts.get(draft_id)
    assert d is not None
    assert d.status == "failed"
    assert d.error == "nope"
    assert await outbox.get_attempts(draft_id) is None
    assert failed and failed[0][0] == draft_id


async def test_run_loop_drains_queue(fresh_db):
    """Smoke test for the full run loop (one tick, then stopped)."""
    draft_id = await _mk()
    await outbox.enqueue(draft_id)

    stop = asyncio.Event()
    task = asyncio.create_task(outbox_worker.run(stop, poll_interval=0.05))
    # Give it a tick or two.
    for _ in range(20):
        if await drafts.get(draft_id) is None:
            break
        await asyncio.sleep(0.05)

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert await drafts.get(draft_id) is None
    assert await idempotency.get_page_id(draft_id) is not None
