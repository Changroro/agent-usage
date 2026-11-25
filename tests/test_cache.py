import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_usage import cache


class CacheTest(unittest.TestCase):
    def test_round_trip_keeps_dates_keys_and_backoff(self):
        reset = datetime(2026, 11, 30, 20, 48, tzinfo=timezone.utc)
        reports = {("codex", "abc|x"): {"status": "ok", "fetched_at": 100.0, "windows": [{"label": "5h", "used": 64.0, "reset_at": reset}],
                                            "reset_credits": {"count": 1, "expires": [reset]}}}
        backoff = {("claude", "system"): (400.0, 300), ("codex", "abc|x"): None}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "reports.json"
            cache.save(reports, backoff, path)
            loaded_reports, loaded_backoff = cache.load(path)
        self.assertEqual(loaded_reports, reports)
        self.assertEqual(loaded_backoff, {("claude", "system"): (400.0, 300)})

    def test_missing_file_is_empty(self):
        self.assertEqual(cache.load(Path("/nonexistent/agent-usage.json")), ({}, {}))


if __name__ == "__main__":
    unittest.main()
