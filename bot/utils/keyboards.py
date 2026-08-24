"""
Inline keyboard builders — glass-style design with emojis.
"""

from __future__ import annotations

import datetime as _dt

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils.country_detector import get_flag


def _btn(text: str, callback_data: str) -> InlineKeyboardButton:
    """Shortcut for creating an inline button."""
    return InlineKeyboardButton(text=text, callback_data=callback_data)


# Telegram allows at most 100 buttons per inline keyboard; keep a safe
# margin for the back / navigation rows.
PAGE_SIZE = 80


def _pager_rows(
    page: int,
    total_pages: int,
    page_cb: str,
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(_btn("◀️", f"{page_cb}:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
    if page < total_pages - 1:
        nav.append(_btn("▶️", f"{page_cb}:{page + 1}"))
    if len(nav) > 1 or total_pages > 1:
        rows.append(nav)
    return rows


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def main_menu_kb(
    is_admin: bool = False,
    has_suspicious: bool = False,
) -> InlineKeyboardMarkup:
    buttons = [
        [_btn("\U0001f511  Grant Account Access", "add_account")],
        [_btn("\U0001f4e5  Import Sessions (.zip)", "import_sessions")],
        [
            _btn("\U0001f4ca  Statistics", "statistics"),
            _btn("\U0001f4e6  Deliver", "deliver_menu"),
        ],
        [_btn("\U0001f310  Proxy Settings", "proxy_menu")],
        [_btn("\U0001f510  2FA Settings", "twofa_menu")],
    ]
    if has_suspicious:
        buttons.append(
            [_btn("❗  Suspicious Accounts", "suspicious_list")]
        )
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


def op_cancel_kb() -> InlineKeyboardMarkup:
    """Stop button for long-running bulk operations."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("\u274c  Stop", "op_cancel")]]
    )


def noop_kb() -> InlineKeyboardMarkup:
    """Keyboard whose only action is a harmless no-op button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("·", "noop")]]
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
            [_btn("\U0001f4c1  Bulk — By Date", "deliver_bulk")],
            [
                _btn(
                    "\U0001f4e6  Bulk — By Country (All Dates)",
                    "deliver_bulk_country",
                )
            ],
            [_btn("\U0001f30d  Bulk — All Accounts", "deliver_bulk_all")],
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
    page: int = 0,
    page_cb: str | None = None,
) -> InlineKeyboardMarkup:
    buttons = []
    total_pages = 1
    if page_cb and len(dates) > PAGE_SIZE:
        total_pages = (len(dates) + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(0, min(page, total_pages - 1))
        dates = dates[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
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
            row.append(_btn("✅", f"ck:{mode}:{iso}"))
            row.append(_btn("\U0001f5d1", f"tr:{mode}:{iso}"))
        buttons.append(row)
    if page_cb:
        buttons.extend(_pager_rows(page, total_pages, page_cb))
    buttons.append([_btn("\U0001f519  Back", back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _spam_emoji(status: str | None) -> str:
    return {
        "green": "\U0001f7e2",
        "yellow": "\U0001f7e1",
        "red": "\U0001f534",
    }.get(status or "unknown", "⚪")


def account_list_kb(
    accounts,
    prefix: str = "acc",
    back_cb: str = "main_menu",
    page: int = 0,
    page_cb: str | None = None,
) -> InlineKeyboardMarkup:
    buttons = []
    total_pages = 1
    if page_cb and len(accounts) > PAGE_SIZE:
        total_pages = (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(0, min(page, total_pages - 1))
        accounts = accounts[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    for acc in accounts:
        phone = acc.phone
        name = f" \u2014 {acc.first_name}" if acc.first_name else ""
        emoji = _spam_emoji(getattr(acc, "spam_status", None))
        sus = " \u2757" if getattr(acc, "is_suspicious", False) else ""
        buttons.append(
            [
                _btn(
                    f"{emoji}  {phone}{name}{sus}",
                    f"{prefix}:{acc.id}",
                )
            ]
        )
    if page_cb:
        buttons.extend(_pager_rows(page, total_pages, page_cb))
    buttons.append([_btn("\U0001f519  Back", back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def session_format_kb(
    back_cb: str = "deliver_menu",
    callback_prefix: str = "bulk_format",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "\U0001f4f1  Telethon Session",
                    f"{callback_prefix}:telethon",
                )
            ],
            [
                _btn(
                    "\U0001f4f1  Pyrogram Session",
                    f"{callback_prefix}:pyrogram",
                )
            ],
            [_btn("\U0001f5a5  TData (Desktop)", f"{callback_prefix}:tdata")],
            [_btn("\U0001f519  Back", back_cb)],
        ]
    )


def bulk_post_delivery_kb() -> InlineKeyboardMarkup:
    """Choose whether successfully sent accounts remain active."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "\U0001f5d1  Remove After Send",
                    "bd_yes",
                ),
                _btn(
                    "\u2705  Keep Active",
                    "bd_no",
                ),
            ]
        ]
    )


def bulk_status_filter_prompt_kb() -> InlineKeyboardMarkup:
    """Ask the user whether to apply spam classification to delivered accounts."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("\u2705  Apply classification", "bd_classify_yes"),
                _btn("\u274c  Skip", "bd_classify_no"),
            ]
        ]
    )


def status_actions_kb(
    counts: dict[str, int] | None = None,
) -> InlineKeyboardMarkup:
    """Offer explicit export and removal actions after a status sweep."""
    counts = counts or {}

    def label(emoji: str, color: str) -> str:
        return f"{emoji}  Export {color.title()} ({counts.get(color, 0)})"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(label("\U0001f7e2", "green"), "sf_export:green"),
                _btn(label("\U0001f7e1", "yellow"), "sf_export:yellow"),
            ],
            [
                _btn(label("\U0001f534", "red"), "sf_export:red"),
                _btn(label("⚪", "unknown"), "sf_export:unknown"),
            ],
            [_btn("\U0001f5d1  Remove by Status", "sf_remove_menu")],
            [_btn("\u2705  Done", "sf_done")],
        ]
    )


def status_remove_kb(
    counts: dict[str, int] | None = None,
) -> InlineKeyboardMarkup:
    """Offer deliberate, status-specific removal actions."""
    counts = counts or {}
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    f"\U0001f7e2  Remove Green ({counts.get('green', 0)})",
                    "sf_rm:green",
                )
            ],
            [
                _btn(
                    f"\U0001f7e1  Remove Yellow ({counts.get('yellow', 0)})",
                    "sf_rm:yellow",
                )
            ],
            [
                _btn(
                    f"\U0001f534  Remove Red ({counts.get('red', 0)})",
                    "sf_rm:red",
                )
            ],
            [
                _btn(
                    f"⚪  Remove Unknown ({counts.get('unknown', 0)})",
                    "sf_rm:unknown",
                )
            ],
            [_btn("\U0001f519  Back", "sf_back")],
        ]
    )


