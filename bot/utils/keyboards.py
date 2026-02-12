"""
Inline keyboard builders — glass-style design with emojis.
"""

from __future__ import annotations

import datetime as _dt
from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils.country_detector import get_flag


def _btn(text: str, callback_data: str) -> InlineKeyboardButton:
    """Shortcut for creating an inline button."""
    return InlineKeyboardButton(text=text, callback_data=callback_data)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [_btn("\U0001f511  Grant Account Access", "add_account")],
        [
            _btn("\U0001f4ca  Statistics", "statistics"),
            _btn("\U0001f4e6  Deliver", "deliver_menu"),
        ],
        [_btn("\U0001f310  Proxy Settings", "proxy_menu")],
        [_btn("\U0001f510  2FA Settings", "twofa_menu")],
    ]
    if is_admin:
        buttons.append(
            [_btn("\U0001f464  Manage Users", "manage_users")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Generic / Utility
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def cancel_kb(back_cb: str | None = None) -> InlineKeyboardMarkup:
    cb = back_cb or "main_menu"
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("\u274c  Cancel", cb)]]
    )


def confirm_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("\u2705  Yes", yes_cb), _btn("\u274c  No", no_cb)]
        ]
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# User Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def manage_users_kb(users) -> InlineKeyboardMarkup:
    buttons = []
    for u in users:
        admin_badge = " \U0001f451" if u.is_admin else ""
        buttons.append(
            [
                _btn(
                    f"\U0001f194 {u.telegram_id}{admin_badge}",
                    f"user_view:{u.telegram_id}",
                )
            ]
        )
    buttons.append([_btn("\u2795  Add User", "user_add")])
    buttons.append([_btn("\U0001f519  Back", "main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def user_detail_kb(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("\U0001f5d1  Remove User", f"user_remove:{telegram_id}")],
            [_btn("\U0001f519  Back", "manage_users")],
        ]
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Delivery
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def deliver_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("\U0001f4f1  Individual Delivery", "deliver_individual")],
            [_btn("\U0001f4c1  Bulk Session Files", "deliver_bulk")],
            [_btn("\U0001f519  Back", "main_menu")],
        ]
    )


