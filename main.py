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
from bot.database import init_db, ensure_admin

# ── Handlers ─────────────────────────────────────────────────────────
from bot.handlers.start import router as start_router
from bot.handlers.add_account import router as add_account_router
from bot.handlers.add_user import router as add_user_router
from bot.handlers.statistics import router as statistics_router
from bot.handlers.deliver import router as deliver_router
from bot.handlers.proxy import router as proxy_router

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    """Run once when the bot starts."""
    await init_db()
    await ensure_admin(ADMIN_ID)

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

    # Register routers (order matters — first match wins for FSM states)
    dp.include_router(start_router)
    dp.include_router(add_account_router)
    dp.include_router(add_user_router)
    dp.include_router(statistics_router)
    dp.include_router(deliver_router)
    dp.include_router(proxy_router)

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
