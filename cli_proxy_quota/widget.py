from .i18n import t
import json
import os
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from . import client, configuration
from .i18n import set_language

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango


ALIAS_PATH = configuration.CONFIG_DIR / "aliases.json"
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
REFRESH_SECONDS = 120
PROVIDER_LABELS = {
    "codex": "OpenAI / Codex",
    "claude": "Claude",
    "openrouter": "OpenRouter",
}
STATUS_STYLES = {
    "exhausted": ("소진", "danger"),
    "full": ("사용 가능", "success"),
    "high": ("사용 가능", "success"),
    "medium": ("사용 가능", "success"),
    "low": ("부족", "warning"),
    "error": ("오류", "danger"),
}
PLAN_LABELS = {"prolite": "Pro Lite", "self_serve_business_prolite": "Business Pro Lite", "team": "Team", "pro": "Pro", "free": "Free", "credits": "Credits", "oauth": "플랜 미확인", "unknown": "플랜 미확인", "max": "Max", "max_5x": "Max 5x", "max_20x": "Max 20x"}
BAR_COLORS = {"success": (34 / 255, 197 / 255, 94 / 255), "warning": (250 / 255, 204 / 255, 21 / 255), "danger": (239 / 255, 68 / 255, 68 / 255)}
LIGHT_CSS = """
.quota-window { background: #ffffff; color: #27272a; font-family: sans-serif; font-size: 10px; border: 1px solid #e4e4e7; border-radius: 8px; }
.compact-header { background: #f8f8f9; padding: 6px 9px; }
.compact-title { color: #27272a; font-size: 12px; font-weight: 600; }
.muted { color: #73737a; font-size: 9px; }
.provider-header { color: #73737a; background: #f8f8f9; padding: 5px 10px; }
.quota-card { padding: 6px 10px; border-bottom: 1px solid #e4e4e7; }
.quota-card:hover { background: #f9f9fa; }
.avatar { color: #27272a; background: #f3f3f5; border: 1px solid #d4d4d8; border-radius: 50%; padding: 0; min-width: 20px; min-height: 20px; box-shadow: none; }
.avatar label { color: #27272a; font-family: sans-serif; font-size: 10px; }
.plan-label { color: #52525b; background: #f3f3f5; border: 1px solid #e4e4e7; border-radius: 4px; padding: 2px 6px; font-family: sans-serif; font-size: 10px; font-weight: 500; }
.compact-button { color: #73737a; background: transparent; border: 0; padding: 2px; min-width: 18px; min-height: 18px; box-shadow: none; }
.compact-button label { color: #73737a; font-size: 10px; }
.compact-button:hover { background: #f3f3f5; }
.compact-button:focus { outline: 1px solid #52525b; }
.compact-button:disabled { color: #a1a1aa; }
.save label { color: #52525b; }
.quota-metric label { color: #73737a; font-family: sans-serif; font-size: 10px; }
.quota-metric .percent { color: #27272a; font-weight: 600; }
.quota-metric .reset { font-size: 9px; }
.reset-credit { color: #73737a; font-size: 9px; }
.notice { color: #946b2d; background: #f8f8f9; padding: 5px 10px; font-size: 9px; }
.quota-menu, .profile-popover { background: #ffffff; color: #27272a; }
.quota-menu menuitem, .quota-menu menuitem label, .quota-menu menuitem check { color: #27272a; font-size: 11px; }
.quota-menu menuitem:hover { background: #f0f0f2; }
.profile-popover label { color: #27272a; font-size: 11px; }
.profile-popover .muted { color: #73737a; font-size: 10px; }
.profile-popover button { color: #27272a; background: #f3f3f5; border: 0; box-shadow: none; }

.provider-header { border: 0; border-radius: 0; min-height: 0; box-shadow: none; }

.quota-window button, .profile-popover button { background-image: none; }
.quota-window .provider-header { background-color: #f8f8f9; }
.quota-window .avatar { background-color: #f3f3f5; }
"""
DARK_PALETTE = {"#ffffff": "#1c1c1e", "#27272a": "#eeeef0", "#f8f8f9": "#242426", "#73737a": "#b0b0b5", "#e4e4e7": "#363639", "#f9f9fa": "#232325", "#f3f3f5": "#2c2c2f", "#d4d4d8": "#424247", "#52525b": "#d4d4d8", "#a1a1aa": "#73737a", "#f0f0f2": "#2d2d30", "#946b2d": "#e9b75f"}


