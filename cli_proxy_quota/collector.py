import fcntl
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from . import client, configuration
from .ledger import Ledger

RECORDING_PATH = "/v8/management/config/observability/usage/usage-statistics-enabled"
QUEUE_PATH = "/v8/management/observability/usage/queue?count=1000"
SAFE_FIELDS = ("execution_id", "timestamp", "provider", "auth_index", "model", "response_model", "failed", "token_breakdown")


class Collector:
    def __init__(self, directory):
        self.key = client.management_key()
        self.management_origin = configuration.load_settings()["base_url"]
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.lock_file = open(self.directory / "collector.lock", "a+")
        os.chmod(self.lock_file.name, 0o600)
        try:
            # ponytail: local lock; add a server lease before supporting multiple collector hosts.
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            raise RuntimeError("Another CLIProxy-quota collector is already running") from None
        self.ledger = Ledger(self.directory / "usage.sqlite3")
        self.pending = self.directory / "pending-usage.json"
        self.stop = threading.Event()
        self.guard = threading.RLock()
        self.threads = []
        self.run_id = None
        self.status = {"recording": None, "started_at": None, "last_collected_at": None, "error": None,
                       "quota_updated_at": None, "quota_error": None, "running": True}
        self.reports = []
        self.errors = []

    def persist_batch(self, records):
        if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
            raise ValueError("Invalid usage queue response")
        safe = [{key: record[key] for key in SAFE_FIELDS if key in record} for record in records]
        with tempfile.NamedTemporaryFile("w", dir=self.directory, delete=False, encoding="utf-8") as handle:
            json.dump(safe, handle)
            handle.flush()
            os.fsync(handle.fileno())
            name = handle.name
        os.replace(name, self.pending)
        self.replay_pending()

    def replay_pending(self):
        if self.pending.exists():
            records = json.loads(self.pending.read_text(encoding="utf-8"))
            self.ledger.append(records)
            self.pending.unlink()

    def collect_once(self):
        self.replay_pending()
        recording = client.management_request(self.key, RECORDING_PATH)
        if not isinstance(recording, bool):
            raise ValueError("Invalid recording setting")
        with self.guard:
            self.status["recording"] = recording
        if not recording:
            return
        if self.run_id is None:
            now = time.time()
            self.run_id = self.ledger.start_collection(now)
            with self.guard:
                self.status["started_at"] = now
        for _ in range(5):
            records = client.management_request(self.key, QUEUE_PATH)
            self.persist_batch(records)
            if len(records) < 1000:
                break
        now = time.time()
        self.ledger.mark_collected(self.run_id, now)
        with self.guard:
            self.status.update(last_collected_at=now, error=None)

    def usage_loop(self):
        delay = 5
        while not self.stop.is_set():
            try:
                self.collect_once()
                delay = 5
            except Exception as error:
                with self.guard:
                    self.status["error"] = str(error)
                self.run_id = None
                delay = min(delay * 2, 30)
            self.stop.wait(delay)

    def quota_loop(self):
        while not self.stop.is_set():
            try:
                reports, errors = client.collect_reports()
                with self.guard:
                    order = {"codex": 0, "claude": 1, "openrouter": 2}
                    reports.sort(key=lambda report: (order[report["provider"]], -report.get("priority", 0)))
                    self.reports, self.errors = reports, errors
                    self.status.update(quota_updated_at=time.time(), quota_error=None)
            except Exception as error:
                with self.guard:
                    self.status["quota_error"] = str(error)
            self.stop.wait(120)

    def start(self):
        for target in (self.usage_loop, self.quota_loop):
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread)
            thread.start()

    def snapshot(self):
        with self.guard:
            snapshot = json.loads(json.dumps({"status": self.status, "reports": self.reports, "errors": self.errors}))
        path = configuration.CONFIG_DIR / "aliases.json"
        aliases = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(aliases, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in aliases.items()):
            raise ValueError("Invalid account aliases")
        for report in snapshot["reports"]:
            report["alias"] = aliases.get(report["name"], "")
        return snapshot

    def enable_recording(self):
        result = client.management_request(self.key, RECORDING_PATH, True, method="PUT")
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise RuntimeError("Could not enable CLIProxy usage recording")
        with self.guard:
            self.status["recording"] = True
        return {"enabled": True}

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(35)
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError("Collector did not stop; retaining its lock")
        self.status["running"] = False
        self.lock_file.close()
