from .i18n import t
from email.utils import parsedate_to_datetime
import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


from .configuration import load_settings, STATE_DIR

STATE_PATH = STATE_DIR / "quota-state.json"
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 900


class UpstreamError(RuntimeError):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(t("사용량 조회 실패: HTTP {v0}", v0=status_code))


class RateLimitedError(RuntimeError):
    def __init__(self, retry_after_seconds):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(t("사용량 요청이 HTTP 429로 제한되었습니다."))


def management_key():
    return load_settings()["management_key"]


def management_request(key, path, payload=None, method=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        load_settings()["base_url"] + path,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method=method or ("POST" if payload is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(t("CLIProxyAPI {v0} 요청 실패: HTTP {v1} {v2}", v0=path, v1=error.code, v2=detail)) from error


def retry_after_seconds(headers, now=None):
    if not isinstance(headers, dict):
        return None
    value = next((value for name, value in headers.items() if name.lower() == "retry-after"), None)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if not isinstance(value, str):
        return None
    try:
        return max(0, int(float(value)))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0, int((retry_at - now).total_seconds()))


def api_call(key, auth_index, url, headers):
    response = management_request(
        key,
        "/v8/management/requests/api-call",
        {
            "auth_index": auth_index,
            "method": "GET",
            "url": url,
            "header": headers,
        },
    )
    status_code = response.get("status_code")
    if status_code == 429:
        response_headers = response.get("headers") or response.get("header", {})
        raise RateLimitedError(retry_after_seconds(response_headers))
    if status_code != 200:
        raise UpstreamError(status_code)
    body = response.get("body")
    if not isinstance(body, str):
        raise RuntimeError(t("{v0} 사용량 응답 본문이 없습니다.", v0=url))
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError(t("{v0} 사용량 응답이 JSON이 아닙니다.", v0=url)) from error


def iso_from_epoch(value):
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_label(value):
    parsed = parse_time(value)
    if parsed is None:
        return t("API 미제공")
    return parsed.astimezone().strftime("%m-%d %H:%M")


def duration_label(seconds):
    labels = {18000: "5h", 604800: "7d"}
    if seconds in labels:
        return labels[seconds]
    if not isinstance(seconds, int) or seconds <= 0:
        raise RuntimeError(t("사용량 윈도우 길이가 올바르지 않습니다: {v0}", v0=seconds))
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds}s"


def report_status(windows):
    remaining = [window["remaining_percent"] for window in windows if isinstance(window.get("remaining_percent"), (int, float))]
    if not remaining:
        return "high"
    lowest = min(remaining)
    if lowest == 0:
        return "exhausted"
    if lowest < 20:
        return "low"
    if lowest < 50:
        return "medium"
    return "high"


def normalize_codex_usage(auth, usage):
    rate_limit = usage.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise RuntimeError(t("Codex 사용량 정보가 없습니다: {v0}", v0=auth.get('email')))
    windows = []
    for key_name in ("primary_window", "secondary_window"):
        source = rate_limit.get(key_name)
        if source is None:
            continue
        used = source.get("used_percent")
        seconds = source.get("limit_window_seconds")
        if not isinstance(used, (int, float)):
            raise RuntimeError(t("Codex 사용량 값이 올바르지 않습니다: {v0}", v0=auth.get('email')))
        used = max(0.0, min(100.0, float(used)))
        reset_at = iso_from_epoch(source.get("reset_at"))
        windows.append(
            {
                "id": str(seconds),
                "label": duration_label(seconds),
                "used_value": used,
                "remaining_percent": 100.0 - used,
                "reset_at": reset_at,
                "reset_label": local_label(reset_at),
            }
        )
    if not windows:
        raise RuntimeError(t("Codex 사용량 윈도우가 없습니다: {v0}", v0=auth.get('email')))
    auth_index = auth.get("auth_index")
    email = auth.get("email") or auth.get("account") or auth_index
    name = auth.get("name") or auth_index
    if not all(isinstance(value, str) and value for value in (auth_index, email, name)):
        raise RuntimeError(t("Codex 인증 계정 정보가 올바르지 않습니다."))
    return {
        "account_id": auth_index,
        "auth_index": auth_index,
        "email": email,
        "name": name,
        "plan_type": str(usage.get("plan_type") or auth.get("plan_type") or (auth.get("id_token") or {}).get("plan_type") or auth.get("account_type") or "codex"),
        "provider": "codex",
        "priority": auth.get("priority", 0),
        "status": report_status(windows),
        "windows": windows,
    }


