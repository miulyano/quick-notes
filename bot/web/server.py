"""aiohttp Web App для правки draft через Telegram Mini App.

Эндпойнты:
  GET  /edit?draft_id=X  → editor.html с инжектнутым __INIT__ (title/body/...).
  POST /edit/submit      → JSON {draft_id,title,body}, обновляет draft и
                            редактирует preview-сообщение в чате.
  GET  /healthz          → 200 ok (для liveness check).

Аутентификация: Telegram WebApp initData передаётся через query (`tgwebappdata`)
для GET и через заголовок `X-Telegram-Init-Data` для POST. Подпись проверяется
HMAC по схеме Telegram (см. bot/web/auth.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from aiogram import Bot
from aiohttp import web

from bot.config import Settings
from bot.services.preview import refresh_preview
from bot.storage import drafts
from bot.storage.drafts import Draft
from bot.web.auth import validate_init_data


logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
EDITOR_TEMPLATE_PATH = STATIC_DIR / "editor.html"

# Заголовок initData в POST-запросах.
INIT_DATA_HEADER = "X-Telegram-Init-Data"
# Query-параметр initData в GET-запросах. Telegram Web App не передаёт initData
# автоматически в URL — клиент сам подставляет его через JS перед навигацией.
# В нашем случае editor.html сам подключает <script>telegram-web-app.js</script>
# и читает initData в браузере, поэтому GET /edit может быть **без** initData
# и просто отдаёт HTML-шаблон. Реальная защита — на POST /edit/submit, где
# отказ невалидному initData блокирует запись.
INIT_DATA_QUERY_PARAM = "_auth"


def _injected_init(payload: dict[str, Any]) -> str:
    """Инжектит payload в editor.html как window.__INIT__.

    JSON-encode + замена `</` на `<\\/` чтобы не сломать HTML, если в title/body
    окажется буквальная последовательность `</script>`.
    """
    encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"<script>window.__INIT__ = {encoded};</script>"


def _render_editor(draft: Draft) -> str:
    template = EDITOR_TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = {
        "draft_id": draft.id,
        "title": draft.title or "",
        "body": draft.formatted or "",
        "workspace": draft.workspace,
        "note_type": draft.note_type or "note",
    }
    init_script = _injected_init(payload)
    # Вставляем сразу перед закрывающим </body> чтобы скрипт editor.html
    # (он идёт ниже) увидел window.__INIT__ при инициализации.
    marker = "</main>"
    if marker in template:
        return template.replace(marker, marker + "\n" + init_script, 1)
    # Fallback: перед </body>.
    return template.replace("</body>", init_script + "\n</body>", 1)


async def _read_init_data(request: web.Request) -> Optional[dict]:
    """Извлечь и провалидировать initData из запроса. None если невалидно."""
    bot_token: str = request.app["bot_token"]
    init_data = request.headers.get(INIT_DATA_HEADER)
    if not init_data:
        init_data = request.query.get(INIT_DATA_QUERY_PARAM)
    if not init_data:
        return None
    return validate_init_data(init_data, bot_token)


async def handle_editor(request: web.Request) -> web.Response:
    """GET /edit?draft_id=X — отдаёт HTML с предзаполненной формой.

    initData в GET опциональна: если есть и валидна — проверяем владельца и
    отдаём конкретный draft; если нет — отдаём 401, чтобы случайные открытия
    URL без Telegram-контекста не светили чужие данные. (Браузер без Telegram
    initData увидит 401 — это намеренно.)
    """
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

    html = _render_editor(draft)
    return web.Response(text=html, content_type="text/html", charset="utf-8")


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
