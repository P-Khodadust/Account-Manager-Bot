"""
Statistics display, paginated to respect Telegram's 4096-char limit.
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot import database as db
from bot.utils.country_detector import get_flag
from bot.utils.decorators import authorized
from bot.utils.keyboards import main_menu_kb, statistics_kb

router = Router(name="statistics")

# Keep each page comfortably below Telegram's 4096-char message cap.
_PAGE_CHAR_LIMIT = 3500


def _build_lines(stats: dict) -> list[str]:
    lines = [
        "\U0001f4ca <b>Account Statistics</b>",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n",
        f"\U0001f4e6  <b>Total Accounts:</b>  {stats['total']}\n",
    ]

    for country, cdata in sorted(stats["countries"].items()):
        flag = get_flag(country)
        lines.append(
            f"\n{flag}  <b>{country}</b>  \u2014  "
            f"{cdata['total']} account(s)"
        )
        for date_str, count in sorted(cdata["dates"].items()):
            lines.append(f"    \U0001f4c5  {date_str}:  <b>{count}</b>")
    return lines


def _paginate(lines: list[str]) -> list[str]:
    """Split rendered lines into pages under the character limit."""
    pages: list[str] = []
    current: list[str] = []
    size = 0

    for line in lines:
        line_len = len(line) + 1
        if current and size + line_len > _PAGE_CHAR_LIMIT:
            pages.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += line_len

    if current:
        pages.append("\n".join(current))
    return pages or ["\U0001f4ca No data."]


async def _render_statistics_page(
    callback: CallbackQuery, page: int
) -> None:
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
        return

    lines = _build_lines(stats)
    pages = _paginate(lines)
    page = max(0, min(page, len(pages) - 1))

    header = (
        "" if len(pages) == 1 else f"<i>(page {page + 1}/{len(pages)})</i>\n"
    )
    text = f"{header}{pages[page]}" if header else pages[page]

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=statistics_kb(page, len(pages)),
    )


@router.callback_query(F.data == "statistics")
@authorized
async def cb_statistics(callback: CallbackQuery) -> None:
    await _render_statistics_page(callback, 0)
    await callback.answer()


@router.callback_query(F.data.startswith("stat_page:"))
@authorized
async def cb_statistics_page(callback: CallbackQuery) -> None:
    try:
        page = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        page = 0
    await _render_statistics_page(callback, page)
    await callback.answer()
