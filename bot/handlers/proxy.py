"""
SOCKS5 proxy management per user:
  - Add proxy (IP, Port, Username, Password)
  - View / set default / delete proxies
  - Issue #2: Proxy rotation toggle (every 3 accounts)
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import database as db
from bot.utils.decorators import authorized
from bot.utils.keyboards import (
    cancel_kb,
    main_menu_kb,
    proxy_detail_kb,
    proxy_menu_kb,
)

router = Router(name="proxy")


class ProxyStates(StatesGroup):
    waiting_details = State()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Proxy menu
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "proxy_menu")
@authorized
async def cb_proxy_menu(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.clear()
    user_id = callback.from_user.id
    proxies = await db.get_proxies(user_id)
    settings = await db.get_user_settings(user_id)
    count = len(proxies)

    await callback.message.edit_text(
        "\U0001f310 <b>Proxy Settings</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"You have <b>{count}</b> proxy configuration(s).\n\n"
        "Proxies are used when connecting to accounts\n"
        "to prevent bans and restrictions.\n\n"
        "\u2705 = currently active (default) proxy",
        parse_mode="HTML",
        reply_markup=proxy_menu_kb(
            proxies,
            rotation_enabled=settings.proxy_rotation_enabled,
            proxy_count=count,
        ),
    )
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Add proxy
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "proxy_add")
@authorized
async def cb_proxy_add(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.message.edit_text(
        "\u2795 <b>Add SOCKS5 Proxy</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Please send the proxy details in this format:\n\n"
        "<code>IP:Port:Username:Password</code>\n\n"
        "Or without authentication:\n"
        "<code>IP:Port</code>\n\n"
        "\U0001f4a1 <i>Example: 192.168.1.1:1080:user:pass</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb("proxy_menu"),
    )
    await state.set_state(ProxyStates.waiting_details)
    await callback.answer()


@router.message(ProxyStates.waiting_details)
@authorized
async def on_proxy_details(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    parts = text.split(":")

    if len(parts) < 2:
        await message.answer(
            "\u26a0\ufe0f Invalid format. Please use:\n"
            "<code>IP:Port</code> or "
            "<code>IP:Port:Username:Password</code>",
            parse_mode="HTML",
            reply_markup=cancel_kb("proxy_menu"),
        )
        return

    host = parts[0].strip()
    try:
        port = int(parts[1].strip())
    except ValueError:
        await message.answer(
            "\u26a0\ufe0f Port must be a number.",
            parse_mode="HTML",
            reply_markup=cancel_kb("proxy_menu"),
        )
        return

    username = parts[2].strip() if len(parts) > 2 else None
    password = parts[3].strip() if len(parts) > 3 else None

    proxy = await db.add_proxy(
        user_id=message.from_user.id,
        host=host,
        port=port,
        username=username,
        password=password,
        label=f"{host}:{port}",
    )

    # If it's the first proxy, set as default
    proxies = await db.get_proxies(message.from_user.id)
    if len(proxies) == 1:
        await db.set_default_proxy(proxy.id, message.from_user.id)

    is_admin = await db.is_user_admin(message.from_user.id)
    await message.answer(
        "\u2705 <b>Proxy Added!</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f539  Host: <b>{host}</b>\n"
        f"\U0001f539  Port: <b>{port}</b>\n"
        f"\U0001f539  Auth: <b>{'Yes' if username else 'No'}</b>\n\n"
        "The proxy will be used for all account operations.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )
    await state.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# View proxy detail
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data.startswith("proxy_view:"))
@authorized
async def cb_proxy_view(callback: CallbackQuery) -> None:
    proxy_id = int(callback.data.split(":")[1])
    proxy = await db.get_proxy_by_id(proxy_id)

    if not proxy or proxy.user_id != callback.from_user.id:
        await callback.answer(
            "\u26a0\ufe0f Proxy not found.", show_alert=True
        )
        return

    default_str = "  \u2705 Default" if proxy.is_default else ""

    await callback.message.edit_text(
        f"\U0001f310 <b>Proxy Details</b>{default_str}\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f539  Host: <code>{proxy.host}</code>\n"
        f"\U0001f539  Port: <code>{proxy.port}</code>\n"
        f"\U0001f539  Username: "
        f"<code>{proxy.username or '\u2014'}</code>\n"
        f"\U0001f539  Password: "
        f"<code>{'\u2022\u2022\u2022\u2022' if proxy.password else '\u2014'}</code>",
        parse_mode="HTML",
        reply_markup=proxy_detail_kb(proxy_id),
    )
    await callback.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Set default proxy
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data.startswith("proxy_default:"))
@authorized
async def cb_proxy_default(callback: CallbackQuery) -> None:
    proxy_id = int(callback.data.split(":")[1])
    await db.set_default_proxy(proxy_id, callback.from_user.id)
    await callback.answer(
        "\u2705 Set as default proxy!", show_alert=True
    )

    # Refresh proxy menu
    user_id = callback.from_user.id
    proxies = await db.get_proxies(user_id)
    settings = await db.get_user_settings(user_id)

    await callback.message.edit_text(
        "\U0001f310 <b>Proxy Settings</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"You have <b>{len(proxies)}</b> proxy configuration(s).\n\n"
        "\u2705 = currently active (default) proxy",
        parse_mode="HTML",
        reply_markup=proxy_menu_kb(
            proxies,
            rotation_enabled=settings.proxy_rotation_enabled,
            proxy_count=len(proxies),
        ),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Delete proxy
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data.startswith("proxy_delete:"))
@authorized
async def cb_proxy_delete(callback: CallbackQuery) -> None:
    proxy_id = int(callback.data.split(":")[1])
    await db.delete_proxy(proxy_id)
    await callback.answer("\U0001f5d1 Proxy deleted.", show_alert=True)

    # Refresh proxy menu
    user_id = callback.from_user.id
    proxies = await db.get_proxies(user_id)
    settings = await db.get_user_settings(user_id)

    # If rotation was enabled but now < 2 proxies, disable it
    if settings.proxy_rotation_enabled and len(proxies) < 2:
        await db.toggle_proxy_rotation(user_id)
        settings = await db.get_user_settings(user_id)

    await callback.message.edit_text(
        "\U0001f310 <b>Proxy Settings</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"You have <b>{len(proxies)}</b> proxy configuration(s).\n\n"
        "\u2705 = currently active (default) proxy",
        parse_mode="HTML",
        reply_markup=proxy_menu_kb(
            proxies,
            rotation_enabled=settings.proxy_rotation_enabled,
            proxy_count=len(proxies),
        ),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Issue #2 — Proxy Rotation Toggle
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(F.data == "proxy_rotation_toggle")
@authorized
async def cb_proxy_rotation_toggle(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    proxy_count = await db.get_proxy_count(user_id)

    if proxy_count < 2:
        await callback.answer(
            "\u274c You need at least 2 proxies to enable rotation.",
            show_alert=True,
        )
        return

    new_state = await db.toggle_proxy_rotation(user_id)
    status = "enabled \u2705" if new_state else "disabled"
    await callback.answer(
        f"\U0001f504 Proxy rotation {status}", show_alert=True
    )

    # Refresh proxy menu
    proxies = await db.get_proxies(user_id)
    settings = await db.get_user_settings(user_id)

    await callback.message.edit_text(
        "\U0001f310 <b>Proxy Settings</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"You have <b>{len(proxies)}</b> proxy configuration(s).\n\n"
        "Proxies are used when connecting to accounts\n"
        "to prevent bans and restrictions.\n\n"
        "\u2705 = currently active (default) proxy",
        parse_mode="HTML",
        reply_markup=proxy_menu_kb(
            proxies,
            rotation_enabled=settings.proxy_rotation_enabled,
            proxy_count=len(proxies),
        ),
    )


@router.callback_query(F.data == "proxy_rotation_disabled")
@authorized
async def cb_proxy_rotation_disabled(callback: CallbackQuery) -> None:
    await callback.answer(
        "\u274c You need at least 2 proxies to enable rotation.\n"
        "Add more proxies first.",
        show_alert=True,
    )