def normalize_reset_credits(payload):
    credits = payload.get("credits")
    count = payload.get("available_count")
    if not isinstance(credits, list) or not isinstance(count, int) or isinstance(count, bool):
        raise RuntimeError(t("Codex 리셋권 응답 형식이 올바르지 않습니다."))
    expires = []
    for credit in credits:
        if not isinstance(credit, dict):
            raise RuntimeError(t("Codex 리셋권 항목 형식이 올바르지 않습니다."))
        if credit.get("status") != "available":
            continue
        expiry = credit.get("expires_at")
        parsed = parse_time(expiry)
        if parsed is None or parsed.tzinfo is None:
            raise RuntimeError(t("Codex 리셋권 만기일이 올바르지 않습니다."))
        expires.append(expiry)
    if count != len(expires):
        raise RuntimeError(t("Codex 리셋권 수와 만기일 수가 일치하지 않습니다."))
    return sorted(expires, key=parse_time)


def claude_plan_type(profile):
    organization = profile.get("organization")
    if not isinstance(organization, dict):
        raise RuntimeError(t("Claude 프로필에 조직 정보가 없습니다."))
    plan = organization.get("organization_type")
    if not isinstance(plan, str) or not plan:
        raise RuntimeError(t("Claude 프로필에 플랜 정보가 없습니다."))
    tier = organization.get("rate_limit_tier")
    if plan == "claude_max":
        return {"default_claude_max_20x": "max_20x", "default_claude_max_5x": "max_5x"}.get(tier, "max")
    return plan.removeprefix("claude_")


def normalize_claude_usage(auth, usage):
    windows = []
    for key_name, label in (("five_hour", "5h"), ("seven_day", "7d")):
        source = usage.get(key_name)
        if not isinstance(source, dict) or not isinstance(source.get("utilization"), (int, float)):
            raise RuntimeError(t("Claude {v0} 사용량 정보가 없습니다: {v1}", v0=label, v1=auth.get('email')))
        used = max(0.0, min(100.0, float(source["utilization"])))
        reset_at = source.get("resets_at")
        if reset_at is not None and parse_time(reset_at) is None:
            raise RuntimeError(t("Claude {v0} 초기화 시각이 올바르지 않습니다: {v1}", v0=label, v1=auth.get('email')))
        windows.append(
            {
                "id": key_name,
                "label": label,
                "used_value": used,
                "remaining_percent": 100.0 - used,
                "reset_at": reset_at,
                "reset_label": local_label(reset_at),
            }
        )
    auth_index = auth.get("auth_index")
    email = auth.get("email") or auth.get("account")
    name = auth.get("name") or email
    if not all(isinstance(value, str) and value for value in (auth_index, email, name)):
        raise RuntimeError(t("Claude 인증 계정 정보가 올바르지 않습니다."))
    return {
        "account_id": auth_index,
        "auth_index": auth_index,
        "email": email,
        "name": name,
        "plan_type": auth.get("plan_type") or "unknown",
        "provider": "claude",
        "status": report_status(windows),
        "windows": windows,
    }


