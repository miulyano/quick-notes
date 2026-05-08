"""Photo handler: одиночное фото с caption, без caption, альбом."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.photo import handle_photo
from bot.services.llm_processor import ProcessedNote
from bot.storage import drafts


class _FakeProgress:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def set_phase(self, _label):
        pass

    async def set_progress_fraction(self, _frac):
        pass

    async def fail(self, _text):
        pass

    async def finish(self):
        pass


@pytest.fixture
def patch_progress(monkeypatch):
    monkeypatch.setattr(
        "bot.handlers.photo.ProgressReporter", lambda *a, **kw: _FakeProgress()
    )


def _photo_size(file_id: str):
    return MagicMock(file_id=file_id)


def _photo_message(
    *,
    file_id: str = "PHOTO-1",
    caption: str | None = None,
    forward_origin=None,
    media_group_id: str | None = None,
    user_id: int = 111,
    chat_id: int = 999,
    message_id: int = 42,
):
    msg = MagicMock()
    msg.from_user.id = user_id
    msg.chat.id = chat_id
    msg.message_id = message_id
    msg.photo = [_photo_size("small"), _photo_size(file_id)]
    msg.caption = caption
    msg.forward_origin = forward_origin
    msg.media_group_id = media_group_id
    sent = MagicMock(message_id=4242)
    msg.answer = AsyncMock(return_value=sent)
    return msg


def _bot_with_get_file(file_path_by_id: dict[str, str] | None = None):
    bot = MagicMock()

    async def fake_get_file(file_id: str):
        path = (file_path_by_id or {}).get(file_id, f"photos/{file_id}.jpg")
        return MagicMock(file_path=path)

    bot.get_file = AsyncMock(side_effect=fake_get_file)
    return bot


@pytest.fixture(autouse=True)
def _clean_processor(monkeypatch):
    yield


async def test_photo_with_caption_runs_llm_and_stores_image_url(
    fresh_db, monkeypatch, patch_progress
):
    seen_inputs: list[str] = []

    async def fake_llm(text):
        seen_inputs.append(text)
        return ProcessedNote(note_type="note", title="Cap title", formatted=text)

    monkeypatch.setattr("bot.handlers.photo.llm_processor.process", fake_llm)
    fake_meta = {"source_kind": "channel", "chat_title": "ChanX", "date": None}
    monkeypatch.setattr("bot.handlers.photo.forward_utils.extract", lambda _m: fake_meta)

    msg = _photo_message(file_id="PHOTO-1", caption="hello world")
    bot = _bot_with_get_file({"PHOTO-1": "photos/p1.jpg"})

    await handle_photo(msg, bot)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.kind == "forward_photo"
    assert d.status == "awaiting_confirm"
    assert d.title == "Cap title"
    assert d.preview_msg_id == 4242

    extras = json.loads(d.extras_json)
    assert extras["image_urls"] == [
        "https://api.telegram.org/file/bottest_token/photos/p1.jpg"
    ]

    raw = json.loads(d.raw_payload)
    assert raw["caption"] == "hello world"
    assert raw["forward"]["source_kind"] == "channel"
    assert raw["photos"][0]["file_id"] == "PHOTO-1"
    assert raw["photos"][0]["file_url"].endswith("/photos/p1.jpg")

    # LLM получил enriched caption (forward-prefix)
    assert seen_inputs and "[Forwarded]" in seen_inputs[0]
    assert "hello world" in seen_inputs[0]


async def test_photo_without_caption_skips_llm(fresh_db, monkeypatch, patch_progress):
    called = []

    async def fake_llm(text):
        called.append(text)
        return ProcessedNote(note_type="note", title="x", formatted=text)

    monkeypatch.setattr("bot.handlers.photo.llm_processor.process", fake_llm)
    fake_meta = {"source_kind": "user", "author": "Alice", "date": None}
    monkeypatch.setattr("bot.handlers.photo.forward_utils.extract", lambda _m: fake_meta)

    msg = _photo_message(file_id="PHOTO-X", caption=None)
    bot = _bot_with_get_file()

    await handle_photo(msg, bot)

    assert called == []  # LLM не звали

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    assert d.kind == "forward_photo"
    assert d.formatted == ""
    assert d.title == "Photo from Alice"
    assert d.note_type == "note"
    assert d.workspace == "personal"

    extras = json.loads(d.extras_json)
    assert extras["image_urls"] == [
        "https://api.telegram.org/file/bottest_token/photos/PHOTO-X.jpg"
    ]


async def test_photo_no_caption_no_forward_uses_default_title(
    fresh_db, monkeypatch, patch_progress
):
    monkeypatch.setattr("bot.handlers.photo.forward_utils.extract", lambda _m: None)

    msg = _photo_message(file_id="P", caption=None)
    bot = _bot_with_get_file()

    await handle_photo(msg, bot)

    d = (await drafts.list_for_user(111))[0]
    assert d.kind == "photo"
    assert d.title == "Photo"


async def test_album_collects_all_image_urls(fresh_db, monkeypatch, patch_progress):
    async def fake_llm(text):
        return ProcessedNote(note_type="note", title="album title", formatted=text)

    monkeypatch.setattr("bot.handlers.photo.llm_processor.process", fake_llm)
    monkeypatch.setattr("bot.handlers.photo.forward_utils.extract", lambda _m: None)

    primary = _photo_message(
        file_id="A1", caption="album body", media_group_id="grp-1", message_id=10
    )
    second = _photo_message(
        file_id="A2", caption=None, media_group_id="grp-1", message_id=11
    )
    third = _photo_message(
        file_id="A3", caption=None, media_group_id="grp-1", message_id=12
    )
    album = [primary, second, third]
    bot = _bot_with_get_file(
        {"A1": "photos/a1.jpg", "A2": "photos/a2.jpg", "A3": "photos/a3.jpg"}
    )

    await handle_photo(primary, bot, album=album)

    items = await drafts.list_for_user(111)
    assert len(items) == 1
    d = items[0]
    extras = json.loads(d.extras_json)
    assert extras["image_urls"] == [
        "https://api.telegram.org/file/bottest_token/photos/a1.jpg",
        "https://api.telegram.org/file/bottest_token/photos/a2.jpg",
        "https://api.telegram.org/file/bottest_token/photos/a3.jpg",
    ]
    raw = json.loads(d.raw_payload)
    assert raw["caption"] == "album body"
    assert raw["media_group_id"] == "grp-1"
    assert len(raw["photos"]) == 3


async def test_get_file_failure_skips_that_photo(
    fresh_db, monkeypatch, patch_progress
):
    monkeypatch.setattr("bot.handlers.photo.forward_utils.extract", lambda _m: None)

    msg = _photo_message(file_id="GOOD", caption=None)
    bot = MagicMock()

    async def boom(_file_id):
        raise RuntimeError("network")

    bot.get_file = AsyncMock(side_effect=boom)

    await handle_photo(msg, bot)

    # Все фото не скачались — draft не создан.
    assert await drafts.list_for_user(111) == []
    msg.answer.assert_awaited()


async def test_llm_failure_marks_draft_failed(fresh_db, monkeypatch, patch_progress):
    async def boom(_text):
        raise RuntimeError("llm down")

    monkeypatch.setattr("bot.handlers.photo.llm_processor.process", boom)
    monkeypatch.setattr("bot.handlers.photo.forward_utils.extract", lambda _m: None)

    msg = _photo_message(file_id="P", caption="non-empty")
    bot = _bot_with_get_file()

    await handle_photo(msg, bot)

    d = (await drafts.list_for_user(111))[0]
    assert d.status == "failed"
    assert d.error and "llm down" in d.error
    raw = json.loads(d.raw_payload)
    assert raw["caption"] == "non-empty"  # payload сохранился
