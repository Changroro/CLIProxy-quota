import importlib.util
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import call, patch


def load_module():
    from cli_proxy_quota.i18n import set_language
    set_language("ko")
    from cli_proxy_quota import client
    return client


class OpenRouterUsageTest(unittest.TestCase):
    def test_null_prefix_is_valid(self):
        module = load_module()

        report = module.normalize_openrouter_usage(
            {"auth_index": "account-1", "name": "openrouter", "prefix": None},
            {"is_free_tier": True},
            0,
            True,
            datetime(2026, 8, 31, tzinfo=timezone.utc),
        )

        self.assertEqual(report["email"], "openrouter · account-1")


class ClaudePlanTest(unittest.TestCase):
    def test_profile_plan_is_fetched_and_preserved_for_rate_limit_cache(self):
        module = load_module()
        auth = {"provider": "claude", "auth_index": "a", "email": "test@example.test", "account_type": "oauth"}
        usage = {key: {"utilization": 20, "resets_at": "2026-10-01T00:00:00Z"} for key in ("five_hour", "seven_day")}
        profile = {"organization": {"organization_type": "claude_max", "rate_limit_tier": "default_claude_max_20x"}}
        self.assertEqual(module.claude_plan_type({"organization": {"organization_type": "claude_pro"}}), "pro")
        self.assertEqual(module.claude_plan_type({"organization": {"organization_type": "claude_max", "rate_limit_tier": "default_claude_max_5x"}}), "max_5x")
        with self.assertRaises(RuntimeError):
            module.claude_plan_type({})
        state = {}
        now = datetime(2026, 9, 30, tzinfo=timezone.utc)
        with patch.object(module, "api_call", side_effect=[usage, profile]) as request:
            reports, errors = module.claude_reports("key", [auth], state, now)
        self.assertFalse(errors)
        self.assertEqual(reports[0]["plan_type"], "max_20x")
        self.assertTrue(request.call_args_list[-1].args[2].endswith("/oauth/profile"))
        module.apply_reset_history(reports, state, now)
        cached = module.cached_claude_report(auth, state, now)
        self.assertEqual(cached["plan_type"], "max_20x")
        with patch.object(module, "api_call", side_effect=[usage, RuntimeError("프로필 조회 실패")]):
            reports, errors = module.claude_reports("key", [auth], state, now)
        self.assertEqual(reports[0]["plan_type"], "unknown")
        self.assertTrue(errors[0]["plan_lookup_failed"])

    def test_null_window_is_skipped_and_not_restored_from_cache(self):
        module = load_module()
        auth = {"provider": "claude", "auth_index": "a", "email": "test@example.test"}
        both = {key: {"utilization": 20, "resets_at": "2026-10-01T00:00:00Z"} for key in ("five_hour", "seven_day")}
        state = {}
        before = datetime(2026, 9, 30, tzinfo=timezone.utc)
        reports = [module.normalize_claude_usage(auth, both)]
        module.apply_reset_history(reports, state, before)

        reports = [module.normalize_claude_usage(auth, {**both, "five_hour": None})]
        self.assertEqual([window["label"] for window in reports[0]["windows"]], ["7d"])
        module.apply_reset_history(reports, state, datetime(2026, 10, 1, tzinfo=timezone.utc))
        cached = module.cached_claude_report(auth, state, datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertEqual([window["label"] for window in cached["windows"]], ["7d"])

        with self.assertRaises(RuntimeError):
            module.normalize_claude_usage(auth, {"five_hour": None, "seven_day": None})



class ResetHistoryTest(unittest.TestCase):
    def test_first_observation_describes_missing_reset_event(self):
        module = load_module()
        reports = [
            {
                "provider": "claude",
                "account_id": "account-1",
                "windows": [
                    {
                        "id": "seven_day",
                        "used_value": 73.0,
                        "reset_at": "2026-09-04T00:19:00Z",
                    }
                ],
            }
        ]

        module.apply_reset_history(reports, {}, datetime(2026, 8, 31, tzinfo=timezone.utc))

        self.assertEqual(reports[0]["windows"][0]["last_reset_label"], "초기화 관측 없음")


class CodexControlsTest(unittest.TestCase):
    def test_persisted_plan_is_used_when_usage_omits_plan(self):
        module = load_module()
        report = module.normalize_codex_usage(
            {"auth_index": "a", "name": "a", "email": "account@example.test",
             "account_type": "oauth", "id_token": {"plan_type": "team"}},
            {"rate_limit": {"primary_window": {"used_percent": 20,
             "limit_window_seconds": 18000, "reset_at": 1790740800}}},
        )
        self.assertEqual(report["plan_type"], "team")

    @staticmethod
    def image_signals(used, reset_at, limit="imagegen_premium"):
        return {"X-Codex-Active-Limit": limit, "X-Codex-Primary-Used-Percent": str(used),
                "X-Codex-Primary-Reset-At": str(reset_at), "X-Codex-Primary-Window-Minutes": "1440"}

    def test_image_window_uses_latest_image_model_only(self):
        module = load_module()
        now = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
        reset_at = int(now.timestamp()) + 3600
        window = module.image_limit_window({"model_quotas": {
            "gpt-image-2": {"observed_at": "2026-11-04T16:14:09.123456789+08:00", "signals": self.image_signals(31, reset_at)},
            "gpt-image-2.5": {"observed_at": "2026-11-04T23:36:17.973383871+08:00", "signals": self.image_signals(100, reset_at)},
            "gpt-6-luna": {"observed_at": "2026-11-05T07:00:00+08:00", "signals": self.image_signals(4, reset_at, "premium")},
        }}, now)
        self.assertEqual(window["remaining_percent"], 0)
        self.assertEqual(window["used_value"], 100)
        self.assertEqual(window["reset_at"], "2026-11-05T01:00:00Z")
        self.assertIn("observed_label", window)

    def test_image_window_shows_reset_after_reset_time_passes(self):
        module = load_module()
        now = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
        window = module.image_limit_window({"model_quotas": {"gpt-image-2.5": {
            "observed_at": "2026-11-04T07:00:00+08:00", "signals": self.image_signals(100, int(now.timestamp()) - 1),
        }}}, now)
        self.assertEqual(window["remaining_percent"], 100)
        self.assertEqual(window["reset_label"], "초기화됨")
        self.assertIsNone(window["reset_at"])

    def test_image_window_is_unknown_without_valid_signal(self):
        module = load_module()
        now = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
        broken = {"observed_at": "2026-11-04T07:00:00+08:00", "signals": {"X-Codex-Active-Limit": "image_gen"}}
        for auth in ({}, {"model_quotas": {"gpt-image-2": broken}}):
            window = module.image_limit_window(auth, now)
            self.assertTrue(window["unknown"])
            self.assertIsNone(window["remaining_percent"])

    def test_exhausted_image_limit_does_not_change_account_status(self):
        module = load_module()
        report = module.normalize_codex_usage(
            {"auth_index": "a", "name": "a", "email": "account@example.test", "model_quotas": {"gpt-image-2": {
                "observed_at": "2099-01-01T00:00:00+00:00", "signals": self.image_signals(100, 4070908800)}}},
            {"rate_limit": {"primary_window": {"used_percent": 0, "limit_window_seconds": 18000, "reset_at": 1790740800}}},
        )
        self.assertEqual(report["status"], "high")
        self.assertEqual([window["id"] for window in report["windows"]], ["18000", "image"])
        self.assertEqual(report["windows"][1]["remaining_percent"], 0)

    def test_reset_history_records_image_reset_once_reset_time_passes(self):
        module = load_module()
        state = {}
        first = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
        second = datetime(2026, 11, 5, 2, 0, tzinfo=timezone.utc)
        auth = {"model_quotas": {"gpt-image-2": {"observed_at": "2026-11-05T07:00:00+08:00",
                "signals": self.image_signals(100, int(first.timestamp()) + 3600)}}}
        for moment in (first, second):
            report = {"provider": "codex", "account_id": "a", "windows": [module.image_limit_window(auth, moment)]}
            module.apply_reset_history([report], state, moment)
        self.assertEqual(state["windows"]["codex:a:image"]["last_reset"]["exact_at"], "2026-11-05T01:00:00Z")

    def test_free_codex_account_is_not_collected(self):
        module = load_module()
        paid = {"provider": "codex", "auth_index": "paid", "account": "acct", "name": "paid", "email": "paid@example.test",
                "id_token": {"plan_type": "team"}}
        free = {"provider": "codex", "auth_index": "free", "account": "acct", "name": "free", "email": "free@example.test",
                "id_token": {"plan_type": "free"}}
        usage = {"rate_limit": {"primary_window": {"used_percent": 0, "limit_window_seconds": 18000, "reset_at": 1790740800}}}
        with patch.object(module, "api_call", side_effect=[usage, {}]) as api_call:
            reports = module.codex_reports("key", [paid, free])
        self.assertEqual([report["auth_index"] for report in reports], ["paid"])
        self.assertEqual({row.args[1] for row in api_call.call_args_list}, {"paid"})

    def test_order_save_keeps_hidden_free_account_last(self):
        module = load_module()
        rows = [
            {"provider": "codex", "auth_index": "a", "id": "a.json", "priority": 1, "id_token": {"plan_type": "team"}},
            {"provider": "codex", "auth_index": "f", "id": "f.json", "priority": 3, "id_token": {"plan_type": "free"}},
            {"provider": "codex", "auth_index": "b", "id": "b.json", "priority": 2, "id_token": {"plan_type": "team"}},
        ]
        def request(_key, path, payload=None, method=None):
            return "fill-first" if path.endswith("strategy") else {"status": "ok"}
        with patch.object(module, "management_key", return_value="key"), patch.object(module, "active_auths", return_value=rows), \
                patch.object(module, "management_request", side_effect=request) as management_request:
            module.set_codex_order(["b", "a"])
        saved = [row.args[2] for row in management_request.call_args_list if row.args[1].endswith("fields")]
        self.assertEqual(saved, [{"name": "b.json", "priority": 3}, {"name": "a.json", "priority": 2}, {"name": "f.json", "priority": 1}])

    def test_reset_credits_keep_only_available_expiry_dates(self):
        module = load_module()
        credits = module.normalize_reset_credits({
            "available_count": 2,
            "credits": [
                {"status": "available", "expires_at": "2026-11-01T00:00:00Z"},
                {"status": "redeemed", "expires_at": "2026-10-01T00:00:00Z"},
                {"status": "available", "expires_at": "2026-10-15T00:00:00Z"},
            ],
        })
        self.assertEqual(credits, ["2026-10-15T00:00:00Z", "2026-11-01T00:00:00Z"])

    def test_order_updates_each_codex_priority(self):
        module = load_module()
        auths = [
            {"provider": "codex", "auth_index": "a", "id": "file-a"},
            {"provider": "codex", "auth_index": "b", "id": "file-b"},
        ]
        with patch.object(module, "management_key", return_value="key"), patch.object(
            module, "active_auths", return_value=auths
        ), patch.object(module, "management_request", side_effect=[
            "fill-first", {"status": "ok"}, {"status": "ok"}
        ]) as request:
            module.set_codex_order(["b", "a"])
        self.assertEqual(request.call_args_list, [
            call("key", "/v8/management/config/routing/strategy"),
            call("key", "/v8/management/credentials/fields", {"name": "file-b", "priority": 2}, method="PATCH"),
            call("key", "/v8/management/credentials/fields", {"name": "file-a", "priority": 1}, method="PATCH"),
        ])

    def test_partial_save_restores_previous_priorities(self):
        module = load_module()
        auths = [
            {"provider": "codex", "auth_index": "a", "id": "file-a", "priority": 20},
            {"provider": "codex", "auth_index": "b", "id": "file-b", "priority": 10},
        ]
        with patch.object(module, "management_key", return_value="key"), patch.object(
            module, "active_auths", return_value=auths
        ), patch.object(module, "management_request", side_effect=[
            "fill-first", {"status": "ok"}, RuntimeError("저장 실패"),
            {"status": "ok"}, {"status": "ok"},
        ]) as request:
            with self.assertRaises(RuntimeError):
                module.set_codex_order(["b", "a"])
        self.assertEqual([entry.args[2] for entry in request.call_args_list[-2:]], [
            {"name": "file-a", "priority": 20},
            {"name": "file-b", "priority": 10},
        ])

    def test_duplicate_accounts_are_rejected_before_writing(self):
        module = load_module()
        with patch.object(module, "management_key", return_value="key"), patch.object(
            module, "active_auths", return_value=[
                {"provider": "codex", "auth_index": "a", "id": "file-a"},
                {"provider": "codex", "auth_index": "b", "id": "file-b"},
            ]
        ), patch.object(module, "management_request") as request:
            with self.assertRaises(RuntimeError):
                module.set_codex_order(["a", "a"])
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