def normalize_openrouter_usage(provider, key_info, observed_requests, observation_complete, observed_at):
    auth_index = provider.get("auth_index")
    name = provider.get("name")
    prefix = provider.get("prefix")
    if not all(isinstance(value, str) and value for value in (auth_index, name)):
        raise RuntimeError(t("OpenRouter provider 정보가 올바르지 않습니다."))
    if prefix is not None and not isinstance(prefix, str):
        raise RuntimeError(t("OpenRouter provider prefix 정보가 올바르지 않습니다."))
    is_free_tier = key_info.get("is_free_tier")
    if not isinstance(is_free_tier, bool):
        raise RuntimeError(t("OpenRouter 무료 티어 정보가 없습니다."))
    if observed_at.tzinfo is None:
        raise RuntimeError(t("OpenRouter 관측 시각에는 timezone이 필요합니다."))
    observed_at = observed_at.astimezone(timezone.utc)
    day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day = day_start.replace(tzinfo=timezone.utc) + timedelta(days=1)
    limit_count = 50 if is_free_tier else 1000
    provider_name = f"{name}/{prefix}" if prefix else name
    display_name = f"{provider_name} · {auth_index}"
    remaining = None
    if observation_complete:
        remaining = max(0.0, min(100.0, (limit_count - observed_requests) * 100.0 / limit_count))
    windows = [
        {
            "id": "free-daily",
            "label": "1d free",
            "used_value": observed_requests,
            "used_count": observed_requests,
            "limit_count": limit_count,
            "observation_complete": observation_complete,
            "remaining_percent": remaining,
            "cycle_id": day_start.date().isoformat(),
            "cycle_started_at": day_start.isoformat().replace("+00:00", "Z"),
            "reset_at": next_day.isoformat().replace("+00:00", "Z"),
            "reset_label": local_label(next_day.isoformat().replace("+00:00", "Z")),
        }
    ]
    return {
        "account_id": auth_index,
        "auth_index": auth_index,
        "email": display_name,
        "name": f"{name}-{auth_index}",
        "plan_type": "free" if is_free_tier else "credits",
        "provider": "openrouter",
        "status": report_status(windows),
        "windows": windows,
    }


def format_event(event):
    exact_at = event.get("exact_at")
    if exact_at:
        return local_label(exact_at)
    before = parse_time(event.get("observed_before"))
    after = parse_time(event.get("observed_after"))
    if before is None or after is None:
        raise RuntimeError(t("초기화 관측 이력 형식이 올바르지 않습니다."))
    before_local = before.astimezone()
    after_local = after.astimezone()
    if before_local.date() == after_local.date():
        return t("{v0:%m-%d} {v1:%H:%M}~{v2:%H:%M} 관측", v0=after_local, v1=before_local, v2=after_local)
    return t("{v0:%m-%d %H:%M}~{v1:%m-%d %H:%M} 관측", v0=before_local, v1=after_local)


def apply_reset_history(reports, state, observed_at):
    if observed_at.tzinfo is None:
        raise RuntimeError(t("관측 시각에는 timezone이 필요합니다."))
    observed_at = observed_at.astimezone(timezone.utc)
    windows_state = state.setdefault("windows", {})
    for report in reports:
        provider = report.get("provider")
        account_id = report.get("account_id")
        if report.get("stale"):
            for window in report.get("windows", []):
                record = windows_state.get(f"{provider}:{account_id}:{window.get('id')}", {})
                event = record.get("last_reset")
                window["last_reset_label"] = format_event(event) if isinstance(event, dict) else t("초기화 관측 없음")
            continue
        for window in report.get("windows", []):
            window_id = window.get("id")
            used_value = window.get("used_value")
            if not isinstance(used_value, (int, float)):
                raise RuntimeError(t("초기화 관측용 사용량 값이 올바르지 않습니다."))
            state_key = f"{provider}:{account_id}:{window_id}"
            record = windows_state.setdefault(state_key, {})
            previous = record.get("observation")
            if isinstance(previous, dict):
                previous_used = previous.get("used_value")
                previous_seen = parse_time(previous.get("observed_at"))
                previous_reset = parse_time(previous.get("reset_at"))
                current_reset = parse_time(window.get("reset_at"))
                cycle_changed = previous.get("cycle_id") != window.get("cycle_id")
                reset_changed = previous.get("reset_at") != window.get("reset_at") or cycle_changed
                boundary_crossed = (
                    previous_seen is not None
                    and previous_reset is not None
                    and previous_seen <= previous_reset <= observed_at
                    and reset_changed
                )
                usage_reset = isinstance(previous_used, (int, float)) and used_value < previous_used and reset_changed
                if previous_seen is not None and (boundary_crossed or usage_reset):
                    exact_at = None
                    if boundary_crossed:
                        exact_at = previous.get("reset_at")
                    cycle_started_at = parse_time(window.get("cycle_started_at"))
                    if exact_at is None and cycle_started_at is not None and previous_seen <= cycle_started_at <= observed_at:
                        exact_at = window.get("cycle_started_at")
                    record["last_reset"] = {
                        "exact_at": exact_at,
                        "observed_before": previous.get("observed_at"),
                        "observed_after": observed_at.isoformat().replace("+00:00", "Z"),
                    }
            record["observation"] = {
                "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
                "used_value": used_value,
                "reset_at": window.get("reset_at"),
                "cycle_id": window.get("cycle_id"),
            }
            event = record.get("last_reset")
            window["last_reset_label"] = format_event(event) if isinstance(event, dict) else t("초기화 관측 없음")