def theme_css(theme):
    if theme not in ("light", "dark"):
        raise ValueError(t("알 수 없는 테마입니다."))
    if theme == "light":
        return LIGHT_CSS.encode()
    import re
    return re.sub(r"#[0-9a-f]{6}", lambda match: DARK_PALETTE.get(match.group(), match.group()), LIGHT_CSS).encode()


def load_reports():
    return client.collect_reports()


def run_reset():
    return client.reset_cooldowns()


def provider_failure_summary(errors):
    labels = []
    for error in errors:
        provider = PROVIDER_LABELS.get(error["provider"], error["provider"].title())
        if error.get("plan_lookup_failed"):
            labels.append(t("{v0} 플랜 조회 실패", v0=provider))
        elif error.get("authentication_required"):
            labels.append(t("{v0} 재인증 필요", v0=provider))
        elif error.get("rate_limited"):
            labels.append(t("{v0} 조회 대기 중", v0=provider))
        else:
            labels.append(t("{v0} 조회 실패", v0=provider))
    return " · ".join(labels)


def visible_quota_windows(report):
    windows = report.get("windows")
    if not isinstance(windows, list) or not windows or not all(isinstance(window, dict) for window in windows):
        raise ValueError(t("사용량 기간 정보가 올바르지 않습니다."))
    if any(window.get("label") == "7d" and window.get("remaining_percent") == 0 for window in windows):
        return [window for window in windows if window.get("label") != "5h"]
    return windows


def display_plan_type(plan_type):
    if not isinstance(plan_type, str) or not plan_type.strip():
        raise ValueError(t("플랜 정보가 올바르지 않습니다."))
    normalized = plan_type.strip().lower()
    label = PLAN_LABELS.get(normalized, normalized.removeprefix("self_serve_").replace("_", " ").title())
    return t(label) if label == "플랜 미확인" else label


def load_aliases():
    if not ALIAS_PATH.exists():
        return {}
    aliases = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    if not isinstance(aliases, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in aliases.items()):
        raise ValueError(t("별칭 파일 형식이 올바르지 않습니다."))
    return aliases


