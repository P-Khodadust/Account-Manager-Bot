"""
Access control decorators for bot handlers.
"""

from __future__ import annotations

import functools
import logging
from typing import Callable, Any

from aiogram.types import CallbackQuery, Message

from bot import database as db

logger = logging.getLogger(__name__)


def authorized(func: Callable) -> Callable:
    """
    Decorator: only allow authorized users.
    Works with both Message and CallbackQuery handlers.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Find the update object (Message or CallbackQuery)
        event = args[0] if args else None
        if event is None:
            return

        if isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            if not await db.is_user_authorized(user_id):
                await event.answer("🚫 Access denied. You are not authorized.", show_alert=True)
                return
        elif isinstance(event, Message):
            user_id = event.from_user.id
            if not await db.is_user_authorized(user_id):
                await event.answer(
                    "🚫 <b>Access Denied</b>\n\n"
                    "You are not authorized to use this bot.\n"
                    "Contact the administrator for access.",
                    parse_mode="HTML",
                )
                return
        else:
            return

        return await func(*args, **kwargs)

    return wrapper


def admin_only(func: Callable) -> Callable:
    """
    Decorator: only allow admin users.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        event = args[0] if args else None
        if event is None:
            return

        if isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            if not await db.is_user_admin(user_id):
                await event.answer("🚫 Admin access required.", show_alert=True)
                return
        elif isinstance(event, Message):
            user_id = event.from_user.id
            if not await db.is_user_admin(user_id):
                await event.answer(
                    "🚫 <b>Admin Only</b>\n\nThis action requires admin privileges.",
                    parse_mode="HTML",
                )
                return

        return await func(*args, **kwargs)

    return wrapper
