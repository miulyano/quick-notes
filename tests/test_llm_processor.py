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
    assert p.workspace == "personal"  # DEFAULT_WORKSPACE


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


async def test_real_path_classifies_workspace(monkeypatch):
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=_fake_completion(
            {
                "type": "note",
                "workspace": "ai_path",
                "title": "Идея для ИИ",
                "properties": {},
                "markdown_body": "тело",
            }
        )
    )
    llm_processor.set_client(fake)

    p = await llm_processor.process("эксперимент с GPT")
    assert p.workspace == "ai_path"


async def test_real_path_unknown_workspace_falls_back(monkeypatch):
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=_fake_completion(
            {"type": "note", "workspace": "narnia", "title": "x", "markdown_body": "y"}
        )
    )
    llm_processor.set_client(fake)

    p = await llm_processor.process("test")
    assert p.workspace == "personal"


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


async def test_real_path_propagates_error_as_llm_error(monkeypatch):
    """Network/SDK ошибка не должна прятаться в stub: handler пишет draft=failed
    и пользователь жмёт /retry. Молчаливый fallback скрывал бы проблему."""
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=RuntimeError("rate limit"))
    llm_processor.set_client(fake)

    with pytest.raises(llm_processor.LLMError):
        await llm_processor.process("hello world")


async def test_real_path_propagates_invalid_json_as_llm_error(monkeypatch):
    """Невалидный JSON от модели — тоже LLMError, а не stub."""
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    msg = MagicMock()
    msg.content = "not a json {"
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=response)
    llm_processor.set_client(fake)

    with pytest.raises(llm_processor.LLMError):
        await llm_processor.process("hello world")


def _plain_completion(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


async def test_process_long_short_path_single_call(monkeypatch):
    """Текст под порогом — один вызов process(), без summary-стадии."""
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=_fake_completion(
            {"type": "note", "title": "Short", "markdown_body": "body"}
        )
    )
    llm_processor.set_client(fake)

    fractions: list[float] = []

    async def collect(f):
        fractions.append(f)

    p = await llm_processor.process_long("hello short", on_fraction=collect)
    assert p.title == "Short"
    assert fake.chat.completions.create.await_count == 1
    assert fractions == [1.0]


async def test_process_long_chunked_map_reduce(monkeypatch):
    """Длинный текст: N summary-вызовов + 1 финальный classify, прогресс монотонный."""
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", "secret")

    long_text = ("paragraph line one. paragraph line two.\n\n") * 4000
    assert len(long_text) > llm_processor.LONG_TEXT_THRESHOLD_CHARS

    summary_calls = {"n": 0}

    async def fake_create(**kwargs):
        messages = kwargs["messages"]
        sys_prompt = messages[0]["content"]
        if "Сожми" in sys_prompt:
            summary_calls["n"] += 1
            return _plain_completion(f"- bullet from chunk {summary_calls['n']}")
        return _fake_completion(
            {"type": "meeting", "title": "Big", "markdown_body": "merged"}
        )

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=fake_create)
    llm_processor.set_client(fake)

    fractions: list[float] = []

    async def collect(f):
        fractions.append(f)

    p = await llm_processor.process_long(long_text, on_fraction=collect)

    assert p.title == "Big"
    assert p.note_type == "meeting"
    # N summary calls + 1 classify call.
    assert fake.chat.completions.create.await_count == summary_calls["n"] + 1
    assert summary_calls["n"] >= 2  # text was big enough to split
    # Progress monotonic, ends at 1.0.
    assert fractions[-1] == 1.0
    assert all(a <= b for a, b in zip(fractions, fractions[1:]))


async def test_process_long_short_path_with_openai_off(monkeypatch):
    """Без OPENAI — стаб, никаких сетевых вызовов даже на длинном тексте."""
    monkeypatch.setattr("bot.services.llm_processor.settings.OPENAI_API_KEY", None)
    long_text = "a" * (llm_processor.LONG_TEXT_THRESHOLD_CHARS + 10)
    p = await llm_processor.process_long(long_text)
    assert p.note_type == "note"
    assert p.title == "a" * 80


async def test_split_for_summary_paragraph_boundary():
    text = "para1.\n\n" + "para2-long. " * 200 + "\n\npara3."
    chunks = llm_processor._split_for_summary(text, 500)
    assert all(len(c) <= 500 for c in chunks)
    assert "para1." in chunks[0]
    assert any("para3." in c for c in chunks)


async def test_split_for_summary_hard_slice_long_line():
    text = "x" * 1500
    chunks = llm_processor._split_for_summary(text, 500)
    assert all(len(c) <= 500 for c in chunks)
    assert "".join(chunks) == text


def test_system_prompt_includes_today_date():
    import datetime as _dt

    prompt = llm_processor._build_system_prompt()
    today = _dt.date.today().isoformat()
    assert f"Сегодня: {today}" in prompt


def test_system_prompt_instructs_meeting_date_in_title():
    prompt = llm_processor._build_system_prompt()
    # Гайд по дате в title должен явно быть в промте.
    assert "(YYYY-MM-DD)" in prompt
    assert "properties.Date" in prompt


def test_system_prompt_sync_keeps_hierarchy_in_body():
    prompt = llm_processor._build_system_prompt()
    assert "сохраняя исходную иерархию" in prompt
    # Старые structured-поля для sync убраны из инструкций.
    assert "extras.status_updates" not in prompt
    assert "extras.blockers" not in prompt
