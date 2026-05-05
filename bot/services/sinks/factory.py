"""Sink factory: выбор провайдера по settings.NOTES_PROVIDER."""

from __future__ import annotations

from bot.config import settings
from bot.services.sinks import Sink
from bot.services.sinks.buildin import get_sink_instance as _buildin
from bot.services.sinks.notion import get_sink_instance as _notion


def get_sink() -> Sink:
    """Вернуть актуальный sink. Перечитывает settings.NOTES_PROVIDER на каждый вызов
    (settings — singleton, переключение в рантайме = переустановить env + перезапуск)."""
    if settings.NOTES_PROVIDER == "buildin":
        return _buildin()
    return _notion()
