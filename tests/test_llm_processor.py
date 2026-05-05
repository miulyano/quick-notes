"""Stub fallback + real path with mocked OpenAI client."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.services import llm_processor


def _fake_completion(payload: dict):
    msg = MagicMock()
    msg.content = json.dumps(payload, ensure_ascii=False)
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture(autouse=True)
def _reset():
    llm_processor.set_client(None)
    yield
    llm_processor.set_client(None)


async def test_stub_uses_first_line_as_title(monkeypatch):
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", None)
    p = await llm_processor.process("Title line\nbody body")
    assert p.note_type == "note"
    assert p.title == "Title line"
    assert p.formatted == "Title line\nbody body"


async def test_stub_truncates_long_title(monkeypatch):
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", None)
    p = await llm_processor.process("a" * 200)
    assert len(p.title) == 80


async def test_stub_handles_empty(monkeypatch):
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", None)
    p = await llm_processor.process("   ")
    assert p.title == "Без названия"


async def test_real_path_classifies_task(monkeypatch):
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=_fake_completion(
            {
                "type": "task",
                "title": "Bump version",
                "properties": {
                    "Name": "Bump version",
                    "Status": "Todo",
                    "Priority": "High",
                    "DueDate": "2026-05-10",
                },
                "extras": {"checklist": ["edit VERSION", "tag release"]},
                "markdown_body": "Подготовить v0.4.0",
            }
        )
    )
    llm_processor.set_client(fake)

    p = await llm_processor.process("надо выкатить релиз 0.4.0 до пятницы")
    assert p.note_type == "task"
    assert p.title == "Bump version"
    assert p.properties["Status"] == "Todo"
    assert p.properties["DueDate"] == "2026-05-10"
    # Template renders checklist after body.
    assert "## Чек-лист" in p.formatted
    assert "- [ ] edit VERSION" in p.formatted


async def test_real_path_unknown_type_falls_back(monkeypatch):
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=_fake_completion(
            {"type": "fairy_tale", "title": "x", "markdown_body": "y"}
        )
    )
    llm_processor.set_client(fake)

    p = await llm_processor.process("test")
    assert p.note_type == "note"


async def test_real_path_falls_back_to_stub_on_error(monkeypatch):
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=RuntimeError("rate limit"))
    llm_processor.set_client(fake)

    p = await llm_processor.process("hello world")
    # On error, stub used → type=note, title=first line.
    assert p.note_type == "note"
    assert p.title == "hello world"
