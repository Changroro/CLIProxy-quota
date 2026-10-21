import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
import time
import urllib.request
from urllib.parse import parse_qs, urlsplit, urlencode
from uuid import UUID

from . import configuration
from .client import display_plan_type
from .i18n import set_language


def read_snapshot(session_id):
    settings = configuration.load_settings()
    parsed = urlsplit(settings["dashboard_url"])
    token = parse_qs(parsed.fragment).get("token", [None])[0]
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or not token:
        raise ValueError("Invalid local collector URL")
    def get(url, key):
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "X-Quota-Client": "1"})
        with urllib.request.urlopen(request, timeout=0.3) as response:
            return json.load(response)
    snapshot = get(f"http://{parsed.netloc}/api/accounts", token)
    if session_id:
        route = get(settings["base_url"] + "/v8/management/observability/routing/session?" + urlencode({"session_id": session_id}), settings["management_key"])
        snapshot["routing"] = route["account"]
    return snapshot


def clean(value):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(value))[:40]


def format_snapshot(snapshot, now, color=False, language="ko"):
    set_language(language)
    ko = language == "ko"
    route = snapshot.get("routing")
    if route is None:
        return "CLIProxy · 연결 대기 · 아직 선택된 계정 없음" if ko else "CLIProxy · Waiting for account selection"
    account = next((item for item in snapshot["reports"] if item.get("auth_index") == route["auth_index"]), None)
    if account is None:
        return "CLIProxy · 선택 계정의 쿼터 조회 대기" if ko else "CLIProxy · Selected account quota pending"
    alias = account.get("alias") or (account.get("email") or "").split("@")[0] or account.get("name") or route["auth_index"]
    heading = f"{clean(account['provider']).capitalize()} · {clean(alias)} · {clean(display_plan_type(account.get('plan_type') or 'unknown'))}"
    if route.get("active"):
        heading += " · " + ("응답 중" if ko else "Responding")
    if color:
        heading = f"\x1b[1m{heading}\x1b[0m"
    observed = snapshot["status"].get("quota_updated_at")
    if snapshot["status"].get("quota_error"):
        heading += " · " + ("쿼터 조회 실패" if ko else "quota refresh failed")
    elif observed is None:
        heading += " · " + ("쿼터 조회 대기" if ko else "quota pending")
    elif not isinstance(observed, (float, int)) or not math.isfinite(observed):
        raise ValueError("Invalid observation time")
    elif now - observed > 180:
        heading += f" · {'캐시' if ko else 'cache'} {int((now-observed)/60)}m"
    segments = []
    for period in ("5h", "7d"):
        window = next((w for w in account["windows"] if w["label"] == period), None)
        value = window.get("remaining_percent") if window else None
        if value is None:
            segments.append(f"? ({period})")
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("Invalid remaining quota")
        value = 100 - value
        filled = int(value/10 + 0.5)
        bar = "█" * filled + "░" * (10-filled)
        if color:
            code = 32 if value < 70 else 33 if value < 90 else 31
            bar = f"\x1b[{code}m{bar}\x1b[0m"
        text = f"{bar} {value:g}%"
        if window.get("reset_at"):
            reset = datetime.fromisoformat(window["reset_at"].replace("Z", "+00:00"))
            if reset.tzinfo is None:
                raise ValueError("Reset time requires timezone")
            minutes = max(0, math.ceil((reset.timestamp() - now) / 60))
            days, minutes = divmod(minutes, 1440)
            hours, minutes = divmod(minutes, 60)
            duration = " ".join(part for part in (f"{days}d" if days else "", f"{hours}h" if hours else "", f"{minutes}m" if minutes or not (days or hours) else "") if part)
            text += f" ({duration} / {period})"
        else:
            text += f" (? / {period})"
        segments.append(text)
    return heading + "\nUsage " + " | ".join(segments)



def main():
    parser = argparse.ArgumentParser(prog="cliproxy-statusline")
    parser.add_argument("--fixture")
    parser.add_argument("--codex", action="store_true")
    parser.add_argument("--session-id")
    parser.add_argument("--language", choices=("ko", "en"), default="ko")
    args = parser.parse_args()
    try:
        session_id = args.session_id
        if args.codex:
            raw = sys.stdin.read(65537)
            if len(raw) > 65536:
                raise ValueError("Invalid Codex status payload")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Invalid Codex status payload")
            session_id = payload.get("session", {}).get("id")
        if session_id:
            session_id = str(UUID(session_id))
        elif not args.codex and not args.fixture:
            parser.error("--session-id is required")
        snapshot = json.loads(Path(args.fixture).read_text(encoding="utf-8")) if args.fixture else read_snapshot(session_id)
        print(format_snapshot(snapshot, time.time(), color=args.codex or sys.stdout.isatty(), language=args.language))
    except Exception as error:
        print("CLIProxy · 계정 연결 확인 불가" if args.language == "ko" else "CLIProxy · Account tracking unavailable")
        print(f"cliproxy-statusline: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(0 if args.codex else 1) from None


if __name__ == "__main__":
    main()
