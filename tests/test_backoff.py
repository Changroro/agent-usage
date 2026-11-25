import unittest

import gi

gi.require_version("Gtk", "3.0")
from agent_usage.widget import BACKOFF_MAX, BACKOFF_START, with_backoff

OK = {"status": "ok", "windows": [{"label": "5h", "used": 10.0, "reset_at": None}]}
LIMITED = {"status": "limited", "error": "대기", "windows": []}


class BackoffTest(unittest.TestCase):
    def test_rate_limit_keeps_last_good_report_and_doubles_wait(self):
        shown, backoff = with_backoff(OK, LIMITED, None, 1000)
        self.assertIs(shown, OK)
        self.assertEqual(backoff, (1000 + BACKOFF_START, BACKOFF_START))
        _, backoff = with_backoff(OK, LIMITED, backoff, 2000)
        self.assertEqual(backoff[1], BACKOFF_START * 2)
        for _ in range(10):
            _, backoff = with_backoff(OK, LIMITED, backoff, 3000)
        self.assertEqual(backoff[1], BACKOFF_MAX)

    def test_rate_limit_without_good_report_shows_waiting(self):
        shown, _ = with_backoff(None, LIMITED, None, 0)
        self.assertEqual(shown["status"], "limited")

    def test_success_clears_backoff(self):
        self.assertEqual(with_backoff(OK, OK, (99, 600), 0), (OK, None))


if __name__ == "__main__":
    unittest.main()
