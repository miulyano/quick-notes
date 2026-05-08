"""Интеграционные тесты на aiohttp-эндпойнты Web App.

Используем aiohttp.test_utils.TestClient напрямую (без pytest-aiohttp), чтобы
не тащить дополнительную зависимость в requirements-dev.
"""

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Settings
from bot.storage import drafts
from bot.web.server import build_app


BOT_TOKEN = "1234567890:fake-bot-token-for-tests"


def _sign(fields: dict, token: str = BOT_TOKEN) -> str:
    pairs = sorted(fields.items())
    dcs = "\n".join(f"{k}={v}" for k, v in pairs)
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return f"{urlencode(pairs)}&hash={digest}"


def _make_init_data(user_id: int = 111, *, auth_date: int | None = None) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAFakeQueryId",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test"}, separators=(",", ":")
        ),
    }
    return _sign(fields)


def _settings() -> Settings:
    s = Settings()
    s.WEBAPP_BASE_URL = "https://example.com"
    return s


def _bot_mock() -> MagicMock:
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()
    return bot


@pytest_asyncio.fixture
async def client(fresh_db):
    bot = _bot_mock()
    settings = _settings()
    # build_app читает settings.BOT_TOKEN. В conftest.py BOT_TOKEN="test_token",
    # но тестовому HMAC нужен наш фиксированный токен — переопределяем здесь.
    settings.BOT_TOKEN = BOT_TOKEN
    app = build_app(bot, settings)
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    test_client.bot = bot  # для assert'ов в тестах
    try:
        yield test_client
    finally:
        await test_client.close()


async def _mk_draft(user_id: int = 111) -> str:
    draft_id = await drafts.create(
        user_id=user_id, chat_id=42, message_id=1, kind="text", raw_payload="x"
    )
    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type="note",
        title="старый заголовок",
        formatted="старое тело",
        preview_msg_id=4242,
    )
    return draft_id


async def test_submit_happy_path_updates_draft_and_refreshes_preview(client):
    draft_id = await _mk_draft(user_id=111)
    init_data = _make_init_data(user_id=111)

    resp = await client.post(
        "/edit/submit",
        json={
            "draft_id": draft_id,
            "title": "Новый заголовок",
            "body": "Новое тело\nс несколькими строками",
        },
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 200

    fresh = await drafts.get(draft_id)
    assert fresh.title == "Новый заголовок"
    assert fresh.formatted == "Новое тело\nс несколькими строками"
    assert fresh.status == "awaiting_confirm"

    client.bot.edit_message_text.assert_awaited()
    kwargs = client.bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 42
    assert kwargs["message_id"] == 4242


async def test_submit_invalid_init_data_returns_401(client):
    draft_id = await _mk_draft()
    resp = await client.post(
        "/edit/submit",
        json={"draft_id": draft_id, "title": "x", "body": "y"},
        headers={"X-Telegram-Init-Data": "garbage&hash=deadbeef"},
    )
    assert resp.status == 401


async def test_submit_no_init_data_returns_401(client):
    draft_id = await _mk_draft()
    resp = await client.post(
        "/edit/submit", json={"draft_id": draft_id, "title": "x", "body": "y"}
    )
    assert resp.status == 401


async def test_submit_foreign_draft_returns_403(client):
    # Draft принадлежит user_id=111, initData подписана user_id=222.
    draft_id = await _mk_draft(user_id=111)
    init_data = _make_init_data(user_id=222)
    resp = await client.post(
        "/edit/submit",
        json={"draft_id": draft_id, "title": "x", "body": "y"},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 403


async def test_submit_unknown_draft_returns_404(client):
    init_data = _make_init_data(user_id=111)
    resp = await client.post(
        "/edit/submit",
        json={"draft_id": "nonexistent", "title": "x", "body": "y"},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 404


async def test_submit_conflict_when_draft_not_awaiting_confirm(client):
    draft_id = await _mk_draft(user_id=111)
    await drafts.update(draft_id, status="saving")
    init_data = _make_init_data(user_id=111)
    resp = await client.post(
        "/edit/submit",
        json={"draft_id": draft_id, "title": "x", "body": "y"},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 409


async def test_submit_long_body_passes_through(client):
    draft_id = await _mk_draft(user_id=111)
    init_data = _make_init_data(user_id=111)
    long_body = "ё" * 8000  # сильно больше 4096 — лимит web_app_data, но мы шлём POST
    resp = await client.post(
        "/edit/submit",
        json={"draft_id": draft_id, "title": "x", "body": long_body},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 200
    fresh = await drafts.get(draft_id)
    assert fresh.formatted == long_body


async def test_submit_invalid_payload_returns_400(client):
    init_data = _make_init_data(user_id=111)
    resp = await client.post(
        "/edit/submit",
        data="not json",
        headers={"X-Telegram-Init-Data": init_data, "Content-Type": "application/json"},
    )
    assert resp.status == 400


async def test_editor_get_returns_static_html(client):
    """GET /edit отдаёт статичный HTML без auth — initData доступна только в JS."""
    resp = await client.get("/edit", params={"draft_id": "anything"})
    assert resp.status == 200
    assert resp.content_type == "text/html"
    text = await resp.text()
    assert "Telegram.WebApp" in text or "telegram-web-app.js" in text
    # Никаких драфтовых данных в HTML — они догружаются через /edit/state.
    assert "старый заголовок" not in text


async def test_state_returns_draft_data(client):
    draft_id = await _mk_draft(user_id=111)
    init_data = _make_init_data(user_id=111)
    resp = await client.get(
        "/edit/state",
        params={"draft_id": draft_id},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["draft_id"] == draft_id
    assert data["title"] == "старый заголовок"
    assert data["body"] == "старое тело"
    assert data["note_type"] == "note"


async def test_state_without_init_data_returns_401(client):
    draft_id = await _mk_draft()
    resp = await client.get("/edit/state", params={"draft_id": draft_id})
    assert resp.status == 401


async def test_state_foreign_user_returns_403(client):
    draft_id = await _mk_draft(user_id=111)
    init_data = _make_init_data(user_id=222)
    resp = await client.get(
        "/edit/state",
        params={"draft_id": draft_id},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 403


async def test_state_missing_draft_returns_404(client):
    init_data = _make_init_data(user_id=111)
    resp = await client.get(
        "/edit/state",
        params={"draft_id": "missing"},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 404


async def test_state_missing_draft_id_returns_400(client):
    init_data = _make_init_data(user_id=111)
    resp = await client.get(
        "/edit/state", headers={"X-Telegram-Init-Data": init_data}
    )
    assert resp.status == 400


async def test_healthz_returns_200(client):
    resp = await client.get("/healthz")
    assert resp.status == 200
    assert (await resp.text()) == "ok"


async def test_state_returns_long_body_intact(client):
    """Длинный body (>4096 символов) должен прийти из /edit/state без обрезки."""
    long_text = "ё" * 10000
    draft_id = await drafts.create(
        user_id=111, chat_id=42, message_id=1, kind="text", raw_payload="x"
    )
    await drafts.update(
        draft_id,
        status="awaiting_confirm",
        note_type="note",
        title="t",
        formatted=long_text,
    )
    init_data = _make_init_data(user_id=111)
    resp = await client.get(
        "/edit/state",
        params={"draft_id": draft_id},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["body"] == long_text
