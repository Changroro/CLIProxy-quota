import argparse
import hmac
import json
import mimetypes
import secrets
import signal
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import configuration
from .collector import Collector
from .ledger import Ledger

WEB_DIR = Path(__file__).with_name("web")
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, collector):
        super().__init__(("127.0.0.1", port), DashboardHandler)
        self.collector = collector
        self.token = secrets.token_urlsafe(32)
        self.base_url = f"http://127.0.0.1:{self.server_port}"
        self.allowed_hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        self.cookie_name = f"quota_session_{self.server_port}"
        self.management_origin = getattr(collector, "management_origin", None)


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        ancestors = self.server.management_origin or "'none'"
        self.send_header("Content-Security-Policy", f"default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors {ancestors}")
        if self.management_bridge_origin():
            self.send_header("Access-Control-Allow-Origin", self.server.management_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Quota-Client")
        self.end_headers()
        self.wfile.write(body)

    def valid_origin(self):
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        return host in self.server.allowed_hosts and (origin is None or origin == f"http://{host}")

    def management_bridge_origin(self):
        return (urlsplit(self.path).path == "/api/management-session"
                and self.headers.get("Host") in self.server.allowed_hosts
                and self.server.management_origin is not None
                and self.headers.get("Origin") == self.server.management_origin)

    def do_OPTIONS(self):
        if (self.management_bridge_origin()
                and self.headers.get("Access-Control-Request-Method") == "POST"
                and set(self.headers.get("Access-Control-Request-Headers", "").lower().replace(" ", "").split(","))
                    <= {"authorization", "content-type", "x-quota-client"}):
            self.respond(204, b"", "text/plain")
        else:
            self.respond(403, {"error": "Invalid origin"})

    def authorized(self):
        if not self.valid_origin() or self.headers.get("X-Quota-Client") != "1":
            return False
        bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return False
        supplied = bearer or (cookie[self.server.cookie_name].value if self.server.cookie_name in cookie else "")
        return hmac.compare_digest(supplied.encode(), self.server.token.encode())

    def do_GET(self):
        if not self.valid_origin():
            self.respond(403, {"error": "Invalid origin"})
            return
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/api/"):
            if not self.authorized():
                self.respond(401, {"error": "Open the dashboard from the widget or CLI to sign in"})
                return
            try:
                if parsed.path == "/api/accounts":
                    self.respond(200, self.server.collector.snapshot())
                elif parsed.path == "/api/usage":
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if set(query) - {"start", "end", "account", "provider", "model", "timezone"} or any(len(values) != 1 for values in query.values()):
                        raise ValueError("Invalid query parameters")
                    start = float(query.get("start", ["0"])[0])
                    end = float(query.get("end", [str(time.time())])[0])
                    filters = {key: query[key][0] for key in ("account", "provider", "model", "timezone") if key in query}
                    data = self.server.collector.ledger.dashboard(start, end, **filters)
                    data.update(self.server.collector.snapshot())
                    data["range"] = {"start": start, "end": end}
                    self.respond(200, data)
                else:
                    self.respond(404, {"error": "Not found"})
            except (ValueError, TypeError) as error:
                self.respond(400, {"error": str(error)})
            except Exception:
                self.respond(500, {"error": "Could not query local usage history"})
            return
        paths = {"/": WEB_DIR / "index.html", "/app.js": WEB_DIR / "app.js", "/style.css": WEB_DIR / "style.css", "/i18n.js": WEB_DIR / "i18n.js"}
        for name in ("cliproxy.png", "codex-symbolic.svg", "claude-symbolic.svg", "openrouter-light.svg", "openrouter-dark.svg"):
            paths[f"/assets/{name}"] = ASSET_DIR / name
        path = paths.get(parsed.path)
        if path is None:
            self.respond(404, "Not found", "text/plain")
        else:
            self.respond(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def do_POST(self):
        bridge = self.management_bridge_origin()
        if not (self.valid_origin() or bridge) or self.headers.get("X-Quota-Client") != "1":
            self.respond(403, {"error": "Invalid origin"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 8192 or self.headers.get_content_type() != "application/json":
                raise ValueError("Invalid request body")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
        except (ValueError, TypeError):
            self.respond(400, {"error": "Invalid request body"})
            return
        if urlsplit(self.path).path == "/api/management-session":
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            expected = getattr(self.server.collector, "key", None)
            if (not bridge or not isinstance(expected, str) or not supplied
                    or not hmac.compare_digest(supplied.encode(), expected.encode())
                    or body.get("proxy_url") != self.server.management_origin):
                self.respond(401, {"error": "Management connection does not match this collector"})
                return
            self.respond(200, {"token": self.server.token})
        elif urlsplit(self.path).path == "/api/session":
            token = body.get("token")
            if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.server.token.encode()):
                self.respond(401, {"error": "Invalid dashboard token"})
                return
            self.send_response(200)
            self.send_header("Set-Cookie", f"{self.server.cookie_name}={self.server.token}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
        elif urlsplit(self.path).path == "/api/recording" and self.authorized():
            try:
                self.respond(200, self.server.collector.enable_recording())
            except Exception:
                self.respond(502, {"error": "Could not enable proxy usage recording"})
        else:
            self.respond(401, {"error": "Unauthorized"})


def main():
    parser = argparse.ArgumentParser(prog="cli-proxy-quota")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("dashboard")
    serve.add_argument("--port", type=int, default=8318)
    serve.add_argument("--no-open", action="store_true")
    usage = sub.add_parser("usage")
    usage.add_argument("--start", type=float, default=0)
    usage.add_argument("--end", type=float, default=time.time())
    usage.add_argument("--account")
    usage.add_argument("--timezone", default="UTC")
    sub.add_parser("open")
    sub.add_parser("open-history")
    args = parser.parse_args()
    if args.command == "open":
        webbrowser.open(configuration.management_url())
        return
    if args.command == "open-history":
        url = configuration.load_settings()["dashboard_url"]
        if not url:
            parser.error("Start the dashboard first")
        webbrowser.open(url)
        return
    if args.command == "usage":
        print(json.dumps(Ledger(configuration.STATE_DIR / "usage.sqlite3").dashboard(args.start, args.end, args.account, timezone=args.timezone), ensure_ascii=False))
        return
    if not 0 <= args.port <= 65535:
        parser.error("Invalid port")
    collector = Collector(configuration.STATE_DIR)
    server = None
    try:
        server = DashboardServer(args.port, collector)
        launch_url = server.base_url + "#token=" + server.token
        configuration.set_option("dashboard_url", launch_url)
        collector.start()
        def shutdown(*_args):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        if not args.no_open:
            webbrowser.open(configuration.management_url())
        print(f"CLIProxy-quota dashboard: {server.base_url}", flush=True)
        server.serve_forever()
    finally:
        if server:
            server.server_close()
        try:
            collector.close()
        finally:
            if server and configuration.stored_settings().get("dashboard_url") == server.base_url + "#token=" + server.token:
                configuration.set_option("dashboard_url", None)


if __name__ == "__main__":
    main()
