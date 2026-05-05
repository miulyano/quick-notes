"""Notion sink (stub for Increment 1).

Increment 2 swaps `create_page` for a real notion-client call. Failure-injection
hook lives here so tests/integration can simulate flaky Notion without
monkeypatching internals.
"""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable, Optional

from bot.storage.drafts import Draft

logger = logging.getLogger(__name__)

# Failure injector for tests/dev. Set to a callable that may raise to simulate
# transient errors. Production: leave None.
FailureInjector = Callable[[Draft], Awaitable[None]]
_failure_injector: Optional[FailureInjector] = None


def set_failure_injector(fn: Optional[FailureInjector]) -> None:
    global _failure_injector
    _failure_injector = fn


async def create_page(draft: Draft) -> str:
    """Stub: log and return a fake page id. Real Notion call in Increment 2."""
    if _failure_injector is not None:
        await _failure_injector(draft)
    page_id = f"stub-page-{uuid.uuid4().hex[:8]}"
    logger.info(
        "STUB notion.create_page draft_id=%s type=%s title=%r body_len=%d page_id=%s",
        draft.id,
        draft.note_type,
        draft.title,
        len(draft.formatted or ""),
        page_id,
    )
    return page_id
