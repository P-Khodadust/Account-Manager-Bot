"""
Inline keyboard builders — glass-style buttons with emojis.

Glass-style = we use subtle emoji accents + clean text to give a modern feel.
Telegram doesn't support actual translucent buttons, so we rely on
well-chosen emoji + clean layout to evoke the aesthetic.
"""

from __future__ import annotations

import datetime as _dt
from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_FLAG_MAP: dict[str, str] = {
    "USA": "🇺🇸",
    "Canada": "🇨🇦",
    "Iran": "🇮🇷",
    "United Kingdom": "🇬🇧",
    "Germany": "🇩🇪",
    "France": "🇫🇷",
    "Turkey": "🇹🇷",
    "Russia": "🇷🇺",
    "India": "🇮🇳",
    "China": "🇨🇳",
    "Japan": "🇯🇵",
    "Brazil": "🇧🇷",
    "Australia": "🇦🇺",
    "Italy": "🇮🇹",
    "Spain": "🇪🇸",
    "Netherlands": "🇳🇱",
    "South Korea": "🇰🇷",
    "UAE": "🇦🇪",
    "Saudi Arabia": "🇸🇦",
    "Ukraine": "🇺🇦",
    "Poland": "🇵🇱",
    "Mexico": "🇲🇽",
    "Indonesia": "🇮🇩",
    "Egypt": "🇪🇬",
    "Pakistan": "🇵🇰",
    "Nigeria": "🇳🇬",
    "Argentina": "🇦🇷",
    "Colombia": "🇨🇴",
    "Thailand": "🇹🇭",
    "Vietnam": "🇻🇳",
    "Philippines": "🇵🇭",
    "Malaysia": "🇲🇾",
    "Singapore": "🇸🇬",
    "Sweden": "🇸🇪",
    "Norway": "🇳🇴",
    "Denmark": "🇩🇰",
    "Finland": "🇫🇮",
    "Switzerland": "🇨🇭",
    "Austria": "🇦🇹",
    "Belgium": "🇧🇪",
    "Portugal": "🇵🇹",
    "Ireland": "🇮🇪",
    "Greece": "🇬🇷",
    "Czech Republic": "🇨🇿",
    "Romania": "🇷🇴",
    "Hungary": "🇭🇺",
    "Israel": "🇮🇱",
    "Iraq": "🇮🇶",
    "Lebanon": "🇱🇧",
    "Jordan": "🇯🇴",
    "Kuwait": "🇰🇼",
    "Qatar": "🇶🇦",
    "Bahrain": "🇧🇭",
    "Oman": "🇴🇲",
    "Afghanistan": "🇦🇫",
    "Bangladesh": "🇧🇩",
    "Sri Lanka": "🇱🇰",
    "Myanmar": "🇲🇲",
    "New Zealand": "🇳🇿",
    "Chile": "🇨🇱",
    "Peru": "🇵🇪",
    "Venezuela": "🇻🇪",
    "Cuba": "🇨🇺",
    "South Africa": "🇿🇦",
    "Kenya": "🇰🇪",
    "Morocco": "🇲🇦",
    "Algeria": "🇩🇿",
    "Tunisia": "🇹🇳",
    "Taiwan": "🇹🇼",
    "Georgia": "🇬🇪",
    "Azerbaijan": "🇦🇿",
    "Uzbekistan": "🇺🇿",
    "Kazakhstan": "🇰🇿",
    "Serbia": "🇷🇸",
    "Croatia": "🇭🇷",
}


def _flag(country: str) -> str:
    return _FLAG_MAP.get(country, "🌍")


def _btn(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def _back_btn(callback_data: str = "main_menu") -> InlineKeyboardButton:
    return InlineKeyboardButton(text="◀️ Back", callback_data=callback_data)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [_btn("🔑  Grant Account Access", "add_account")],
        [_btn("📊  Statistics", "statistics")],
        [_btn("📦  Deliver Accounts", "deliver_menu")],
        [_btn("🌐  Proxy Settings", "proxy_menu")],
    ]
    if is_admin:
        rows.append([_btn("👤  Manage Users", "manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Country selection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def country_select_kb(
    countries: Sequence[str],
    prefix: str = "country",
    back_cb: str = "main_menu",
) -> InlineKeyboardMarkup:
    rows = []
    for c in countries:
        rows.append([_btn(f"{_flag(c)}  {c}", f"{prefix}:{c}")])
    rows.append([_back_btn(back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Date selection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def date_select_kb(
    dates: Sequence[_dt.date],
    prefix: str = "date",
    back_cb: str = "main_menu",
    counts: dict[str, int] | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    for d in dates:
        d_val = d
        if isinstance(d, _dt.datetime):
            d_val = d.date()
        label = d_val.strftime("%B %d, %Y")
        iso = d_val.isoformat()
        count_str = f"  ({counts[iso]})" if counts and iso in counts else ""
        rows.append([_btn(f"📅  {label}{count_str}", f"{prefix}:{iso}")])
    rows.append([_back_btn(back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Account list
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def account_list_kb(
    accounts: list,
    prefix: str = "acc",
    back_cb: str = "main_menu",
) -> InlineKeyboardMarkup:
    rows = []
    for acc in accounts:
        label = f"📱  {acc.phone}"
        if acc.first_name:
            label += f"  ({acc.first_name})"
        rows.append([_btn(label, f"{prefix}:{acc.id}")])
    rows.append([_back_btn(back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Account actions (after selecting for delivery)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def account_actions_kb(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄  Resend Code", f"resend_code:{account_id}")],
        [_btn("🚪  Log Out of Account", f"logout_acc:{account_id}")],
        [_back_btn("deliver_menu")],
    ])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deliver menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def deliver_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📱  Individual Account", "deliver_individual")],
        [_btn("📁  Bulk Session Files", "deliver_bulk")],
        [_back_btn("main_menu")],
    ])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Session format selection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def session_format_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📗  Telethon Session", "bulk_format:telethon")],
        [_btn("📘  Pyrogram Session", "bulk_format:pyrogram")],
        [_back_btn("deliver_menu")],
    ])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Proxy menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def proxy_menu_kb(proxies: list | None = None) -> InlineKeyboardMarkup:
    rows = [
        [_btn("➕  Add Proxy", "proxy_add")],
    ]
    if proxies:
        for p in proxies:
            default = " ✅" if p.is_default else ""
            label = p.label or f"{p.host}:{p.port}"
            rows.append([_btn(f"🔹  {label}{default}", f"proxy_view:{p.id}")])
    rows.append([_back_btn("main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_detail_kb(proxy_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⭐  Set as Default", f"proxy_default:{proxy_id}")],
        [_btn("🗑  Delete Proxy", f"proxy_delete:{proxy_id}")],
        [_back_btn("proxy_menu")],
    ])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# User management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def manage_users_kb(users: list | None = None) -> InlineKeyboardMarkup:
    rows = [
        [_btn("➕  Add User", "user_add")],
    ]
    if users:
        for u in users:
            tag = "👑" if u.is_admin else "👤"
            label = u.label or str(u.telegram_id)
            rows.append([_btn(f"{tag}  {label} ({u.telegram_id})", f"user_view:{u.telegram_id}")])
    rows.append([_back_btn("main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_detail_kb(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗑  Remove User", f"user_remove:{telegram_id}")],
        [_back_btn("manage_users")],
    ])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Confirmation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def confirm_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("✅  Yes", yes_cb),
            _btn("❌  No", no_cb),
        ]
    ])


def cancel_kb(cb: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("❌  Cancel", cb)],
    ])