def country_select_kb(
    countries: list[str],
    prefix: str = "country",
    back_cb: str = "main_menu",
) -> InlineKeyboardMarkup:
    buttons = []
    for c in countries:
        flag = get_flag(c)
        buttons.append([_btn(f"{flag}  {c}", f"{prefix}:{c}")])
    buttons.append([_btn("\U0001f519  Back", back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def date_select_kb(
    dates,
    prefix: str = "date",
    back_cb: str = "main_menu",
    counts: dict | None = None,
    show_logout_sessions: bool = False,
) -> InlineKeyboardMarkup:
    buttons = []
    for d in dates:
        if isinstance(d, _dt.datetime):
            d = d.date()
        label = d.strftime("%B %d, %Y")
        iso = d.isoformat()
        count_str = f"  ({counts[iso]})" if counts and iso in counts else ""
        row = [_btn(f"\U0001f4c5  {label}{count_str}", f"{prefix}:{iso}")]
        if show_logout_sessions:
            mode = "i" if "ind" in prefix else "b"
            row.append(_btn("\U0001f6aa", f"ls:{mode}:{iso}"))
        buttons.append(row)
    buttons.append([_btn("\U0001f519  Back", back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def account_list_kb(
    accounts,
    prefix: str = "acc",
    back_cb: str = "main_menu",
) -> InlineKeyboardMarkup:
    buttons = []
    for acc in accounts:
        phone = acc.phone
        name = f" \u2014 {acc.first_name}" if acc.first_name else ""
        buttons.append(
            [_btn(f"\U0001f4f1  {phone}{name}", f"{prefix}:{acc.id}")]
        )
    buttons.append([_btn("\U0001f519  Back", back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def session_format_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("\U0001f4f1  Telethon Session", "bulk_format:telethon")],
            [_btn("\U0001f4f1  Pyrogram Session", "bulk_format:pyrogram")],
            [_btn("\U0001f519  Back", "deliver_menu")],
        ]
    )


# ── Individual Delivery Keyboards ────────────────────────────────────


def listening_kb(
    account_id: int, has_next: bool = False
) -> InlineKeyboardMarkup:
    """Keyboard shown while the bot listens for login codes."""
    buttons = [
        [_btn("\U0001f504  Restart Listener", f"resend_code:{account_id}")],
        [
            _btn(
                "\U0001f6aa  Log Out of Account",
                f"logout_acc:{account_id}",
            )
        ],
    ]
    if has_next:
        buttons.append(
            [_btn("\u27a1\ufe0f  Next", f"next_acc:{account_id}")]
        )
    buttons.append([_btn("\u274c  Cancel", "deliver_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def code_received_kb(
    account_id: int, has_next: bool = False
) -> InlineKeyboardMarkup:
    """Keyboard shown after a login code is captured."""
    buttons = [
        [_btn("\U0001f504  Listen Again", f"resend_code:{account_id}")],
        [
            _btn(
                "\U0001f6aa  Log Out of Account",
                f"logout_acc:{account_id}",
            )
        ],
    ]
    if has_next:
        buttons.append(
            [_btn("\u27a1\ufe0f  Next", f"next_acc:{account_id}")]
        )
    buttons.append([_btn("\U0001f519  Back to Menu", "deliver_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def account_actions_kb(
    account_id: int, has_next: bool = False
) -> InlineKeyboardMarkup:
    """General account action buttons."""
    buttons = [
        [_btn("\U0001f504  Resend Code", f"resend_code:{account_id}")],
        [
            _btn(
                "\U0001f6aa  Log Out of Account",
                f"logout_acc:{account_id}",
            )
        ],
    ]
    if has_next:
        buttons.append(
            [_btn("\u27a1\ufe0f  Next", f"next_acc:{account_id}")]
        )
    buttons.append([_btn("\U0001f519  Back to Menu", "deliver_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def next_confirm_kb(account_id: int) -> InlineKeyboardMarkup:
    """Confirm whether to logout current account before moving to next."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "\u2705  Yes, logout and continue",
                    f"next_logout:{account_id}",
                )
            ],
            [
                _btn(
                    "\u274c  No, keep logged in",
                    f"next_keep:{account_id}",
                )
            ],
            [_btn("\U0001f519  Cancel", f"resend_code:{account_id}")],
        ]
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Proxy Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def proxy_menu_kb(
    proxies,
    rotation_enabled: bool = False,
    proxy_count: int = 0,
) -> InlineKeyboardMarkup:
    buttons = []
    for p in proxies:
        default_mark = "\u2705 " if p.is_default else ""
        buttons.append(
            [
                _btn(
                    f"{default_mark}\U0001f310 {p.host}:{p.port}",
                    f"proxy_view:{p.id}",
                )
            ]
        )
    buttons.append([_btn("\u2795  Add Proxy", "proxy_add")])

    # Rotation toggle
    if proxy_count >= 2:
        status = "ON \u2705" if rotation_enabled else "OFF"
        buttons.append(
            [
                _btn(
                    f"\U0001f504  Rotate proxy per account: {status}",
                    "proxy_rotation_toggle",
                )
            ]
        )
    else:
        buttons.append(
            [
                _btn(
                    "\U0001f504  Rotate proxy per account (need 2+)",
                    "proxy_rotation_disabled",
                )
            ]
        )

    buttons.append([_btn("\U0001f519  Back", "main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxy_detail_kb(proxy_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("\u2705  Set as Default", f"proxy_default:{proxy_id}")],
            [_btn("\U0001f5d1  Delete Proxy", f"proxy_delete:{proxy_id}")],
            [_btn("\U0001f519  Back", "proxy_menu")],
        ]
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2FA Settings
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def twofa_menu_kb(has_password: bool = False) -> InlineKeyboardMarkup:
    pwd_icon = "\u2705" if has_password else "\u26a0\ufe0f"
    buttons = [
        [_btn(f"\U0001f511  Set 2FA Password  {pwd_icon}", "twofa_set_pwd")],
        [_btn("\u2705  Enable 2FA (All Accounts)", "twofa_enable_all")],
        [_btn("\u274c  Disable 2FA (All Accounts)", "twofa_disable_all")],
        [_btn("\U0001f195  Enable for New Accounts Only", "twofa_enable_new")],
        [_btn("\U0001f519  Back", "main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def twofa_disable_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("\u2705  Yes, disable 2FA", "twofa_disable_confirm")],
            [_btn("\u274c  Cancel", "twofa_menu")],
        ]
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Logout Other Sessions (per date category)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def logout_sessions_confirm_kb(
    mode: str, date_iso: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "\u2705  Yes, terminate other sessions",
                    f"ls_y:{mode}:{date_iso}",
                )
            ],
            [_btn("\u274c  Cancel", f"ls_n:{mode}:{date_iso}")],
        ]
    )
