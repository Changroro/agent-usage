import unittest
from datetime import datetime, timedelta, timezone

from agent_usage import alerts

RESET = datetime(2026, 11, 30, 12, tzinfo=timezone.utc)
KEY = ("codex", "system")


def report(used, reset_at=RESET, status="ok"):
    return {KEY: {"status": status, "windows": [{"label": "5h", "used": used, "reset_at": reset_at}]}}


def kinds(events):
    return [kind for kind, _key, _window in events]


class AlertTest(unittest.TestCase):
    def test_each_alert_fires_once_per_cycle(self):
        sent = {}
        self.assertEqual(kinds(alerts.check(report(50), sent, 90)), [])
        self.assertEqual(kinds(alerts.check(report(91), sent, 90)), ["threshold"])
        self.assertEqual(kinds(alerts.check(report(95), sent, 90)), [])
        self.assertEqual(kinds(alerts.check(report(100), sent, 90)), ["full"])
        self.assertEqual(kinds(alerts.check(report(100), sent, 90)), [])
        self.assertEqual(kinds(alerts.check(report(3, RESET + timedelta(hours=5)), sent, 90)), ["reset"])
        self.assertEqual(sent, {})

    def test_jumping_straight_to_full_sends_only_full(self):
        sent = {}
        self.assertEqual(kinds(alerts.check(report(100), sent, 90)), ["full"])
        self.assertEqual(kinds(alerts.check(report(100), sent, 90)), [])

    def test_reset_time_jitter_is_not_a_reset(self):
        sent = {}
        alerts.check(report(92), sent, 90)
        self.assertEqual(kinds(alerts.check(report(93, RESET + timedelta(seconds=20)), sent, 90)), [])

    def test_without_reset_time_a_drop_below_threshold_is_a_reset(self):
        sent = {}
        alerts.check(report(92, None), sent, 90)
        self.assertEqual(kinds(alerts.check(report(10, None), sent, 90)), ["reset"])

    def test_untouched_window_and_failed_report_send_nothing(self):
        sent = {}
        self.assertEqual(alerts.check(report(99, status="error"), sent, 90), [])
        self.assertEqual(kinds(alerts.check(report(40), sent, 90)), [])
        self.assertEqual(sent, {})


if __name__ == "__main__":
    unittest.main()
