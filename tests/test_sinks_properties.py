"""Unit-тесты на общую сборку properties (notion + buildin shapes)."""

from __future__ import annotations

import json

from bot.services.sinks._properties import build_properties, wrap_property
from bot.storage.drafts import Draft


def _draft(properties_json: str | None, title: str = "T", note_type: str = "note") -> Draft:
    return Draft(
        id="d1",
        user_id=1,
        chat_id=1,
        message_id=None,
        preview_msg_id=None,
        status="awaiting_confirm",
        kind="text",
        raw_payload="raw",
        transcribed=None,
        note_type=note_type,
        formatted="body",
        title=title,
        properties=properties_json,
        error=None,
        created_at=0,
        updated_at=0,
        workspace="personal",
    )


class _NoteType:
    def __init__(self, props):
        self.properties = props


class _Prop:
    def __init__(self, name, kind, select_options=()):
        self.name = name
        self.kind = kind
        self.select_options = select_options


def test_wrap_title_notion_shape():
    out = wrap_property("title", "hi", shape="notion")
    assert out == {"title": [{"type": "text", "text": {"content": "hi"}}]}


def test_wrap_title_buildin_shape():
    out = wrap_property("title", "hi", shape="buildin")
    assert out == {
        "type": "title",
        "title": [{"type": "text", "text": {"content": "hi"}}],
    }


def test_wrap_select_both_shapes():
    assert wrap_property("select", "Todo", shape="notion") == {"select": {"name": "Todo"}}
    assert wrap_property("select", "Todo", shape="buildin") == {
        "type": "select",
        "select": {"name": "Todo"},
    }


def test_wrap_multi_select_normalizes_scalar():
    out = wrap_property("multi_select", "tag", shape="notion")
    assert out == {"multi_select": [{"name": "tag"}]}


def test_wrap_checkbox_coerces_truthy():
    assert wrap_property("checkbox", 1, shape="notion") == {"checkbox": True}
    assert wrap_property("checkbox", 0, shape="buildin") == {
        "type": "checkbox",
        "checkbox": False,
    }


def test_wrap_none_returns_none():
    assert wrap_property("title", None, shape="notion") is None


def test_wrap_unknown_kind_returns_none():
    assert wrap_property("brand_new_kind", "x", shape="notion") is None


def test_build_properties_fills_title_from_draft():
    nt = _NoteType([_Prop("Name", "title")])
    draft = _draft(properties_json=None, title="From draft")
    out = build_properties(nt, draft, shape="notion")
    assert out["Name"]["title"][0]["text"]["content"] == "From draft"
    assert "CreatedAt" in out


def test_build_properties_title_always_from_draft_ignoring_extracted():
    """Title-property всегда из draft.title — LLM может класть «голую» тему
    без даты-в-скобках в properties.<Name>, а draft.title содержит итоговый
    заголовок страницы (включая `(DD.MM.YYYY)` для meeting/1on1)."""
    nt = _NoteType([_Prop("Name", "title"), _Prop("Status", "select")])
    extracted = {"Name": "From LLM (без даты)", "Status": "Todo"}
    draft = _draft(properties_json=json.dumps(extracted), title="Тема (08.05.2026)")
    out = build_properties(nt, draft, shape="buildin")
    assert out["Name"]["title"][0]["text"]["content"] == "Тема (08.05.2026)"
    assert out["Status"] == {"type": "select", "select": {"name": "Todo"}}


def test_build_properties_invalid_json_falls_back_to_draft_title():
    nt = _NoteType([_Prop("Name", "title")])
    draft = _draft(properties_json="not json {", title="Fallback")
    out = build_properties(nt, draft, shape="notion")
    assert out["Name"]["title"][0]["text"]["content"] == "Fallback"


def test_build_properties_adds_default_name_when_no_title_prop():
    nt = _NoteType([_Prop("Status", "select")])
    draft = _draft(properties_json=None, title="My note")
    out = build_properties(nt, draft, shape="notion")
    assert "Name" in out
    assert out["Name"]["title"][0]["text"]["content"] == "My note"


def test_build_properties_date_taken_from_title():
    """Date property синхронизируется с датой в title — даже если LLM
    положила в extracted.Date другую дату."""
    nt = _NoteType([_Prop("Name", "title"), _Prop("Date", "date")])
    extracted = {"Date": "2026-01-01"}
    draft = _draft(properties_json=json.dumps(extracted), title="Тема (08.05.2026)")
    out = build_properties(nt, draft, shape="notion")
    assert out["Date"] == {"date": {"start": "2026-05-08"}}


def test_build_properties_date_falls_back_to_extracted_when_title_has_no_date():
    nt = _NoteType([_Prop("Name", "title"), _Prop("Date", "date")])
    extracted = {"Date": "2026-05-08"}
    draft = _draft(properties_json=json.dumps(extracted), title="Просто тема")
    out = build_properties(nt, draft, shape="notion")
    assert out["Date"] == {"date": {"start": "2026-05-08"}}


def test_build_properties_date_invalid_in_title_falls_back():
    """Если в title невалидная дата (30.02.2026) — берём extracted."""
    nt = _NoteType([_Prop("Name", "title"), _Prop("Date", "date")])
    extracted = {"Date": "2026-01-01"}
    draft = _draft(properties_json=json.dumps(extracted), title="Тема (30.02.2026)")
    out = build_properties(nt, draft, shape="notion")
    assert out["Date"] == {"date": {"start": "2026-01-01"}}


def test_build_properties_due_date_not_overridden_by_title():
    """Прочие date-property (DueDate у task) не должны цеплять дату из title."""
    nt = _NoteType([_Prop("Name", "title"), _Prop("DueDate", "date")])
    extracted = {"DueDate": "2026-01-01"}
    draft = _draft(properties_json=json.dumps(extracted), title="Сделать (08.05.2026)")
    out = build_properties(nt, draft, shape="notion")
    assert out["DueDate"] == {"date": {"start": "2026-01-01"}}


def test_build_properties_date_buildin_shape():
    nt = _NoteType([_Prop("Name", "title"), _Prop("Date", "date")])
    draft = _draft(properties_json=None, title="Тема (08.05.2026)")
    out = build_properties(nt, draft, shape="buildin")
    assert out["Date"] == {"type": "date", "date": {"start": "2026-05-08"}}
