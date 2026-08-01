"""Regression tests for status filtering and post-action state."""

from types import SimpleNamespace
import unittest

from bot.utils.status_workflow import (
    count_account_statuses,
    filter_accounts_by_status,
    normalize_spam_status,
    without_account_ids,
)


def account(account_id: int, status: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=account_id, spam_status=status)


class StatusWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.accounts = [
            account(1, "green"),
            account(2, "yellow"),
            account(3, "red"),
            account(4, "yellow"),
            account(5, None),
        ]

    def test_yellow_filter_returns_only_yellow_accounts(self) -> None:
        filtered = filter_accounts_by_status(self.accounts, "yellow")

        self.assertEqual([item.id for item in filtered], [2, 4])

    def test_filtering_does_not_mutate_or_remove_red_accounts(self) -> None:
        original_ids = [item.id for item in self.accounts]

        filtered = filter_accounts_by_status(self.accounts, "red")

        self.assertEqual([item.id for item in filtered], [3])
        self.assertEqual([item.id for item in self.accounts], original_ids)

    def test_counts_include_all_status_buttons(self) -> None:
        self.assertEqual(
            count_account_statuses(self.accounts),
            {"green": 1, "yellow": 2, "red": 1, "unknown": 1},
        )

    def test_unrecognized_status_is_unknown(self) -> None:
        self.assertEqual(normalize_spam_status("unexpected"), "unknown")
        self.assertEqual(normalize_spam_status(None), "unknown")

    def test_remove_after_send_drops_only_successful_ids_from_state(self) -> None:
        remaining = without_account_ids([1, 2, 3, 4], [2, 4])

        self.assertEqual(remaining, [1, 3])


if __name__ == "__main__":
    unittest.main()
