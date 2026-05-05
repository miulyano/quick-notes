"""Background worker that drains the outbox into Notion.

Runs as an asyncio task. Single-consumer by design — there is one bot process,
so we don't need row-level locking. On each tick:

1. claim_due → list of draft_ids ready to retry
2. for each: check idempotency (already saved? skip Notion call), else
   notion.create_page → commit_save (atomic insert+delete) → fire ack callback
3. on error: outbox.mark_failed (attempts++, expo backoff), at max_attempts mark
   draft as failed so user sees it in /list

The worker doesn't know about Telegram. main.py wires `on_saved`/`on_failed`
callbacks that hold a Bot reference and edit the preview message.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from bot.services.sinks.factory import get_sink
from bot.storage import drafts, idempotency, outbox, save_tx
from bot.storage.drafts import Draft

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECS = 2.0
MAX_ATTEMPTS = 8

OnSaved = Callable[[Draft, str], Awaitable[None]]
OnFailed = Callable[[Draft, str], Awaitable[None]]


async def process_one(
    draft_id: str,
    *,
    on_saved: Optional[OnSaved] = None,
    on_failed: Optional[OnFailed] = None,
) -> None:
    cached = await idempotency.get_page_id(draft_id)
    draft = await drafts.get(draft_id)
    if cached is not None:
        # Recovered after crash between Notion-success and local commit.
        # No second API call — just finish the local cleanup.
        await save_tx.commit_save(draft_id, cached)
        if draft is not None and on_saved is not None:
            await on_saved(draft, cached)
        return

    if draft is None:
        # Draft was cancelled while sitting in outbox. Drop the queue entry.
        await outbox.delete(draft_id)
        return

    try:
        page_id = await get_sink().create_page(draft)
    except Exception as exc:
        attempts = await outbox.mark_failed(draft_id, str(exc))
        logger.warning("outbox save failed draft=%s attempt=%d err=%s", draft_id, attempts, exc)
        if attempts >= MAX_ATTEMPTS:
            await drafts.update(draft_id, status="failed", error=str(exc))
            await outbox.delete(draft_id)
            if on_failed is not None:
                await on_failed(draft, str(exc))
        return

    await save_tx.commit_save(draft_id, page_id)
    if on_saved is not None:
        await on_saved(draft, page_id)


async def run(
    stop_event: asyncio.Event,
    *,
    on_saved: Optional[OnSaved] = None,
    on_failed: Optional[OnFailed] = None,
    poll_interval: float = POLL_INTERVAL_SECS,
) -> None:
    logger.info("outbox worker started")
    while not stop_event.is_set():
        try:
            due = await outbox.claim_due()
        except Exception:
            logger.exception("outbox.claim_due failed")
            due = []
        for draft_id in due:
            if stop_event.is_set():
                break
            try:
                await process_one(draft_id, on_saved=on_saved, on_failed=on_failed)
            except Exception:
                logger.exception("process_one crashed draft=%s", draft_id)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass
    logger.info("outbox worker stopped")
