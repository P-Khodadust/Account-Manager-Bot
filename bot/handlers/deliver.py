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
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    Message,
)

from bot import database as db
from bot.utils.cancellation import (
    begin_operation,
    handle_cancel_callback,
    is_cancelled,
)
from bot.utils.country_detector import get_flag
from bot.utils.decorators import authorized
from bot.utils.keyboards import (
    account_actions_kb,
    account_list_kb,
    bulk_country_format_kb,
    bulk_post_delivery_kb,
    bulk_status_filter_prompt_kb,
    cancel_kb,
    country_select_kb,
    date_select_kb,
    deliver_menu_kb,
    listening_kb,
    logout_sessions_confirm_kb,
    main_menu_kb,
    next_confirm_kb,
    op_cancel_kb,
    session_format_kb,
    status_actions_kb,
    status_export_format_kb,
    status_post_export_kb,
    status_remove_kb,
    suspicious_clear_kb,
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
from bot.utils.status_workflow import (
    SPAM_STATUSES,
    count_account_statuses,
    filter_accounts_by_status,
    normalize_spam_status,
    without_account_ids,
)

logger = logging.getLogger(__name__)

router = Router(name="deliver")

SESSION_FORMATS = {"telethon", "pyrogram", "tdata"}


@dataclass
class BulkZipResult:
    """Archive on disk plus the exact accounts converted into it."""

    file_path: Path
    successful_ids: list[int]
    failed_ids: list[int]

    def cleanup(self) -> None:
        try:
            self.file_path.unlink(missing_ok=True)
        except Exception:
            pass


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
            page_cb="ind_dpage",
        ),
    )
    await callback.answer()


async def _render_ind_date_page(
    callback: CallbackQuery,
    state: FSMContext,
    page: int,
) -> None:
    user_id = callback.from_user.id
    data = await state.get_data()
    country = data.get("ind_country", "")

    dates = await db.get_dates_for_country(user_id, country)
    if not dates:
        await callback.answer(
            "\U0001f4ed No accounts in this category.", show_alert=True
        )
        return

    counts: dict[str, int] = {}
    for d in dates:
        d_val = d.date() if isinstance(d, _dt.datetime) else d
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
            page=page,
            page_cb="ind_dpage",
        ),
    )


@router.callback_query(F.data.startswith("ind_dpage:"))
@authorized
async def cb_ind_date_page(
    callback: CallbackQuery, state: FSMContext
) -> None:
    try:
        page = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        page = 0
    await _render_ind_date_page(callback, state, page)
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
            page_cb="acc_page",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acc_page:"))
@authorized
async def cb_account_list_page(
    callback: CallbackQuery, state: FSMContext
) -> None:
    try:
        page = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        page = 0

    data = await state.get_data()
    country = data.get("ind_country", "")
    date_iso = data.get("ind_date", "")
    user_id = callback.from_user.id

    if not country or not date_iso:
        await callback.answer(
            "\u26a0\ufe0f Selection expired. Please start again.",
            show_alert=True,
        )
        return

    date_obj = _dt.date.fromisoformat(date_iso)
    accounts = await db.get_accounts_filtered(user_id, country, date_obj)
    if not accounts:
        await callback.answer(
            "\U0001f4ed No accounts found.", show_alert=True
        )
        return

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
            page=page,
            page_cb="acc_page",
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
    account = await db.get_account_by_id(
        account_id,
        owner_id=callback.from_user.id,
    )

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
    account = await db.get_account_by_id(
        account_id,
        owner_id=callback.from_user.id,
    )

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
    account = await db.get_account_by_id(
        account_id,
        owner_id=callback.from_user.id,
    )

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
        # Transient failure — do NOT remove a possibly-still-valid
        # account from the active list.
        await callback.answer(
            "\u26a0\ufe0f Logout failed (network error?). "
            "Account kept active \u2014 please retry.",
            show_alert=True,
        )

    is_admin = await db.is_user_admin(callback.from_user.id)
    if success:
        await callback.message.edit_text(
            "\U0001f6aa <b>Account Logged Out</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"\U0001f4f1 {account.phone} has been logged out\n"
            "and removed from your statistics.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin),
        )
        await state.clear()
    else:
        await callback.message.edit_text(
            "\u26a0\ufe0f <b>Logout Failed</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"Could not log out of {account.phone}.\n"
            "The account remains active \u2014 try again shortly.",
            parse_mode="HTML",
            reply_markup=account_actions_kb(
                account_id,
                has_next=await _has_next_from_state(state),
            ),
        )