def load_state():
    if not STATE_PATH.exists():
        return {}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise RuntimeError(t("사용량 이력 파일 형식이 올바르지 않습니다: {v0}", v0=STATE_PATH))
    return state


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=STATE_PATH.parent, delete=False) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = handle.name
    os.replace(temporary_path, STATE_PATH)


def active_auths(key):
    payload = management_request(key, "/v8/management/credentials")
    files = payload.get("files")
    if not isinstance(files, list):
        raise RuntimeError(t("CLIProxyAPI 인증 목록 형식이 올바르지 않습니다."))
    return [row for row in files if not row.get("disabled")]


def set_codex_order(auth_indices):
    key = management_key()
    auths = [row for row in active_auths(key) if row.get("provider") == "codex"]
    current = {row.get("auth_index"): row for row in auths}
    if not auth_indices or len(auth_indices) != len(current) or set(auth_indices) != set(current):
        raise RuntimeError(t("Codex 계정 목록이 바뀌었습니다. 새로고침한 뒤 다시 저장하세요."))
    if not all(isinstance(auth.get("id"), str) and auth["id"] for auth in auths):
        raise RuntimeError(t("Codex 계정 저장용 ID가 없습니다."))
    strategy = management_request(key, "/v8/management/config/routing/strategy")
    if strategy != "fill-first":
        raise RuntimeError(t("계정 순서를 적용하려면 CLIProxy routing.strategy가 fill-first여야 합니다."))
    changed = []
    try:
        for priority, auth_index in zip(range(len(auth_indices), 0, -1), auth_indices):
            auth = current[auth_index]
            changed.append(auth)
            result = management_request(
                key, "/v8/management/credentials/fields",
                {"name": auth["id"], "priority": priority}, method="PATCH",
            )
            if result.get("status") != "ok":
                raise RuntimeError(t("Codex 계정 우선순위 저장에 실패했습니다."))
    except Exception as error:
        restore_errors = []
        for auth in reversed(changed):
            try:
                result = management_request(
                    key, "/v8/management/credentials/fields",
                    {"name": auth["id"], "priority": auth.get("priority", 0)}, method="PATCH",
                )
                if result.get("status") != "ok":
                    raise RuntimeError(t("이전 우선순위 복원 실패"))
            except Exception as restore_error:
                restore_errors.append(str(restore_error))
        if restore_errors:
            raise RuntimeError(t("순서 저장 실패, 이전 순서 복원도 실패했습니다: ") + "; ".join(restore_errors)) from error
        raise


def codex_reports(key, auths):
    reports = []
    for auth in (row for row in auths if row.get("provider") == "codex"):
        auth_index = auth.get("auth_index")
        account_id = auth.get("account")
        if not all(isinstance(value, str) and value for value in (auth_index, account_id)):
            raise RuntimeError(t("Codex 인증 계정 정보가 올바르지 않습니다."))
        usage = api_call(
            key,
            auth_index,
            "https://chatgpt.com/backend-api/wham/usage",
            {
                "Authorization": "Bearer $TOKEN$",
                "Accept": "application/json",
                "ChatGPT-Account-Id": account_id,
                "User-Agent": "codex-cli/0.1.0",
            },
        )
        report = normalize_codex_usage(auth, usage)
        try:
            credits = api_call(
                key, auth_index,
                "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits",
                {
                    "Authorization": "Bearer $TOKEN$",
                    "Accept": "application/json",
                    "ChatGPT-Account-ID": account_id,
                    "OpenAI-Beta": "codex-1",
                    "originator": "Codex Desktop",
                },
            )
            report["reset_credit_expiries"] = normalize_reset_credits(credits)
        except Exception as error:
            report["reset_credits_error"] = str(error)
        reports.append(report)
    return reports


