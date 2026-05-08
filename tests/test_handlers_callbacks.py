import json
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.callbacks import (
    on_back,
    on_cancel,
    on_change_type,
    on_change_workspace,
    on_save,
    on_set_type,
    on_set_workspace,
    on_toggle_kind,
)
from bot.services import llm_processor
from bot.services.llm_processor import LLMError, ProcessedNote
from bot.storage import drafts, outbox


async def _mk_draft(note_type="note", *, raw_payload: str = "x") -> str:
    draft_id = await drafts.create(
        user_id=111, chat_id=1, message_id=1, kind="text", raw_payload=raw_payload
    )
    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type=note_type,
        title="t",
        formatted="body",
    )
    return draft_id


def _processed(*, kind: str, title: str = "Sync (08.05.2026)") -> ProcessedNote:
    return ProcessedNote(
        note_type="meeting",
        title=title,
        formatted="re-rendered body",
        workspace="work",
        properties={"Date": "2026-05-08"},
        extras={"kind": kind},
    )


def _cb(data: str):
    cb = MagicMock()
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.edit_text = AsyncMock()
    return cb


async def test_save_enqueues_and_marks_saving(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"save:{draft_id}")

    await on_save(cb)

    d = await drafts.get(draft_id)
    assert d.status == "saving"
    assert await outbox.get_attempts(draft_id) == 0


async def test_save_unknown_draft(fresh_db):
    cb = _cb("save:missing")
    await on_save(cb)
    cb.answer.assert_awaited_with("Черновик не найден", show_alert=True)


async def test_cancel_deletes_draft(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"cancel:{draft_id}")

    await on_cancel(cb)

    assert await drafts.get(draft_id) is None
    cb.message.edit_text.assert_awaited()


async def test_change_type_shows_picker(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"chtype:{draft_id}")

    await on_change_type(cb)

    cb.message.edit_reply_markup.assert_awaited()
    # Confirm the keyboard sent contains type buttons.
    kwargs = cb.message.edit_reply_markup.await_args.kwargs
    rows = kwargs["reply_markup"].inline_keyboard
    callback_data = [b.callback_data for row in rows for b in row]
    assert any(c.startswith("settype:") for c in callback_data)
    assert any(c.startswith("back:") for c in callback_data)


async def test_set_type_updates_and_renders_preview(fresh_db):
    draft_id = await _mk_draft(note_type="note")
    cb = _cb(f"settype:{draft_id}:task")

    await on_set_type(cb)

    d = await drafts.get(draft_id)
    assert d.note_type == "task"
    cb.message.edit_text.assert_awaited()


async def test_back_restores_main_keyboard(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"back:{draft_id}")

    await on_back(cb)

    cb.message.edit_reply_markup.assert_awaited()


async def test_change_workspace_shows_picker(fresh_db):
    draft_id = await _mk_draft()
    cb = _cb(f"chws:{draft_id}")

    await on_change_workspace(cb)

    cb.message.edit_reply_markup.assert_awaited()
    rows = cb.message.edit_reply_markup.await_args.kwargs["reply_markup"].inline_keyboard
    callback_data = [b.callback_data for row in rows for b in row]
    assert any(c.startswith("setws:") for c in callback_data)
    assert any(c.startswith("back:") for c in callback_data)


async def test_set_workspace_updates_draft(fresh_db):
    draft_id = await _mk_draft(note_type="note")
    cb = _cb(f"setws:{draft_id}:work")

    await on_set_workspace(cb)

    d = await drafts.get(draft_id)
    assert d.workspace == "work"
    cb.message.edit_text.assert_awaited()


async def test_toggle_kind_flips_meeting_to_sync(fresh_db, monkeypatch):
    draft_id = await _mk_draft(note_type="meeting", raw_payload="команда обсудила статусы")
    await drafts.update(draft_id, extras_json=json.dumps({"kind": "meeting"}))

    process_mock = AsyncMock(return_value=_processed(kind="sync"))
    monkeypatch.setattr(llm_processor, "process", process_mock)

    cb = _cb(f"togglekind:{draft_id}")
    await on_toggle_kind(cb)

    process_mock.assert_awaited_once()
    assert process_mock.await_args.kwargs["force_meeting_kind"] == "sync"

    d = await drafts.get(draft_id)
    assert json.loads(d.extras_json)["kind"] == "sync"
    assert d.formatted == "re-rendered body"
    assert d.title == "Sync (08.05.2026)"
    cb.message.edit_text.assert_awaited()


async def test_toggle_kind_flips_sync_to_meeting(fresh_db, monkeypatch):
    draft_id = await _mk_draft(note_type="meeting", raw_payload="kick-off релиза")
    await drafts.update(draft_id, extras_json=json.dumps({"kind": "sync"}))

    process_mock = AsyncMock(return_value=_processed(kind="meeting"))
    monkeypatch.setattr(llm_processor, "process", process_mock)

    cb = _cb(f"togglekind:{draft_id}")
    await on_toggle_kind(cb)

    assert process_mock.await_args.kwargs["force_meeting_kind"] == "meeting"
    d = await drafts.get(draft_id)
    assert json.loads(d.extras_json)["kind"] == "meeting"


async def test_toggle_kind_default_meeting_when_no_extras(fresh_db, monkeypatch):
    draft_id = await _mk_draft(note_type="meeting", raw_payload="meeting text")

    process_mock = AsyncMock(return_value=_processed(kind="sync"))
    monkeypatch.setattr(llm_processor, "process", process_mock)

    cb = _cb(f"togglekind:{draft_id}")
    await on_toggle_kind(cb)

    assert process_mock.await_args.kwargs["force_meeting_kind"] == "sync"
    d = await drafts.get(draft_id)
    assert json.loads(d.extras_json)["kind"] == "sync"


async def test_toggle_kind_rejects_non_meeting(fresh_db, monkeypatch):
    draft_id = await _mk_draft(note_type="note")
    process_mock = AsyncMock()
    monkeypatch.setattr(llm_processor, "process", process_mock)

    cb = _cb(f"togglekind:{draft_id}")
    await on_toggle_kind(cb)

    cb.answer.assert_awaited_with("Доступно только для митингов", show_alert=True)
    process_mock.assert_not_awaited()
    d = await drafts.get(draft_id)
    assert d.extras_json is None


async def test_toggle_kind_handles_llm_error(fresh_db, monkeypatch):
    draft_id = await _mk_draft(note_type="meeting", raw_payload="meeting text")
    await drafts.update(draft_id, extras_json=json.dumps({"kind": "meeting"}))

    monkeypatch.setattr(
        llm_processor, "process", AsyncMock(side_effect=LLMError("boom"))
    )

    cb = _cb(f"togglekind:{draft_id}")
    await on_toggle_kind(cb)

    cb.answer.assert_any_await("LLM не отвечает, попробуй позже", show_alert=True)
    d = await drafts.get(draft_id)
    # extras_json не изменился
    assert json.loads(d.extras_json)["kind"] == "meeting"
    assert d.formatted == "body"


async def test_toggle_kind_no_source_text(fresh_db, monkeypatch):
    """Драфт без transcribed и без raw_payload (искусственный кейс) — alert, не падает."""
    draft_id = await _mk_draft(note_type="meeting", raw_payload="")
    process_mock = AsyncMock()
    monkeypatch.setattr(llm_processor, "process", process_mock)

    cb = _cb(f"togglekind:{draft_id}")
    await on_toggle_kind(cb)

    cb.answer.assert_awaited_with(
        "Не могу перегенерировать: нет исходного текста", show_alert=True
    )
    process_mock.assert_not_awaited()
