"""
Global aiogram middlewares.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import TelegramObject


class SuppressNotModifiedMiddleware(BaseMiddleware):
    """Swallow harmless ``message is not modified`` BadRequest errors.

    Happens when a user double-clicks an inline button and the handler
    edits the message with identical content. Everything else re-raises.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return None
            raise
