"""Forward metadata extraction + LLM-input enrichment."""

import datetime as _dt
from unittest.mock import MagicMock

from aiogram.types import (
    Chat,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    User,
)

from bot.utils import forward as forward_utils


def _msg(origin):
    m = MagicMock()
    m.forward_origin = origin
    return m


def test_no_forward_returns_none():
    m = MagicMock()
    m.forward_origin = None
    assert forward_utils.extract(m) is None


def test_user_origin():
    user = User(id=1, is_bot=False, first_name="Иван", last_name="Петров", username="ivan")
    origin = MessageOriginUser(
        type="user",
        date=_dt.datetime(2026, 5, 4, 14, 30, tzinfo=_dt.timezone.utc),
        sender_user=user,
    )
    meta = forward_utils.extract(_msg(origin))
    assert meta["source_kind"] == "user"
    assert meta["author"] == "Иван Петров"
    assert meta["author_username"] == "ivan"
    assert meta["date"].startswith("2026-05-04T14:30")


def test_hidden_user_origin():
    origin = MessageOriginHiddenUser(
        type="hidden_user",
        date=_dt.datetime.now(_dt.timezone.utc),
        sender_user_name="Мистер X",
    )
    meta = forward_utils.extract(_msg(origin))
    assert meta["source_kind"] == "hidden_user"
    assert meta["author"] == "Мистер X"


def test_chat_origin():
    chat = Chat(id=-100, type="supergroup", title="Команда")
    origin = MessageOriginChat(
        type="chat",
        date=_dt.datetime.now(_dt.timezone.utc),
        sender_chat=chat,
        author_signature="Алёна",
    )
    meta = forward_utils.extract(_msg(origin))
    assert meta["source_kind"] == "chat"
    assert meta["chat_title"] == "Команда"
    assert meta["author_signature"] == "Алёна"


def test_channel_origin():
    chat = Chat(id=-100, type="channel", title="Notion News", username="notionhq")
    origin = MessageOriginChannel(
        type="channel",
        date=_dt.datetime.now(_dt.timezone.utc),
        chat=chat,
        message_id=42,
        author_signature="Editor",
    )
    meta = forward_utils.extract(_msg(origin))
    assert meta["source_kind"] == "channel"
    assert meta["chat_title"] == "Notion News"
    assert meta["chat_username"] == "notionhq"
    assert meta["original_message_id"] == 42


def test_format_prefix_user():
    p = forward_utils.format_prefix(
        {"source_kind": "user", "author": "Иван", "author_username": "ivan", "date": "2026-05-04"}
    )
    assert "Forwarded" in p
    assert "Иван" in p
    assert "@ivan" in p
    assert "2026-05-04" in p


def test_format_prefix_channel_with_signature():
    p = forward_utils.format_prefix(
        {
            "source_kind": "channel",
            "chat_title": "News",
            "chat_username": "newsroom",
            "author_signature": "Ed",
            "date": None,
        }
    )
    assert "News" in p
    assert "@newsroom" in p
    assert "/ Ed" in p


def test_enrich_prepends_prefix():
    meta = {"source_kind": "user", "author": "Vasya", "date": "2026-05-04"}
    out = forward_utils.enrich("текст", meta)
    assert out.startswith("[Forwarded]")
    assert "текст" in out


def test_enrich_no_prefix_returns_text():
    out = forward_utils.enrich("plain", {})
    assert out == "plain"