def cached_claude_report(auth, state, retry_at):
    auth_index = auth["auth_index"]
    windows_state = state.get("windows", {})
    cached_usage = {}
    observed_at = []
    for state_window, usage_window in (("five_hour", "five_hour"), ("seven_day", "seven_day")):
        record = windows_state.get(f"claude:{auth_index}:{state_window}", {})
        observation = record.get("observation", {})
        used = observation.get("used_value")
        if not isinstance(used, (int, float)):
            return None
        cached_usage[usage_window] = {
            "utilization": used,
            "resets_at": observation.get("reset_at"),
        }
        seen_at = parse_time(observation.get("observed_at"))
        if seen_at is not None:
            observed_at.append(seen_at)
    report = normalize_claude_usage({**auth, "plan_type": state.get("claude_plans", {}).get(auth_index)}, cached_usage)
    report["stale"] = True
    report["stale_as_of"] = min(observed_at).isoformat().replace("+00:00", "Z") if observed_at else None
    report["retry_at"] = retry_at.isoformat().replace("+00:00", "Z")
    return report


def claude_reports(key, auths, state, observed_at):
    reports = []
    errors = []
    retry_state = state.setdefault("claude_retry_after", {})
    if not isinstance(retry_state, dict):
        raise RuntimeError(t("Claude 재시도 대기 상태 형식이 올바르지 않습니다."))
    for auth in (row for row in auths if row.get("provider") == "claude"):
        auth_index = auth.get("auth_index")
        if not isinstance(auth_index, str) or not auth_index:
            raise RuntimeError(t("Claude 인증 계정 정보가 올바르지 않습니다."))
        retry_at = parse_time(retry_state[auth_index]) if auth_index in retry_state else None
        if retry_at is not None and observed_at < retry_at:
            cached = cached_claude_report(auth, state, retry_at)
            if cached is not None:
                reports.append(cached)
            remaining = max(0, int((retry_at - observed_at).total_seconds()))
            errors.append(
                {
                    "provider": "claude",
                    "message": t("Anthropic HTTP 429 대기 중: {v0}초 후 재조회", v0=remaining),
                    "rate_limited": True,
                }
            )
            continue
        if retry_at is not None:
            retry_state.pop(auth_index, None)
        try:
            usage = api_call(
                key,
                auth_index,
                "https://api.anthropic.com/api/oauth/usage",
                {
                    "Authorization": "Bearer $TOKEN$",
                    "Accept": "application/json",
                    "anthropic-beta": "oauth-2025-04-20",
                    "User-Agent": "claude-code/2.1.0",
                },
            )
        except RateLimitedError as error:
            delay = error.retry_after_seconds
            if delay is None:
                delay = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
            retry_at = observed_at + timedelta(seconds=delay)
            retry_state[auth_index] = retry_at.isoformat().replace("+00:00", "Z")
            cached = cached_claude_report(auth, state, retry_at)
            if cached is not None:
                reports.append(cached)
            errors.append(
                {
                    "provider": "claude",
                    "message": t("Anthropic HTTP 429 대기 중: {v0}초 후 재조회", v0=delay),
                    "rate_limited": True,
                }
            )
            continue
        report = normalize_claude_usage(auth, usage)
        try:
            profile = api_call(key, auth_index, "https://api.anthropic.com/api/oauth/profile", {
                "Authorization": "Bearer $TOKEN$",
                "Accept": "application/json",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "claude-code/2.1.0",
            })
            report["plan_type"] = claude_plan_type(profile)
            state.setdefault("claude_plans", {})[auth_index] = report["plan_type"]
        except Exception as error:
            errors.append({"provider": "claude", "plan_lookup_failed": True, "message": str(error)})
        reports.append(report)
    return reports, errors


def recent_day_count(entry, observed_at):
    buckets = entry.get("recent_requests")
    if not isinstance(buckets, list) or not buckets:
        return 0, False
    observed_at = observed_at.astimezone(timezone.utc)
    day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    current_bucket = int(observed_at.timestamp()) // 600
    oldest_start = datetime.fromtimestamp((current_bucket - len(buckets) + 1) * 600, timezone.utc)
    complete = oldest_start <= day_start
    count = 0
    for index, bucket in enumerate(buckets):
        bucket_start = datetime.fromtimestamp((current_bucket - len(buckets) + 1 + index) * 600, timezone.utc)
        if bucket_start < day_start:
            continue
        success = bucket.get("success")
        failed = bucket.get("failed")
        if not isinstance(success, int) or not isinstance(failed, int):
            raise RuntimeError(t("OpenRouter 최근 요청 통계 형식이 올바르지 않습니다."))
        count += success + failed
    return count, complete


