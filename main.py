"""
Entry point — Telegram Account Manager Bot.

Usage:
    python main.py
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN, ADMIN_ID
from bot.middlewares import SuppressNotModifiedMiddleware
from bot.database import (
    init_db,
    ensure_admin,
    run_migrations,
    get_authorized_users,
    get_all_active_accounts,
    get_default_proxy,
    mark_account_status,
    mark_suspicious,
)

# ── Handlers ─────────────────────────────────────────────────────────
from bot.handlers.start import router as start_router
from bot.handlers.add_account import router as add_account_router
from bot.handlers.add_user import router as add_user_router
from bot.handlers.statistics import router as statistics_router
from bot.handlers.deliver import router as deliver_router
from bot.handlers.proxy import router as proxy_router
from bot.handlers.twofa import router as twofa_router

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── Periodic Session Validation ──────────────────────────────────────

async def periodic_session_check(bot: Bot) -> None:
    """Validate all stored sessions every 6 hours.

    Marks removed / banned accounts as inactive automatically so
    statistics stay accurate without manual intervention. The owner
    is DM'd whenever a session ends unexpectedly so they know it
    became suspicious and was removed from their stats.
    """
    from bot.utils.session_manager import validate_session

    await asyncio.sleep(300)  # initial 5-min delay after startup

    while True:
        try:
            users = await get_authorized_users()
            for user in users:
                accounts = await get_all_active_accounts(user.telegram_id)
                if not accounts:
                    continue

                proxy = await get_default_proxy(user.telegram_id)
                invalidated = 0

                for acc in accounts:
                    try:
                        status = await validate_session(
                            acc.session_string, proxy
                        )
                        if status in ("removed", "invalid"):
                            await mark_account_status(acc.id, status)
                            await mark_suspicious(acc.id, True)
                            invalidated += 1
                            logger.info(
                                "Auto-detected: account %s (%s) → %s",
                                acc.phone,
                                acc.id,
                                status,
                            )
                            try:
                                reason = (
                                    "logged out elsewhere"
                                    if status == "removed"
                                    else "deactivated/banned"
                                )
                                await bot.send_message(
                                    acc.owner_id,
                                    "⚠️ <b>Session expired</b>\n"
                                    "━━━━━━━━━━━━\n\n"
                                    f"📱 <code>{acc.phone}</code>\n"
                                    f"Reason: <i>{reason}</i>\n\n"
                                    "The account has been marked as "
                                    "<b>suspicious</b> and removed "
                                    "from your statistics.",
                                    parse_mode="HTML",
                                )
                            except Exception:
                                logger.exception(
                                    "Failed to notify owner of expired "
                                    "session for %s",
                                    acc.phone,
                                )
                    except Exception:
                        pass  # skip individual errors
                    # Small delay between accounts to avoid flooding
                    await asyncio.sleep(2)

                if invalidated:
                    logger.info(
                        "User %s: %d session(s) invalidated this cycle.",
                        user.telegram_id,
                        invalidated,
                    )
        except Exception:
            logger.exception("Error in periodic session validation")

        await asyncio.sleep(6 * 3600)  # run every 6 hours


# ── Startup / Main ───────────────────────────────────────────────────

async def on_startup(bot: Bot) -> None:
    """Run once when the bot starts."""
    await init_db()
    await run_migrations()
    await ensure_admin(ADMIN_ID)

    # Launch background session validator
    asyncio.create_task(periodic_session_check(bot))

    me = await bot.get_me()
    logger.info(
        "Bot started as @%s (ID: %s)",
        me.username,
        me.id,
    )
    logger.info("Admin ID: %s", ADMIN_ID)


async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Ignore "message is not modified" from double-clicked inline buttons
    not_modified_mw = SuppressNotModifiedMiddleware()
    dp.callback_query.outer_middleware(not_modified_mw)
    dp.message.outer_middleware(not_modified_mw)

    # Register routers (order matters — first match wins for FSM states)
    dp.include_router(start_router)
    dp.include_router(add_account_router)
    dp.include_router(add_user_router)
    dp.include_router(statistics_router)
    dp.include_router(deliver_router)
    dp.include_router(proxy_router)
    dp.include_router(twofa_router)

    # Startup hook
    dp.startup.register(on_startup)

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
