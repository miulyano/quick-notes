"""Preview button handlers."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.domain.note_types import TYPES
from bot.domain.workspaces import WORKSPACES
from bot.handlers.inputs import format_preview, preview_keyboard
from bot.storage import drafts, outbox

router = Router()
logger = logging.getLogger(__name__)


def _types_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    """Per-type chooser. 2 columns × N rows + back row."""
    buttons = [
        InlineKeyboardButton(text=t.label, callback_data=f"settype:{draft_id}:{t.key}")
        for t in TYPES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:{draft_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _workspaces_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    """Per-workspace chooser. 2 columns × N rows + back row."""
    buttons = [
        InlineKeyboardButton(text=w.label, callback_data=f"setws:{draft_id}:{w.key}")
        for w in WORKSPACES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:{draft_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("save:"))
async def on_save(cb: CallbackQuery) -> None:
    draft_id = cb.data.split(":", 1)[1]
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    await drafts.update(draft_id, status="saving")
    await outbox.enqueue(draft_id)
    await cb.answer("⏳ Сохраняю…")
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel(cb: CallbackQuery) -> None:
    draft_id = cb.data.split(":", 1)[1]
    await drafts.delete(draft_id)
    await cb.answer("Отменено")
    if cb.message is not None:
        try:
            await cb.message.edit_text("✖️ Отменено")
        except Exception:
            pass


@router.callback_query(F.data.startswith("chtype:"))
async def on_change_type(cb: CallbackQuery) -> None:
    draft_id = cb.data.split(":", 1)[1]
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=_types_keyboard(draft_id))
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data.startswith("settype:"))
async def on_set_type(cb: CallbackQuery) -> None:
    _, draft_id, type_key = cb.data.split(":", 2)
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    await drafts.update(draft_id, note_type=type_key)
    if cb.message is not None:
        try:
            await cb.message.edit_text(
                format_preview(
                    draft.title or "", draft.formatted or "", type_key, draft.workspace
                ),
                reply_markup=preview_keyboard(draft_id),
            )
        except Exception:
            pass
    await cb.answer(f"Тип: {type_key}")


@router.callback_query(F.data.startswith("chws:"))
async def on_change_workspace(cb: CallbackQuery) -> None:
    draft_id = cb.data.split(":", 1)[1]
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=_workspaces_keyboard(draft_id))
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data.startswith("setws:"))
async def on_set_workspace(cb: CallbackQuery) -> None:
    _, draft_id, ws_key = cb.data.split(":", 2)
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    await drafts.update(draft_id, workspace=ws_key)
    if cb.message is not None:
        try:
            await cb.message.edit_text(
                format_preview(
                    draft.title or "",
                    draft.formatted or "",
                    draft.note_type or "note",
                    ws_key,
                ),
                reply_markup=preview_keyboard(draft_id),
            )
        except Exception:
            pass
    await cb.answer(f"Workspace: {ws_key}")


@router.callback_query(F.data.startswith("back:"))
async def on_back(cb: CallbackQuery) -> None:
    draft_id = cb.data.split(":", 1)[1]
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=preview_keyboard(draft_id))
        except Exception:
            pass
    await cb.answer()
