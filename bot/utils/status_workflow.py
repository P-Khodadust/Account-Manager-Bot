"""Pure helpers for spam-status classification workflows."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, TypeVar

SPAM_STATUS_ORDER = ("green", "yellow", "red", "unknown")
SPAM_STATUSES = frozenset(SPAM_STATUS_ORDER)

_AccountT = TypeVar("_AccountT")


def normalize_spam_status(status: str | None) -> str:
    """Return a supported status, falling back to ``unknown``."""
    if status is not None and status in SPAM_STATUSES:
        return status
    return "unknown"


def filter_accounts_by_status(
    accounts: Iterable[_AccountT],
    status: str,
) -> list[_AccountT]:
    """Return accounts whose stored classification exactly matches status."""
    if status not in SPAM_STATUSES:
        return []
    return [
        account
        for account in accounts
        if normalize_spam_status(
            getattr(account, "spam_status", None)
        )
        == status
    ]


def count_account_statuses(accounts: Iterable[Any]) -> dict[str, int]:
    """Count every supported status, including zero-count groups."""
    counts = {status: 0 for status in SPAM_STATUS_ORDER}
    for account in accounts:
        status = normalize_spam_status(
            getattr(account, "spam_status", None)
        )
        counts[status] += 1
    return counts


def without_account_ids(
    account_ids: Sequence[int],
    removed_ids: Iterable[int],
) -> list[int]:
    """Preserve scan order while removing successfully handled IDs."""
    removed = set(removed_ids)
    return [
        account_id
        for account_id in account_ids
        if account_id not in removed
    ]
