"""
Account addition flow:
  1. User clicks "Grant Account Access"
  2. Bot asks for phone number
  3. Bot sends login code via Telegram API
  4. User provides login code
  5. If 2FA -> bot asks for password
  6. Account saved to database

Proxy rotation: uses get_active_proxy() so the rotation counter
determines which proxy is used.  After a successful account save
the counter is incremented.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import database as db
from bot.utils.decorators import authorized
from bot.utils.keyboards import cancel_kb, main_menu_kb
from bot.utils.country_detector import detect_country, format_phone_display
from bot.utils.session_manager import request_code, submit_code, submit_2fa

logger = logging.getLogger(__name__)

router = Router(name="add_account")


# ── FSM States ───────────────────────────────────────────────────────

class AddAccountStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_2fa = State()


# ── Step 1: Start flow ──────────────────────────────────────────────

@router.callback_query(F.data == "add_account")
@authorized
async def cb_add_account(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.clear()
    await callback.message.edit_text(
        "\U0001f511 <b>Grant Account Access</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        "Please send the <b>phone number</b> of the\n"
        "Telegram account you want to add.\n\n"
        "\U0001f4dd <i>Format: +1234567890 (with country code)</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AddAccountStates.waiting_phone)
    await callback.answer()


# ── Step 2: Receive phone number ────────────────────────────────────

@router.message(AddAccountStates.waiting_phone)
@authorized
async def on_phone_received(message: Message, state: FSMContext) -> None:
    phone = message.text.strip()

    # Basic validation
    if not phone.startswith("+") or len(phone) < 8:
        await message.answer(
            "\u26a0\ufe0f Please enter a valid phone number starting "
            "with <b>+</b>\n"
            "Example: <code>+14155552671</code>",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        return

    # Detect country
    country = detect_country(phone)
    display_phone = format_phone_display(phone)

    await message.answer(
        f"\U0001f4f1 Phone: <b>{display_phone}</b>\n"
        f"\U0001f30d Country: <b>{country}</b>\n\n"
        f"\u23f3 Sending login code\u2026",
        parse_mode="HTML",
    )

    # Get user's proxy (rotation-aware)
    proxy = await db.get_active_proxy(message.from_user.id)

    # Request login code
    client, result = await request_code(phone, proxy=proxy)

    if result.error:
        await message.answer(
            result.error,
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        await state.clear()
        return

    if result.needs_code:
        # Store data in FSM
        await state.update_data(
            phone=phone,
            country=country,
            phone_code_hash=result.phone_code_hash,
        )
        # Save the pending session string so we can reconnect later
        pending_session = client.session.save()
        await state.update_data(pending_session=pending_session)
        await client.disconnect()

        await message.answer(
            "\u2705 <b>Login code sent!</b>\n\n"
            "\U0001f4e8 Please enter the login code you received\n"
            "in Telegram on that account.\n\n"
            "\U0001f4a1 <i>The code is usually 5 digits.</i>",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        await state.set_state(AddAccountStates.waiting_code)
    else:
        await client.disconnect()
        await message.answer(
            "\u274c Unexpected error. Please try again.",
            reply_markup=cancel_kb(),
        )
        await state.clear()


# ── Step 3: Receive login code ──────────────────────────────────────

@router.message(AddAccountStates.waiting_code)
@authorized
async def on_code_received(message: Message, state: FSMContext) -> None:
    code = message.text.strip()
    data = await state.get_data()

    phone = data["phone"]
    phone_code_hash = data["phone_code_hash"]
    pending_session = data.get("pending_session")

    # Reconnect client with the pending session
    from bot.utils.session_manager import create_client

    proxy = await db.get_active_proxy(message.from_user.id)
    client = create_client(session=pending_session, proxy=proxy)
    await client.connect()

    result = await submit_code(client, phone, code, phone_code_hash)

    if result.error:
        await client.disconnect()
        await message.answer(
            f"{result.error}\n\n"
            "Please enter the code again or /start to cancel.",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        return

    if result.needs_2fa:
        # Save updated session for 2FA step
        updated_session = client.session.save()
        await state.update_data(pending_session=updated_session)
        await client.disconnect()

        await message.answer(
            "\U0001f510 <b>Two-Factor Authentication</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\n\n"
            "This account has 2FA enabled.\n"
            "Please enter your <b>cloud password</b>.",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        await state.set_state(AddAccountStates.waiting_2fa)
        return

    if result.success:
        await client.disconnect()
        await _save_account(message, state, result)
        return

    await client.disconnect()
    await message.answer(
        "\u274c An unexpected error occurred. Please try again.",
        reply_markup=cancel_kb(),
    )
    await state.clear()


# ── Step 4: Receive 2FA password ────────────────────────────────────

@router.message(AddAccountStates.waiting_2fa)
@authorized
async def on_2fa_received(message: Message, state: FSMContext) -> None:
    password = message.text.strip()
    data = await state.get_data()
    pending_session = data.get("pending_session")

    proxy = await db.get_active_proxy(message.from_user.id)

    from bot.utils.session_manager import create_client

    client = create_client(session=pending_session, proxy=proxy)
    await client.connect()

    result = await submit_2fa(client, password)
    await client.disconnect()

    if result.error:
        await message.answer(
            f"{result.error}\n\nPlease try again or /start to cancel.",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        return

    if result.success:
        await _save_account(message, state, result)
        return

    await message.answer(
        "\u274c An unexpected error occurred. Please try again.",
        reply_markup=cancel_kb(),
    )
    await state.clear()


# ── Save account to database ────────────────────────────────────────

async def _save_account(
    message: Message, state: FSMContext, result
) -> None:
    data = await state.get_data()
    phone = data["phone"]
    country = data["country"]
    display_phone = format_phone_display(phone)

    try:
        account = await db.add_account(
            owner_id=message.from_user.id,
            phone=phone,
            country=country,
            session_string=result.session_string,
            tg_user_id=(
                result.user_info.get("id") if result.user_info else None
            ),
            first_name=(
                result.user_info.get("first_name")
                if result.user_info
                else None
            ),
            username=(
                result.user_info.get("username")
                if result.user_info
                else None
            ),
        )

        # Increment proxy rotation counter after successful save
        await db.increment_rotation_counter(message.from_user.id)

        name = (
            result.user_info.get("first_name", "")
            if result.user_info
            else ""
        )
        username = (
            result.user_info.get("username", "")
            if result.user_info
            else ""
        )
        uname_str = f" (@{username})" if username else ""

        is_admin = await db.is_user_admin(message.from_user.id)
        await message.answer(
            "\u2705 <b>Account Added Successfully!</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\n\n"
            f"\U0001f4f1  Phone: <b>{display_phone}</b>\n"
            f"\U0001f464  Name: <b>{name}{uname_str}</b>\n"
            f"\U0001f30d  Country: <b>{country}</b>\n"
            f"\U0001f4c5  Date: "
            f"<b>{account.date_added.strftime('%B %d, %Y')}</b>\n\n"
            "The account has been saved and categorized.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin),
        )
    except Exception as e:
        logger.exception("Failed to save account")
        if (
            "uq_owner_phone" in str(e).lower()
            or "unique" in str(e).lower()
        ):
            await message.answer(
                "\u26a0\ufe0f This phone number is already in your "
                "account list.",
                parse_mode="HTML",
                reply_markup=cancel_kb(),
            )
        else:
            await message.answer(
                f"\u274c Error saving account: {e}",
                parse_mode="HTML",
                reply_markup=cancel_kb(),
            )

    await state.clear()
