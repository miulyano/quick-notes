"""Text-input handler: persist draft → run LLM → show preview with action buttons."""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.domain.note_types import get as get_note_type
from bot.domain.workspaces import get as get_workspace
from bot.services import llm_processor
from bot.storage import drafts
from bot.utils import forward as forward_utils

router = Router()
logger = logging.getLogger(__name__)


PREVIEW_BODY_LIMIT = 3500
PREVIEW_TRUNCATE_MARKER = "\n\n— превью обрезано, в Notion уйдёт полный текст —"


def preview_keyboard(draft_id: str, *, show_kind_toggle: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="💾 Save", callback_data=f"save:{draft_id}"),
            InlineKeyboardButton(text="✖️ Cancel", callback_data=f"cancel:{draft_id}"),
        ],
        [
            InlineKeyboardButton(text="🔁 Type", callback_data=f"chtype:{draft_id}"),
            InlineKeyboardButton(text="📁 Workspace", callback_data=f"chws:{draft_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit:{draft_id}"),
        ],
    ]
    if show_kind_toggle:
        rows.append(
            [InlineKeyboardButton(text="🔄 Sync ↔ Meeting", callback_data=f"togglekind:{draft_id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _meeting_kind_label(extras_json: str | None) -> str:
    """Возвращает '' для default-meeting или ' (sync)' для kind=sync."""
    if not extras_json:
        return ""
    try:
        extras = json.loads(extras_json)
    except (TypeError, ValueError):
        return ""
    kind = (extras.get("kind") or "").lower() if isinstance(extras, dict) else ""
    return " (sync)" if kind == "sync" else ""


def format_preview(
    title: str,
    body: str,
    note_type_key: str,
    workspace_key: str,
    extras_json: str | None = None,
) -> str:
    note_type = get_note_type(note_type_key)
    workspace = get_workspace(workspace_key)
    body_short = (
        body
        if len(body) <= PREVIEW_BODY_LIMIT
        else body[:PREVIEW_BODY_LIMIT] + PREVIEW_TRUNCATE_MARKER
    )
    kind_suffix = _meeting_kind_label(extras_json) if note_type_key == "meeting" else ""
    return (
        f"<b>{title}</b>\n"
        f"<i>{note_type.label}{kind_suffix} · 📁 {workspace.label}</i>\n\n{body_short}"
    )


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    user = message.from_user
    text = message.text or ""
    if not text.strip():
        return

    forward_meta = forward_utils.extract(message)
    kind = "forward" if forward_meta else "text"
    payload = (
        json.dumps({"text": text, "forward": forward_meta}, ensure_ascii=False)
        if forward_meta
        else text
    )

    draft_id = await drafts.create(
        user_id=user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        kind=kind,
        raw_payload=payload,
    )

    llm_input = forward_utils.enrich(text, forward_meta) if forward_meta else text

    try:
        processed = await llm_processor.process(llm_input)
    except Exception as exc:
        logger.exception("llm_processor.process failed for draft=%s", draft_id)
        await drafts.update(draft_id, status="failed", error=str(exc))
        await message.answer("⚠️ Не получилось обработать. Доступно через /list.")
        return

    extras_json = json.dumps(processed.extras, ensure_ascii=False)
    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type=processed.note_type,
        title=processed.title,
        formatted=processed.formatted,
        properties=json.dumps(processed.properties, ensure_ascii=False),
        workspace=processed.workspace,
        extras_json=extras_json,
    )

    preview = format_preview(
        processed.title,
        processed.formatted,
        processed.note_type,
        processed.workspace,
        extras_json,
    )
    sent = await message.answer(
        preview,
        reply_markup=preview_keyboard(
            draft_id, show_kind_toggle=processed.note_type == "meeting"
        ),
    )
    await drafts.update(draft_id, preview_msg_id=sent.message_id)
