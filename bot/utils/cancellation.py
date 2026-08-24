"""
Cooperative cancellation for long-running handler loops.

Handlers that iterate over many accounts (bulk exports, 2FA sweeps,
session termination, chat cleanup) check ``is_cancelled`` between
iterations so a user can stop the operation early.
"""

from __future__ import annotations

import logging

from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)

_cancel_requested: set[int] = set()


def request_cancel(user_id: int) -> None:
    """Flag the given user's running operation for cancellation."""
    _cancel_requested.add(user_id)


def is_cancelled(user_id: int) -> bool:
    """Return True once, then auto-clear (one cancel per operation)."""
    if user_id in _cancel_requested:
        _cancel_requested.discard(user_id)
        return True
    return False


def begin_operation(user_id: int) -> None:
    """Clear any stale flag before starting a new operation."""
    _cancel_requested.discard(user_id)


async def handle_cancel_callback(
    callback: CallbackQuery, done_text: str
) -> None:
    """Register the user's cancel request and answer the button."""
    request_cancel(callback.from_user.id)
    await callback.answer(done_text, show_alert=True)
