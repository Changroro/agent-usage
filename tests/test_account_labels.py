import unittest
from unittest import mock

from agent_usage import accounts


class AccountLabelTest(unittest.TestCase):
    def test_system_accounts_show_email_and_fall_back_without_one(self):
        system = [{"provider": "claude", "id": "system", "label": None, "home": None, "source": "system"},
                  {"provider": "antigravity", "id": "system", "label": None, "home": None, "source": "system"}]
        own = {"provider": "claude", "id": "x", "label": "work", "home": "/tmp/x"}
        emails = {("claude", "system"): "me@example.com", ("claude", "x"): "work@example.com"}
        with mock.patch.object(accounts, "system_accounts", return_value=system), \
             mock.patch.object(accounts, "account_email", side_effect=lambda account: emails.get((account["provider"], account["id"]))):
            labels = [account["label"] for account in accounts.list_accounts({"accounts": [own], "selected": {}})]
        self.assertEqual(labels, ["me@example.com", accounts.t("시스템 기본값"), "work"])


if __name__ == "__main__":
    unittest.main()
