import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def load_module():
    from cli_proxy_quota.i18n import set_language
    set_language("ko")
    from cli_proxy_quota import widget
    return widget


class StatusStylesTest(unittest.TestCase):
    def test_dark_theme_preserves_status_colors_and_changes_surface(self):
        module = load_module()
        css = module.theme_css("dark").decode()
        self.assertIn("background: #1c1c1e", css)
        self.assertIn("color: #eeeef0", css)
        self.assertNotIn("#ffffff", css)
        self.assertEqual(module.BAR_COLORS["success"], (34 / 255, 197 / 255, 94 / 255))
        with self.assertRaises(ValueError):
            module.theme_css("invalid")

    def test_full_status_is_available(self):
        module = load_module()
        self.assertEqual(module.STATUS_STYLES["full"], ("사용 가능", "success"))


class DisplayPlanTypeTest(unittest.TestCase):
    def test_business_prolite_plan_is_human_readable(self):
        module = load_module()

        self.assertEqual(
            module.display_plan_type("self_serve_business_prolite"),
            "Business Pro Lite",
        )

    def test_known_short_plan_names_remain_readable(self):
        module = load_module()

        self.assertEqual(module.display_plan_type("prolite"), "Pro Lite")
        self.assertEqual(module.display_plan_type("team"), "Team")


class ProviderFailureSummaryTest(unittest.TestCase):
    def test_failed_provider_is_visible_in_header(self):
        module = load_module()
        errors = [{"provider": "openrouter", "message": "provider 정보가 올바르지 않습니다."}]

        self.assertEqual(module.provider_failure_summary(errors), "OpenRouter 조회 실패")

    def test_authentication_failure_is_distinct_from_rate_limit_wait(self):
        module = load_module()
        self.assertEqual(module.provider_failure_summary([
            {"provider": "claude", "message": "HTTP 401", "authentication_required": True}
        ]), "Claude 재인증 필요")
        self.assertEqual(module.provider_failure_summary([
            {"provider": "claude", "message": "HTTP 429", "rate_limited": True}
        ]), "Claude 조회 대기 중")


class AccountOrderTest(unittest.TestCase):
    def test_edit_starts_in_live_priority_order_and_moves_account(self):
        module = load_module()
        window = SimpleNamespace(
            saving_order=False, order_editing=False, pending_order=[],
            settings={"dashboard_url": None},
            reports=[
                {"provider": "codex", "auth_index": "a", "priority": 10},
                {"provider": "claude", "auth_index": "c"},
                {"provider": "codex", "auth_index": "b", "priority": 20},
            ],
            order_button=Mock(), save_order_button=Mock(), cancel_order_button=Mock(), render_cards=Mock(),
            updated_label=Mock(), dashboard_button=Mock(), refresh_button=Mock(), menu_button=Mock(),
        )
        module.QuotaWindow.toggle_order_edit(window, None)
        self.assertEqual(window.pending_order, ["b", "a"])
        module.QuotaWindow.move_account(window, "a", -1)
        self.assertEqual(window.pending_order, ["a", "b"])
        module.QuotaWindow.move_account(window, "a", -1)
        self.assertEqual(window.pending_order, ["a", "b"])
        module.QuotaWindow.toggle_order_edit(window, None)
        self.assertFalse(window.order_editing)
        self.assertEqual(window.pending_order, [])


if __name__ == "__main__":
    unittest.main()
