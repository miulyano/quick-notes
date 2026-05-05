import asyncio
import logging
import os
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.domain.workspaces import WORKSPACES
from bot.handlers import callbacks, commands, inputs, voice
from bot.middlewares.auth import AuthMiddleware
from bot.services.sinks import buildin as buildin_sink
from bot.storage import db, drafts
from bot.storage.drafts import Draft
from bot.workers import outbox_worker


logger = logging.getLogger(__name__)

STUCK_SAVING_THRESHOLD_SECS = 300  # 5 minutes


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
    async def on_saved(draft: Draft, page_id: str) -> None:
        if draft.preview_msg_id is None:
            return
        provider_label = "Buildin" if settings.NOTES_PROVIDER == "buildin" else "Notion"
        with suppress(Exception):
            await bot.edit_message_text(
                chat_id=draft.chat_id,
                message_id=draft.preview_msg_id,
                text=f"✅ Сохранено в {provider_label}\n<code>{page_id}</code>",
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
        with suppress(asyncio.CancelledError):
            await worker_task
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
