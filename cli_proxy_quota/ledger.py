from .i18n import t
import sqlite3
import math
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    requested_at REAL NOT NULL,
    provider TEXT NOT NULL,
    account_id TEXT NOT NULL,
    model TEXT NOT NULL,
    model_source TEXT NOT NULL CHECK (model_source IN ('reported', 'requested')),
    failed INTEGER NOT NULL CHECK (failed IN (0, 1)),
    token_source TEXT NOT NULL,
    input_tokens INTEGER CHECK (input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens >= 0),
    cache_read_tokens INTEGER CHECK (cache_read_tokens >= 0),
    cache_write_tokens INTEGER CHECK (cache_write_tokens >= 0),
    reasoning_tokens INTEGER CHECK (reasoning_tokens >= 0),
    total_tokens INTEGER CHECK (total_tokens >= 0)
);
CREATE INDEX IF NOT EXISTS executions_period ON executions(requested_at);
CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL,
    last_collected_at REAL
);
"""


def normalize_event(event):
    identity = [event.get(key) for key in ("execution_id", "provider", "auth_index")]
    model = event.get("response_model") or event.get("model")
    model_source = "reported" if event.get("response_model") else "requested"
    if not all(isinstance(value, str) and value for value in identity + [model]):
        raise ValueError(t("사용량 이벤트의 실행·계정·모델 정보가 없습니다."))
    moment = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(t("사용량 시각에는 시간대가 필요합니다."))
    failed = event.get("failed")
    if not isinstance(failed, bool):
        raise ValueError(t("사용량 이벤트의 성공 여부가 없습니다."))
    breakdown = event.get("token_breakdown")
    counters = [None] * 6
    source = "missing"
    if isinstance(breakdown, dict):
        source = breakdown.get("quality", "missing")
        if breakdown.get("schema_version") != 2:
            raise ValueError(t("지원하지 않는 토큰 집계 스키마입니다."))
        if source == "complete":
            inputs = breakdown["input"]
            outputs = breakdown["output"]
            counters = [
                inputs["uncached_tokens"], outputs["total_tokens"],
                inputs["cache_read_tokens"], inputs["cache_write_tokens"],
                outputs["reasoning_tokens"], breakdown["total_tokens"],
            ]
            if not all(type(value) is int and value >= 0 for value in counters + [
                inputs["total_tokens"], outputs["non_reasoning_tokens"], breakdown["unclassified_tokens"],
            ]):
                raise ValueError(t("토큰 집계 값이 올바르지 않습니다."))
            plain, output, read, write, reasoning, total = counters
            if (plain + read + write != inputs["total_tokens"]
                    or reasoning + outputs["non_reasoning_tokens"] != output
                    or total != plain + read + write + output
                    or breakdown.get("unclassified_tokens") != 0):
                raise ValueError(t("토큰 집계 합계가 일치하지 않습니다."))
        elif source not in ("inconsistent", "unclassified"):
            raise ValueError(t("알 수 없는 토큰 측정 상태입니다."))
    return (*identity[:1], moment.timestamp(), *identity[1:], model, model_source, int(failed), source, *counters)


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(SCHEMA)
        self.path.chmod(0o600)

    def append(self, events):
        rows = [normalize_event(event) for event in events]
        with closing(sqlite3.connect(self.path)) as db, db:
            before = db.total_changes
            db.executemany(
                "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(execution_id) DO NOTHING", rows,
            )
            return db.total_changes - before

    def filters(self, start, end, account=None, provider=None, model=None):
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (start, end)) or end <= start:
            raise ValueError("Invalid time range")
        where = "requested_at >= ? AND requested_at < ?"
        values = [start, end]
        for column, value in (("account_id", account), ("provider", provider), ("model", model)):
            if value is not None:
                if not isinstance(value, str) or not value:
                    raise ValueError("Invalid usage filter")
                where += f" AND {column} = ?"
                values.append(value)
        return where, values

    def summary(self, start, end, account=None, provider=None, model=None):
        where, values = self.filters(start, end, account, provider, model)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            result = db.execute(
                "SELECT COUNT(*) AS requests, SUM(failed) AS failures, "
                "COUNT(*) - COUNT(total_tokens) AS unmeasured, "
                "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
                "SUM(cache_read_tokens) AS cache_read_tokens, "
                "SUM(cache_write_tokens) AS cache_write_tokens, "
                "SUM(reasoning_tokens) AS reasoning_tokens, SUM(total_tokens) AS total_tokens "
                "FROM executions WHERE " + where, values,
            ).fetchone()
        return dict(result)

    def dashboard(self, start, end, account=None, provider=None, model=None, timezone="UTC"):
        where, values = self.filters(start, end, account, provider, model)
        try:
            zone = ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError, TypeError):
            raise ValueError("Invalid timezone") from None
        metrics = ("COUNT(*) AS requests, SUM(failed) AS failures, "
                   "COUNT(*) - COUNT(total_tokens) AS unmeasured, "
                   "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
                   "SUM(cache_read_tokens) AS cache_read_tokens, SUM(cache_write_tokens) AS cache_write_tokens, "
                   "SUM(reasoning_tokens) AS reasoning_tokens, "
                   "SUM(total_tokens) AS total_tokens")
        bucket = 3600 if end - start <= 2 * 86400 else 86400
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            db.create_function("local_day", 1, lambda moment: datetime.fromtimestamp(moment, zone).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            db.execute("BEGIN")
            summary = db.execute(f"SELECT {metrics} FROM executions WHERE {where}", values).fetchone()
            accounts = db.execute(f"SELECT provider, account_id, {metrics} FROM executions WHERE {where} GROUP BY provider, account_id ORDER BY total_tokens DESC", values).fetchall()
            daily = db.execute(f"SELECT local_day(requested_at) AS timestamp, {metrics} FROM executions WHERE {where} GROUP BY timestamp ORDER BY timestamp", values).fetchall()
            timeline = daily if bucket == 86400 else db.execute(f"SELECT CAST((requested_at - ?) / ? AS INTEGER) * ? + ? AS timestamp, {metrics} FROM executions WHERE {where} GROUP BY timestamp ORDER BY timestamp", [start, bucket, bucket, start, *values]).fetchall()
            models = [row[0] for row in db.execute("SELECT DISTINCT model FROM executions ORDER BY model")]
            coverage = db.execute("SELECT MIN(started_at) AS started_at, MAX(last_collected_at) AS last_collected_at FROM collection_runs").fetchone()
            runs = db.execute("SELECT started_at, last_collected_at FROM collection_runs ORDER BY started_at").fetchall()
        return {"summary": dict(summary), "accounts": [dict(row) for row in accounts],
                "timeline": [dict(row) for row in timeline], "daily": [dict(row) for row in daily], "models": models,
                "coverage": dict(coverage), "collection_runs": [dict(row) for row in runs], "bucket_seconds": bucket, "timezone": timezone}

    def start_collection(self, moment):
        with closing(sqlite3.connect(self.path)) as db, db:
            return db.execute("INSERT INTO collection_runs(started_at) VALUES (?)", [moment]).lastrowid

    def mark_collected(self, run_id, moment):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE collection_runs SET last_collected_at = ? WHERE id = ?", [moment, run_id])
