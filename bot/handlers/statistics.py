"""
Statistics display — breakdown by country and date.
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot import database as db
from bot.utils.country_detector import get_flag
from bot.utils.decorators import authorized
from bot.utils.keyboards import main_menu_kb

router = Router(name="statistics")


@router.callback_query(F.data == "statistics")
@authorized
async def cb_statistics(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    stats = await db.get_statistics(user_id)

    if stats["total"] == 0:
        is_admin = await db.is_user_admin(user_id)
        await callback.message.edit_text(
            "\U0001f4ca <b>Statistics</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\U0001f4ed You don't have any accounts yet.\n"
            "Use <b>Grant Account Access</b> to add your first account!",
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin),
        )
        await callback.answer()
        return

    # Build statistics text
    lines = [
        "\U0001f4ca <b>Account Statistics</b>",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n",
        f"\U0001f4e6  <b>Total Accounts:</b>  {stats['total']}\n",
    ]

    for country, cdata in sorted(stats["countries"].items()):
        flag = get_flag(country)
        lines.append(f"\n{flag}  <b>{country}</b>  \u2014  {cdata['total']} account(s)")
        for date_str, count in sorted(cdata["dates"].items()):
            lines.append(f"    \U0001f4c5  {date_str}:  <b>{count}</b>")

    text = "\n".join(lines)

    is_admin = await db.is_user_admin(user_id)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await callback.answer()
