import asyncio
import html
import logging
import os
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.domain.note_types import TYPES
from bot.domain.workspaces import WORKSPACES
from bot.handlers import callbacks, commands, documents, edit, inputs, voice
from bot.middlewares.auth import AuthMiddleware
from bot.services import llm_processor
from bot.services.sinks import PageRef
from bot.services.sinks import buildin as buildin_sink
from bot.services.sinks import notion as notion_sink
from bot.storage import db, drafts
from bot.storage.drafts import Draft
from bot.workers import outbox_worker


logger = logging.getLogger(__name__)

STUCK_SAVING_THRESHOLD_SECS = 300  # 5 minutes

# Сколько ждать завершения текущего outbox-attempt при shutdown. Чуть больше
# httpx-таймаута (30s), чтобы успеть докрутить in-flight запрос.
WORKER_SHUTDOWN_TIMEOUT_SECS = 35.0


async def _buildin_health_check() -> None:
    """Validate Buildin token + проверить, что заданы space_id для каждого workspace.

    Fail-fast при неправильной настройке: бот не должен стартовать со сломанным
    sink, иначе все save'ы пойдут в backoff и user не увидит причину.
    """
    if settings.NOTES_PROVIDER != "buildin":
        return
    if not settings.buildin_enabled:
        logger.warning(
            "NOTES_PROVIDER=buildin, но BUILDIN_TOKEN пуст — sink работает в stub-режиме"
        )
        return
    try:
        me = await buildin_sink.users_me()
    except Exception as exc:
        raise RuntimeError(f"Buildin health-check failed (GET /v1/users/me): {exc}") from exc
    bot_name = me.get("name") or me.get("id") or "<unknown>"
    logger.info("Buildin auth OK — bot=%s", bot_name)

    missing = [w.space_env for w in WORKSPACES if not settings.buildin_space_id(w.key)]
    if missing:
        logger.warning(
            "Не заданы env-переменные spaces: %s — соответствующие workspace'ы "
            "будут писать через fallback DB, а setup_buildin_dbs не сможет создать DBs",
            ", ".join(missing),
        )

    # Резолвим database id для каждой пары (workspace, type), чтобы вылавливать
    # опечатки в env-именах (BUILDIN_DB_<WS>_<TYPE>): pydantic их не валидирует
    # из-за extra="ignore", иначе ошибка проявится только при первом сохранении.
    fallbacks: list[str] = []
    no_db: list[str] = []
    for w in WORKSPACES:
        for t in TYPES:
            ws_env = f"BUILDIN_DB_{w.key.upper()}_{t.key.upper()}"
            type_env = f"BUILDIN_DB_{t.key.upper()}"
            resolved = settings.database_id_for(
                t.db_env, provider="buildin", workspace_key=w.key
            )
            if resolved is None:
                no_db.append(f"{w.key}/{t.key}")
            elif resolved == settings.BUILDIN_DB_DEFAULT and not (
                os.environ.get(ws_env) or os.environ.get(type_env)
            ):
                fallbacks.append(f"{w.key}/{t.key}")
    if fallbacks:
        logger.info(
            "buildin DB fallback на BUILDIN_DB_DEFAULT для: %s",
            ", ".join(fallbacks),
        )
    if no_db:
        logger.warning(
            "buildin DB не сконфигурирован для: %s — сохранения в эти ws/type "
            "будут падать. Задай BUILDIN_DB_<WS>_<TYPE> или BUILDIN_DB_DEFAULT.",
            ", ".join(no_db),
        )


async def _recover_stuck_drafts() -> None:
    """Drafts left in `saving` past the threshold likely belong to a crashed run.

    Move them back to `awaiting_confirm` so the user can retry from /list, or
    so a fresh outbox entry (if still present) can pick them up cleanly.
    """
    stale = await drafts.find_stale_saving(STUCK_SAVING_THRESHOLD_SECS)
    for draft in stale:
        await drafts.update(draft.id, status="awaiting_confirm")
        logger.warning("recovered stuck draft id=%s back to awaiting_confirm", draft.id)


def _make_save_callbacks(bot: Bot):
    async def on_saved(draft: Draft, page_ref: PageRef) -> None:
        if draft.preview_msg_id is None:
            return
        provider_label = "Buildin" if settings.NOTES_PROVIDER == "buildin" else "Notion"
        if page_ref.url:
            url_attr = html.escape(page_ref.url, quote=True)
            text = f'✅ <a href="{url_attr}">Открыть в {provider_label}</a>'
        else:
            text = f"✅ Сохранено в {provider_label}\n<code>{page_ref.id}</code>"
        with suppress(Exception):
            await bot.edit_message_text(
                chat_id=draft.chat_id,
                message_id=draft.preview_msg_id,
                text=text,
                disable_web_page_preview=True,
            )

    async def on_failed(draft: Draft, error: str) -> None:
        if draft.preview_msg_id is None:
            return
        with suppress(Exception):
            await bot.edit_message_text(
                chat_id=draft.chat_id,
                message_id=draft.preview_msg_id,
                text=f"⚠️ Не получилось сохранить (см. /retry).\n<i>{error}</i>",
            )

    return on_saved, on_failed


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_path = settings.DATABASE_PATH
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    os.makedirs(settings.TEMP_DIR, exist_ok=True)
    await db.init_db(db_path)
    await _buildin_health_check()
    await _recover_stuck_drafts()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(voice.router)
    dp.include_router(documents.router)
    dp.include_router(edit.router)
    dp.include_router(inputs.router)

    on_saved, on_failed = _make_save_callbacks(bot)
    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(
        outbox_worker.run(stop_event, on_saved=on_saved, on_failed=on_failed)
    )

    logging.info("Bot started. Allowed users: %s", settings.allowed_user_ids)
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(worker_task, timeout=WORKER_SHUTDOWN_TIMEOUT_SECS)
        except asyncio.TimeoutError:
            logger.warning(
                "outbox worker не завершился за %ss — отменяем in-flight",
                WORKER_SHUTDOWN_TIMEOUT_SECS,
            )
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
        except asyncio.CancelledError:
            pass
        await llm_processor.close_client()
        await buildin_sink.close()
        await notion_sink.close()
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
