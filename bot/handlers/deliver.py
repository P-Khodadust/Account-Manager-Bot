"""
Account delivery — two methods:

Method 1  Individual Account Delivery  (Issue #1 — code listener)
  → Select country → date → account
  → Bot connects to account session and listens for login codes
  → When Telegram sends the code (from user 777000) the bot captures it
  → Bot delivers the captured code to the user

Method 2  Bulk Session File Delivery
  → Choose format (Telethon / Pyrogram) → country → date → quantity
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
    listening_kb,
    main_menu_kb,
    session_format_kb,
)
from bot.utils.session_manager import (
    logout_account,
    start_code_listener,
    stop_code_listener,
    telethon_string_to_pyrogram_session,
    telethon_string_to_session_file,
)

logger = logging.getLogger(__name__)

router = Router(name="deliver")


# ── FSM States ───────────────────────────────────────────────────────

class DeliverStates(StatesGroup):
    # Only bulk delivery needs FSM (user types a quantity)
    bulk_waiting_quantity = State()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deliver menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "deliver_menu")
@authorized
async def cb_deliver_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    # Stop any active listener when returning to menu
    await stop_code_listener(callback.from_user.id)

    await callback.message.edit_text(
        "\U0001f4e6 <b>Deliver Accounts</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        "Choose your delivery method:\n\n"
        "\U0001f4f1  <b>Individual</b> \u2014 Deliver one account at a time\n"
        "\U0001f4c1  <b>Bulk Sessions</b> \u2014 Export multiple session "
        "files as ZIP",
        parse_mode="HTML",
        reply_markup=deliver_menu_kb(),
    )
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# METHOD 1: Individual Account Delivery  (Issue #1 rewrite)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "deliver_individual")
@authorized
async def cb_deliver_individual(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    countries = await db.get_countries_for_owner(user_id)

    if not countries:
        await callback.answer(
            "\U0001f4ed You don't have any accounts.", show_alert=True
        )
        return

    await state.update_data(delivery_mode="individual")
    await callback.message.edit_text(
        "\U0001f4f1 <b>Individual Delivery</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        "Select a country category:",
        parse_mode="HTML",
        reply_markup=country_select_kb(
            countries, prefix="ind_country", back_cb="deliver_menu"
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ind_country:"))
@authorized
async def cb_ind_country(
    callback: CallbackQuery, state: FSMContext
) -> None:
    country = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    dates = await db.get_dates_for_country(user_id, country)
    if not dates:
        await callback.answer(
            "\U0001f4ed No accounts in this category.", show_alert=True
        )
        return

    await state.update_data(ind_country=country)

    # Calculate counts per date
    counts: dict[str, int] = {}
    for d in dates:
        d_val = d
        if isinstance(d_val, _dt.datetime):
            d_val = d_val.date()
        accs = await db.get_accounts_filtered(user_id, country, d)
        counts[d_val.isoformat()] = len(accs)

    await callback.message.edit_text(
        f"\U0001f4f1 <b>Individual Delivery</b> \u2192 "
        f"<b>{country}</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        "Select a date category:",
        parse_mode="HTML",
        reply_markup=date_select_kb(
            dates,
            prefix="ind_date",
            back_cb="deliver_individual",
            counts=counts,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ind_date:"))
@authorized
async def cb_ind_date(
    callback: CallbackQuery, state: FSMContext
) -> None:
    date_iso = callback.data.split(":", 1)[1]
    date_obj = _dt.date.fromisoformat(date_iso)
    data = await state.get_data()
    country = data.get("ind_country", "")
    user_id = callback.from_user.id

    accounts = await db.get_accounts_filtered(user_id, country, date_obj)
    if not accounts:
        await callback.answer(
            "\U0001f4ed No accounts found.", show_alert=True
        )
        return

    await state.update_data(ind_date=date_iso)
    date_label = date_obj.strftime("%B %d, %Y")

    await callback.message.edit_text(
        f"\U0001f4f1 <b>Individual Delivery</b>\n"
        f"\U0001f30d {country}  \u2022  \U0001f4c5 {date_label}\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        f"Found <b>{len(accounts)}</b> account(s).\n"
        "Select an account to deliver:",
        parse_mode="HTML",
        reply_markup=account_list_kb(
            accounts,
            prefix="ind_acc",
            back_cb=f"ind_country:{country}",
        ),
    )
    await callback.answer()


# ── Select account → start listening ────────────────────────────────

@router.callback_query(F.data.startswith("ind_acc:"))
@authorized
async def cb_ind_acc_select(
    callback: CallbackQuery, state: FSMContext
) -> None:
    account_id = int(callback.data.split(":")[1])
    account = await db.get_account_by_id(account_id)

    if not account or account.owner_id != callback.from_user.id:
        await callback.answer(
            "\u26a0\ufe0f Account not found.", show_alert=True
        )
        return

    # Get proxy (rotation-aware)
    proxy = await db.get_active_proxy(callback.from_user.id)

    # Start background code listener
    success, error = await start_code_listener(
        session_string=account.session_string,
        phone=account.phone,
        account_id=account_id,
        user_id=callback.from_user.id,
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        proxy=proxy,
    )

    if not success:
        await callback.message.edit_text(
            f"\u274c <b>Delivery Error</b>\n\n{error}",
            parse_mode="HTML",
            reply_markup=account_actions_kb(account_id),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "\U0001f4f1 <b>Listening for Login Code</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        f"Phone: <code>{account.phone}</code>\n\n"
        "\U0001f442 I'm now monitoring this account for\n"
        "incoming login codes.\n\n"
        "\U0001f4dd <b>Instructions:</b>\n"
        "1. Log into this account on another device\n"
        "2. Telegram will send a code to this account\n"
        "3. I'll capture and deliver it to you\n\n"
        "\u23f3 <i>Listening\u2026 (5 min timeout)</i>",
        parse_mode="HTML",
        reply_markup=listening_kb(account_id),
    )
    await callback.answer()


# ── Resend / Restart Listener ────────────────────────────────────────

@router.callback_query(F.data.startswith("resend_code:"))
@authorized
async def cb_resend_code(
    callback: CallbackQuery, state: FSMContext
) -> None:
    account_id = int(callback.data.split(":")[1])
    account = await db.get_account_by_id(account_id)

    if not account or account.owner_id != callback.from_user.id:
        await callback.answer(
            "\u26a0\ufe0f Account not found.", show_alert=True
        )
        return

    proxy = await db.get_active_proxy(callback.from_user.id)

    success, error = await start_code_listener(
        session_string=account.session_string,
        phone=account.phone,
        account_id=account_id,
        user_id=callback.from_user.id,
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        proxy=proxy,
    )

    if not success:
        await callback.answer(
            f"Error: {error}", show_alert=True
        )
        return

    await callback.message.edit_text(
        "\U0001f504 <b>Listener Restarted</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        f"Phone: <code>{account.phone}</code>\n\n"
        "\U0001f442 Listening for new login code\u2026\n"
        "Please attempt to log in again.\n\n"
        "\u23f3 <i>Listening\u2026 (5 min timeout)</i>",
        parse_mode="HTML",
        reply_markup=listening_kb(account_id),
    )
    await callback.answer("\u2705 Listener restarted!", show_alert=True)


# ── Logout Account ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("logout_acc:"))
@authorized
async def cb_logout_account(
    callback: CallbackQuery, state: FSMContext
) -> None:
    account_id = int(callback.data.split(":")[1])
    account = await db.get_account_by_id(account_id)

    if not account or account.owner_id != callback.from_user.id:
        await callback.answer(
            "\u26a0\ufe0f Account not found.", show_alert=True
        )
        return

    # Stop listener if active
    await stop_code_listener(callback.from_user.id)

    proxy = await db.get_active_proxy(callback.from_user.id)
    success = await logout_account(account.session_string, proxy=proxy)

    if success:
        await db.deactivate_account(account_id)
        await callback.answer(
            "\u2705 Account logged out and removed.", show_alert=True
        )
    else:
        await callback.answer(
            "\u26a0\ufe0f Logout failed. Account may already be logged out.",
            show_alert=True,
        )
        await db.deactivate_account(account_id)

    is_admin = await db.is_user_admin(callback.from_user.id)
    await callback.message.edit_text(
        "\U0001f6aa <b>Account Logged Out</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4f1 {account.phone} has been logged out\n"
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
async def cb_deliver_bulk(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.update_data(delivery_mode="bulk")
    await callback.message.edit_text(
        "\U0001f4c1 <b>Bulk Session Delivery</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        "Choose the session file format:",
        parse_mode="HTML",
        reply_markup=session_format_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_format:"))
@authorized
async def cb_bulk_format(
    callback: CallbackQuery, state: FSMContext
) -> None:
    fmt = callback.data.split(":")[1]  # "telethon" or "pyrogram"
    user_id = callback.from_user.id

    countries = await db.get_countries_for_owner(user_id)
    if not countries:
        await callback.answer(
            "\U0001f4ed You don't have any accounts.", show_alert=True
        )
        return

    await state.update_data(bulk_format=fmt)
    fmt_label = "Telethon" if fmt == "telethon" else "Pyrogram"

    await callback.message.edit_text(
        f"\U0001f4c1 <b>Bulk Delivery</b> \u2014 <b>{fmt_label}</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        "Select a country category:",
        parse_mode="HTML",
        reply_markup=country_select_kb(
            countries, prefix="bulk_country", back_cb="deliver_bulk"
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_country:"))
@authorized
async def cb_bulk_country(
    callback: CallbackQuery, state: FSMContext
) -> None:
    country = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    dates = await db.get_dates_for_country(user_id, country)
    if not dates:
        await callback.answer(
            "\U0001f4ed No accounts in this category.", show_alert=True
        )
        return

    await state.update_data(bulk_country=country)

    counts: dict[str, int] = {}
    for d in dates:
        d_val = d
        if isinstance(d_val, _dt.datetime):
            d_val = d_val.date()
        accs = await db.get_accounts_filtered(user_id, country, d)
        counts[d_val.isoformat()] = len(accs)

    data = await state.get_data()
    fmt = data.get("bulk_format", "telethon")
    fmt_label = "Telethon" if fmt == "telethon" else "Pyrogram"

    await callback.message.edit_text(
        f"\U0001f4c1 <b>Bulk Delivery</b> \u2014 "
        f"<b>{fmt_label}</b> \u2192 <b>{country}</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        "Select a date category:",
        parse_mode="HTML",
        reply_markup=date_select_kb(
            dates,
            prefix="bulk_date",
            back_cb=f"bulk_format:{fmt}",
            counts=counts,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_date:"))
@authorized
async def cb_bulk_date(
    callback: CallbackQuery, state: FSMContext
) -> None:
    date_iso = callback.data.split(":", 1)[1]
    date_obj = _dt.date.fromisoformat(date_iso)
    data = await state.get_data()
    country = data.get("bulk_country", "")
    user_id = callback.from_user.id

    accounts = await db.get_accounts_filtered(user_id, country, date_obj)
    if not accounts:
        await callback.answer(
            "\U0001f4ed No accounts found.", show_alert=True
        )
        return

    await state.update_data(bulk_date=date_iso)
    date_label = date_obj.strftime("%B %d, %Y")

    await callback.message.edit_text(
        f"\U0001f4c1 <b>Bulk Delivery</b>\n"
        f"\U0001f30d {country}  \u2022  \U0001f4c5 {date_label}\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4ca Available accounts: <b>{len(accounts)}</b>\n\n"
        f"How many accounts do you want to export?\n"
        f"<i>Enter a number (1\u2013{len(accounts)}):</i>",
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
    accounts = await db.get_accounts_filtered(
        message.from_user.id, country, date_obj
    )

    try:
        qty = int(message.text.strip())
    except ValueError:
        await message.answer(
            "\u26a0\ufe0f Please enter a valid number.",
            reply_markup=cancel_kb("deliver_bulk"),
        )
        return

    if qty < 1 or qty > len(accounts):
        await message.answer(
            f"\u26a0\ufe0f Please enter a number between 1 and "
            f"{len(accounts)}.",
            reply_markup=cancel_kb("deliver_bulk"),
        )
        return

    selected = accounts[:qty]

    await message.answer(
        "\u23f3 Converting sessions and creating ZIP file\u2026"
    )

    # ── Create ZIP in memory ──
    zip_buffer = io.BytesIO()
    date_label = date_obj.strftime("%Y-%m-%d")
    ext = ".session"

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for acc in selected:
            with tempfile.NamedTemporaryFile(
                suffix=ext, delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)

            try:
                if fmt == "telethon":
                    success = telethon_string_to_session_file(
                        acc.session_string, tmp_path
                    )
                else:
                    success = telethon_string_to_pyrogram_session(
                        acc.session_string,
                        tmp_path,
                        user_id=acc.tg_user_id or 0,
                    )

                if success:
                    with open(tmp_path, "rb") as f:
                        file_data = f.read()
                    safe_phone = (
                        acc.phone.replace("+", "").replace(" ", "")
                    )
                    zf.writestr(f"{safe_phone}.session", file_data)
            except Exception:
                logger.exception(
                    "Failed to convert session for %s", acc.phone
                )
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    zip_buffer.seek(0)
    zip_data = zip_buffer.getvalue()

    safe_country = country.replace(" ", "_")
    zip_filename = (
        f"{safe_country}_{date_label}_{fmt}_{qty}accounts.zip"
    )
    fmt_label = "Telethon" if fmt == "telethon" else "Pyrogram"

    await message.answer_document(
        BufferedInputFile(zip_data, filename=zip_filename),
        caption=(
            f"\U0001f4c1 <b>Session Files Delivered!</b>\n\n"
            f"\U0001f4e6  Format: <b>{fmt_label}</b>\n"
            f"\U0001f30d  Country: <b>{country}</b>\n"
            f"\U0001f4c5  Date: "
            f"<b>{date_obj.strftime('%B %d, %Y')}</b>\n"
            f"\U0001f4ca  Accounts: <b>{qty}</b>"
        ),
        parse_mode="HTML",
    )

    # Store IDs for potential logout
    selected_ids = [acc.id for acc in selected]
    await state.update_data(bulk_delivered_ids=selected_ids)
    await state.set_state(None)

    await message.answer(
        "\U0001f512 <b>Log out of delivered accounts?</b>\n\n"
        "Would you like to log out all delivered accounts\n"
        "and remove them from your statistics?",
        parse_mode="HTML",
        reply_markup=confirm_kb("bulk_logout_yes", "bulk_logout_no"),
    )


@router.callback_query(F.data == "bulk_logout_yes")
@authorized
async def cb_bulk_logout_yes(
    callback: CallbackQuery, state: FSMContext
) -> None:
    data = await state.get_data()
    delivered_ids = data.get("bulk_delivered_ids", [])

    if not delivered_ids:
        await callback.answer(
            "No accounts to log out.", show_alert=True
        )
        await state.clear()
        return

    await callback.message.edit_text(
        "\u23f3 Logging out accounts\u2026 This may take a moment.",
        parse_mode="HTML",
    )

    proxy = await db.get_active_proxy(callback.from_user.id)
    success_count = 0

    for acc_id in delivered_ids:
        acc = await db.get_account_by_id(acc_id)
        if acc:
            try:
                await logout_account(acc.session_string, proxy=proxy)
                success_count += 1
            except Exception:
                logger.exception("Failed to logout account %s", acc_id)

    await db.deactivate_accounts(delivered_ids)

    is_admin = await db.is_user_admin(callback.from_user.id)
    await callback.message.edit_text(
        f"\u2705 <b>Logout Complete</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f6aa  Logged out: "
        f"<b>{success_count}/{len(delivered_ids)}</b> accounts\n"
        f"\U0001f4ca  Statistics updated.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "bulk_logout_no")
@authorized
async def cb_bulk_logout_no(
    callback: CallbackQuery, state: FSMContext
) -> None:
    is_admin = await db.is_user_admin(callback.from_user.id)
    await callback.message.edit_text(
        "\u2705 Accounts kept active.\n\n"
        "Returning to main menu.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await state.clear()
    await callback.answer()
