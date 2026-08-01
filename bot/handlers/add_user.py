"""
User management (admin only):
  - Add authorized user by Telegram ID
  - View user list
  - Remove user
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import database as db
from bot.config import ADMIN_ID
from bot.utils.decorators import admin_only
from bot.utils.keyboards import (
    manage_users_kb,
    user_detail_kb,
    cancel_kb,
    main_menu_kb,
)

router = Router(name="add_user")


class AddUserStates(StatesGroup):
    waiting_id = State()


# ── Show user list ───────────────────────────────────────────────────

@router.callback_query(F.data == "manage_users")
@admin_only
async def cb_manage_users(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    users = await db.get_authorized_users()
    await callback.message.edit_text(
        "👤 <b>User Management</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"Total authorized users: <b>{len(users)}</b>\n\n"
        "Select a user to manage or add a new one.",
        parse_mode="HTML",
        reply_markup=manage_users_kb(users),
    )
    await callback.answer()


# ── Start add user flow ──────────────────────────────────────────────

@router.callback_query(F.data == "user_add")
@admin_only
async def cb_user_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "➕ <b>Add New User</b>\n"
        "━━━━━━━━━━━━\n\n"
        "Please send the <b>Telegram numeric ID</b>\n"
        "of the user you want to authorize.\n\n"
        "💡 <i>Users can find their ID using @userinfobot</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb("manage_users"),
    )
    await state.set_state(AddUserStates.waiting_id)
    await callback.answer()


@router.message(AddUserStates.waiting_id)
@admin_only
async def on_user_id_received(message: Message, state: FSMContext) -> None:
    text = message.text.strip()

    try:
        telegram_id = int(text)
    except ValueError:
        await message.answer(
            "⚠️ Please enter a valid numeric Telegram ID.",
            parse_mode="HTML",
            reply_markup=cancel_kb("manage_users"),
        )
        return

    added = await db.add_authorized_user(
        telegram_id=telegram_id,
        added_by=message.from_user.id,
        label=f"User {telegram_id}",
    )

    if added:
        await message.answer(
            f"✅ <b>User Added!</b>\n\n"
            f"Telegram ID: <code>{telegram_id}</code>\n"
            f"They can now use the bot.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin=True),
        )
    else:
        await message.answer(
            f"ℹ️ User <code>{telegram_id}</code> is already authorized.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin=True),
        )

    await state.clear()


# ── View user detail ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("user_view:"))
@admin_only
async def cb_user_view(callback: CallbackQuery) -> None:
    telegram_id = int(callback.data.split(":")[1])

    is_main_admin = (telegram_id == ADMIN_ID)
    admin_badge = " 👑 Main Admin" if is_main_admin else ""

    await callback.message.edit_text(
        f"👤 <b>User Details</b>\n"
        f"━━━━━━━━━━━━\n\n"
        f"🆔  Telegram ID: <code>{telegram_id}</code>{admin_badge}\n",
        parse_mode="HTML",
        reply_markup=user_detail_kb(telegram_id) if not is_main_admin else manage_users_kb(await db.get_authorized_users()),
    )
    await callback.answer()


# ── Remove user ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("user_remove:"))
@admin_only
async def cb_user_remove(callback: CallbackQuery) -> None:
    telegram_id = int(callback.data.split(":")[1])

    if telegram_id == ADMIN_ID:
        await callback.answer("🚫 Cannot remove the main admin.", show_alert=True)
        return

    removed = await db.remove_authorized_user(telegram_id)

    if removed:
        await callback.answer("✅ User removed.", show_alert=True)
    else:
        await callback.answer("⚠️ User not found.", show_alert=True)

    # Refresh the user list
    users = await db.get_authorized_users()
    await callback.message.edit_text(
        "👤 <b>User Management</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"Total authorized users: <b>{len(users)}</b>\n\n"
        "Select a user to manage or add a new one.",
        parse_mode="HTML",
        reply_markup=manage_users_kb(users),
    )
