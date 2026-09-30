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
