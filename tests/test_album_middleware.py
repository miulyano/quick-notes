"""AlbumMiddleware: агрегация Telegram-альбома (общий media_group_id)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from bot.middlewares.album import AlbumMiddleware


def _msg(media_group_id: str | None, mid: int = 1) -> MagicMock:
    m = MagicMock()
    m.media_group_id = media_group_id
    m.message_id = mid
    return m


async def test_passthrough_when_no_media_group():
    mw = AlbumMiddleware(debounce=0.05)
    seen: list = []

    async def handler(event, data):
        seen.append((event, data))
        return "ok"

    result = await mw(handler, _msg(None, mid=1), {"foo": "bar"})
    assert result == "ok"
    assert len(seen) == 1
    assert "album" not in seen[0][1]


async def test_aggregates_three_messages_one_handler_call():
    mw = AlbumMiddleware(debounce=0.05)
    seen: list = []

    async def handler(event, data):
        seen.append((event, data))

    m1 = _msg("grp-A", mid=1)
    m2 = _msg("grp-A", mid=2)
    m3 = _msg("grp-A", mid=3)

    r1 = await mw(handler, m1, {"k": "v"})
    r2 = await mw(handler, m2, {"k": "v"})
    r3 = await mw(handler, m3, {"k": "v"})
    assert r1 is None and r2 is None and r3 is None

    # Подождать дольше debounce, чтобы flush сработал.
    await asyncio.sleep(0.2)

    assert len(seen) == 1
    event, data = seen[0]
    assert event is m1  # первое сообщение группы
    album = data["album"]
    assert [m.message_id for m in album] == [1, 2, 3]


async def test_two_groups_isolated():
    mw = AlbumMiddleware(debounce=0.05)
    seen: list = []

    async def handler(event, data):
        seen.append((event.media_group_id, len(data["album"])))

    await mw(handler, _msg("A", mid=1), {})
    await mw(handler, _msg("B", mid=10), {})
    await mw(handler, _msg("A", mid=2), {})
    await mw(handler, _msg("B", mid=11), {})

    await asyncio.sleep(0.2)

    seen_sorted = sorted(seen)
    assert seen_sorted == [("A", 2), ("B", 2)]


async def test_handler_exception_swallowed_and_logged(caplog):
    mw = AlbumMiddleware(debounce=0.05)

    async def handler(_event, _data):
        raise RuntimeError("bang")

    await mw(handler, _msg("err-grp", mid=1), {})
    await asyncio.sleep(0.2)
    # Не падает наружу — иначе тест бы упал на этой же строке через task error.
    assert any("album flush handler failed" in r.message for r in caplog.records)
