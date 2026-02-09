"""
Statistics display — breakdown by country and date.
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot import database as db
from bot.utils.decorators import authorized
from bot.utils.keyboards import main_menu_kb

router = Router(name="statistics")

_FLAG_MAP = {
    "USA": "🇺🇸", "Canada": "🇨🇦", "Iran": "🇮🇷",
    "United Kingdom": "🇬🇧", "Germany": "🇩🇪", "France": "🇫🇷",
    "Turkey": "🇹🇷", "Russia": "🇷🇺", "India": "🇮🇳",
    "China": "🇨🇳", "Japan": "🇯🇵", "Brazil": "🇧🇷",
    "Australia": "🇦🇺", "Italy": "🇮🇹", "Spain": "🇪🇸",
    "Netherlands": "🇳🇱", "UAE": "🇦🇪", "Ukraine": "🇺🇦",
}


def _flag(country: str) -> str:
    return _FLAG_MAP.get(country, "🌍")


@router.callback_query(F.data == "statistics")
@authorized
async def cb_statistics(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    stats = await db.get_statistics(user_id)

    if stats["total"] == 0:
        is_admin = await db.is_user_admin(user_id)
        await callback.message.edit_text(
            "📊 <b>Statistics</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 You don't have any accounts yet.\n"
            "Use <b>Grant Account Access</b> to add your first account!",
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin),
        )
        await callback.answer()
        return

    # Build statistics text
    lines = [
        "📊 <b>Account Statistics</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━\n",
        f"📦  <b>Total Accounts:</b>  {stats['total']}\n",
    ]

    for country, cdata in sorted(stats["countries"].items()):
        flag = _flag(country)
        lines.append(f"\n{flag}  <b>{country}</b>  —  {cdata['total']} account(s)")
        for date_str, count in sorted(cdata["dates"].items()):
            lines.append(f"    📅  {date_str}:  <b>{count}</b>")

    text = "\n".join(lines)

    is_admin = await db.is_user_admin(user_id)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await callback.answer()
