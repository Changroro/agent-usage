import unittest

from agent_usage.providers import FIVE_HOURS, WEEK
from agent_usage.widget import headline


def w(label, used, seconds):
    return {"label": label, "used": used, "reset_at": None, "seconds": seconds}


def shown(*windows):
    return headline({"windows": list(windows)})["label"]


class HeadlineTest(unittest.TestCase):
    def test_short_limit_comes_first_even_when_weekly_is_higher(self):
        self.assertEqual(shown(w("week", 80, WEEK), w("5h", 20, FIVE_HOURS)), "5h")

    def test_exhausted_short_limit_moves_to_weekly(self):
        self.assertEqual(shown(w("5h", 100, FIVE_HOURS), w("week", 60, WEEK)), "week")

    def test_exhausted_weekly_wins_over_open_short_limit(self):
        self.assertEqual(shown(w("5h", 40, FIVE_HOURS), w("week", 100, WEEK)), "week")
        self.assertEqual(shown(w("5h", 100, FIVE_HOURS), w("week", 100, WEEK)), "week")

    def test_same_length_model_limits_use_the_most_used(self):
        self.assertEqual(shown(w("gemini 5h", 99, FIVE_HOURS), w("gpt 5h", 0, FIVE_HOURS), w("gemini week", 25, WEEK)), "gemini 5h")

    def test_only_weekly_and_no_windows(self):
        self.assertEqual(shown(w("week", 83, WEEK)), "week")
        self.assertIsNone(headline({"windows": []}))


if __name__ == "__main__":
    unittest.main()
