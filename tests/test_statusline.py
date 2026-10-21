import unittest
from cli_proxy_quota.statusline import format_snapshot


class StatuslineTest(unittest.TestCase):
    def test_actual_account_retry_and_no_guess(self):
        def account(index, alias, quota):
            return {"auth_index": index, "alias": alias, "provider": "codex", "plan_type": "PRO", "windows": [{"label": "5h", "remaining_percent": quota}, {"label": "7d", "remaining_percent": 40}]}
        snapshot = {"status": {"quota_updated_at": 1000}, "reports": [account("first", "우선 계정", 10), account("actual", "실제 계정", 70)], "routing": {"auth_index": "actual", "active": True}}
        result = format_snapshot(snapshot, 1000)
        self.assertIn("실제 계정", result)
        self.assertIn("응답 중", result)
        self.assertIn("30%", result)
        self.assertNotIn("우선 계정", result)
        snapshot["routing"] = {"auth_index": "first", "active": True}
        self.assertIn("우선 계정", format_snapshot(snapshot, 1000))
        snapshot["routing"] = None
        self.assertIn("연결 대기", format_snapshot(snapshot, 1000))

    def test_missing_values_stale_and_terminal_escape(self):
        snapshot = {"status": {"quota_updated_at": 1000}, "routing": {"auth_index": "a", "active": False}, "reports": [{"auth_index": "a", "alias": "safe\x1b\n", "provider": "codex", "windows": [{"label": "5h", "remaining_percent": 0}]}]}
        result = format_snapshot(snapshot, 1300)
        self.assertIn("캐시 5m", result)
        self.assertNotIn("최근 사용", result)
        self.assertNotIn("Last used", format_snapshot(snapshot, 1300, language="en"))
        self.assertIn("100%", result)
        self.assertIn("? (7d)", result)
        self.assertNotIn("\x1b", result)
        self.assertEqual(len(result.splitlines()), 2)
        snapshot["reports"][0]["windows"][0]["remaining_percent"] = float("nan")
        with self.assertRaises(ValueError): format_snapshot(snapshot, 1000)

    def test_usage_percent_and_relative_resets(self):
        snapshot = {"status": {"quota_updated_at": 0}, "routing": {"auth_index": "a", "active": True}, "reports": [{"auth_index": "a", "provider": "codex", "windows": [{"label": "5h", "remaining_percent": 15, "reset_at": "1970-01-01T04:55:00Z"}, {"label": "7d", "remaining_percent": 100, "reset_at": "1970-01-05T20:00:00Z"}]}]}
        self.assertEqual(format_snapshot(snapshot, 0).splitlines()[1], "Usage █████████░ 85% (4h 55m / 5h) | ░░░░░░░░░░ 0% (4d 20h / 7d)")