def status_export_format_kb(color: str) -> InlineKeyboardMarkup:
    """Choose the format for a status-filtered archive."""
    return session_format_kb(
        back_cb="sf_back",
        callback_prefix=f"sf_fmt:{color}",
    )


def status_post_export_kb(color: str) -> InlineKeyboardMarkup:
    """Choose whether successfully sent filtered accounts stay active."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "\U0001f5d1  Remove After Send",
                    f"sf_sent_rm:{color}",
                )
            ],
            [_btn("\u2705  Keep Active", "sf_back")],
        ]
    )


def trash_confirm_kb(mode: str, key: str) -> InlineKeyboardMarkup:
    """Confirm bulk chat deletion. ``key`` is the date iso or scope id."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "\u2705  Yes, delete chats",
                    f"tr_y:{mode}:{key}",
                )
            ],
            [_btn("\u274c  Cancel", f"tr_n:{mode}:{key}")],
        ]
    )


def bulk_country_format_kb(scope: str) -> InlineKeyboardMarkup:
    """Session-format selector reused for the new bulk scopes.

    ``scope`` is ``"country"`` (then country picker next) or ``"all"``.
    """
    prefix = f"bulk{scope}_format"
    return session_format_kb(
        back_cb="deliver_menu",
        callback_prefix=prefix,
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
# Statistics / Suspicious Accounts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def statistics_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Pager for paginated statistics text."""
    buttons = _pager_rows(page, total_pages, "stat_page")
    buttons.append([_btn("\U0001f519  Back", "main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def suspicious_clear_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("\U0001f9f9  Clear All Flags", "sus_clear")],
            [_btn("\U0001f519  Back", "main_menu")],
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
