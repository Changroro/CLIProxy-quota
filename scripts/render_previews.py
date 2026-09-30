import argparse
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cli_proxy_quota import widget
from cli_proxy_quota.i18n import set_language
from gi.repository import Gdk, GLib, Gtk

parser = argparse.ArgumentParser()
parser.add_argument("--language", choices=("en", "ko"), default="en")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
set_language(args.language)
args.output.mkdir(parents=True, exist_ok=True)
reports = []
for index, (provider, plan, remaining) in enumerate([
    ("codex", "prolite", (85, 62)),
    ("codex", "team", (42, 24)),
    ("codex", "self_serve_business_prolite", (12, 8)),
    ("claude", "max_20x", (91, 68)),
    ("openrouter", "free", (100, 100)),
]):
    windows = [{"label": period, "remaining_percent": value, "reset_at": "2026-10-07T01:00:00Z",
                "reset_label": "10-07 10:00", "last_reset_label": "10-06 10:00"}
               for period, value in zip(("5h", "7d"), remaining)]
    if provider == "openrouter":
        windows = [{"label": "1d free", "remaining_percent": None, "used_count": 12,
                    "limit_count": 50, "reset_label": "10-07 00:00", "last_reset_label": "10-06 00:00"}]
    reports.append({"provider": provider, "name": f"demo-{index}", "email": f"demo-{index}@example.test",
                    "account_id": f"demo-{index}", "auth_index": f"demo-{index}", "priority": 5-index,
                    "plan_type": plan, "status": "high", "windows": windows,
                    "reset_credit_expiries": ["2026-11-01T00:00:00Z"]})
settings = {"base_url": "http://127.0.0.1:8317", "management_key": "demo-only",
            "theme": "light", "language": args.language, "dashboard_url": None}
with patch.object(widget, "load_reports", return_value=(reports, [])), patch.object(widget, "load_aliases", return_value={}), patch.object(widget.configuration, "load_settings", return_value=settings), patch.object(widget.configuration, "save_theme"):
    window = widget.QuotaWindow(lambda _: None)
    window.show_all()
    window.move(20, 20)
    def capture(theme):
        width, height = window.get_size()
        assert width == 260, (width, height)
        Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, width, height).savev(str(args.output / f"{args.language}-{theme}.png"), "png", [], [])
        if theme == "light":
            with patch.object(widget.configuration, "save_language") as save_language, patch.object(widget.os, "execv") as restart, patch.dict(widget.os.environ):
                active = type("Active", (), {"get_active": lambda self: True})()
                window.choose_language(active, args.language)
                save_language.assert_called_once_with(args.language)
                restart.assert_called_once()
            window.theme_items["dark"].set_active(True)
            GLib.timeout_add(500, capture, "dark")
        else:
            Gtk.main_quit()
        return False
    GLib.timeout_add(800, capture, "light")
    Gtk.main()
    window.destroyed = True
    window.destroy()
