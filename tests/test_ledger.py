import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cli_proxy_quota.ledger import Ledger


def event(identifier):
    return {
        "execution_id": identifier, "request_id": "same-inbound-request",
        "timestamp": "2026-09-30T01:00:00Z", "provider": "codex",
        "auth_index": "account-1", "model": "requested", "response_model": "actual",
        "failed": False, "api_key": "NEVER_STORE_THIS_KEY",
        "token_breakdown": {
            "schema_version": 2, "quality": "complete", "total_tokens": 150,
            "unclassified_tokens": 0,
            "input": {"total_tokens": 120, "uncached_tokens": 80,
                      "cache_read_tokens": 30, "cache_write_tokens": 10},
            "output": {"total_tokens": 30, "non_reasoning_tokens": 20, "reasoning_tokens": 10},
        },
    }


class LedgerTest(unittest.TestCase):
    def test_execution_deduplication_account_filter_and_token_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "usage.sqlite")
            self.assertEqual(ledger.append([event("first"), event("second")]), 2)
            self.assertEqual(ledger.append([event("first")]), 0)
            result = ledger.summary(0, 2000000000, "account-1")
            self.assertEqual(result["requests"], 2)
            self.assertEqual(result["total_tokens"], 300)
            self.assertEqual(result["input_tokens"], 160)
            self.assertEqual(result["reasoning_tokens"], 20)
            self.assertEqual(result["unmeasured"], 0)
            self.assertEqual(ledger.summary(0, 2000000000, "other")["requests"], 0)
            self.assertNotIn(b"NEVER_STORE_THIS_KEY", ledger.path.read_bytes())
            with sqlite3.connect(ledger.path) as db:
                self.assertEqual(db.execute("SELECT model FROM executions LIMIT 1").fetchone()[0], "actual")

    def test_missing_tokens_are_not_reported_as_zero_and_invalid_batch_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "usage.sqlite")
            missing = event("missing")
            del missing["token_breakdown"]
            ledger.append([missing])
            result = ledger.summary(0, 2000000000)
            self.assertIsNone(result["total_tokens"])
            self.assertEqual(result["unmeasured"], 1)
            broken = copy.deepcopy(event("broken"))
            broken["token_breakdown"]["total_tokens"] = 160
            with self.assertRaises(ValueError):
                ledger.append([event("valid"), broken])
            self.assertEqual(ledger.summary(0, 2000000000)["requests"], 1)


if __name__ == "__main__":
    unittest.main()