async def _has_next_from_state(state: FSMContext) -> bool:
    """Whether a 'Next' account exists after the current position."""
    data = await state.get_data()
    account_ids = data.get("ind_account_ids", [])
    current_idx = data.get("ind_current_idx", 0)
    return bool(account_ids) and current_idx < len(account_ids) - 1


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

    account = await db.get_account_by_id(
        account_id,
        owner_id=callback.from_user.id,
    )
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
    account = await db.get_account_by_id(
        account_id,
        owner_id=callback.from_user.id,
    )

    if account and account.owner_id == callback.from_user.id:
        proxy = await db.get_active_proxy(callback.from_user.id)
        if await logout_account(account.session_string, proxy=proxy):
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
        acc = await db.get_account_by_id(
            account_ids[next_idx],
            owner_id=user_id,
        )
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
            page_cb="bulk_dpage",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_dpage:"))
@authorized
async def cb_bulk_date_page(
    callback: CallbackQuery, state: FSMContext
) -> None:
    try:
        page = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        page = 0

    data = await state.get_data()
    country = data.get("bulk_country", "")
    fmt = data.get("bulk_format", "telethon")
    user_id = callback.from_user.id

    dates = await db.get_dates_for_country(user_id, country)
    if not dates:
        await callback.answer(
            "\U0001f4ed No accounts in this category.", show_alert=True
        )
        return

    counts: dict[str, int] = {}
    for d in dates:
        d_val = d.date() if isinstance(d, _dt.datetime) else d
        accs = await db.get_accounts_filtered(user_id, country, d)
        counts[d_val.isoformat()] = len(accs)

    fmt_label = "Telethon" if fmt == "telethon" else (
        "TData" if fmt == "tdata" else "Pyrogram"
    )

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
            page=page,
            page_cb="bulk_dpage",
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

    if fmt not in SESSION_FORMATS:
        await message.answer(
            "❌ Unsupported session format. Please start again.",
            reply_markup=cancel_kb(cancel_back),
        )
        await state.clear()
        return

    proxy = await db.get_active_proxy(user_id)
    archive = await _build_bulk_zip(selected, fmt, proxy)

    if not archive.successful_ids:
        archive.cleanup()
        await message.answer(
            "❌ No session files could be converted. "
            "No accounts were removed.",
            reply_markup=cancel_kb(cancel_back),
        )
        return

    fmt_label = {
        "telethon": "Telethon",
        "pyrogram": "Pyrogram",
        "tdata": "TData (Desktop)",
    }.get(fmt, fmt)

    exported_count = len(archive.successful_ids)
    zip_filename = (
        f"{filename_prefix}_{fmt}_{exported_count}accounts.zip"
    )

    try:
        await message.answer_document(
            FSInputFile(archive.file_path, filename=zip_filename),
            caption=(
                "\U0001f4c1 <b>Session Files Delivered!</b>\n\n"
                f"\U0001f4e6  Format: <b>{fmt_label}</b>\n"
                f"{scope_label}"
                f"\U0001f4ca  Accounts sent: <b>{exported_count}</b>"
                + (
                    f"\n⚠️  Conversion failures: "
                    f"<b>{len(archive.failed_ids)}</b>"
                    if archive.failed_ids
                    else ""
                )
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to send bulk session archive")
        await message.answer(
            "❌ Telegram could not send the archive. "
            "No accounts were removed; please try again.",
            reply_markup=cancel_kb(cancel_back),
        )
        return
    finally:
        archive.cleanup()

    await _post_delivery_prompt(
        message, state, archive.successful_ids
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Shared bulk helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _build_bulk_zip(
    accounts: list,
    fmt: str,
    proxy=None,
) -> BulkZipResult:
    """Build an archive on disk (streamed, not held in RAM) and report
    exactly which conversions succeeded."""
    fd = tempfile.NamedTemporaryFile(
        suffix=".zip", delete=False
    )
    zip_path = Path(fd.name)
    fd.close()

    if fmt not in SESSION_FORMATS:
        return BulkZipResult(zip_path, [], [acc.id for acc in accounts])

    successful_ids: list[int] = []
    failed_ids: list[int] = []
    used_names: set[str] = set()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for acc in accounts:
            safe_phone = acc.phone.replace("+", "").replace(" ", "")
            converted = False
            try:
                if fmt == "pyrogram" and not acc.tg_user_id:
                    # A Pyrogram session without the real user id cannot
                    # be resumed by buyers — treat as failed conversion.
                    logger.warning(
                        "Skipping Pyrogram export for %s "
                        "(no tg_user_id stored)",
                        acc.phone,
                    )
                elif fmt == "telethon":
                    with tempfile.NamedTemporaryFile(
                        suffix=".session", delete=False
                    ) as tmp:
                        tmp_path = Path(tmp.name)
                    try:
                        if telethon_string_to_session_file(
                            acc.session_string, tmp_path
                        ):
                            archive_name = _unique_archive_name(
                                f"{safe_phone}.session",
                                acc.id,
                                used_names,
                            )
                            zf.writestr(
                                archive_name,
                                tmp_path.read_bytes(),
                            )
                            converted = True
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
                            archive_name = _unique_archive_name(
                                f"{safe_phone}.session",
                                acc.id,
                                used_names,
                            )
                            zf.writestr(
                                archive_name,
                                tmp_path.read_bytes(),
                            )
                            converted = True
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
                            archive_name = _unique_archive_name(
                                f"{safe_phone}_tdata.zip",
                                acc.id,
                                used_names,
                            )
                            zf.writestr(
                                archive_name,
                                tmp_path.read_bytes(),
                            )
                            converted = True
                    finally:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
            except Exception:
                logger.exception(
                    "Failed to convert session for %s", acc.phone
                )
            if converted:
                successful_ids.append(acc.id)
            else:
                failed_ids.append(acc.id)
    return BulkZipResult(zip_path, successful_ids, failed_ids)


def _unique_archive_name(
    desired_name: str,
    account_id: int,
    used_names: set[str],
) -> str:
    """Prevent duplicate phone numbers from overwriting ZIP members."""
    if desired_name not in used_names:
        used_names.add(desired_name)
        return desired_name

    path = Path(desired_name)
    unique_name = f"{path.stem}_{account_id}{path.suffix}"
    used_names.add(unique_name)
    return unique_name


async def _post_delivery_prompt(
    message: Message,
    state: FSMContext,
    delivered_ids: list[int],
) -> None:
    await state.update_data(bulk_delivered_ids=delivered_ids)
    await state.set_state(None)
    await message.answer(
        "❔ <b>Remove After Send?</b>\n"
        "━━━━━━━━━━━━\n\n"
        "Only the accounts successfully included in the sent archive "
        "are eligible.\n\n"
        "🗑 <b>Remove After Send</b> — remove them from the active list "
        "and statistics now.\n"
        "✅ <b>Keep Active</b> — leave them unchanged.",
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
        reply_markup=op_cancel_kb(),
    )
    await callback.answer()
    begin_operation(user_id)

    success_count = 0
    terminated_total = 0
    failed_count = 0

    for i, acc in enumerate(accounts):
        if is_cancelled(user_id):
            break

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
                    reply_markup=op_cancel_kb(),
                )
            except Exception:
                pass

        await asyncio.sleep(1.5)

    stopped_early = success_count + failed_count < total
    date_label = date_obj.strftime("%B %d, %Y")
    is_admin = await db.is_user_admin(user_id)

    done_note = (
        "\n\u274c <i>Stopped early by user.</i>" if stopped_early else ""
    )
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
        + f"{done_note}\n\U0001f4f1 Bot remains logged in to all accounts.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )


@router.callback_query(F.data == "op_cancel")
@authorized
async def cb_op_cancel(callback: CallbackQuery) -> None:
    await handle_cancel_callback(
        callback, "\u274c Stopping after the current account\u2026"
    )


@router.callback_query(F.data.startswith("ls_n:"))
@authorized
async def cb_logout_sessions_no(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Cancel session termination and return to the date listing."""
    parts = callback.data.split(":")
    mode = parts[1]

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
    """Remove successfully sent accounts from active lists and stats."""
    data = await state.get_data()
    ids = data.get("bulk_delivered_ids", [])
    if not ids:
        await callback.answer("Nothing to do.", show_alert=True)
        return

    removed = await db.deactivate_accounts(
        ids,
        status="delivered",
        user_id=callback.from_user.id,
    )

    await callback.message.edit_text(
        "✅ <b>Remove After Send Complete</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"\U0001f4ca {removed} account(s) removed from the active list "
        "and statistics.\n"
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
    """Keep successfully sent accounts active and offer classification."""
    data = await state.get_data()
    ids = data.get("bulk_delivered_ids", [])
    if not ids:
        await callback.answer("Nothing to do.", show_alert=True)
        return

    await callback.message.edit_text(
        "✅ <b>Accounts Kept Active</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"📊  Accounts unchanged: <b>{len(ids)}</b>\n"
        "They remain in the active list and statistics.\n\n"
        "Do you want to apply spam-status classification\n"
        "(green / yellow / red) to these accounts?",
        parse_mode="HTML",
        reply_markup=bulk_status_filter_prompt_kb(),
    )
    await callback.answer()


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

    await callback.answer()
    counts, breakdown, stopped_early = await _run_status_sweep(
        callback, ids
    )
    await state.update_data(
        status_sweep_ids=ids,
        status_counts=counts,
        status_breakdown=breakdown,
    )

    note = (
        "\n\n\u274c <i>Sweep stopped early \u2014 remaining accounts "
        "not checked.</i>"
        if stopped_early
        else ""
    )
    await callback.message.edit_text(
        _format_status_summary(counts, breakdown)
        + note
        + "\n\nExport a status group or choose a deliberate "
        "removal action below.",
        parse_mode="HTML",
        reply_markup=status_actions_kb(counts),
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
) -> tuple[dict[str, int], list[tuple[str, str]], bool]:
    """Classify accounts without changing their active state.

    Returns ``(counts, breakdown, stopped_early)``.
    """
    total = len(account_ids)
    counts = {"green": 0, "yellow": 0, "red": 0, "unknown": 0}
    breakdown: list[tuple[str, str]] = []
    user_id = callback.from_user.id
    accounts = await db.get_accounts_by_ids(
        user_id,
        account_ids,
        include_inactive=True,
    )
    accounts_by_id = {account.id: account for account in accounts}

    begin_operation(user_id)
    stopped_early = False

    for i, acc_id in enumerate(account_ids):
        if is_cancelled(user_id):
            stopped_early = True
            break

        acc = accounts_by_id.get(acc_id)
        if not acc:
            counts["unknown"] += 1
            breakdown.append((f"Account {acc_id}", "unknown"))
        else:
            proxy = await db.get_active_proxy(user_id)
            try:
                status, _text = await check_spam_status(
                    acc.session_string, proxy=proxy
                )
            except Exception:
                logger.exception("Status check failed for %s", acc.phone)
                status = "unknown"

            status = normalize_spam_status(status)

            await db.set_spam_status(
                acc_id,
                status,
                user_id=user_id,
            )
            counts[status] += 1
            breakdown.append((acc.phone, status))
            await db.increment_rotation_counter(user_id)

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
                    reply_markup=op_cancel_kb(),
                )
            except Exception:
                pass
        await asyncio.sleep(1.0)

    return counts, breakdown, stopped_early


def _format_status_summary(
    counts: dict[str, int],
    _breakdown: list[tuple[str, str]],
) -> str:
    total_count = sum(counts.values())
    denominator = total_count or 1
    pct = {
        status: round(100 * counts.get(status, 0) / denominator)
        for status in SPAM_STATUSES
    }
    lines = [
        "✅ <b>Status Sweep Complete</b>",
        "━━━━━━━━━━━━",
        "",
        f"📊  Scanned: <b>{total_count}</b>",
        "",
        f"\U0001f7e2  Green:  <b>{counts.get('green', 0)}</b>  "
        f"({pct.get('green', 0)}%)",
        f"\U0001f7e1  Yellow: <b>{counts.get('yellow', 0)}</b>  "
        f"({pct.get('yellow', 0)}%)",
        f"\U0001f534  Red:    <b>{counts.get('red', 0)}</b>  "
        f"({pct.get('red', 0)}%)",
        f"⚪  Unknown: <b>{counts.get('unknown', 0)}</b>  "
        f"({pct.get('unknown', 0)}%)",
    ]
    return "\n".join(lines)


async def _get_status_accounts(
    state: FSMContext,
    user_id: int,
    color: str,
    *,
    include_inactive: bool,
) -> list:
    """Return owner-scoped accounts from the latest sweep by status."""
    if color not in SPAM_STATUSES:
        return []
    data = await state.get_data()
    account_ids = data.get("status_sweep_ids", [])
    accounts = await db.get_accounts_by_ids(
        user_id,
        account_ids,
        include_inactive=include_inactive,
    )
    return filter_accounts_by_status(accounts, color)


async def _refresh_status_actions(
    callback: CallbackQuery,
    state: FSMContext,
    notice: str | None = None,
) -> None:
    """Render the latest sweep and its action keyboard from FSM data."""
    data = await state.get_data()
    account_ids = data.get("status_sweep_ids", [])
    accounts = await db.get_accounts_by_ids(
        callback.from_user.id,
        account_ids,
        include_inactive=True,
    )
    counts = count_account_statuses(accounts)
    breakdown = [
        (account.phone, normalize_spam_status(account.spam_status))
        for account in accounts
    ]

    await state.update_data(
        status_counts=counts,
        status_breakdown=breakdown,
    )
    text = _format_status_summary(counts, breakdown)
    if notice:
        text += f"\n\n{notice}"
    text += "\n\nExport a status group or choose a removal action."
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=status_actions_kb(counts),
    )


@router.callback_query(F.data.startswith("sf_export:"))
@authorized
async def cb_status_export(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Choose a file format for one classified status group."""
    color = callback.data.split(":", 1)[1]
    if color not in SPAM_STATUSES:
        await callback.answer("Invalid status.", show_alert=True)
        return

    accounts = await _get_status_accounts(
        state,
        callback.from_user.id,
        color,
        include_inactive=True,
    )
    if not accounts:
        await callback.answer(
            f"No {color} accounts to export.", show_alert=True
        )
        return

    await callback.message.edit_text(
        f"📦 <b>Export {color.title()} Accounts</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"Found <b>{len(accounts)}</b> classified account(s).\n"
        "Choose the session file format:",
        parse_mode="HTML",
        reply_markup=status_export_format_kb(color),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sf_fmt:"))
@authorized
async def cb_status_export_format(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Build and send a ZIP containing only the selected status."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Invalid export request.", show_alert=True)
        return
    _, color, fmt = parts
    if color not in SPAM_STATUSES or fmt not in SESSION_FORMATS:
        await callback.answer("Invalid export request.", show_alert=True)
        return

    accounts = await _get_status_accounts(
        state,
        callback.from_user.id,
        color,
        include_inactive=True,
    )
    if not accounts:
        await callback.answer(
            f"No {color} accounts to export.", show_alert=True
        )
        return

    await callback.answer()
    await callback.message.edit_text(
        f"⏳ Building {color.title()} account archive…",
        parse_mode="HTML",
    )

    proxy = await db.get_active_proxy(callback.from_user.id)
    archive = await _build_bulk_zip(accounts, fmt, proxy)
    if not archive.successful_ids:
        archive.cleanup()
        await _refresh_status_actions(
            callback,
            state,
            notice=(
                f"❌ No {color} session files could be converted. "
                "No accounts were removed."
            ),
        )
        return

    exported_count = len(archive.successful_ids)
    filename = f"status_{color}_{fmt}_{exported_count}accounts.zip"
    fmt_label = {
        "telethon": "Telethon",
        "pyrogram": "Pyrogram",
        "tdata": "TData (Desktop)",
    }[fmt]
    try:
        await callback.message.answer_document(
            FSInputFile(archive.file_path, filename=filename),
            caption=(
                f"📦 <b>{color.title()} Accounts</b>\n\n"
                f"Status: <b>{color.title()}</b>\n"
                f"Format: <b>{fmt_label}</b>\n"
                f"Accounts sent: <b>{exported_count}</b>"
                + (
                    f"\n⚠️ Conversion failures: "
                    f"<b>{len(archive.failed_ids)}</b>"
                    if archive.failed_ids
                    else ""
                )
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "Failed to send %s status archive", color
        )
        await _refresh_status_actions(
            callback,
            state,
            notice=(
                "❌ Telegram could not send the filtered archive. "
                "No accounts were removed."
            ),
        )
        return
    finally:
        archive.cleanup()
    await state.update_data(
        status_last_export_ids=archive.successful_ids,
        status_last_export_color=color,
    )
    await callback.message.edit_text(
        f"✅ <b>{color.title()} Archive Sent</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"Successfully sent <b>{exported_count}</b> account(s).\n\n"
        "Choose whether these successfully sent accounts should remain "
        "active.",
        parse_mode="HTML",
        reply_markup=status_post_export_kb(color),
    )


@router.callback_query(F.data.startswith("sf_sent_rm:"))
@authorized
async def cb_status_remove_after_send(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Deactivate only accounts included in the last sent status ZIP."""
    color = callback.data.split(":", 1)[1]
    data = await state.get_data()
    ids = data.get("status_last_export_ids", [])
    last_color = data.get("status_last_export_color")
    if color not in SPAM_STATUSES or color != last_color or not ids:
        await callback.answer(
            "No completed export is available to remove.",
            show_alert=True,
        )
        return

    removed = await db.deactivate_accounts(
        ids,
        status=f"removed_{color}",
        user_id=callback.from_user.id,
    )
    remaining_ids = without_account_ids(
        data.get("status_sweep_ids", []),
        ids,
    )
    await state.update_data(
        status_sweep_ids=remaining_ids,
        status_last_export_ids=[],
        status_last_export_color=None,
    )
    await callback.answer(
        f"Removed {removed} active account(s).", show_alert=True
    )
    await _refresh_status_actions(
        callback,
        state,
        notice=(
            f"🗑 Remove After Send processed the {len(ids)} successfully "
            f"sent {color} account(s); {removed} were active and are now "
            "absent from statistics."
        ),
    )


@router.callback_query(F.data == "sf_remove_menu")
@authorized
async def cb_status_remove_menu(
    callback: CallbackQuery, state: FSMContext
) -> None:
    counts: dict[str, int] = {}
    for color in ("green", "yellow", "red", "unknown"):
        accounts = await _get_status_accounts(
            state,
            callback.from_user.id,
            color,
            include_inactive=False,
        )
        counts[color] = len(accounts)

    await callback.message.edit_text(
        "🗑 <b>Remove Accounts by Status</b>\n"
        "━━━━━━━━━━━━\n\n"
        "This action removes matching active accounts from the active "
        "list and statistics. It does not log the bot out.\n\n"
        "Choose a status:",
        parse_mode="HTML",
        reply_markup=status_remove_kb(counts),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sf_rm:"))
@authorized
async def cb_status_remove(
    callback: CallbackQuery, state: FSMContext
) -> None:
    color = callback.data.split(":", 1)[1]
    if color not in SPAM_STATUSES:
        await callback.answer("Invalid status.", show_alert=True)
        return

    accounts = await _get_status_accounts(
        state,
        callback.from_user.id,
        color,
        include_inactive=False,
    )
    if not accounts:
        await callback.answer(
            f"No active {color} accounts to remove.", show_alert=True
        )
        return

    ids = [account.id for account in accounts]
    removed = await db.deactivate_accounts(
        ids,
        status=f"removed_{color}",
        user_id=callback.from_user.id,
    )
    data = await state.get_data()
    remaining_ids = without_account_ids(
        data.get("status_sweep_ids", []),
        ids,
    )
    await state.update_data(status_sweep_ids=remaining_ids)
    await callback.answer(
        f"Removed {removed} {color} account(s).", show_alert=True
    )
    await _refresh_status_actions(
        callback,
        state,
        notice=(
            f"🗑 Removed <b>{removed}</b> {color} account(s) from the "
            "active list and statistics."
        ),
    )


@router.callback_query(F.data == "sf_back")
@authorized
async def cb_status_back(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await _refresh_status_actions(callback, state)
    await callback.answer()


@router.callback_query(F.data == "sf_done")
@authorized
async def cb_status_done(
    callback: CallbackQuery, state: FSMContext
) -> None:
    is_admin = await db.is_user_admin(callback.from_user.id)
    suspicious = await db.get_suspicious_accounts(callback.from_user.id)
    await callback.message.edit_text(
        "✅ Status workflow complete.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(
            is_admin,
            has_suspicious=bool(suspicious),
        ),
    )
    await state.clear()
    await callback.answer()


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

    await callback.message.edit_text(
        "⏳ <b>Status Sweep</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"Checking <b>{len(accounts)}</b> account(s) via @SpamBot…",
        parse_mode="HTML",
    )
    await callback.answer()

    ids = [a.id for a in accounts]
    counts, breakdown, stopped_early = await _run_status_sweep(
        callback, ids
    )
    await state.update_data(
        status_sweep_ids=ids,
        status_counts=counts,
        status_breakdown=breakdown,
    )
    note = (
        "\n\n\u274c <i>Sweep stopped early \u2014 remaining accounts "
        "not checked.</i>"
        if stopped_early
        else ""
    )
    await callback.message.edit_text(
        _format_status_summary(counts, breakdown)
        + note
        + "\n\nExport a status group or choose a deliberate "
        "removal action below.",
        parse_mode="HTML",
        reply_markup=status_actions_kb(counts),
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
        reply_markup=op_cancel_kb(),
    )
    await callback.answer()
    begin_operation(user_id)

    proxy = await db.get_active_proxy(user_id)
    chats_total = 0
    groups_total = 0
    err_total = 0
    processed = 0
    for i, acc in enumerate(accounts):
        if is_cancelled(user_id):
            break

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
                    reply_markup=op_cancel_kb(),
                )
            except Exception:
                pass
        await asyncio.sleep(1.5)
        processed = i + 1

    is_admin = await db.is_user_admin(user_id)
    suspicious = await db.get_suspicious_accounts(user_id)
    done_note = (
        f"\n❌ <i>Stopped early after {processed}/{total} accounts.</i>"
        if processed < total
        else ""
    )
    await callback.message.edit_text(
        "✅ <b>Bulk Chat Cleanup Complete</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"📂  Accounts processed: <b>{min(processed, total)}</b>\n"
        f"🧹  1:1 chats deleted: <b>{chats_total}</b>\n"
        f"👥  Groups/channels left: <b>{groups_total}</b>\n"
        + (f"⚠️  Errors: <b>{err_total}</b>\n" if err_total else "")
        + f"{done_note}\nThe bot remains logged in to every account.",
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
        reply_markup=suspicious_clear_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "sus_clear")
@authorized
async def cb_sus_clear(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cleared = await db.clear_suspicious_flags(user_id)
    is_admin = await db.is_user_admin(user_id)
    await callback.answer(
        f"🧹 Cleared flags on {cleared} account(s).", show_alert=True
    )
    await callback.message.edit_text(
        "❗ <b>Suspicious Accounts</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"🧹 Cleared flags on <b>{cleared}</b> account(s).",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
