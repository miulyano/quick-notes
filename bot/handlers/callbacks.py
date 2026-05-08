"""Preview button handlers."""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import settings
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


def _edit_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    """Submenu для выбора поля правки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Title", callback_data=f"editfld:{draft_id}:title"),
                InlineKeyboardButton(text="📄 Body", callback_data=f"editfld:{draft_id}:body"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:{draft_id}")],
        ]
    )


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
    await cb.answer()
    if cb.message is not None:
        provider_label = "Buildin" if settings.NOTES_PROVIDER == "buildin" else "Notion"
        try:
            await cb.message.edit_text(
                f"⏳ Сохраняю в {provider_label}…", reply_markup=None
            )
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
                    draft.title or "",
                    draft.formatted or "",
                    type_key,
                    draft.workspace,
                    draft.extras_json,
                ),
                reply_markup=preview_keyboard(
                    draft_id, show_kind_toggle=type_key == "meeting"
                ),
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
                    draft.extras_json,
                ),
                reply_markup=preview_keyboard(
                    draft_id, show_kind_toggle=(draft.note_type or "") == "meeting"
                ),
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
            await cb.message.edit_reply_markup(
                reply_markup=preview_keyboard(
                    draft_id, show_kind_toggle=(draft.note_type or "") == "meeting"
                )
            )
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data.startswith("edit:"))
async def on_edit(cb: CallbackQuery) -> None:
    """Показывает подменю выбора поля правки (title/body)."""
    draft_id = cb.data.split(":", 1)[1]
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=_edit_keyboard(draft_id))
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data.startswith("editfld:"))
async def on_edit_field(cb: CallbackQuery) -> None:
    """Переводит draft в awaiting_edit_<field>, снимает кнопки, шлёт prompt."""
    _, draft_id, field = cb.data.split(":", 2)
    if field not in ("title", "body"):
        await cb.answer("Неизвестное поле", show_alert=True)
        return
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    new_status = "awaiting_edit_title" if field == "title" else "awaiting_edit_body"
    await drafts.update(draft_id, status=new_status)
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        prompt = (
            "✏️ Пришли новый заголовок одним сообщением. /cancel — отмена."
            if field == "title"
            else "✏️ Пришли новое тело заметки одним сообщением. /cancel — отмена."
        )
        try:
            await cb.message.answer(prompt)
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data.startswith("togglekind:"))
async def on_toggle_kind(cb: CallbackQuery) -> None:
    """Переключает extras.kind sync↔meeting для type=meeting драфта.

    Тело (`draft.formatted`) формирует LLM, шаблон `_render_sync` теперь
    passthrough — переключение влияет только на label в превью и метаданные,
    которые поедут в Notion (через property/будущие интеграции). Поэтому
    повторного LLM-вызова делать не нужно.
    """
    draft_id = cb.data.split(":", 1)[1]
    draft = await drafts.get(draft_id)
    if draft is None:
        await cb.answer("Черновик не найден", show_alert=True)
        return
    if (draft.note_type or "") != "meeting":
        await cb.answer("Доступно только для митингов", show_alert=True)
        return

    try:
        extras = json.loads(draft.extras_json) if draft.extras_json else {}
    except (TypeError, ValueError):
        extras = {}
    if not isinstance(extras, dict):
        extras = {}

    current_kind = (extras.get("kind") or "meeting").lower()
    new_kind = "meeting" if current_kind == "sync" else "sync"
    extras["kind"] = new_kind
    extras_json = json.dumps(extras, ensure_ascii=False)
    await drafts.update(draft_id, extras_json=extras_json)

    if cb.message is not None:
        try:
            await cb.message.edit_text(
                format_preview(
                    draft.title or "",
                    draft.formatted or "",
                    draft.note_type or "note",
                    draft.workspace,
                    extras_json,
                ),
                reply_markup=preview_keyboard(draft_id, show_kind_toggle=True),
            )
        except Exception:
            pass
    await cb.answer(f"Kind: {new_kind}")
