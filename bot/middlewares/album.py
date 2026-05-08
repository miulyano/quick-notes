"""Album aggregator middleware.

Telegram отправляет каждое фото из альбома (media_group) отдельным update'ом.
Чтобы handler photo.py запускался один раз на весь альбом и собирал все URL
фото в одну заметку, накапливаем сообщения с одинаковым `media_group_id` и
после `DEBOUNCE_SECS` тишины вызываем handler один раз с полным списком.

Контракт:
- сообщение без `media_group_id` → pass-through (handler вызывается сразу).
- сообщение с `media_group_id` → буферизуем; middleware возвращает None.
- через DEBOUNCE_SECS после последнего апдейта группы — handler вызывается
  один раз с `data["album"] = [Message, …]`. handler решает сам, что брать
  из `event` (первое сообщение группы) и что — из `album`.

Order'ность album в asyncio-таске сохраняем по приходу update'ов (Telegram
гарантирует chronological order для группы, но не на уровне dispatcher
по разным update'ам — на практике порядок совпадает в подавляющем
большинстве случаев; критичной семантики порядка у нас нет).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

logger = logging.getLogger(__name__)

DEBOUNCE_SECS = 1.0


class AlbumMiddleware(BaseMiddleware):
    def __init__(self, debounce: float = DEBOUNCE_SECS) -> None:
        self._debounce = debounce
        self._groups: dict[str, list[Message]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._data: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Callable[[Message, dict[str, Any]], Awaitable[Any]]] = {}
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        gid = getattr(event, "media_group_id", None)
        if not gid:
            return await handler(event, data)

        async with self._lock:
            self._groups.setdefault(gid, []).append(event)
            self._data[gid] = data
            self._handlers[gid] = handler
            prev = self._tasks.get(gid)
            if prev is not None:
                prev.cancel()
            self._tasks[gid] = asyncio.create_task(self._flush(gid))
        return None

    async def _flush(self, gid: str) -> None:
        try:
            await asyncio.sleep(self._debounce)
        except asyncio.CancelledError:
            return
        async with self._lock:
            msgs = self._groups.pop(gid, [])
            data = self._data.pop(gid, {})
            handler = self._handlers.pop(gid, None)
            self._tasks.pop(gid, None)
        if not msgs or handler is None:
            return
        try:
            await handler(msgs[0], {**data, "album": msgs})
        except Exception:
            logger.exception("album flush handler failed gid=%s size=%d", gid, len(msgs))
