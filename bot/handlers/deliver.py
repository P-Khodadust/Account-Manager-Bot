"""
Account delivery — two methods:

Method 1  Individual Account Delivery  (with "Next" sequential navigation)
  → Select country → date → account list
  → Bot connects to account session and listens for login codes
  → When Telegram sends the code (from user 777000) the bot captures it
  → Bot delivers the captured code to the user
  → "Next" button allows walking through all accounts in the category

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
from bot.utils.country_detector import get_flag
from bot.utils.decorators import authorized
from bot.utils.keyboards import (
    account_actions_kb,
    account_list_kb,
    bulk_country_format_kb,
    bulk_post_delivery_kb,
    bulk_status_filter_prompt_kb,
    bulk_status_remove_kb,
    cancel_kb,
    confirm_kb,
    country_select_kb,
    date_select_kb,
    deliver_menu_kb,
    listening_kb,
    logout_sessions_confirm_kb,
    main_menu_kb,
    next_confirm_kb,
    session_format_kb,
    trash_confirm_kb,
)
from bot.utils.session_manager import (
    check_spam_status,
    delete_personal_chats_and_leave_groups,
    logout_account,
    start_code_listener,
    stop_code_listener,
    telethon_string_to_pyrogram_session,
    telethon_string_to_session_file,
    telethon_string_to_tdata_zip,
    terminate_other_sessions,
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
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Choose your delivery method:\n\n"
        "\U0001f4f1  <b>Individual</b> \u2014 Deliver one account at a time\n"
        "\U0001f4c1  <b>Bulk Sessions</b> \u2014 Export multiple session "
        "files as ZIP",
        parse_mode="HTML",
        reply_markup=deliver_menu_kb(),
    )
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# METHOD 1: Individual Account Delivery
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
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
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
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Select a date category:",
        parse_mode="HTML",
        reply_markup=date_select_kb(
            dates,
            prefix="ind_date",
            back_cb="deliver_individual",
            counts=counts,
            show_logout_sessions=True,
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

    # Store the ordered list of account IDs for sequential navigation
    await state.update_data(
        ind_date=date_iso,
        ind_account_ids=[acc.id for acc in accounts],
    )
    date_label = date_obj.strftime("%B %d, %Y")

    await callback.message.edit_text(
        f"\U0001f4f1 <b>Individual Delivery</b>\n"
        f"{get_flag(country)} {country}  \u2022  \U0001f4c5 {date_label}\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
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

    # Determine position in the list and whether a "Next" exists
    data = await state.get_data()
    account_ids = data.get("ind_account_ids", [])
    try:
        current_idx = account_ids.index(account_id)
    except ValueError:
        current_idx = 0
    has_next = current_idx < len(account_ids) - 1

    await state.update_data(
        ind_current_idx=current_idx,
        ind_account_id=account_id,
    )

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
        has_next=has_next,
    )

    if not success:
        await callback.message.edit_text(
            f"\u274c <b>Delivery Error</b>\n\n{error}",
            parse_mode="HTML",
            reply_markup=account_actions_kb(account_id, has_next=has_next),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "\U0001f4f1 <b>Listening for Login Code</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"Phone: <code>{account.phone}</code>\n\n"
        "\U0001f442 I'm now monitoring this account for\n"
        "incoming login codes.\n\n"
        "\u23f3 <i>Listening\u2026 (5 min timeout)</i>",
        parse_mode="HTML",
        reply_markup=listening_kb(account_id, has_next=has_next),
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

    # Determine has_next from state
    data = await state.get_data()
    account_ids = data.get("ind_account_ids", [])
    current_idx = data.get("ind_current_idx", 0)
    has_next = bool(account_ids) and current_idx < len(account_ids) - 1

    proxy = await db.get_active_proxy(callback.from_user.id)

    success, error = await start_code_listener(
        session_string=account.session_string,
        phone=account.phone,
        account_id=account_id,
        user_id=callback.from_user.id,
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        proxy=proxy,
        has_next=has_next,
    )

    if not success:
        await callback.answer(
            f"Error: {error}", show_alert=True
        )
        return

    await callback.message.edit_text(
        "\U0001f504 <b>Listener Restarted</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"Phone: <code>{account.phone}</code>\n\n"
        "\U0001f442 Listening for new login code\u2026\n"
        "Please attempt to log in again.\n\n"
        "\u23f3 <i>Listening\u2026 (5 min timeout)</i>",
        parse_mode="HTML",
        reply_markup=listening_kb(account_id, has_next=has_next),
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
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4f1 {account.phone} has been logged out\n"
        "and removed from your statistics.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await state.clear()


# ── "Next" button — sequential navigation ────────────────────────────

@router.callback_query(F.data.startswith("next_acc:"))
@authorized
async def cb_next_acc(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """User clicked ➡️ Next — ask whether to logout current account."""
    account_id = int(callback.data.split(":")[1])

    # Stop any active listener before proceeding
    await stop_code_listener(callback.from_user.id)

    account = await db.get_account_by_id(account_id)
    phone_display = account.phone if account else "this account"

    await callback.message.edit_text(
        "\U0001f504 <b>Next Account</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"Current: <code>{phone_display}</code>\n\n"
        "Log out of this account before\n"
        "moving to the next one?",
        parse_mode="HTML",
        reply_markup=next_confirm_kb(account_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("next_logout:"))
@authorized
async def cb_next_logout(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Logout current account, then move to the next one."""
    account_id = int(callback.data.split(":")[1])
    account = await db.get_account_by_id(account_id)

    if account and account.owner_id == callback.from_user.id:
        proxy = await db.get_active_proxy(callback.from_user.id)
        await logout_account(account.session_string, proxy=proxy)
        await db.deactivate_account(account_id)

    await _move_to_next_account(callback, state)


