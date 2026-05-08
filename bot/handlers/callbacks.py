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
from bot.services import llm_processor
from bot.storage import drafts, outbox
from bot.utils import forward as forward_utils

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


def _llm_input_from_draft(draft) -> str | None:
    """Возвращает текст для повторной LLM-обработки или None.

    voice/document уже сохраняют распознанный текст в `draft.transcribed`;
    для text/forward оригинал лежит в `raw_payload` (для forward — JSON-обёртка
    с метаданными). Для драфтов без распознанного текста возвращаем None —
    re-run невозможен.
    """
    if draft.transcribed:
        return draft.transcribed
    raw = draft.raw_payload or ""
    if not raw:
        return None
    if (draft.kind or "") == "forward":
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return raw
        text = (payload or {}).get("text") or ""
        meta = (payload or {}).get("forward")
        if meta:
            return forward_utils.enrich(text, meta)
        return text
    return raw


@router.callback_query(F.data.startswith("togglekind:"))
async def on_toggle_kind(cb: CallbackQuery) -> None:
    """Переключает extras.kind sync↔meeting и перегенерирует тело через LLM.

    Структура body для meeting (Agenda/Discussion/Decisions/Action items) и
    sync (иерархия по людям/зонам, passthrough) принципиально разная — без
    повторного LLM-прогона переключение давало бы рассогласование между
    ярлыком и содержимым. Передаём `force_meeting_kind` подсказкой, и LLM
    переразмечает body под нужный шаблон.
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

    text = _llm_input_from_draft(draft)
    if not text:
        await cb.answer(
            "Не могу перегенерировать: нет исходного текста", show_alert=True
        )
        return

    await cb.answer("Перегенерирую…")

    try:
        processed = await llm_processor.process(text, force_meeting_kind=new_kind)
    except llm_processor.LLMError:
        logger.exception("toggle_kind LLM re-run failed for draft=%s", draft_id)
        await cb.answer("LLM не отвечает, попробуй позже", show_alert=True)
        return

    extras_json = json.dumps(processed.extras, ensure_ascii=False)
    await drafts.update(
        draft_id,
        note_type=processed.note_type,
        title=processed.title,
        formatted=processed.formatted,
        properties=json.dumps(processed.properties, ensure_ascii=False),
        workspace=processed.workspace,
        extras_json=extras_json,
    )

    if cb.message is not None:
        try:
            await cb.message.edit_text(
                format_preview(
                    processed.title,
                    processed.formatted,
                    processed.note_type,
                    processed.workspace,
                    extras_json,
                ),
                reply_markup=preview_keyboard(draft_id, show_kind_toggle=True),
            )
        except Exception:
            pass