def openrouter_reports(key, observed_at):
    # v8 설정 응답에는 사용량 조회에 필요한 런타임 auth-index가 없다.
    compatibility = management_request(key, "/v0/management/openai-compatibility")
    providers = compatibility.get("openai-compatibility")
    if not isinstance(providers, list):
        raise RuntimeError(t("CLIProxyAPI OpenAI 호환 provider 목록 형식이 올바르지 않습니다."))
    usage = management_request(key, "/v8/management/observability/usage/api-keys")
    provider_usage = usage.get("openrouter", {})
    if not isinstance(provider_usage, dict):
        raise RuntimeError(t("CLIProxyAPI OpenRouter 요청 통계 형식이 올바르지 않습니다."))
    reports = []
    for provider in (row for row in providers if row.get("name") == "openrouter"):
        entries = provider.get("api-key-entries")
        if not isinstance(entries, list):
            raise RuntimeError(t("OpenRouter API key 목록 형식이 올바르지 않습니다."))
        for entry in entries:
            auth_index = entry.get("auth-index")
            api_key = entry.get("api-key")
            if not all(isinstance(value, str) and value for value in (auth_index, api_key)):
                raise RuntimeError(t("OpenRouter API key 정보가 올바르지 않습니다."))
            usage_entry = next((value for composite, value in provider_usage.items() if composite.endswith(f"|{api_key}")), None)
            if not isinstance(usage_entry, dict):
                raise RuntimeError(t("OpenRouter 요청 통계를 찾을 수 없습니다: {v0}", v0=auth_index))
            count, complete = recent_day_count(usage_entry, observed_at)
            key_payload = api_call(
                key,
                auth_index,
                "https://openrouter.ai/api/v1/key",
                {"Authorization": "Bearer $TOKEN$", "Accept": "application/json"},
            )
            key_info = key_payload.get("data")
            if not isinstance(key_info, dict):
                raise RuntimeError(t("OpenRouter API key 사용량 정보가 없습니다."))
            reports.append(
                normalize_openrouter_usage(
                    {"name": provider["name"], "prefix": provider.get("prefix"), "auth_index": auth_index},
                    key_info,
                    count,
                    complete,
                    observed_at,
                )
            )
    return reports


def collect_reports():
    key = management_key()
    state = load_state()
    observed_at = datetime.now(timezone.utc)
    auths = active_auths(key)
    reports = []
    errors = []
    for provider, collect in (
        ("codex", lambda: codex_reports(key, auths)),
        ("claude", lambda: claude_reports(key, auths, state, observed_at)),
        ("openrouter", lambda: openrouter_reports(key, observed_at)),
    ):
        try:
            result = collect()
            if provider == "claude":
                claude_data, claude_errors = result
                reports.extend(claude_data)
                errors.extend(claude_errors)
            else:
                reports.extend(result)
        except Exception as error:
            errors.append({"provider": provider, "message": str(error), "authentication_required": isinstance(error, UpstreamError) and error.status_code in (401, 403)})
    apply_reset_history(reports, state, observed_at)
    save_state(state)
    if not reports:
        detail = "; ".join(f"{error['provider']}: {error['message']}" for error in errors)
        raise RuntimeError(t("사용량을 불러오지 못했습니다: {v0}", v0=detail))
    return reports, errors


def reset_cooldowns():
    key = management_key()
    targets = [auth for auth in active_auths(key) if auth.get("unavailable") is True or auth.get("status") == "error"]
    if not targets:
        return t("쿨다운 상태인 계정이 없습니다.")
    for auth in targets:
        result = management_request(key, "/v8/management/routing/cooldown/reset", {"auth_index": auth["auth_index"]})
        if result.get("status") != "ok":
            raise RuntimeError(t("쿨다운 초기화에 실패했습니다."))
    return t("계정 {v0}개의 프록시 쿨다운을 초기화했습니다.", v0=len(targets))