def save_aliases(aliases):
    ALIAS_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ALIAS_PATH.parent, delete=False) as handle:
        json.dump(aliases, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = handle.name
    os.replace(temporary_path, ALIAS_PATH)


class QuotaBar(Gtk.DrawingArea):
    def __init__(self, remaining, color):
        super().__init__()
        self.remaining = max(0, min(100, remaining))
        self.color = color
        self.set_size_request(96, 5)
        self.set_valign(Gtk.Align.CENTER)
        self.get_accessible().set_name(t("잔여량 {v0:g}%", v0=self.remaining))
        self.connect("draw", self.draw_bar)

    def draw_bar(self, _widget, context):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        context.rectangle(0, 0, width, height)
        context.set_source_rgb(*( (0.21, 0.21, 0.22) if self.get_toplevel().effective_theme == "dark" else (0.91, 0.91, 0.925) ))
        context.fill()
        fill_width = width * self.remaining / 100
        if fill_width > 0:
            context.rectangle(0, 0, fill_width, height)
            context.set_source_rgb(*self.color)
            context.fill()
        return False


class QuotaWindow(Gtk.Window):
    def __init__(self, reports_updated):
        super().__init__(title=t("CLIProxy 사용량"))
        self.reports_updated = reports_updated
        self.reports = []
        self.provider_errors = []
        self.account_expanded = {}
        self.aliases = load_aliases()
        self.refreshing = False
        self.resetting = False
        self.destroyed = False
        self.pinned = True
        self.settings = configuration.load_settings()
        self.theme_choice = self.settings["theme"]
        self.effective_theme = "light"
        self.order_editing = False
        self.pending_order = []
        self.saving_order = False

        self.set_default_size(260, -1)
        self.set_icon_from_file(str(ASSET_DIR / "cliproxy.png"))
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_decorated(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.get_style_context().add_class("quota-window")
        self.connect("delete-event", self.hide_window)

        self.theme_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), self.theme_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        schema_source = Gio.SettingsSchemaSource.get_default()
        self.system_settings = Gio.Settings.new("org.gnome.desktop.interface") if schema_source and schema_source.lookup("org.gnome.desktop.interface", True) else None
        if self.system_settings:
            self.system_settings.connect("changed::color-scheme", self.system_theme_changed)
        Gtk.Settings.get_default().connect("notify::gtk-theme-name", self.system_theme_changed)
        Gtk.Settings.get_default().connect("notify::gtk-application-prefer-dark-theme", self.system_theme_changed)
        self.apply_theme()

        header_event = Gtk.EventBox()
        header_event.connect("button-press-event", self.start_move)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        header.get_style_context().add_class("compact-header")
        title = Gtk.Label(label="CLIProxy")
        title.get_style_context().add_class("compact-title")
        header.pack_start(title, False, False, 2)
        self.updated_label = Gtk.Label(label="…")
        self.updated_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.updated_label.set_max_width_chars(6)
        self.updated_label.get_style_context().add_class("muted")
        header.pack_start(self.updated_label, True, True, 0)
        self.dashboard_button = Gtk.Button.new_from_icon_name("view-grid-symbolic", Gtk.IconSize.MENU)
        self.dashboard_button.get_style_context().add_class("compact-button")
        self.dashboard_button.set_tooltip_text(t("대시보드 열기") if self.settings["dashboard_url"] else t("대시보드 연결 후 사용할 수 있습니다"))
        self.dashboard_button.set_sensitive(self.settings["dashboard_url"] is not None)
        self.dashboard_button.set_no_show_all(self.settings["dashboard_url"] is None)
        self.dashboard_button.connect("clicked", self.open_dashboard)
        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.MENU)
        self.refresh_button.set_tooltip_text(t("지금 새로고침"))
        self.refresh_button.get_style_context().add_class("compact-button")
        self.refresh_button.connect("clicked", lambda _button: self.refresh())
        self.order_button = Gtk.MenuItem(label=t("Codex 순서 편집"))
        self.order_button.set_tooltip_text(t("Codex 계정을 위에서부터 먼저 사용"))
        self.order_button.connect("activate", self.toggle_order_edit)
        self.order_button.set_sensitive(False)
        self.save_order_button = Gtk.Button(label=t("저장"))
        self.save_order_button.get_style_context().add_class("compact-button")
        self.save_order_button.connect("clicked", self.save_order)
        self.save_order_button.set_no_show_all(True)
        self.cancel_order_button = Gtk.Button(label=t("취소"))
        self.cancel_order_button.get_style_context().add_class("compact-button")
        self.cancel_order_button.connect("clicked", self.toggle_order_edit)
        self.cancel_order_button.set_no_show_all(True)
        self.reset_button = Gtk.MenuItem(label=t("쿨다운 리셋"))
        self.reset_button.set_tooltip_text(t("쿨다운 리셋"))
        self.reset_button.connect("activate", lambda _item: self.reset_cooldown())
        self.pin_button = Gtk.CheckMenuItem(label=t("항상 위로 고정"))
        self.pin_button.set_active(True)
        self.pin_button.set_tooltip_text(t("항상 위 고정 해제"))
        self.pin_button.connect("toggled", self.toggle_pin)
        menu = Gtk.Menu()
        menu.get_style_context().add_class("quota-menu")
        for item in (self.order_button, self.pin_button, self.reset_button, Gtk.SeparatorMenuItem()):
            menu.append(item)
        appearance = Gtk.MenuItem(label=t("테마 (라이트 / 다크)"))
        themes = Gtk.Menu()
        group = None
        self.theme_items = {}
        for choice, text in (("system", t("시스템 테마")), ("light", t("라이트")), ("dark", t("다크"))):
            item = Gtk.RadioMenuItem.new_with_label(group, text)
            group = item.get_group()
            item.set_active(choice == self.theme_choice)
            item.connect("toggled", self.choose_theme, choice)
            themes.append(item)
            self.theme_items[choice] = item
        themes.get_style_context().add_class("quota-menu")
        appearance.set_submenu(themes)
        menu.append(appearance)
        language_menu = Gtk.MenuItem(label=t("언어 / Language"))
        language_choices = Gtk.Menu()
        language_choices.get_style_context().add_class("quota-menu")
        group = None
        for choice, label in (("system", t("시스템 언어")), ("ko", "한국어"), ("en", "English")):
            item = Gtk.RadioMenuItem.new_with_label(group, label)
            group = item.get_group()
            item.set_active(choice == self.settings["language"])
            item.connect("toggled", self.choose_language, choice)
            language_choices.append(item)
        language_menu.set_submenu(language_choices)
        menu.append(language_menu)
        close_item = Gtk.MenuItem(label=t("창 숨기기"))
        close_item.connect("activate", lambda _item: self.hide())
        menu.append(close_item)
        menu.show_all()
        menu_button = Gtk.MenuButton(label="⋯")
        self.menu_button = menu_button
        menu_button.set_tooltip_text(t("사용량 창 메뉴"))
        menu_button.get_style_context().add_class("compact-button")
        menu_button.set_popup(menu)
        header.pack_end(menu_button, False, False, 0)
        header.pack_end(self.refresh_button, False, False, 0)
        header.pack_end(self.dashboard_button, False, False, 0)
        header.pack_end(self.save_order_button, False, False, 0)
        header.pack_end(self.cancel_order_button, False, False, 0)
        header_event.add(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        outer.pack_start(header_event, False, False, 0)
        self.cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.pack_start(self.cards, False, False, 0)
        self.notice_label = Gtk.Label(xalign=0)
        self.notice_label.set_line_wrap(True)
        self.notice_label.set_max_width_chars(32)
        self.notice_label.set_no_show_all(True)
        self.notice_label.get_style_context().add_class("notice")
        outer.pack_start(self.notice_label, False, False, 0)
        self.add(outer)

        self.refresh()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self.auto_refresh)

    def apply_theme(self):
        gtk = Gtk.Settings.get_default()
        system_dark = gtk.get_property("gtk-application-prefer-dark-theme") or gtk.get_property("gtk-theme-name").lower().endswith(("-dark", ":dark"))
        if self.system_settings:
            system_dark = system_dark or self.system_settings.get_string("color-scheme") == "prefer-dark"
        self.effective_theme = ("dark" if system_dark else "light") if self.theme_choice == "system" else self.theme_choice
        self.theme_provider.load_from_data(theme_css(self.effective_theme))
        self.queue_draw()
        if hasattr(self, "cards"):
            self.render_cards()

    def system_theme_changed(self, *_args):
        if self.theme_choice == "system":
            self.apply_theme()

    def choose_theme(self, item, choice):
        if item.get_active():
            try:
                configuration.save_theme(choice)
            except Exception as error:
                self.show_error(error, t("모양 설정을 저장하지 못했습니다."))
                return
            self.theme_choice = choice
            self.apply_theme()

    def open_dashboard(self, _button):
        if self.settings["dashboard_url"]:
            Gio.AppInfo.launch_default_for_uri(self.settings["dashboard_url"], None)

    def choose_language(self, item, choice):
        if item.get_active():
            try:
                configuration.save_language(choice)
                os.environ["CLIPROXY_LANGUAGE"] = choice
                os.execv(sys.executable, [sys.executable, *sys.argv])
            except Exception as error:
                self.show_error(error, t("언어 설정을 적용하지 못했습니다."))

    def show_notice(self, text, detail=None):
        self.notice_label.set_text(text)
        self.notice_label.set_tooltip_text(detail)
        self.notice_label.set_visible(bool(text))

    def hide_window(self, *_args):
        self.hide()
        return True

    def start_move(self, _widget, event):
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return False

    def toggle_pin(self, button):
        self.pinned = button.get_active()
        self.set_keep_above(self.pinned)
        tooltip = t("항상 위 고정 해제") if self.pinned else t("항상 위로 고정")
        self.pin_button.set_tooltip_text(tooltip)

    def toggle_order_edit(self, _button):
        if self.saving_order:
            return
        self.order_editing = not self.order_editing
        if self.order_editing:
            codex_reports = [report for report in self.reports if report.get("provider") == "codex"]
            codex_reports.sort(key=lambda report: -report.get("priority", 0))
            self.pending_order = [report["auth_index"] for report in codex_reports]
            self.cancel_order_button.show()
            self.save_order_button.show()
        else:
            self.pending_order = []
            self.cancel_order_button.hide()
            self.save_order_button.hide()
        for control in (self.updated_label, self.dashboard_button, self.refresh_button, self.menu_button):
            hidden = self.order_editing or (control is self.dashboard_button and self.settings["dashboard_url"] is None)
            control.set_no_show_all(hidden)
            control.set_visible(not hidden)
        self.render_cards()

    def move_account(self, auth_index, step):
        if self.saving_order:
            return
        position = self.pending_order.index(auth_index)
        target = position + step
        if 0 <= target < len(self.pending_order):
            self.pending_order[position], self.pending_order[target] = self.pending_order[target], self.pending_order[position]
            self.render_cards()

    def save_order(self, _button):
        if self.saving_order or self.refreshing or not self.order_editing:
            return
        self.saving_order = True
        self.save_order_button.set_sensitive(False)
        self.cancel_order_button.set_sensitive(False)
        self.refresh_button.set_sensitive(False)
        self.order_button.set_sensitive(False)
        threading.Thread(target=self.perform_save_order, args=(self.pending_order[:],), daemon=True).start()

    def perform_save_order(self, order):
        try:
            client.set_codex_order(order)
        except Exception as error:
            GLib.idle_add(self.finish_save_order, error)
            return
        GLib.idle_add(self.finish_save_order, None)

    def finish_save_order(self, error):
        if self.destroyed:
            return False
        self.saving_order = False
        self.save_order_button.set_sensitive(True)
        self.cancel_order_button.set_sensitive(True)
        self.refresh_button.set_sensitive(True)
        self.order_button.set_sensitive(True)
        if error is not None:
            detail = str(error)
            self.show_error(RuntimeError(detail or str(error)), t("계정 순서를 저장하지 못했습니다."))
            return False
        self.toggle_order_edit(None)
        self.refresh()
        return False

    def auto_refresh(self):
        if self.destroyed:
            return False
        self.refresh()
        return True

    def refresh(self):
        if self.refreshing or self.saving_order:
            return
        self.refreshing = True
        self.refresh_button.set_sensitive(False)
        self.save_order_button.set_sensitive(False)
        self.updated_label.set_text(t("갱신 중"))
        threading.Thread(target=self.fetch_reports, daemon=True).start()

    def fetch_reports(self):
        try:
            reports, errors = load_reports()
        except Exception as error:
            GLib.idle_add(self.finish_refresh, None, error)
            return
        GLib.idle_add(self.finish_refresh, (reports, errors), None)

    def finish_refresh(self, result, error):
        if self.destroyed:
            return False
        self.refreshing = False
        self.refresh_button.set_sensitive(True)
        self.save_order_button.set_sensitive(True)
        if error is not None:
            self.updated_label.set_text(t("오류"))
            self.show_notice(t("서버 연결 실패"), str(error))
            return False
        reports, provider_errors = result
        previous_reports = self.reports
        previous_errors = self.provider_errors
        self.reports = reports
        self.provider_errors = provider_errors
        self.order_button.set_sensitive(any(report.get("provider") == "codex" for report in reports))
        try:
            self.render_cards()
        except Exception as render_error:
            self.reports = previous_reports
            self.provider_errors = previous_errors
            self.updated_label.set_text(t("오류"))
            self.show_notice(t("사용량 표시 실패"), str(render_error))
            return False
        if provider_errors:
            self.updated_label.set_text(f"{datetime.now():%H:%M}")
            self.show_notice(provider_failure_summary(provider_errors))
            details = "\n".join(
                f"{PROVIDER_LABELS.get(error['provider'], error['provider'].title())}: {error['message']}"
                for error in provider_errors
            )
            self.updated_label.set_tooltip_text(details)
            self.notice_label.set_tooltip_text(details)
        else:
            self.updated_label.set_text(f"{datetime.now():%H:%M}")
            self.updated_label.set_tooltip_text(None)
            self.show_notice("")
        self.reports_updated(reports)
        return False

    def render_cards(self):
        grouped = {}
        for report in self.reports:
            provider = report.get("provider")
            if not isinstance(provider, str):
                raise ValueError(t("계정 서비스 정보가 올바르지 않습니다."))
            grouped.setdefault(provider, []).append(report)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for provider, reports in grouped.items():
            if provider == "codex":
                if self.order_editing:
                    positions = {identifier: index for index, identifier in enumerate(self.pending_order)}
                    reports.sort(key=lambda report: positions.get(report["auth_index"], len(positions)))
                else:
                    reports.sort(key=lambda report: -report.get("priority", 0))
            for index, report in enumerate(reports, 1):
                content.pack_start(self.account_card(report, index), False, False, 0)
        for child in self.cards.get_children():
            self.cards.remove(child)
            child.destroy()
        self.cards.pack_start(content, False, False, 0)
        self.cards.show_all()

    def toggle_account(self, _button, name):
        self.account_expanded[name] = not self.account_expanded.get(name, True)
        self.render_cards()

    def account_card(self, report, provider_index):
        name = report.get("name")
        plan_type = report.get("plan_type")
        status = report.get("status")
        windows = report.get("windows")
        if not all(isinstance(value, str) for value in (name, plan_type, status)):
            raise ValueError(t("계정 정보가 올바르지 않습니다."))
        if not isinstance(windows, list) or not windows:
            raise ValueError(t("{v0}의 사용량 기간 정보가 없습니다.", v0=name))
        status_style = STATUS_STYLES.get(status)
        if status_style is None:
            raise ValueError(t("알 수 없는 계정 상태입니다: {v0}", v0=status))
        status_label, _color_class = status_style
        status_label = t(status_label)
        display_windows = visible_quota_windows(report)
        if not display_windows:
            raise ValueError(t("{v0}의 표시할 사용량 기간 정보가 없습니다.", v0=name))

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.get_style_context().add_class("quota-card")
        email = report.get("email")
        provider = report.get("provider")
        if not isinstance(email, str) or not isinstance(provider, str):
            raise ValueError(t("계정 이메일 또는 provider 정보가 올바르지 않습니다."))
        if report.get("stale"):
            stale_as_of = report.get("stale_as_of")
            stale_label = (
                datetime.fromisoformat(stale_as_of.replace("Z", "+00:00"))
                .astimezone()
                .strftime("%m-%d %H:%M")
                if isinstance(stale_as_of, str)
                else t("시각 미상")
            )
            card.set_tooltip_text(t("마지막 성공값 · {v0} 기준 · 재조회 대기 중", v0=stale_label))
        label = self.aliases.get(name) or email
        for window in display_windows:
            if not all(isinstance(window.get(key), str) for key in ("label", "reset_label", "last_reset_label")):
                raise ValueError(t("초기화 시각 정보가 올바르지 않습니다."))
        reset_summary = "\n".join(t("{v0} 다음 초기화 {v1}", v0=window['label'], v1=window['reset_label']) for window in display_windows)
        last_reset_summary = "\n".join(t("{v0} 직전 초기화 {v1}", v0=window['label'], v1=window['last_reset_label']) for window in display_windows)
        avatar = Gtk.Button()
        if provider in ("codex", "claude"):
            icon_file = Gio.File.new_for_path(str(ASSET_DIR / f"{provider}-symbolic.svg"))
            avatar.add(Gtk.Image.new_from_gicon(Gio.FileIcon.new(icon_file), Gtk.IconSize.MENU))
        elif provider == "openrouter":
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ASSET_DIR / f"openrouter-{self.effective_theme}.svg"), 16, 16, True)
            avatar.add(Gtk.Image.new_from_pixbuf(pixbuf))
        else:
            raise ValueError(t("서비스 아이콘이 없습니다: {v0}", v0=provider))
        avatar.set_tooltip_text(t("{v0} 계정 {v1} 정보", v0=provider.title(), v1=provider_index))
        avatar.get_style_context().add_class("avatar")
        avatar.set_valign(Gtk.Align.CENTER)
        avatar.connect(
            "clicked",
            lambda button: self.show_profile(
                button, name, label, email, provider, plan_type, status_label, reset_summary, last_reset_summary
            ),
        )
        profile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        profile.pack_start(avatar, False, False, 0)
        display_plan = display_plan_type(plan_type)
        plan_label = Gtk.Label(label=display_plan)
        plan_label.set_xalign(0)
        plan_label.get_style_context().add_class("plan-label")
        plan_label.set_ellipsize(Pango.EllipsizeMode.END)
        plan_label.set_max_width_chars(22)
        plan_label.set_tooltip_text(t("수집된 플랜 코드: {v0}", v0=plan_type))
        profile.pack_start(plan_label, False, False, 0)
        if provider == "codex" and self.order_editing:
            for icon, step, enabled in (
                ("go-up-symbolic", -1, provider_index > 1),
                ("go-down-symbolic", 1, provider_index < sum(row.get("provider") == "codex" for row in self.reports)),
            ):
                button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.MENU)
                button.get_style_context().add_class("compact-button")
                button.set_sensitive(enabled)
                button.set_tooltip_text(t("우선순위 올리기") if step == -1 else t("우선순위 내리기"))
                button.connect("clicked", lambda _button, direction=step: self.move_account(report["auth_index"], direction))
                profile.pack_start(button, False, False, 0)
        expanded = self.account_expanded.get(name, True)
        collapse = Gtk.Button.new_from_icon_name("pan-down-symbolic" if expanded else "pan-end-symbolic", Gtk.IconSize.MENU)
        collapse.get_style_context().add_class("compact-button")
        collapse.set_tooltip_text(t("계정 사용량 접기") if expanded else t("계정 사용량 펼치기"))
        collapse.connect("clicked", self.toggle_account, name)
        profile.pack_end(collapse, False, False, 0)
        card.pack_start(profile, False, False, 0)
        if not expanded:
            return card
        card.pack_start(self.quota_metrics(display_windows), False, False, 0)
        if provider == "codex":
            if "reset_credits_error" in report:
                credits_label = Gtk.Label(label=t("Reset 조회 실패 ⓘ"), xalign=0)
                credits_label.set_tooltip_text(report["reset_credits_error"])
            else:
                expiries = report.get("reset_credit_expiries")
                if not isinstance(expiries, list):
                    raise ValueError(t("Codex 리셋권 정보가 없습니다."))
                dates = [datetime.fromisoformat(expiry.replace("Z", "+00:00")).astimezone() for expiry in expiries]
                text = t("Reset 만기  ") + " · ".join(date.strftime("%m/%d") for date in dates) if dates else t("Reset 0개")
                credits_label = Gtk.Label(label=text, xalign=0)
                credits_label.set_tooltip_text("\n".join(date.strftime(t("Reset 만기 %Y-%m-%d %H:%M")) for date in dates))
            credits_label.set_line_wrap(True)
            credits_label.set_max_width_chars(30)
            credits_label.set_margin_start(28)
            credits_label.get_style_context().add_class("reset-credit")
            card.pack_start(credits_label, False, False, 0)
        return card

    def show_profile(
        self,
        avatar,
        account_name,
        label,
        email,
        provider,
        plan_type,
        status_label,
        reset_summary,
        last_reset_summary,
    ):
        popover = Gtk.Popover.new(avatar)
        popover.get_style_context().add_class("profile-popover")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.set_border_width(9)
        title = Gtk.Label(label=label, xalign=0)
        title.get_style_context().add_class("compact-title")
        content.pack_start(title, False, False, 0)
        content.pack_start(Gtk.Label(label=email, xalign=0), False, False, 0)
        display_plan = display_plan_type(plan_type)
        detail = Gtk.Label(label=f"{provider} · {display_plan} · {status_label}", xalign=0)
        detail.get_style_context().add_class("muted")
        content.pack_start(detail, False, False, 0)
        reset = Gtk.Label(label=reset_summary, xalign=0)
        reset.get_style_context().add_class("muted")
        content.pack_start(reset, False, False, 0)
        last_reset = Gtk.Label(label=last_reset_summary, xalign=0)
        last_reset.get_style_context().add_class("muted")
        content.pack_start(last_reset, False, False, 0)
        edit_button = Gtk.Button(label=t("별칭 변경"))
        edit_button.connect(
            "clicked",
            lambda _button: (popover.popdown(), self.edit_alias(account_name, label)),
        )
        content.pack_start(edit_button, False, False, 0)
        popover.add(content)
        popover.show_all()

    def quota_metrics(self, windows):
        metrics = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        metrics.get_style_context().add_class("quota-metric")
        metrics.set_margin_start(28)
        for quota_window in windows:
            remaining = quota_window.get("remaining_percent")
            label = quota_window.get("label")
            reset_label = quota_window.get("reset_label")
            last_reset_label = quota_window.get("last_reset_label")
            if not all(isinstance(value, str) for value in (label, reset_label, last_reset_label)):
                raise ValueError(t("사용량 기간 정보가 올바르지 않습니다."))
            if isinstance(remaining, (int, float)):
                color_class = "danger" if remaining < 20 else "warning" if remaining < 50 else "success"
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                row.get_style_context().add_class("quota-metric")
                row.set_tooltip_text(t("{v0} 다음 초기화: {v1}\n직전 초기화: {v2}", v0=label, v1=reset_label, v2=last_reset_label))
                period = Gtk.Label(label=label.removesuffix(" free"), xalign=0)
                period.set_width_chars(2)
                row.pack_start(period, False, False, 0)
                row.pack_start(QuotaBar(remaining, BAR_COLORS[color_class]), True, True, 0)
                percent = Gtk.Label(label=f"{remaining:g}%", xalign=1)
                percent.set_width_chars(4)
                percent.get_style_context().add_class("percent")
                row.pack_start(percent, False, False, 0)
                reset_at = quota_window.get("reset_at")
                if isinstance(reset_at, str):
                    reset_time = datetime.fromisoformat(reset_at.replace("Z", "+00:00")).astimezone()
                    short_reset = t("{v0}월 {v1}일", v0=reset_time.month, v1=reset_time.day)
                else:
                    short_reset = t("미제공")
                reset = Gtk.Label(label=short_reset, xalign=1)
                reset.set_width_chars(7)
                reset.get_style_context().add_class("reset")
                row.pack_start(reset, False, False, 0)
                metrics.pack_start(row, False, False, 0)
            else:
                used_count = quota_window.get("used_count")
                limit_count = quota_window.get("limit_count")
                if not isinstance(used_count, int) or not isinstance(limit_count, int):
                    raise ValueError(t("관측 요청량 정보가 올바르지 않습니다."))
                metrics.pack_start(
                    Gtk.Label(label=t("{v0}  ≥{v1} / {v2}회", v0=label, v1=used_count, v2=limit_count), xalign=0),
                    False,
                    False,
                    0,
                )
        return metrics

    def edit_alias(self, account_name, current_label):
        dialog = Gtk.Dialog(title=t("계정 별칭"), transient_for=self, modal=True)
        dialog.get_style_context().add_class("profile-popover")
        dialog.add_button(t("취소"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t("저장"), Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_text(self.aliases.get(account_name, ""))
        entry.set_placeholder_text(current_label)
        entry.set_activates_default(True)
        dialog.set_default_response(Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.add(entry)
        dialog.show_all()
        response = dialog.run()
        alias = entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        if alias:
            self.aliases[account_name] = alias
        else:
            self.aliases.pop(account_name, None)
        save_aliases(self.aliases)
        self.render_cards()

    def show_error(self, error, message=None):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.NONE,
            text=message or t("계정 사용량을 불러오지 못했습니다."),
        )
        dialog.format_secondary_text(str(error))
        dialog.add_button(t("닫기"), Gtk.ResponseType.CLOSE)
        dialog.get_style_context().add_class("profile-popover")
        dialog.run()
        dialog.destroy()

    def reset_cooldown(self):
        if self.resetting:
            return
        self.resetting = True
        self.reset_button.set_sensitive(False)
        threading.Thread(target=self.perform_reset, daemon=True).start()

    def perform_reset(self):
        try:
            output = run_reset()
        except Exception as error:
            GLib.idle_add(self.finish_reset, None, error)
            return
        GLib.idle_add(self.finish_reset, output, None)

    def finish_reset(self, output, error):
        if self.destroyed:
            return False
        self.resetting = False
        self.reset_button.set_sensitive(True)
        self.show_reset_result(output, error)
        if error is None:
            self.refresh()
        return False

    def show_reset_result(self, output, error):
        if error is None:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.NONE,
                text=t("쿨다운을 리셋했습니다."),
            )
        else:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.NONE,
                text=t("쿨다운 리셋에 실패했습니다."),
            )
        dialog.format_secondary_text(output if error is None else str(error))
        dialog.add_button(t("닫기"), Gtk.ResponseType.CLOSE)
        dialog.get_style_context().add_class("profile-popover")
        dialog.run()
        dialog.destroy()


