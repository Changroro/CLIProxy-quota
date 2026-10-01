import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from cli_proxy_quota import collector as collection
from cli_proxy_quota.dashboard import DashboardServer
from cli_proxy_quota.ledger import Ledger
from test_ledger import event


class DashboardTest(unittest.TestCase):
    def test_management_embed_checks_origin_key_and_proxy_without_opening_other_api_origins(self):
        with tempfile.TemporaryDirectory() as directory:
            class Companion:
                key = "test-management-key"
                management_origin = "http://127.0.0.1:8317"
                ledger = Ledger(Path(directory) / "usage.sqlite3")
            worker = Companion()
            server = DashboardServer(0, worker)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def call(path, origin=None, key=worker.key, proxy=worker.management_origin, method="POST"):
                    headers = {"Content-Type": "application/json", "X-Quota-Client": "1", "Authorization": "Bearer " + key}
                    if origin is not None:
                        headers["Origin"] = origin
                    if method == "OPTIONS":
                        headers.update({"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization, content-type, x-quota-client"})
                    body = json.dumps({"proxy_url": proxy}).encode() if method == "POST" else None
                    return urllib.request.urlopen(urllib.request.Request(server.base_url + path, headers=headers, data=body, method=method), timeout=3)
                with call("/api/management-session", worker.management_origin, method="OPTIONS") as response:
                    self.assertEqual(response.status, 204)
                    self.assertEqual(response.headers["Access-Control-Allow-Origin"], worker.management_origin)
                for origin, key, proxy, expected in [
                    ("http://attacker.invalid", worker.key, worker.management_origin, 403),
                    (worker.management_origin, "wrong", worker.management_origin, 401),
                    (worker.management_origin, worker.key, "http://other-proxy:8317", 401),
                    (None, worker.key, worker.management_origin, 401),
                ]:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        call("/api/management-session", origin, key, proxy)
                    self.assertEqual(error.exception.code, expected)
                with call("/api/management-session", worker.management_origin) as response:
                    self.assertEqual(json.load(response)["token"], server.token)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    call("/api/usage", worker.management_origin, method="GET")
                self.assertEqual(error.exception.code, 403)
                with urllib.request.urlopen(server.base_url) as response:
                    self.assertIn("frame-ancestors " + worker.management_origin, response.headers["Content-Security-Policy"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_collector_persists_local_and_remote_client_usage_equally(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collection.client, "management_key", return_value="test"), patch.object(collection.configuration, "load_settings", return_value={"base_url": "http://127.0.0.1:8317"}):
            worker = collection.Collector(directory)
            try:
                local, remote = event("local-client"), event("remote-client")
                local["client_ip"] = "127.0.0.1"
                remote["client_ip"] = "203.0.113.5"
                worker.persist_batch([local, remote])
                summary = worker.ledger.summary(0, 2000000000)
                self.assertEqual(summary["requests"], 2)
                self.assertEqual(summary["total_tokens"], 300)
            finally:
                worker.close()

    def test_filters_totals_and_chart_buckets_share_the_same_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "usage.sqlite3")
            first, second, missing = event("a"), event("b"), event("c")
            second.update(auth_index="account-2", provider="claude", response_model="other", failed=True)
            missing.update(auth_index="account-2", timestamp="2026-10-01T01:00:00Z")
            del missing["token_breakdown"]
            ledger.append([first, second, missing])
            result = ledger.dashboard(1790700000, 1791000000)
            self.assertEqual(result["summary"]["requests"], 3)
            self.assertEqual(sum(row["requests"] for row in result["accounts"]), 3)
            self.assertEqual(sum(row["requests"] for row in result["daily"]), 3)
            self.assertEqual(result["summary"]["total_tokens"], 300)
            self.assertEqual(result["summary"]["unmeasured"], 1)
            filtered = ledger.dashboard(1790700000, 1791000000, account="account-2", provider="claude", model="other")
            self.assertEqual(filtered["summary"]["requests"], 1)
            self.assertEqual(filtered["summary"]["failures"], 1)
            self.assertEqual(filtered["accounts"][0]["total_tokens"], 150)
            with self.assertRaises(ValueError):
                ledger.dashboard(float("nan"), 100)
            with self.assertRaises(ValueError):
                ledger.dashboard(100, 0)

    def test_calendar_day_buckets_follow_the_requested_timezone(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "usage.sqlite3")
            first, second = event("before-midnight"), event("after-midnight")
            first["timestamp"] = "2026-09-30T14:00:00Z"
            second["timestamp"] = "2026-09-30T16:00:00Z"
            ledger.append([first, second])
            self.assertEqual(len(ledger.dashboard(1790700000, 1791000000, timezone="UTC")["daily"]), 1)
            self.assertEqual(len(ledger.dashboard(1790700000, 1791000000, timezone="Asia/Seoul")["daily"]), 2)
            with self.assertRaises(ValueError):
                ledger.dashboard(0, 100, timezone="Not/A/Timezone")

    def test_collector_lock_replay_and_secrets_exclusion_without_live_queue(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collection.client, "management_key", return_value="test"), patch.object(collection.configuration, "load_settings", return_value={"base_url": "http://127.0.0.1:8317"}):
            worker = collection.Collector(directory)
            try:
                with self.assertRaises(RuntimeError):
                    collection.Collector(directory)
                raw = event("safe")
                with patch.object(worker.ledger, "append", side_effect=RuntimeError("disk failed")):
                    with self.assertRaises(RuntimeError):
                        worker.persist_batch([raw])
                self.assertNotIn("NEVER_STORE_THIS_KEY", worker.pending.read_text())
                self.assertEqual(worker.pending.stat().st_mode & 0o777, 0o600)
                worker.replay_pending()
                self.assertFalse(worker.pending.exists())
                self.assertEqual(worker.ledger.summary(0, 2000000000)["requests"], 1)
                with patch.object(collection.client, "management_request", return_value=False) as request:
                    worker.collect_once()
                    request.assert_called_once_with("test", collection.RECORDING_PATH)
            finally:
                worker.close()

    def test_local_api_requires_session_and_rejects_cross_origin_and_invalid_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            class FakeCollector:
                ledger = Ledger(Path(directory) / "usage.sqlite3")
                def snapshot(self):
                    return {"reports": [{"windows": [{"reset_at": None, "last_reset_event": None}]}], "errors": [], "status": {"quota_error": None, "quota_updated_at": 1790722800}}
            server = DashboardServer(0, FakeCollector())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, headers=None, body=None):
                    req = urllib.request.Request(server.base_url + path, headers={"X-Quota-Client": "1", **(headers or {})}, data=None if body is None else json.dumps(body).encode())
                    return urllib.request.urlopen(req, timeout=3)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("/api/usage")
                self.assertEqual(error.exception.code, 401)
                with request("/api/session", {"Content-Type": "application/json"}, {"token": server.token}) as response:
                    cookie = response.headers["Set-Cookie"]
                    self.assertIn("HttpOnly", cookie)
                    self.assertIn("SameSite=Strict", cookie)
                from cli_proxy_quota import widget
                from cli_proxy_quota.i18n import set_language
                set_language("ko")
                with patch.object(widget.configuration, "load_settings", return_value={"dashboard_url": server.base_url + "#token=" + server.token}):
                    reports, errors = widget.load_reports()
                self.assertFalse(errors)
                self.assertEqual(reports[0]["quota_observed_at"], 1790722800)
                self.assertEqual(reports[0]["windows"][0]["last_reset_label"], "초기화 관측 없음")
                headers = {"Cookie": cookie.split(";", 1)[0]}
                with request("/api/usage?start=0&end=2000000000", headers) as response:
                    self.assertEqual(json.load(response)["summary"]["requests"], 0)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("/api/usage?start=nan", headers)
                self.assertEqual(error.exception.code, 400)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("/api/usage", {**headers, "Origin": "http://attacker.invalid"})
                self.assertEqual(error.exception.code, 403)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("/api/usage", {**headers, "Host": "attacker.invalid"})
                self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
