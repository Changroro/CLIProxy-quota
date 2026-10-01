import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cli_proxy_quota.dashboard import DashboardServer
from cli_proxy_quota.ledger import Ledger

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8320)
parser.add_argument("--session-file", type=Path, default=Path("/tmp/quota-dashboard-preview.json"))
args = parser.parse_args()

with tempfile.TemporaryDirectory() as directory:
    class Demo:
        ledger = Ledger(Path(directory) / "demo.sqlite3")
        reports = []
        def snapshot(self):
            return {"status": {"recording": True, "started_at": time.time()-12*86400,
                     "last_collected_at": time.time(), "quota_updated_at": time.time(), "quota_error": None,
                     "error": None, "running": True, "demo": True}, "reports": self.reports, "errors": []}
    worker = Demo()
    rows = []
    now = datetime.now(timezone.utc)
    for index, (provider, plan) in enumerate([("codex", "prolite"), ("codex", "team"), ("codex", "self_serve_business_prolite"), ("claude", "max_20x"), ("openrouter", "free")]):
        worker.reports.append({"provider": provider, "plan_type": plan, "email": f"demo-{index+1}@example.test", "name": f"demo-{index+1}", "auth_index": f"demo-{index+1}", "windows": [{"label": "5h", "remaining_percent": 87-index*18, "reset_at": (now+timedelta(hours=3)).isoformat()}, {"label": "7d", "remaining_percent": 69-index*13, "reset_at": (now+timedelta(days=4)).isoformat()}]})
        if provider == "openrouter":
            worker.reports[-1]["windows"] = [{"label": "1d free", "remaining_percent": None, "used_count": 12, "limit_count": 50}]
        for day in range(12):
            for hour in range(3):
                amount = 1200+(index+1)*(day+2)*83+hour*600
                output = 300+index*120+day*43
                cache = 250+hour*130
                rows.append({"execution_id": f"demo-{index}-{day}-{hour}", "timestamp": (now-timedelta(days=day, hours=hour)).isoformat(), "provider": provider, "auth_index": f"demo-{index+1}", "model": "gpt-5" if provider=="codex" else "claude-sonnet" if provider=="claude" else "free-model", "failed": (day+hour+index)%17==0,
                             "token_breakdown": {"schema_version": 2, "quality": "complete", "total_tokens": amount+output+cache, "unclassified_tokens": 0, "input": {"uncached_tokens": amount, "total_tokens": amount+cache, "cache_read_tokens": cache, "cache_write_tokens": 0}, "output": {"total_tokens": output, "non_reasoning_tokens": output, "reasoning_tokens": 0}}})
    worker.ledger.append(rows)
    run_id = worker.ledger.start_collection(time.time()-12*86400)
    worker.ledger.mark_collected(run_id,time.time())
    server = DashboardServer(args.port,worker)
    args.session_file.write_text(json.dumps({"url":server.base_url+'#token='+server.token}))
    args.session_file.chmod(0o600)
    print(f"Synthetic demo dashboard: {server.base_url}",flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        args.session_file.unlink(missing_ok=True)
