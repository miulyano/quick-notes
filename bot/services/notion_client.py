"""Compat-shim: реальная реализация переехала в bot/services/sinks/notion.py.

Этот модуль остаётся точкой входа для существующих тестов и потенциальных
сторонних импортов. Логику здесь не добавлять — менять `sinks/notion.py`.
"""

from bot.config import settings  # noqa: F401  — used by test monkeypatching
from bot.services.sinks.notion import (  # noqa: F401
    MAX_BLOCKS_PER_PAGE,
    build_properties,
    create_page,
    get_sink_instance,
    set_client,
    set_failure_injector,
)
