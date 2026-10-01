from .i18n import t
import json
import os
import tempfile
import fcntl
from pathlib import Path
from urllib.parse import urlparse


CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cli-proxy-quota"
CONFIG_PATH = CONFIG_DIR / "config.json"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "cli-proxy-quota"


def stored_settings():
    if not CONFIG_PATH.exists():
        return {}
    settings = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError(t("설정 파일은 JSON 객체여야 합니다: {v0}", v0=CONFIG_PATH))
    return settings


def load_settings():
    settings = stored_settings()
    base_url = os.environ.get("CLIPROXY_BASE_URL", settings.get("base_url", "http://127.0.0.1:8317"))
    key = os.environ.get("CLIPROXY_MANAGEMENT_KEY", settings.get("management_key"))
    parsed = urlparse(base_url) if isinstance(base_url, str) else None
    if parsed is None or parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(t("CLIProxy 서버 주소가 올바르지 않습니다."))
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError(t("서버 주소에는 관리 API 경로 없이 호스트와 포트만 입력하세요."))
    if not isinstance(key, str) or not key.strip():
        raise ValueError(t("CLIPROXY_MANAGEMENT_KEY 또는 {v0}의 management_key가 필요합니다.", v0=CONFIG_PATH))
    theme = settings.get("theme", "system")
    if theme not in ("system", "light", "dark"):
        raise ValueError(t("theme은 system, light, dark 중 하나여야 합니다."))
    language = settings.get("language", "system")
    if language not in ("system", "en", "ko"):
        raise ValueError(t("language는 system, en, ko 중 하나여야 합니다."))
    dashboard = settings.get("dashboard_url")
    if dashboard is not None and (not isinstance(dashboard, str) or urlparse(dashboard).scheme not in ("http", "https")):
        raise ValueError(t("대시보드 주소가 올바르지 않습니다."))
    return {"base_url": base_url.rstrip("/"), "management_key": key.strip(), "theme": theme, "language": language, "dashboard_url": dashboard}


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=CONFIG_DIR, delete=False) as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, CONFIG_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def management_url():
    return load_settings()["base_url"] + "/management.html?theme=cli-proxy-quota&v=usage"


def save_theme(theme):
    if theme not in ("system", "light", "dark"):
        raise ValueError(t("알 수 없는 테마입니다."))
    set_option("theme", theme)


def save_language(language):
    if language not in ("system", "en", "ko"):
        raise ValueError(t("language는 system, en, ko 중 하나여야 합니다."))
    set_option("language", language)


def set_option(name, value):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(CONFIG_DIR / "settings.lock", "a+") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        settings = stored_settings()
        if value is None:
            settings.pop(name, None)
        else:
            settings[name] = value
        save_settings(settings)
