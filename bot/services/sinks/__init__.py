"""Sink-абстракция: куда сохранять заметки.

Sink — провайдер хранилища заметок (Notion, Buildin, …). Реализации лежат в
`bot/services/sinks/notion.py` и `bot/services/sinks/buildin.py`. Выбор
провайдера в рантайме — `factory.get_sink()` (читает settings.NOTES_PROVIDER).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol

from bot.storage.drafts import Draft

FailureInjector = Callable[[Draft], Awaitable[None]]


@dataclass(frozen=True)
class PageRef:
    """Ссылка на созданную страницу: id (для idempotency) + url (для UI)."""

    id: str
    url: Optional[str] = None


class Sink(Protocol):
    """Интерфейс провайдера хранилища заметок."""

    async def create_page(self, draft: Draft) -> PageRef:
        """Создать страницу в провайдере. Возвращает PageRef(id, url)."""
        ...

    def set_failure_injector(self, fn: Optional[FailureInjector]) -> None:
        """Test hook: инжектить ошибку перед вызовом create_page."""
        ...
