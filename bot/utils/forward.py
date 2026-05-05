"""Telegram forward metadata extraction.

aiogram 3 exposes the source of a forwarded message via `message.forward_origin`,
which is one of:
- MessageOriginUser   — forwarded from a user with a public profile.
- MessageOriginHiddenUser — user hid their account; only their stored display name is exposed.
- MessageOriginChat   — forwarded from a (group/supergroup) chat by a known author.
- MessageOriginChannel — forwarded from a channel; may include a chat id, message_id, and signature.

`extract` returns a dict ready to (a) store inside `drafts.raw_payload` for
auditability and (b) prepend as a markdown context block to the text that goes
into the LLM, so the classifier knows the message wasn't authored by the user.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from aiogram.types import (
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)


def extract(message: Message) -> Optional[dict[str, Any]]:
    """Pull forward metadata from `message.forward_origin`.

    Returns None when the message wasn't forwarded.
    """
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None

    meta: dict[str, Any] = {"date": _iso(getattr(origin, "date", None))}

    if isinstance(origin, MessageOriginUser):
        user = origin.sender_user
        meta["source_kind"] = "user"
        meta["author"] = _user_display(user)
        meta["author_username"] = getattr(user, "username", None)
    elif isinstance(origin, MessageOriginHiddenUser):
        meta["source_kind"] = "hidden_user"
        meta["author"] = origin.sender_user_name
    elif isinstance(origin, MessageOriginChat):
        meta["source_kind"] = "chat"
        meta["chat_title"] = getattr(origin.sender_chat, "title", None)
        meta["author_signature"] = getattr(origin, "author_signature", None)
    elif isinstance(origin, MessageOriginChannel):
        meta["source_kind"] = "channel"
        meta["chat_title"] = getattr(origin.chat, "title", None)
        meta["chat_username"] = getattr(origin.chat, "username", None)
        meta["original_message_id"] = origin.message_id
        meta["author_signature"] = getattr(origin, "author_signature", None)
    else:
        meta["source_kind"] = "unknown"

    return meta


def _user_display(user) -> str:
    if user is None:
        return ""
    parts = [
        (getattr(user, "first_name", "") or "").strip(),
        (getattr(user, "last_name", "") or "").strip(),
    ]
    return " ".join(p for p in parts if p)


def _iso(date) -> Optional[str]:
    if date is None:
        return None
    if isinstance(date, _dt.datetime):
        return date.isoformat()
    return str(date)


def format_prefix(meta: dict[str, Any]) -> str:
    """Render forward metadata as a context block prepended to the LLM input.

    Kept compact on purpose — the LLM should see source attribution, not the
    full raw dict.
    """
    src = meta.get("source_kind")
    parts: list[str] = []
    if src == "user":
        author = meta.get("author") or "unknown"
        username = meta.get("author_username")
        who = f"{author}" + (f" (@{username})" if username else "")
        parts.append(f"От: {who}")
    elif src == "hidden_user":
        parts.append(f"От: {meta.get('author') or 'скрытый пользователь'}")
    elif src == "chat":
        title = meta.get("chat_title") or "чат"
        sig = meta.get("author_signature")
        parts.append(f"Из чата: {title}" + (f" / {sig}" if sig else ""))
    elif src == "channel":
        title = meta.get("chat_title") or "канал"
        username = meta.get("chat_username")
        sig = meta.get("author_signature")
        head = title + (f" (@{username})" if username else "")
        parts.append(f"Из канала: {head}" + (f" / {sig}" if sig else ""))

    if meta.get("date"):
        parts.append(f"Когда: {meta['date']}")

    if not parts:
        return ""
    return "[Forwarded] " + "; ".join(parts)


def enrich(text: str, meta: dict[str, Any]) -> str:
    """Prepend the rendered forward prefix to the original text for the LLM."""
    prefix = format_prefix(meta)
    if not prefix:
        return text
    return f"{prefix}\n\n{text}"
