"""
2FA Settings — manage two-factor authentication for stored accounts.

Buttons:
  1. Set 2FA Password    — set the shared password used for all 2FA ops
  2. Enable 2FA (All)    — turn on 2FA for every active account
  3. Disable 2FA (All)   — remove 2FA from every active account
  4. Enable for New Only — enable 2FA only on accounts that lack it
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import database as db
from bot.utils.cancellation import (
    begin_operation,
    handle_cancel_callback,
    is_cancelled,
)
from bot.utils.crypto import decrypt_password, encrypt_password
from bot.utils.decorators import authorized
from bot.utils.keyboards import (
    cancel_kb,
    op_cancel_kb,
    twofa_disable_confirm_kb,
    twofa_menu_kb,
)
from bot.utils.session_manager import (
    check_account_has_2fa,
    disable_2fa_on_account,
    enable_2fa_on_account,
)

logger = logging.getLogger(__name__)

router = Router(name="twofa")


# ── FSM States ───────────────────────────────────────────────────────

class TwoFAStates(StatesGroup):
    waiting_password = State()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "twofa_menu")
@authorized
async def cb_twofa_menu(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.clear()
    user_id = callback.from_user.id
    encrypted_pwd = await db.get_twofa_password(user_id)
    has_password = encrypted_pwd is not None

    await callback.message.edit_text(
        "\U0001f510 <b>2FA Settings</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Manage two-factor authentication\n"
        "for all your stored accounts.\n\n"
        + (
            "\u2705 Password is set."
            if has_password
            else "\u26a0\ufe0f No password set yet. "
            "Please set one first."
        ),
        parse_mode="HTML",
        reply_markup=twofa_menu_kb(has_password=has_password),
    )
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Set 2FA Password
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "twofa_set_pwd")
@authorized
async def cb_twofa_set_pwd(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.message.edit_text(
        "\U0001f511 <b>Set 2FA Password</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Enter the password you want to use for\n"
        "2FA on all your accounts.\n\n"
        "\U0001f4dd <i>Minimum 8 characters.</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb("twofa_menu"),
    )
    await state.set_state(TwoFAStates.waiting_password)
    await callback.answer()


@router.message(TwoFAStates.waiting_password)
@authorized
async def on_2fa_password_received(
    message: Message, state: FSMContext
) -> None:
    password = message.text.strip()

    if len(password) < 8:
        await message.answer(
            "\u26a0\ufe0f Password must be at least 8 characters.\n"
            "Please try again.",
            parse_mode="HTML",
            reply_markup=cancel_kb("twofa_menu"),
        )
        return

    encrypted = encrypt_password(password)
    await db.set_twofa_password(message.from_user.id, encrypted)
    await state.clear()

    # Delete the message containing the plaintext password
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        "\u2705 <b>2FA Password Saved</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Your 2FA password has been encrypted\n"
        "and stored securely.\n\n"
        "You can now enable/disable 2FA on\n"
        "your accounts from the 2FA menu.",
        parse_mode="HTML",
        reply_markup=twofa_menu_kb(has_password=True),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _require_password(callback: CallbackQuery) -> str | None:
    """Return the decrypted 2FA password or show an alert and
    return ``None``."""
    encrypted = await db.get_twofa_password(callback.from_user.id)
    if not encrypted:
        await callback.answer(
            "\u26a0\ufe0f Please set a 2FA password first!",
            show_alert=True,
        )
        return None
    try:
        return decrypt_password(encrypted)
    except ValueError:
        await callback.answer(
            "\u274c Could not decrypt password. "
            "Please re-set it.",
            show_alert=True,
        )
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Enable 2FA — All Accounts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "twofa_enable_all")
@authorized
async def cb_twofa_enable_all(
    callback: CallbackQuery, state: FSMContext
) -> None:
    password = await _require_password(callback)
    if not password:
        return

    user_id = callback.from_user.id
    accounts = await db.get_all_active_accounts(user_id)
    if not accounts:
        await callback.answer(
            "\U0001f4ed No active accounts.", show_alert=True
        )
        return

    total = len(accounts)
    await callback.message.edit_text(
        f"\u23f3 <b>Enabling 2FA\u2026</b>  0/{total}\n"
        "Please wait, this may take a while.",
        parse_mode="HTML",
        reply_markup=op_cancel_kb(),
    )
    await callback.answer()
    begin_operation(user_id)

    enabled = 0
    skipped = 0
    failed = 0

    for i, acc in enumerate(accounts):
        if is_cancelled(user_id):
            break

        proxy = await db.get_active_proxy(user_id)

        ok, reason = await enable_2fa_on_account(
            acc.session_string, password, proxy=proxy
        )

        if ok:
            enabled += 1
            await db.update_account_2fa(acc.id, True)
        elif reason == "already_has_2fa":
            skipped += 1
            await db.update_account_2fa(acc.id, True)
        else:
            failed += 1
            if reason.startswith("flood_wait:"):
                wait = int(reason.split(":")[1])
                await asyncio.sleep(min(wait, 60))

        await db.increment_rotation_counter(user_id)

        if (i + 1) % 5 == 0 or i == total - 1:
            try:
                await callback.message.edit_text(
                    f"\u23f3 <b>Enabling 2FA\u2026</b>  "
                    f"{i + 1}/{total}\n"
                    f"\u2705 {enabled}  \u23ed {skipped}  "
                    f"\u274c {failed}",
                    parse_mode="HTML",
                    reply_markup=op_cancel_kb(),
                )
            except Exception:
                pass

        await asyncio.sleep(2)

    processed = enabled + skipped + failed
    done_note = (
        f"\n\u274c <i>Stopped early \u2014 {processed}/{total} "
        "processed.</i>"
        if processed < total
        else ""
    )
    await callback.message.edit_text(
        "\u2705 <b>2FA Enable Complete</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4ca  Total: <b>{total}</b>\n"
        f"\u2705  Enabled: <b>{enabled}</b>\n"
        f"\u23ed  Already had 2FA: <b>{skipped}</b>\n"
        f"\u274c  Failed: <b>{failed}</b>"
        + done_note,
        parse_mode="HTML",
        reply_markup=twofa_menu_kb(has_password=True),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Disable 2FA — All Accounts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "twofa_disable_all")
@authorized
async def cb_twofa_disable_all(
    callback: CallbackQuery, state: FSMContext
) -> None:
    password = await _require_password(callback)
    if not password:
        return

    await callback.message.edit_text(
        "\u26a0\ufe0f <b>Disable 2FA</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "This will remove 2FA from <b>all</b>\n"
        "your active accounts.\n\n"
        "Are you sure?",
        parse_mode="HTML",
        reply_markup=twofa_disable_confirm_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "twofa_disable_confirm")
@authorized
async def cb_twofa_disable_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    password = await _require_password(callback)
    if not password:
        return

    user_id = callback.from_user.id
    accounts = await db.get_all_active_accounts(user_id)
    if not accounts:
        await callback.answer(
            "\U0001f4ed No active accounts.", show_alert=True
        )
        return

    total = len(accounts)
    await callback.message.edit_text(
        f"\u23f3 <b>Disabling 2FA\u2026</b>  0/{total}\n"
        "Please wait, this may take a while.",
        parse_mode="HTML",
        reply_markup=op_cancel_kb(),
    )
    await callback.answer()
    begin_operation(user_id)

    disabled = 0
    skipped = 0
    failed = 0

    for i, acc in enumerate(accounts):
        if is_cancelled(user_id):
            break

        proxy = await db.get_active_proxy(user_id)

        ok, reason = await disable_2fa_on_account(
            acc.session_string, password, proxy=proxy
        )

        if ok:
            disabled += 1
            await db.update_account_2fa(acc.id, False)
        elif reason == "no_2fa":
            skipped += 1
            await db.update_account_2fa(acc.id, False)
        else:
            failed += 1
            if reason.startswith("flood_wait:"):
                wait = int(reason.split(":")[1])
                await asyncio.sleep(min(wait, 60))

        await db.increment_rotation_counter(user_id)

        if (i + 1) % 5 == 0 or i == total - 1:
            try:
                await callback.message.edit_text(
                    f"\u23f3 <b>Disabling 2FA\u2026</b>  "
                    f"{i + 1}/{total}\n"
                    f"\u274c {disabled}  \u23ed {skipped}  "
                    f"\u26a0\ufe0f {failed}",
                    parse_mode="HTML",
                    reply_markup=op_cancel_kb(),
                )
            except Exception:
                pass

        await asyncio.sleep(2)

    processed = disabled + skipped + failed
    done_note = (
        f"\n\u274c <i>Stopped early \u2014 {processed}/{total} "
        "processed.</i>"
        if processed < total
        else ""
    )
    await callback.message.edit_text(
        "\u274c <b>2FA Disable Complete</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4ca  Total: <b>{total}</b>\n"
        f"\u274c  Disabled: <b>{disabled}</b>\n"
        f"\u23ed  Had no 2FA: <b>{skipped}</b>\n"
        f"\u26a0\ufe0f  Failed: <b>{failed}</b>"
        + done_note,
        parse_mode="HTML",
        reply_markup=twofa_menu_kb(has_password=True),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Enable for New Accounts Only
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "twofa_enable_new")
@authorized
async def cb_twofa_enable_new(
    callback: CallbackQuery, state: FSMContext
) -> None:
    password = await _require_password(callback)
    if not password:
        return

    user_id = callback.from_user.id
    accounts = await db.get_all_active_accounts(user_id)
    if not accounts:
        await callback.answer(
            "\U0001f4ed No active accounts.", show_alert=True
        )
        return

    total = len(accounts)
    await callback.message.edit_text(
        f"\u23f3 <b>Scanning accounts\u2026</b>  0/{total}\n"
        "Detecting 2FA status and enabling\n"
        "on new accounts only.",
        parse_mode="HTML",
        reply_markup=op_cancel_kb(),
    )
    await callback.answer()
    begin_operation(user_id)

    enabled = 0
    skipped = 0
    failed = 0

    for i, acc in enumerate(accounts):
        if is_cancelled(user_id):
            break

        proxy = await db.get_active_proxy(user_id)

        # First check current 2FA status via API
        has_2fa = await check_account_has_2fa(
            acc.session_string, proxy=proxy
        )

        if has_2fa is True:
            skipped += 1
            await db.update_account_2fa(acc.id, True)
        elif has_2fa is False:
            ok, reason = await enable_2fa_on_account(
                acc.session_string, password, proxy=proxy
            )
            if ok:
                enabled += 1
                await db.update_account_2fa(acc.id, True)
            elif reason == "already_has_2fa":
                skipped += 1
                await db.update_account_2fa(acc.id, True)
            else:
                failed += 1
                if reason.startswith("flood_wait:"):
                    wait = int(reason.split(":")[1])
                    await asyncio.sleep(min(wait, 60))
        else:
            failed += 1  # check failed (session invalid, etc.)

        await db.increment_rotation_counter(user_id)

        if (i + 1) % 5 == 0 or i == total - 1:
            try:
                await callback.message.edit_text(
                    f"\u23f3 <b>Processing\u2026</b>  "
                    f"{i + 1}/{total}\n"
                    f"\u2705 {enabled}  \u23ed {skipped}  "
                    f"\u274c {failed}",
                    parse_mode="HTML",
                    reply_markup=op_cancel_kb(),
                )
            except Exception:
                pass

        await asyncio.sleep(2)

    processed = enabled + skipped + failed
    done_note = (
        f"\n\u274c <i>Stopped early \u2014 {processed}/{total} "
        "processed.</i>"
        if processed < total
        else ""
    )
    await callback.message.edit_text(
        "\U0001f195 <b>New-Account 2FA Complete</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4ca  Total: <b>{total}</b>\n"
        f"\u2705  Enabled: <b>{enabled}</b>\n"
        f"\u23ed  Already had 2FA: <b>{skipped}</b>\n"
        f"\u274c  Failed: <b>{failed}</b>"
        + done_note,
        parse_mode="HTML",
        reply_markup=twofa_menu_kb(has_password=True),
    )


@router.callback_query(F.data == "op_cancel")
@authorized
async def cb_op_cancel(callback: CallbackQuery) -> None:
    await handle_cancel_callback(
        callback, "\u274c Stopping after the current account\u2026"
    )
