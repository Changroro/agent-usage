import json
import re
import unittest
from pathlib import Path

from agent_usage import accounts, providers


class ParsingTest(unittest.TestCase):
    def test_codex_usage_windows_and_reset_count(self):
        report = providers.parse_codex_usage({
            "plan_type": "team",
            "rate_limit": {"primary_window": {"used_percent": 100, "limit_window_seconds": 18000, "reset_at": 1795582292},
                           "secondary_window": {"used_percent": 68, "limit_window_seconds": 604800, "reset_at": 1796002165}},
            "additional_rate_limits": None, "rate_limit_reset_credits": {"available_count": 1}})
        self.assertEqual([(w["label"], w["used"]) for w in report["windows"]], [("5h", 100.0), (providers.t("주간"), 68.0)])
        self.assertEqual(report["reset_count"], 1)

    def test_reset_credits_rejects_count_mismatch(self):
        with self.assertRaises(RuntimeError):
            providers.parse_reset_credits({"available_count": 2, "credits": [{"id": "a", "status": "available", "expires_at": "2026-12-02T16:52:33Z"}]})

    def test_reset_credits_keep_ids_soonest_first(self):
        parsed = providers.parse_reset_credits({"available_count": 3, "credits": [
            {"id": "late", "status": "available", "expires_at": "2026-12-02T16:52:33Z"}, {"id": "used", "status": "used", "expires_at": None},
            {"id": "never", "status": "available", "expires_at": None},
            {"id": "soon", "status": "available", "expires_at": "2026-11-30T20:48:02Z"}]})
        self.assertEqual(parsed["count"], 3)
        self.assertEqual([credit["id"] for credit in parsed["credits"]], ["soon", "late", "never"])
        self.assertEqual(parsed["credits"][0]["expires"].day, 30)

    def test_image_headers(self):
        window = providers.parse_image_headers({"x-codex-active-limit": "imagegen_premium", "x-codex-primary-window-minutes": "1440",
                                                "x-codex-primary-used-percent": "46", "x-codex-primary-reset-at": "1795659160"})
        self.assertEqual(window["used"], 46.0)
        with self.assertRaises(RuntimeError):
            providers.parse_image_headers({"x-codex-active-limit": "premium"})

    def test_claude_usage_skips_null_windows_and_adds_scoped(self):
        windows = providers.parse_claude_usage({"five_hour": None, "seven_day": {"utilization": 78.0, "resets_at": "2026-11-29T00:59:59+00:00"},
                                                "limits": [{"kind": "weekly_all", "percent": 78}, {"kind": "weekly_scoped", "percent": 3, "resets_at": "2026-11-29T00:59:59+00:00",
                                                           "scope": {"model": {"display_name": "Fable"}}}]})
        self.assertEqual([w["used"] for w in windows], [78.0, 3.0])

    def test_antigravity_output_and_signed_out(self):
        line = json.dumps({"status": "SUCCESS", "command": {"data": {"groups": [{"name": "Gemini Models", "buckets": [
            {"window": "5h", "remaining_fraction": 0.25, "reset_time": "2026-11-25T06:47:53Z"},
            {"window": "weekly", "remaining_fraction": 1, "reset_time": "2026-12-02T01:47:53Z", "disabled": True}]}]}}})
        windows = providers.parse_antigravity("noise\n" + line)
        self.assertEqual([(w["label"], w["used"]) for w in windows], [("Gemini · 5h", 75.0)])
        with self.assertRaises(providers.LoginExpired):
            providers.parse_antigravity("Authentication required. Please visit the URL to log in:")

    def test_login_url_from_osc8_hyperlink(self):
        line = "\x1b]8;;https://claude.ai/oauth/x?a=1\x1b\\https://claude.ai/oauth/x?a=1\x1b]8;;\x1b\\\n"
        self.assertEqual(accounts.URL.search(line).group(0), "https://claude.ai/oauth/x?a=1")
        self.assertEqual(accounts.ANSI.sub("", line).strip(), "https://claude.ai/oauth/x?a=1")

    def test_every_message_is_translated(self):
        english = json.loads(Path(providers.__file__).with_name("translations.json").read_text())
        source = "".join(path.read_text() for path in Path(providers.__file__).parent.glob("*.py"))
        self.assertEqual(set(re.findall(r'\bt\("([^"]+)"', source)), set(english))


if __name__ == "__main__":
    unittest.main()