class UsageApplication(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.cliproxyquota.Widget",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.window = None
        self.summary_items = {}

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        self.window = QuotaWindow(self.update_summaries)
        self.window.set_application(self)
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "cli-proxy-quota",
            str(ASSET_DIR / "cliproxy.png"),
            AyatanaAppIndicator3.IndicatorCategory.SYSTEM_SERVICES,
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title(t("CLIProxy 사용량"))
        menu = Gtk.Menu()
        open_item = Gtk.MenuItem(label=t("사용량 열기"))
        open_item.connect("activate", lambda _item: self.show_window())
        menu.append(open_item)
        menu.append(Gtk.SeparatorMenuItem())
        self.menu = menu
        self.summary_end = Gtk.SeparatorMenuItem()
        menu.append(self.summary_end)
        refresh_item = Gtk.MenuItem(label=t("지금 새로고침"))
        refresh_item.connect("activate", lambda _item: self.window.refresh())
        menu.append(refresh_item)
        reset_item = Gtk.MenuItem(label=t("쿨다운 리셋"))
        reset_item.connect("activate", lambda _item: self.window.reset_cooldown())
        menu.append(reset_item)
        quit_item = Gtk.MenuItem(label=t("종료"))
        quit_item.connect("activate", lambda _item: self.stop())
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        if "--background" not in args:
            self.show_window()
        return 0

    def show_window(self):
        self.window.show_all()
        self.window.present()

    def update_summaries(self, reports):
        grouped_reports = {}
        for report in reports:
            provider = report.get("provider")
            grouped_reports.setdefault(provider, []).append(report)
        for item in self.summary_items.values():
            self.menu.remove(item)
        self.summary_items = {}
        position = self.menu.get_children().index(self.summary_end)
        for provider, provider_reports in grouped_reports.items():
            available = sum(report.get("status") not in ("exhausted", "error") for report in provider_reports)
            label = PROVIDER_LABELS.get(provider, provider.title())
            item = Gtk.MenuItem(label=t("{v0} {v1}/{v2} 사용 가능", v0=label, v1=available, v2=len(provider_reports)))
            item.set_sensitive(False)
            self.menu.insert(item, position)
            item.show()
            self.summary_items[provider] = item
            position += 1

    def stop(self):
        self.window.destroyed = True
        self.window.destroy()
        self.release()
        self.quit()


def main():
    settings = configuration.load_settings()
    set_language(os.environ.get("CLIPROXY_LANGUAGE", settings["language"]))
    application = UsageApplication()
    raise SystemExit(application.run(sys.argv))


if __name__ == "__main__":
    main()
