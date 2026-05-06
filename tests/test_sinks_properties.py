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


def test_build_properties_uses_extracted_when_present():
    nt = _NoteType([_Prop("Name", "title"), _Prop("Status", "select")])
    extracted = {"Name": "From LLM", "Status": "Todo"}
    draft = _draft(properties_json=json.dumps(extracted), title="From draft")
    out = build_properties(nt, draft, shape="buildin")
    assert out["Name"]["title"][0]["text"]["content"] == "From LLM"
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
