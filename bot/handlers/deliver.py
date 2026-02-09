"""
Account delivery — two methods:

Method 1  Individual Account Delivery
  → Select country → date → account → get login code → deliver

Method 2  Bulk Session File Delivery
  → Choose format (Telethon/Pyrogram) → country → date → quantity
  → Convert sessions → ZIP → send → optionally logout
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import io
import logging
import tempfile
import zipfile
from pathlib import Path

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)

from bot import database as db
from bot.config import SESSIONS_DIR
from bot.utils.decorators import authorized
from bot.utils.keyboards import (
    account_actions_kb,
    account_list_kb,
    cancel_kb,
    confirm_kb,
    country_select_kb,
    date_select_kb,
    deliver_menu_kb,
    main_menu_kb,
    session_format_kb,
)
from bot.utils.session_manager import (
    logout_account,
    request_delivery_code,
    submit_code,
    telethon_string_to_pyrogram_session,
    telethon_string_to_session_file,
)

logger = logging.getLogger(__name__)

router = Router(name="deliver")


# ── FSM States ───────────────────────────────────────────────────────

class DeliverStates(StatesGroup):
    # Individual delivery
    ind_waiting_code = State()
    # Bulk delivery
    bulk_waiting_quantity = State()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deliver menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "deliver_menu")
@authorized
async def cb_deliver_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "📦 <b>Deliver Accounts</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose your delivery method:\n\n"
        "📱  <b>Individual</b> — Deliver one account at a time\n"
        "📁  <b>Bulk Sessions</b> — Export multiple session files as ZIP",
        parse_mode="HTML",
        reply_markup=deliver_menu_kb(),
    )
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# METHOD 1: Individual Account Delivery
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "deliver_individual")
@authorized
async def cb_deliver_individual(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    countries = await db.get_countries_for_owner(user_id)

    if not countries:
        await callback.answer("📭 You don't have any accounts.", show_alert=True)
        return

    await state.update_data(delivery_mode="individual")
    await callback.message.edit_text(
        "📱 <b>Individual Delivery</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a country category:",
        parse_mode="HTML",
        reply_markup=country_select_kb(countries, prefix="ind_country", back_cb="deliver_menu"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ind_country:"))
@authorized
async def cb_ind_country(callback: CallbackQuery, state: FSMContext) -> None:
    country = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    dates = await db.get_dates_for_country(user_id, country)
    if not dates:
        await callback.answer("📭 No accounts in this category.", show_alert=True)
        return

    await state.update_data(ind_country=country)

    # Calculate counts per date
    counts = {}
    for d in dates:
        d_val = d if isinstance(d, _dt.date) and not isinstance(d, _dt.datetime) else d
        if isinstance(d_val, _dt.datetime):
            d_val = d_val.date()
        accs = await db.get_accounts_filtered(user_id, country, d)
        counts[d_val.isoformat()] = len(accs)

    await callback.message.edit_text(
        f"📱 <b>Individual Delivery</b> → <b>{country}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a date category:",
        parse_mode="HTML",
        reply_markup=date_select_kb(dates, prefix="ind_date", back_cb="deliver_individual", counts=counts),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ind_date:"))
@authorized
async def cb_ind_date(callback: CallbackQuery, state: FSMContext) -> None:
    date_iso = callback.data.split(":", 1)[1]
    date_obj = _dt.date.fromisoformat(date_iso)
    data = await state.get_data()
    country = data.get("ind_country", "")
    user_id = callback.from_user.id

    accounts = await db.get_accounts_filtered(user_id, country, date_obj)
    if not accounts:
        await callback.answer("📭 No accounts found.", show_alert=True)
        return

    await state.update_data(ind_date=date_iso)
    date_label = date_obj.strftime("%B %d, %Y")

    await callback.message.edit_text(
        f"📱 <b>Individual Delivery</b>\n"
        f"🌍 {country}  •  📅 {date_label}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Found <b>{len(accounts)}</b> account(s).\n"
        "Select an account to deliver:",
        parse_mode="HTML",
        reply_markup=account_list_kb(accounts, prefix="ind_acc", back_cb=f"ind_country:{country}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ind_acc:"))
@authorized
async def cb_ind_acc_select(callback: CallbackQuery, state: FSMContext) -> None:
    account_id = int(callback.data.split(":")[1])
    account = await db.get_account_by_id(account_id)

    if not account or account.owner_id != callback.from_user.id:
        await callback.answer("⚠️ Account not found.", show_alert=True)
        return

    await state.update_data(ind_account_id=account_id)

    # Request delivery code
    proxy = await db.get_default_proxy(callback.from_user.id)
    client, result = await request_delivery_code(
        account.session_string, account.phone, proxy=proxy
    )

    if result.error:
        await callback.message.edit_text(
            f"❌ <b>Delivery Error</b>\n\n{result.error}",
            parse_mode="HTML",
            reply_markup=account_actions_kb(account_id),
        )
        await callback.answer()
        return

    if result.needs_code:
        await state.update_data(
            delivery_phone=account.phone,
            delivery_phone_code_hash=result.phone_code_hash,
        )
        if client:
            pending = client.session.save()
            await state.update_data(delivery_pending_session=pending)
            await client.disconnect()

        await callback.message.edit_text(
            f"📱 <b>Delivering Account</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Phone: <b>{account.phone}</b>\n\n"
            "📨 A login code has been sent to this account.\n"
            "Please enter the code below:",
            parse_mode="HTML",
            reply_markup=account_actions_kb(account_id),
        )
        await state.set_state(DeliverStates.ind_waiting_code)
        await callback.answer()


# Receive login code for individual delivery
@router.message(DeliverStates.ind_waiting_code)
@authorized
async def on_ind_code_received(message: Message, state: FSMContext) -> None:
    code = message.text.strip()
    data = await state.get_data()

    account_id = data.get("ind_account_id")
    account = await db.get_account_by_id(account_id)
    if not account:
        await message.answer("⚠️ Account not found.", reply_markup=cancel_kb("deliver_menu"))
        await state.clear()
        return

    phone = data.get("delivery_phone", account.phone)
    phone_code_hash = data.get("delivery_phone_code_hash")
    pending_session = data.get("delivery_pending_session")

    from bot.utils.session_manager import create_client
    proxy = await db.get_default_proxy(message.from_user.id)
    client = create_client(session=pending_session, proxy=proxy)
    await client.connect()

    result = await submit_code(client, phone, code, phone_code_hash)
    session_string = client.session.save()
    await client.disconnect()

    if result.error:
        await message.answer(
            f"{result.error}\n\nTry again or use the buttons below.",
            parse_mode="HTML",
            reply_markup=account_actions_kb(account_id),
        )
        return

    if result.success:
        # Deliver the account credentials
        is_admin = await db.is_user_admin(message.from_user.id)
        await message.answer(
            "✅ <b>Account Delivered!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📱  Phone: <code>{account.phone}</code>\n"
            f"🔑  Session: <code>{session_string[:50]}...</code>\n"
            f"👤  Name: {account.first_name or 'N/A'}\n"
            f"🌍  Country: {account.country}\n\n"
            "📋 <i>Full session string sent below.</i>",
            parse_mode="HTML",
            reply_markup=account_actions_kb(account_id),
        )

        # Send full session string as a separate message
        await message.answer(
            f"<code>{session_string}</code>",
            parse_mode="HTML",
        )
        await state.set_state(None)
        return

    await message.answer(
        "❌ Unexpected error. Please try again.",
        reply_markup=account_actions_kb(account_id),
    )


# ── Resend Code ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("resend_code:"))
@authorized
async def cb_resend_code(callback: CallbackQuery, state: FSMContext) -> None:
    account_id = int(callback.data.split(":")[1])
    account = await db.get_account_by_id(account_id)

    if not account or account.owner_id != callback.from_user.id:
        await callback.answer("⚠️ Account not found.", show_alert=True)
        return

    proxy = await db.get_default_proxy(callback.from_user.id)
    client, result = await request_delivery_code(
        account.session_string, account.phone, proxy=proxy
    )

    if result.error:
        await callback.answer(result.error, show_alert=True)
        return

    if result.needs_code:
        await state.update_data(
            delivery_phone=account.phone,
            delivery_phone_code_hash=result.phone_code_hash,
            ind_account_id=account_id,
        )
        if client:
            pending = client.session.save()
            await state.update_data(delivery_pending_session=pending)
            await client.disconnect()

        await callback.answer("✅ New code sent!", show_alert=True)
        await state.set_state(DeliverStates.ind_waiting_code)


# ── Logout Account ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("logout_acc:"))
@authorized
async def cb_logout_account(callback: CallbackQuery, state: FSMContext) -> None:
    account_id = int(callback.data.split(":")[1])
    account = await db.get_account_by_id(account_id)

    if not account or account.owner_id != callback.from_user.id:
        await callback.answer("⚠️ Account not found.", show_alert=True)
        return

    proxy = await db.get_default_proxy(callback.from_user.id)
    success = await logout_account(account.session_string, proxy=proxy)

    if success:
        await db.deactivate_account(account_id)
        await callback.answer("✅ Account logged out and removed.", show_alert=True)
    else:
        await callback.answer("⚠️ Logout failed. Account may already be logged out.", show_alert=True)
        await db.deactivate_account(account_id)

    is_admin = await db.is_user_admin(callback.from_user.id)
    await callback.message.edit_text(
        "🚪 <b>Account Logged Out</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 {account.phone} has been logged out\n"
        "and removed from your statistics.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await state.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# METHOD 2: Bulk Session File Delivery
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "deliver_bulk")
@authorized
async def cb_deliver_bulk(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(delivery_mode="bulk")
    await callback.message.edit_text(
        "📁 <b>Bulk Session Delivery</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose the session file format:",
        parse_mode="HTML",
        reply_markup=session_format_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_format:"))
@authorized
async def cb_bulk_format(callback: CallbackQuery, state: FSMContext) -> None:
    fmt = callback.data.split(":")[1]  # "telethon" or "pyrogram"
    user_id = callback.from_user.id

    countries = await db.get_countries_for_owner(user_id)
    if not countries:
        await callback.answer("📭 You don't have any accounts.", show_alert=True)
        return

    await state.update_data(bulk_format=fmt)
    await callback.message.edit_text(
        f"📁 <b>Bulk Delivery</b> — <b>{'Telethon' if fmt == 'telethon' else 'Pyrogram'}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a country category:",
        parse_mode="HTML",
        reply_markup=country_select_kb(countries, prefix="bulk_country", back_cb="deliver_bulk"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_country:"))
@authorized
async def cb_bulk_country(callback: CallbackQuery, state: FSMContext) -> None:
    country = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    dates = await db.get_dates_for_country(user_id, country)
    if not dates:
        await callback.answer("📭 No accounts in this category.", show_alert=True)
        return

    await state.update_data(bulk_country=country)

    counts = {}
    for d in dates:
        d_val = d if isinstance(d, _dt.date) and not isinstance(d, _dt.datetime) else d
        if isinstance(d_val, _dt.datetime):
            d_val = d_val.date()
        accs = await db.get_accounts_filtered(user_id, country, d)
        counts[d_val.isoformat()] = len(accs)

    data = await state.get_data()
    fmt = data.get("bulk_format", "telethon")

    await callback.message.edit_text(
        f"📁 <b>Bulk Delivery</b> — <b>{'Telethon' if fmt == 'telethon' else 'Pyrogram'}</b> → <b>{country}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a date category:",
        parse_mode="HTML",
        reply_markup=date_select_kb(dates, prefix="bulk_date", back_cb=f"bulk_format:{fmt}", counts=counts),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_date:"))
@authorized
async def cb_bulk_date(callback: CallbackQuery, state: FSMContext) -> None:
    date_iso = callback.data.split(":", 1)[1]
    date_obj = _dt.date.fromisoformat(date_iso)
    data = await state.get_data()
    country = data.get("bulk_country", "")
    user_id = callback.from_user.id

    accounts = await db.get_accounts_filtered(user_id, country, date_obj)
    if not accounts:
        await callback.answer("📭 No accounts found.", show_alert=True)
        return

    await state.update_data(bulk_date=date_iso)
    date_label = date_obj.strftime("%B %d, %Y")

    await callback.message.edit_text(
        f"📁 <b>Bulk Delivery</b>\n"
        f"🌍 {country}  •  📅 {date_label}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Available accounts: <b>{len(accounts)}</b>\n\n"
        f"How many accounts do you want to export?\n"
        f"<i>Enter a number (1–{len(accounts)}):</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb("deliver_bulk"),
    )
    await state.set_state(DeliverStates.bulk_waiting_quantity)
    await callback.answer()


@router.message(DeliverStates.bulk_waiting_quantity)
@authorized
async def on_bulk_quantity(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    country = data.get("bulk_country", "")
    date_iso = data.get("bulk_date", "")
    fmt = data.get("bulk_format", "telethon")

    date_obj = _dt.date.fromisoformat(date_iso)
    accounts = await db.get_accounts_filtered(message.from_user.id, country, date_obj)

    try:
        qty = int(message.text.strip())
    except ValueError:
        await message.answer(
            "⚠️ Please enter a valid number.",
            reply_markup=cancel_kb("deliver_bulk"),
        )
        return

    if qty < 1 or qty > len(accounts):
        await message.answer(
            f"⚠️ Please enter a number between 1 and {len(accounts)}.",
            reply_markup=cancel_kb("deliver_bulk"),
        )
        return

    selected = accounts[:qty]

    await message.answer("⏳ Converting sessions and creating ZIP file...")

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    date_label = date_obj.strftime("%Y-%m-%d")
    ext = ".session"

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, acc in enumerate(selected, 1):
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                if fmt == "telethon":
                    success = telethon_string_to_session_file(
                        acc.session_string, tmp_path
                    )
                else:
                    success = telethon_string_to_pyrogram_session(
                        acc.session_string, tmp_path,
                        user_id=acc.tg_user_id or 0,
                    )

                if success:
                    # Read file content
                    with open(tmp_path, "rb") as f:
                        file_data = f.read()
                    # Use phone as filename
                    safe_phone = acc.phone.replace("+", "").replace(" ", "")
                    zf.writestr(f"{safe_phone}.session", file_data)
            except Exception:
                logger.exception(f"Failed to convert session for {acc.phone}")
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    zip_buffer.seek(0)
    zip_data = zip_buffer.getvalue()

    # Construct filename with date
    safe_country = country.replace(" ", "_")
    zip_filename = f"{safe_country}_{date_label}_{fmt}_{qty}accounts.zip"

    # Send ZIP file
    await message.answer_document(
        BufferedInputFile(zip_data, filename=zip_filename),
        caption=(
            f"📁 <b>Session Files Delivered!</b>\n\n"
            f"📦  Format: <b>{'Telethon' if fmt == 'telethon' else 'Pyrogram'}</b>\n"
            f"🌍  Country: <b>{country}</b>\n"
            f"📅  Date: <b>{date_obj.strftime('%B %d, %Y')}</b>\n"
            f"📊  Accounts: <b>{qty}</b>"
        ),
        parse_mode="HTML",
    )

    # Store selected account IDs for potential logout
    selected_ids = [acc.id for acc in selected]
    await state.update_data(bulk_delivered_ids=selected_ids)
    await state.set_state(None)

    # Ask about logout
    await message.answer(
        "🔒 <b>Log out of delivered accounts?</b>\n\n"
        "Would you like to log out all delivered accounts\n"
        "and remove them from your statistics?",
        parse_mode="HTML",
        reply_markup=confirm_kb("bulk_logout_yes", "bulk_logout_no"),
    )


@router.callback_query(F.data == "bulk_logout_yes")
@authorized
async def cb_bulk_logout_yes(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    delivered_ids = data.get("bulk_delivered_ids", [])

    if not delivered_ids:
        await callback.answer("No accounts to log out.", show_alert=True)
        await state.clear()
        return

    await callback.message.edit_text(
        "⏳ Logging out accounts... This may take a moment.",
        parse_mode="HTML",
    )

    proxy = await db.get_default_proxy(callback.from_user.id)
    success_count = 0

    for acc_id in delivered_ids:
        acc = await db.get_account_by_id(acc_id)
        if acc:
            try:
                await logout_account(acc.session_string, proxy=proxy)
                success_count += 1
            except Exception:
                logger.exception(f"Failed to logout account {acc_id}")

    await db.deactivate_accounts(delivered_ids)

    is_admin = await db.is_user_admin(callback.from_user.id)
    await callback.message.edit_text(
        f"✅ <b>Logout Complete</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚪  Logged out: <b>{success_count}/{len(delivered_ids)}</b> accounts\n"
        f"📊  Statistics updated.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "bulk_logout_no")
@authorized
async def cb_bulk_logout_no(callback: CallbackQuery, state: FSMContext) -> None:
    is_admin = await db.is_user_admin(callback.from_user.id)
    await callback.message.edit_text(
        "✅ Accounts kept active.\n\n"
        "Returning to main menu.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await state.clear()
    await callback.answer()
