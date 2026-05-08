"""aiohttp Web App для правки draft через Telegram Mini App.

Эндпойнты:
  GET  /edit?draft_id=X  → editor.html (статика, без auth — initData становится
                            доступна только после загрузки telegram-web-app.js
                            на клиенте).
  GET  /edit/state?draft_id=X → JSON {title,body,workspace,note_type}.
                            Авторизация: X-Telegram-Init-Data в заголовке.
  POST /edit/submit      → JSON {draft_id,title,body}, обновляет draft и
                            редактирует preview-сообщение в чате. Авторизация
                            та же.
  GET  /healthz          → 200 ok (для liveness check).

Telegram передаёт initData через URL-fragment (`#tgWebAppData=...`), который
никогда не достигает сервера; JS-библиотека `telegram-web-app.js` парсит его
в `Telegram.WebApp.initData`. Поэтому первый GET /edit идёт без initData
(статичный HTML), а данные draft фронт догружает через `/edit/state` с
заголовком `X-Telegram-Init-Data`. Подпись валидируется HMAC по схеме
Telegram (см. bot/web/auth.py).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiohttp import web

from bot.config import Settings
from bot.services.preview import refresh_preview
from bot.storage import drafts
from bot.web.auth import validate_init_data


logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
EDITOR_TEMPLATE_PATH = STATIC_DIR / "editor.html"

# Заголовок initData во всех data-запросах (state/submit).
INIT_DATA_HEADER = "X-Telegram-Init-Data"


async def _read_init_data(request: web.Request) -> Optional[dict]:
    """Извлечь и провалидировать initData из заголовка. None если невалидно."""
    bot_token: str = request.app["bot_token"]
    init_data = request.headers.get(INIT_DATA_HEADER)
    if not init_data:
        return None
    return validate_init_data(init_data, bot_token)


async def handle_editor(request: web.Request) -> web.Response:
    """GET /edit?draft_id=X — отдаёт статичный HTML.

    Авторизации тут нет: Telegram передаёт initData через URL-fragment, а
    он не доходит до сервера. Реальная защита — на /edit/state и /edit/submit
    (initData в заголовке X-Telegram-Init-Data, выставляется фронтом после
    `Telegram.WebApp.ready()`).
    """
    html = EDITOR_TEMPLATE_PATH.read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def handle_state(request: web.Request) -> web.Response:
    """GET /edit/state?draft_id=X — JSON c title/body/workspace/note_type."""
    draft_id = request.query.get("draft_id")
    if not draft_id:
        return web.json_response({"error": "draft_id required"}, status=400)

    auth = await _read_init_data(request)
    if auth is None:
        return web.json_response({"error": "invalid initData"}, status=401)

    draft = await drafts.get(draft_id)
    if draft is None:
        return web.json_response({"error": "draft not found"}, status=404)

    user_id = (auth.get("user") or {}).get("id")
    if user_id != draft.user_id:
        return web.json_response({"error": "forbidden"}, status=403)

    return web.json_response(
        {
            "draft_id": draft.id,
            "title": draft.title or "",
            "body": draft.formatted or "",
            "workspace": draft.workspace,
            "note_type": draft.note_type or "note",
        }
    )


async def handle_submit(request: web.Request) -> web.Response:
    """POST /edit/submit — записывает новые title/body и перерисовывает preview."""
    auth = await _read_init_data(request)
    if auth is None:
        return web.json_response({"error": "invalid initData"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid payload"}, status=400)

    draft_id = body.get("draft_id")
    title = body.get("title")
    body_text = body.get("body")
    if not isinstance(draft_id, str) or not draft_id:
        return web.json_response({"error": "draft_id required"}, status=400)
    if not isinstance(title, str) or not isinstance(body_text, str):
        return web.json_response({"error": "title and body required"}, status=400)

    draft = await drafts.get(draft_id)
    if draft is None:
        return web.json_response({"error": "draft not found"}, status=404)

    user_id = (auth.get("user") or {}).get("id")
    if user_id != draft.user_id:
        return web.json_response({"error": "forbidden"}, status=403)

    # Гонка: пока юзер правил, кто-то нажал Save/Cancel в чате.
    if draft.status != "awaiting_confirm":
        return web.json_response(
            {"error": "Черновик уже сохранён или отменён"}, status=409
        )

    await drafts.update(draft_id, title=title, formatted=body_text)
    fresh = await drafts.get(draft_id)
    if fresh is not None:
        bot: Bot = request.app["bot"]
        await refresh_preview(bot, fresh)

    return web.json_response({"ok": True})


async def handle_health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot: Bot, settings: Settings) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["bot_token"] = settings.BOT_TOKEN
    app.router.add_get("/edit", handle_editor)
    app.router.add_get("/edit/state", handle_state)
    app.router.add_post("/edit/submit", handle_submit)
    app.router.add_get("/healthz", handle_health)
    return app


async def run_server(
    bot: Bot, settings: Settings, *, stop_event: Optional[asyncio.Event] = None
) -> None:
    """Поднять aiohttp на WEBAPP_BIND_HOST:WEBAPP_PORT и держать до stop_event.

    Если stop_event=None — ждать вечно (until cancelled).
    """
    if not settings.webapp_enabled:
        logger.warning("WEBAPP_BASE_URL не задан — aiohttp-сервер не стартует")
        return
    app = build_app(bot, settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.WEBAPP_BIND_HOST, settings.WEBAPP_PORT)
    await site.start()
    logger.info(
        "WebApp server listening on %s:%d", settings.WEBAPP_BIND_HOST, settings.WEBAPP_PORT
    )
    try:
        if stop_event is None:
            # Wait forever; cancellation propagates from caller.
            await asyncio.Event().wait()
        else:
            await stop_event.wait()
    finally:
        await runner.cleanup()
