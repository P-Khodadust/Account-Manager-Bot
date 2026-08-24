"""
/start command and main menu navigation.
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from bot import database as db
from bot.utils.decorators import authorized
from bot.utils.keyboards import main_menu_kb

router = Router(name="start")

WELCOME_TEXT = (
    "🏠 <b>Account Manager</b>\n"
    "━━━━━━━━━━━━\n\n"
    "Welcome! Use the menu below to manage\n"
    "your Telegram accounts.\n\n"
    "🔑  <b>Grant Account Access</b> — Add a new account\n"
    "📊  <b>Statistics</b> — View your account metrics\n"
    "📦  <b>Deliver Accounts</b> — Export or deliver\n"
    "🌐  <b>Proxy Settings</b> — Configure SOCKS5 proxies\n"
)


@router.message(CommandStart())
@authorized
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id
    is_admin = await db.is_user_admin(user_id)
    suspicious = await db.get_suspicious_accounts(user_id)
    await message.answer(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_kb(
            is_admin, has_suspicious=bool(suspicious)
        ),
    )


@router.callback_query(F.data == "main_menu")
@authorized
async def cb_main_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    is_admin = await db.is_user_admin(user_id)
    suspicious = await db.get_suspicious_accounts(user_id)
    await callback.message.edit_text(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_kb(
            is_admin, has_suspicious=bool(suspicious)
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    """Silently acknowledge decorative buttons (e.g. page indicators)."""
    await callback.answer()
