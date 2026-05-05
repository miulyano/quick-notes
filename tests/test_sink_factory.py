"""Factory: get_sink() возвращает нужный sink по NOTES_PROVIDER."""

from bot.services.sinks import buildin as buildin_module
from bot.services.sinks import notion as notion_module
from bot.services.sinks.factory import get_sink


def test_factory_returns_buildin_when_provider_buildin(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.factory.settings.NOTES_PROVIDER", "buildin")
    assert get_sink() is buildin_module.get_sink_instance()


def test_factory_returns_notion_when_provider_notion(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.factory.settings.NOTES_PROVIDER", "notion")
    assert get_sink() is notion_module.get_sink_instance()