@router.callback_query(F.data.startswith("next_keep:"))
@authorized
async def cb_next_keep(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Keep current account logged in, move to the next one."""
    await _move_to_next_account(callback, state)


async def _move_to_next_account(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Find the next active account in the category and start listening."""
    data = await state.get_data()
    account_ids = data.get("ind_account_ids", [])
    current_idx = data.get("ind_current_idx", 0)
    user_id = callback.from_user.id

    # Search for the next active account
    next_idx = current_idx + 1
    next_account = None
    while next_idx < len(account_ids):
        acc = await db.get_account_by_id(account_ids[next_idx])
        if acc:
            next_account = acc
            break
        next_idx += 1

    if not next_account:
        is_admin = await db.is_user_admin(user_id)
        await callback.message.edit_text(
            "\u2705 <b>No More Accounts</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "You've reached the end of the account\n"
            "list in this category.\n\n"
            "Return to the main menu to continue.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin),
        )
        await state.clear()
        await callback.answer()
        return

    # Update position in state
    has_next = next_idx < len(account_ids) - 1
    await state.update_data(
        ind_current_idx=next_idx,
        ind_account_id=next_account.id,
    )

    # Start listener for the next account
    proxy = await db.get_active_proxy(user_id)
    success, error = await start_code_listener(
        session_string=next_account.session_string,
        phone=next_account.phone,
        account_id=next_account.id,
        user_id=user_id,
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        proxy=proxy,
        has_next=has_next,
    )

    if not success:
        await callback.message.edit_text(
            f"\u274c <b>Delivery Error</b>\n\n{error}",
            parse_mode="HTML",
            reply_markup=account_actions_kb(
                next_account.id, has_next=has_next
            ),
        )
        await callback.answer()
        return

    position = next_idx + 1
    total = len(account_ids)

    await callback.message.edit_text(
        f"\U0001f4f1 <b>Listening for Login Code</b>  "
        f"({position}/{total})\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"Phone: <code>{next_account.phone}</code>\n\n"
        "\U0001f442 I'm now monitoring this account for\n"
        "incoming login codes.\n\n"
        "\u23f3 <i>Listening\u2026 (5 min timeout)</i>",
        parse_mode="HTML",
        reply_markup=listening_kb(next_account.id, has_next=has_next),
    )
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# METHOD 2: Bulk Session File Delivery
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "deliver_bulk")
@authorized
async def cb_deliver_bulk(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.update_data(delivery_mode="bulk", bulk_scope="date")
    await callback.message.edit_text(
        "\U0001f4c1 <b>Bulk Session Delivery</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
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
    fmt = callback.data.split(":")[1]  # "telethon" / "pyrogram" / "tdata"
    user_id = callback.from_user.id

    countries = await db.get_countries_for_owner(user_id)
    if not countries:
        await callback.answer(
            "\U0001f4ed You don't have any accounts.", show_alert=True
        )
        return

    await state.update_data(bulk_format=fmt)
    fmt_label = {
        "telethon": "Telethon",
        "pyrogram": "Pyrogram",
        "tdata": "TData (Desktop)",
    }.get(fmt, fmt)

    await callback.message.edit_text(
        f"\U0001f4c1 <b>Bulk Delivery</b> \u2014 <b>{fmt_label}</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
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
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Select a date category:",
        parse_mode="HTML",
        reply_markup=date_select_kb(
            dates,
            prefix="bulk_date",
            back_cb=f"bulk_format:{fmt}",
            counts=counts,
            show_logout_sessions=True,
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
        f"{get_flag(country)} {country}  \u2022  \U0001f4c5 {date_label}\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
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
    scope = data.get("bulk_scope", "date")
    fmt = data.get("bulk_format", "telethon")
    user_id = message.from_user.id

    if scope == "date":
        country = data.get("bulk_country", "")
        date_iso = data.get("bulk_date", "")
        date_obj = _dt.date.fromisoformat(date_iso)
        accounts = await db.get_accounts_filtered(
            user_id, country, date_obj
        )
        scope_label = (
            f"{get_flag(country)}  Country: <b>{country}</b>\n"
            f"\U0001f4c5  Date: "
            f"<b>{date_obj.strftime('%B %d, %Y')}</b>\n"
        )
        filename_prefix = (
            f"{country.replace(' ', '_')}_"
            f"{date_obj.strftime('%Y-%m-%d')}"
        )
        cancel_back = "deliver_bulk"
    elif scope == "country":
        country = data.get("bulk_country", "")
        accounts = await db.get_accounts_for_country(user_id, country)
        scope_label = (
            f"{get_flag(country)}  Country: <b>{country}</b>\n"
            "\U0001f4c5  Dates: <b>all</b>\n"
        )
        filename_prefix = f"{country.replace(' ', '_')}_alldates"
        cancel_back = "deliver_bulk_country"
    else:
        accounts = await db.get_all_accounts_for_owner(user_id)
        scope_label = "\U0001f30d  Scope: <b>All accounts</b>\n"
        filename_prefix = "all_accounts"
        cancel_back = "deliver_bulk_all"

    try:
        qty = int(message.text.strip())
    except ValueError:
        await message.answer(
            "\u26a0\ufe0f Please enter a valid number.",
            reply_markup=cancel_kb(cancel_back),
        )
        return

    if qty < 1 or qty > len(accounts):
        await message.answer(
            f"\u26a0\ufe0f Please enter a number between 1 and "
            f"{len(accounts)}.",
            reply_markup=cancel_kb(cancel_back),
        )
        return

    selected = accounts[:qty]

    await message.answer(
        "\u23f3 Converting sessions and creating ZIP file\u2026"
    )

    proxy = await db.get_active_proxy(user_id)
    zip_data = await _build_bulk_zip(selected, fmt, proxy)

    fmt_label = {
        "telethon": "Telethon",
        "pyrogram": "Pyrogram",
        "tdata": "TData (Desktop)",
    }.get(fmt, fmt)

    zip_filename = f"{filename_prefix}_{fmt}_{qty}accounts.zip"

    await message.answer_document(
        BufferedInputFile(zip_data, filename=zip_filename),
        caption=(
            "\U0001f4c1 <b>Session Files Delivered!</b>\n\n"
            f"\U0001f4e6  Format: <b>{fmt_label}</b>\n"
            f"{scope_label}"
            f"\U0001f4ca  Accounts: <b>{qty}</b>"
        ),
        parse_mode="HTML",
    )

    selected_ids = [acc.id for acc in selected]
    await _post_delivery_prompt(message, state, selected_ids)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Shared bulk helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _build_bulk_zip(
    accounts: list,
    fmt: str,
    proxy=None,
) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for acc in accounts:
            safe_phone = acc.phone.replace("+", "").replace(" ", "")
            try:
                if fmt == "telethon":
                    with tempfile.NamedTemporaryFile(
                        suffix=".session", delete=False
                    ) as tmp:
                        tmp_path = Path(tmp.name)
                    try:
                        if telethon_string_to_session_file(
                            acc.session_string, tmp_path
                        ):
                            zf.writestr(
                                f"{safe_phone}.session",
                                tmp_path.read_bytes(),
                            )
                    finally:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                elif fmt == "pyrogram":
                    with tempfile.NamedTemporaryFile(
                        suffix=".session", delete=False
                    ) as tmp:
                        tmp_path = Path(tmp.name)
                    try:
                        if telethon_string_to_pyrogram_session(
                            acc.session_string,
                            tmp_path,
                            user_id=acc.tg_user_id or 0,
                        ):
                            zf.writestr(
                                f"{safe_phone}.session",
                                tmp_path.read_bytes(),
                            )
                    finally:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                elif fmt == "tdata":
                    with tempfile.NamedTemporaryFile(
                        suffix=".zip", delete=False
                    ) as tmp:
                        tmp_path = Path(tmp.name)
                    try:
                        ok = await telethon_string_to_tdata_zip(
                            acc.session_string, tmp_path, proxy=proxy
                        )
                        if ok:
                            zf.writestr(
                                f"{safe_phone}_tdata.zip",
                                tmp_path.read_bytes(),
                            )
                    finally:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
            except Exception:
                logger.exception(
                    "Failed to convert session for %s", acc.phone
                )
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


async def _post_delivery_prompt(
    message: Message,
    state: FSMContext,
    delivered_ids: list[int],
) -> None:
    await state.update_data(bulk_delivered_ids=delivered_ids)
    await state.set_state(None)
    await message.answer(
        "❔ <b>Remove delivered accounts from statistics?</b>\n"
        "━━━━━━━━━━━━\n\n"
        "✅ <b>Yes</b> — accounts removed from stats; "
        "the bot stays logged in.\n"
        "❌ <b>No</b> — other sessions are terminated so "
        "the file you just received is invalidated; accounts stay in stats.",
        parse_mode="HTML",
        reply_markup=bulk_post_delivery_kb(),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Logout Other Sessions (per date category)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.callback_query(F.data.startswith("ls:"))
@authorized
async def cb_logout_sessions_prompt(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Show confirmation before terminating other sessions."""
    parts = callback.data.split(":")
    mode = parts[1]       # "i" or "b"
    date_iso = parts[2]

    data = await state.get_data()
    country = (
        data.get("ind_country")
        if mode == "i"
        else data.get("bulk_country")
    ) or ""
    user_id = callback.from_user.id

    date_obj = _dt.date.fromisoformat(date_iso)
    date_label = date_obj.strftime("%B %d, %Y")
    accounts = await db.get_accounts_filtered(user_id, country, date_obj)

    flag = get_flag(country)
    await callback.message.edit_text(
        "\u26a0\ufe0f <b>Logout Other Sessions</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"{flag} {country}  \u2022  \U0001f4c5 {date_label}\n\n"
        f"This will terminate all other devices\n"
        f"from <b>{len(accounts)}</b> account(s).\n\n"
        "The bot will remain logged in.\n\n"
        "Continue?",
        parse_mode="HTML",
        reply_markup=logout_sessions_confirm_kb(mode, date_iso),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ls_y:"))
@authorized
async def cb_logout_sessions_yes(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Terminate other sessions for all accounts in the date category."""
    parts = callback.data.split(":")
    mode = parts[1]
    date_iso = parts[2]

    data = await state.get_data()
    country = (
        data.get("ind_country")
        if mode == "i"
        else data.get("bulk_country")
    ) or ""
    user_id = callback.from_user.id

    date_obj = _dt.date.fromisoformat(date_iso)
    accounts = await db.get_accounts_filtered(user_id, country, date_obj)
    total = len(accounts)

    await callback.message.edit_text(
        f"\u23f3 <b>Terminating sessions\u2026</b>  0/{total}",
        parse_mode="HTML",
    )
    await callback.answer()

    success_count = 0
    terminated_total = 0
    failed_count = 0

    for i, acc in enumerate(accounts):
        proxy = await db.get_active_proxy(user_id)

        ok, terminated, err = await terminate_other_sessions(
            acc.session_string, proxy=proxy
        )

        if ok:
            success_count += 1
            terminated_total += terminated
        else:
            failed_count += 1

        await db.increment_rotation_counter(user_id)

        if (i + 1) % 5 == 0 or i == total - 1:
            try:
                await callback.message.edit_text(
                    f"\u23f3 <b>Terminating sessions\u2026</b>  "
                    f"{i + 1}/{total}",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await asyncio.sleep(1.5)

    date_label = date_obj.strftime("%B %d, %Y")
    is_admin = await db.is_user_admin(user_id)

    await callback.message.edit_text(
        "\u2705 <b>Sessions Terminated</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4c5  Date: <b>{date_label}</b>\n"
        f"\u2705  Accounts processed: <b>{success_count}/{total}</b>\n"
        f"\U0001f6aa  Sessions terminated: <b>{terminated_total}</b>\n"
        + (
            f"\u274c  Failed: <b>{failed_count}</b>\n"
            if failed_count
            else ""
        )
        + "\n\U0001f4f1 Bot remains logged in to all accounts.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )


@router.callback_query(F.data.startswith("ls_n:"))
@authorized
async def cb_logout_sessions_no(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Cancel session termination and return to the date listing."""
    parts = callback.data.split(":")
    mode = parts[1]
    date_iso = parts[2]

    data = await state.get_data()
    country = (
        data.get("ind_country")
        if mode == "i"
        else data.get("bulk_country")
    ) or ""
    user_id = callback.from_user.id

    dates = await db.get_dates_for_country(user_id, country)

    counts: dict[str, int] = {}
    for d in dates:
        d_val = d.date() if isinstance(d, _dt.datetime) else d
        accs = await db.get_accounts_filtered(user_id, country, d)
        counts[d_val.isoformat()] = len(accs)

    prefix = "ind_date" if mode == "i" else "bulk_date"
    back_cb = (
        "deliver_individual"
        if mode == "i"
        else "deliver_bulk"
    )

    flag = get_flag(country)
    await callback.message.edit_text(
        f"{flag} <b>{country}</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Select a date category:",
        parse_mode="HTML",
        reply_markup=date_select_kb(
            dates,
            prefix=prefix,
            back_cb=back_cb,
            counts=counts,
            show_logout_sessions=True,
        ),
    )
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Bulk: post-delivery Yes/No
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.callback_query(F.data == "bd_yes")
@authorized
async def cb_bd_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """Yes → deactivate (remove from stats); bot stays logged in."""
    data = await state.get_data()
    ids = data.get("bulk_delivered_ids", [])
    if not ids:
        await callback.answer("Nothing to do.", show_alert=True)
        return

    await db.deactivate_accounts(ids, status="delivered_removed")

    await callback.message.edit_text(
        "✅ <b>Removed from statistics</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"\U0001f4ca {len(ids)} account(s) deactivated.\n"
        "The bot remains logged in inside each account.\n\n"
        "Do you want to apply spam-status classification\n"
        "(green / yellow / red) to the delivered accounts?",
        parse_mode="HTML",
        reply_markup=bulk_status_filter_prompt_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "bd_no")
@authorized
async def cb_bd_no(callback: CallbackQuery, state: FSMContext) -> None:
    """No → terminate other sessions so the delivered file is unusable."""
    data = await state.get_data()
    ids = data.get("bulk_delivered_ids", [])
    if not ids:
        await callback.answer("Nothing to do.", show_alert=True)
        return

    total = len(ids)
    await callback.message.edit_text(
        f"⏳ <b>Invalidating delivered files…</b>  0/{total}",
        parse_mode="HTML",
    )
    await callback.answer()

    proxy = await db.get_active_proxy(callback.from_user.id)
    success = 0
    terminated_total = 0
    for i, acc_id in enumerate(ids):
        acc = await db.get_account_by_id(acc_id)
        if acc:
            try:
                ok, terminated, _ = await terminate_other_sessions(
                    acc.session_string, proxy=proxy
                )
                if ok:
                    success += 1
                    terminated_total += terminated
            except Exception:
                logger.exception("Failed terminating sessions for %s", acc_id)
        if (i + 1) % 5 == 0 or i == total - 1:
            try:
                await callback.message.edit_text(
                    f"⏳ <b>Invalidating delivered files…</b>  "
                    f"{i + 1}/{total}",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await asyncio.sleep(1.5)

    await callback.message.edit_text(
        "✅ <b>Delivered files invalidated</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"\U0001f6aa  Sessions terminated: <b>{terminated_total}</b>\n"
        f"✅  Accounts processed: <b>{success}/{total}</b>\n"
        "Accounts remain in your statistics.\n\n"
        "Do you want to apply spam-status classification\n"
        "(green / yellow / red) to these accounts?",
        parse_mode="HTML",
        reply_markup=bulk_status_filter_prompt_kb(),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Bulk: optional spam-status classification
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.callback_query(F.data == "bd_classify_no")
@authorized
async def cb_bd_classify_no(
    callback: CallbackQuery, state: FSMContext
) -> None:
    is_admin = await db.is_user_admin(callback.from_user.id)
    suspicious = await db.get_suspicious_accounts(callback.from_user.id)
    await callback.message.edit_text(
        "✅ Done. Returning to main menu.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin, has_suspicious=bool(suspicious)),
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "bd_classify_yes")
@authorized
async def cb_bd_classify_yes(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Run @SpamBot status check across delivered accounts."""
    data = await state.get_data()
    ids = data.get("bulk_delivered_ids", [])
    if not ids:
        await callback.answer("Nothing to classify.", show_alert=True)
        return

    proxy = await db.get_active_proxy(callback.from_user.id)
    counts, breakdown = await _run_status_sweep(callback, ids, proxy)
    await state.update_data(bulk_classify_counts=counts)

    await callback.message.edit_text(
        _format_status_summary(counts, breakdown)
        + "\n\nUse the buttons below to remove accounts by status.",
        parse_mode="HTML",
        reply_markup=bulk_status_remove_kb(),
    )


@router.callback_query(F.data.startswith("bd_rm:"))
@authorized
async def cb_bd_rm(callback: CallbackQuery, state: FSMContext) -> None:
    color = callback.data.split(":", 1)[1]
    data = await state.get_data()
    ids = data.get("bulk_delivered_ids", [])

    if color == "done":
        is_admin = await db.is_user_admin(callback.from_user.id)
        suspicious = await db.get_suspicious_accounts(
            callback.from_user.id
        )
        await callback.message.edit_text(
            "✅ Classification complete. Returning to main menu.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(
                is_admin, has_suspicious=bool(suspicious)
            ),
        )
        await state.clear()
        await callback.answer()
        return

    matching: list[int] = []
    for acc_id in ids:
        acc = await db.get_account_by_id(acc_id)
        if acc and acc.spam_status == color:
            matching.append(acc_id)

    if not matching:
        await callback.answer(
            f"No {color} accounts to remove.", show_alert=True
        )
        return

    await db.deactivate_accounts(matching, status=f"removed_{color}")
    await callback.answer(
        f"Removed {len(matching)} {color} account(s).", show_alert=True
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Bulk by Country (all dates) and Bulk All Accounts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.callback_query(F.data == "deliver_bulk_country")
@authorized
async def cb_deliver_bulk_country(
    callback: CallbackQuery, state: FSMContext
) -> None:
    countries = await db.get_countries_for_owner(callback.from_user.id)
    if not countries:
        await callback.answer(
            "📭 You don't have any accounts.", show_alert=True
        )
        return
    await state.update_data(bulk_scope="country")
    await callback.message.edit_text(
        "\U0001f4e6 <b>Bulk — By Country (All Dates)</b>\n"
        "━━━━━━━━━━━━\n\n"
        "Choose the session file format:",
        parse_mode="HTML",
        reply_markup=bulk_country_format_kb("country"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulkcountry_format:"))
@authorized
async def cb_bulkcountry_format(
    callback: CallbackQuery, state: FSMContext
) -> None:
    fmt = callback.data.split(":", 1)[1]
    countries = await db.get_countries_for_owner(callback.from_user.id)
    await state.update_data(bulk_format=fmt, bulk_scope="country")

    await callback.message.edit_text(
        "\U0001f4e6 <b>Bulk — By Country (All Dates)</b>\n"
        "━━━━━━━━━━━━\n\n"
        "Select a country:",
        parse_mode="HTML",
        reply_markup=country_select_kb(
            countries,
            prefix="bulkc_country",
            back_cb="deliver_bulk_country",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulkc_country:"))
@authorized
async def cb_bulkc_country(
    callback: CallbackQuery, state: FSMContext
) -> None:
    country = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    accounts = await db.get_accounts_for_country(user_id, country)
    if not accounts:
        await callback.answer(
            "📭 No accounts in this country.", show_alert=True
        )
        return

    await state.update_data(bulk_country=country)

    await callback.message.edit_text(
        f"\U0001f4e6 <b>Bulk — {country}</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"\U0001f4ca Available accounts: <b>{len(accounts)}</b>\n\n"
        f"How many accounts do you want to export?\n"
        f"<i>Enter a number (1–{len(accounts)}):</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb("deliver_bulk_country"),
    )
    await state.set_state(DeliverStates.bulk_waiting_quantity)
    await callback.answer()


@router.callback_query(F.data == "deliver_bulk_all")
@authorized
async def cb_deliver_bulk_all(
    callback: CallbackQuery, state: FSMContext
) -> None:
    accounts = await db.get_all_accounts_for_owner(callback.from_user.id)
    if not accounts:
        await callback.answer(
            "📭 You don't have any accounts.", show_alert=True
        )
        return
    await state.update_data(bulk_scope="all")
    await callback.message.edit_text(
        "\U0001f30d <b>Bulk — All Accounts</b>\n"
        "━━━━━━━━━━━━\n\n"
        "Choose the session file format:",
        parse_mode="HTML",
        reply_markup=bulk_country_format_kb("all"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulkall_format:"))
@authorized
async def cb_bulkall_format(
    callback: CallbackQuery, state: FSMContext
) -> None:
    fmt = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    accounts = await db.get_all_accounts_for_owner(user_id)
    await state.update_data(bulk_format=fmt, bulk_scope="all")

    await callback.message.edit_text(
        "\U0001f30d <b>Bulk — All Accounts</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"\U0001f4ca Available accounts: <b>{len(accounts)}</b>\n\n"
        f"How many accounts do you want to export?\n"
        f"<i>Enter a number (1–{len(accounts)}):</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb("deliver_bulk_all"),
    )
    await state.set_state(DeliverStates.bulk_waiting_quantity)
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# @SpamBot Status Sweep helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _format_progress_bar(done: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return ""
    filled = int(width * done / total)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


async def _run_status_sweep(
    callback: CallbackQuery,
    account_ids: list[int],
    proxy,
) -> tuple[dict[str, int], list[tuple[str, str]]]:
    total = len(account_ids)
    counts = {"green": 0, "yellow": 0, "red": 0, "unknown": 0}
    breakdown: list[tuple[str, str]] = []
    auto_removed_red: list[int] = []

    for i, acc_id in enumerate(account_ids):
        acc = await db.get_account_by_id(acc_id)
        if not acc:
            counts["unknown"] += 1
            continue
        try:
            status, _text = await check_spam_status(
                acc.session_string, proxy=proxy
            )
        except Exception:
            logger.exception("Status check failed for %s", acc.phone)
            status = "unknown"

        await db.set_spam_status(acc_id, status)
        counts[status] = counts.get(status, 0) + 1
        breakdown.append((acc.phone, status))

        if status == "red":
            auto_removed_red.append(acc_id)

        if (i + 1) % 3 == 0 or i == total - 1:
            done = i + 1
            bar = _format_progress_bar(done, total)
            try:
                await callback.message.edit_text(
                    "✅ <b>Status Sweep</b>\n"
                    "━━━━━━━━━━━━\n\n"
                    f"Checked: <b>{done}/{total}</b>\n"
                    f"<code>{bar}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await asyncio.sleep(1.0)

    if auto_removed_red:
        await db.deactivate_accounts(
            auto_removed_red, status="auto_removed_red"
        )

    return counts, breakdown


def _format_status_summary(
    counts: dict[str, int],
    breakdown: list[tuple[str, str]],
) -> str:
    total = sum(counts.values()) or 1
    pct = {k: round(100 * v / total) for k, v in counts.items()}
    bar = _format_progress_bar(
        counts.get("green", 0) + counts.get("yellow", 0),
        total,
    )
    lines = [
        "✅ <b>Status Sweep Complete</b>",
        "━━━━━━━━━━━━",
        "",
        f"\U0001f7e2  Green:  <b>{counts.get('green', 0)}</b>  "
        f"({pct.get('green', 0)}%)",
        f"\U0001f7e1  Yellow: <b>{counts.get('yellow', 0)}</b>  "
        f"({pct.get('yellow', 0)}%)",
        f"\U0001f534  Red:    <b>{counts.get('red', 0)}</b>  "
        f"({pct.get('red', 0)}%)  <i>(auto-removed)</i>",
    ]
    if counts.get("unknown"):
        lines.append(
            f"⚪  Unknown: <b>{counts['unknown']}</b>  "
            f"({pct.get('unknown', 0)}%)"
        )
    lines.append("")
    lines.append(f"<code>{bar}</code>")
    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ✅ Per-date Status Check Button
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.callback_query(F.data.startswith("ck:"))
@authorized
async def cb_status_check(
    callback: CallbackQuery, state: FSMContext
) -> None:
    parts = callback.data.split(":")
    mode = parts[1]
    date_iso = parts[2]
    user_id = callback.from_user.id

    data = await state.get_data()
    country = (
        data.get("ind_country")
        if mode == "i"
        else data.get("bulk_country")
    ) or ""

    date_obj = _dt.date.fromisoformat(date_iso)
    accounts = await db.get_accounts_filtered(user_id, country, date_obj)
    if not accounts:
        await callback.answer("No accounts here.", show_alert=True)
        return

    proxy = await db.get_active_proxy(user_id)
    await callback.message.edit_text(
        "⏳ <b>Status Sweep</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"Checking <b>{len(accounts)}</b> account(s) via @SpamBot…",
        parse_mode="HTML",
    )
    await callback.answer()

    ids = [a.id for a in accounts]
    counts, breakdown = await _run_status_sweep(callback, ids, proxy)

    is_admin = await db.is_user_admin(user_id)
    suspicious = await db.get_suspicious_accounts(user_id)
    await callback.message.edit_text(
        _format_status_summary(counts, breakdown),
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin, has_suspicious=bool(suspicious)),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🗑 Trash — bulk chat / group cleanup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.callback_query(F.data.startswith("tr:"))
@authorized
async def cb_trash_prompt(
    callback: CallbackQuery, state: FSMContext
) -> None:
    parts = callback.data.split(":")
    mode = parts[1]
    date_iso = parts[2]

    data = await state.get_data()
    country = (
        data.get("ind_country")
        if mode == "i"
        else data.get("bulk_country")
    ) or ""

    date_obj = _dt.date.fromisoformat(date_iso)
    date_label = date_obj.strftime("%B %d, %Y")
    accounts = await db.get_accounts_filtered(
        callback.from_user.id, country, date_obj
    )

    flag = get_flag(country)
    await callback.message.edit_text(
        "\U0001f5d1 <b>Bulk Chat Cleanup</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"{flag} {country}  •  📅 {date_label}\n\n"
        f"Delete every 1:1 chat and leave every group/channel\n"
        f"on <b>{len(accounts)}</b> account(s)?\n\n"
        "<i>The bot remains logged in.</i>",
        parse_mode="HTML",
        reply_markup=trash_confirm_kb(mode, date_iso),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_n:"))
@authorized
async def cb_trash_no(callback: CallbackQuery, state: FSMContext) -> None:
    is_admin = await db.is_user_admin(callback.from_user.id)
    await callback.message.edit_text(
        "✅ Cancelled.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_y:"))
@authorized
async def cb_trash_yes(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    mode = parts[1]
    date_iso = parts[2]

    data = await state.get_data()
    country = (
        data.get("ind_country")
        if mode == "i"
        else data.get("bulk_country")
    ) or ""

    date_obj = _dt.date.fromisoformat(date_iso)
    user_id = callback.from_user.id
    accounts = await db.get_accounts_filtered(user_id, country, date_obj)
    total = len(accounts)

    await callback.message.edit_text(
        f"⏳ <b>Cleaning chats…</b>  0/{total}",
        parse_mode="HTML",
    )
    await callback.answer()

    proxy = await db.get_active_proxy(user_id)
    chats_total = 0
    groups_total = 0
    err_total = 0
    for i, acc in enumerate(accounts):
        try:
            chats, groups, errs = (
                await delete_personal_chats_and_leave_groups(
                    acc.session_string, proxy=proxy
                )
            )
            chats_total += chats
            groups_total += groups
            err_total += errs
        except Exception:
            logger.exception("Trash failed for %s", acc.phone)
            err_total += 1

        if (i + 1) % 2 == 0 or i == total - 1:
            try:
                await callback.message.edit_text(
                    f"⏳ <b>Cleaning chats…</b>  {i + 1}/{total}",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await asyncio.sleep(1.5)

    is_admin = await db.is_user_admin(user_id)
    suspicious = await db.get_suspicious_accounts(user_id)
    await callback.message.edit_text(
        "✅ <b>Bulk Chat Cleanup Complete</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"📂  Accounts processed: <b>{total}</b>\n"
        f"🧹  1:1 chats deleted: <b>{chats_total}</b>\n"
        f"👥  Groups/channels left: <b>{groups_total}</b>\n"
        + (f"⚠️  Errors: <b>{err_total}</b>\n" if err_total else "")
        + "\nThe bot remains logged in to every account.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin, has_suspicious=bool(suspicious)),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Suspicious accounts list
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.callback_query(F.data == "suspicious_list")
@authorized
async def cb_suspicious_list(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    items = await db.get_suspicious_accounts(user_id)
    is_admin = await db.is_user_admin(user_id)

    if not items:
        await callback.message.edit_text(
            "❗ <b>Suspicious Accounts</b>\n"
            "━━━━━━━━━━━━\n\n"
            "No suspicious accounts. 🎉",
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin),
        )
        await callback.answer()
        return

    lines = [
        "❗ <b>Suspicious Accounts</b>",
        "━━━━━━━━━━━━",
        "",
        "<i>Sessions that ended unexpectedly. They've been "
        "removed from your statistics.</i>",
        "",
    ]
    for acc in items[:50]:
        when = (
            acc.spam_checked_at.strftime("%Y-%m-%d %H:%M")
            if acc.spam_checked_at
            else (
                acc.created_at.strftime("%Y-%m-%d")
                if acc.created_at
                else "-"
            )
        )
        lines.append(
            f"📱 <code>{acc.phone}</code>  •  "
            f"status: <b>{acc.status}</b>  •  {when}"
        )
    if len(items) > 50:
        lines.append(f"\n<i>… and {len(items) - 50} more.</i>")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin, has_suspicious=True),
    )
    await callback.answer()
