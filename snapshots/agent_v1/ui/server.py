"""Minimal web UI (plan 6.1/6.2) - Python standard library only, bound to 127.0.0.1.

    python -m ui.server            -> http://127.0.0.1:8000
    python -m ui.server --inproc   (no MCP subprocesses)
"""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
from agent import approval, audit
from agent.react_agent import HardwareAgent
from agent.tools import PERMISSIONS

STATIC = Path(__file__).parent / "static"
MAX_BODY = 10_000
AGENT: HardwareAgent | None = None
LOCK = threading.Lock()  # one agent / one MCP session pair -> serialize questions


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(data)

    def _json(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_BODY:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *a):  # keep console quiet
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
        if u.path == "/api/info":
            return self._send(200, {"llm": AGENT.llm.name, "tools": AGENT.hub.tool_names(),
                                    "owners": AGENT.hub.owner, "permissions": PERMISSIONS,
                                    "transport": AGENT.hub.transport})
        if u.path == "/api/audit":
            n = int(parse_qs(u.query).get("n", ["30"])[0])
            return self._send(200, audit.tail(min(n, 200)))
        if u.path == "/api/history":
            s = parse_qs(u.query).get("session", ["web"])[0][:64]
            return self._send(200, AGENT.episodic.history(s))
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc)})
        if self.path == "/api/ask":
            q = str(body.get("question", "")).strip()[:1000]
            if not q:
                return self._send(400, {"error": "empty question"})
            with LOCK:
                res = AGENT.ask(q, session_id=str(body.get("session_id", "web"))[:64])
            return self._send(200, res)
        if self.path == "/api/approve":
            return self._send(200, approval.decide(str(body.get("action_id", "")), bool(body.get("approve")),
                                                   approver="web-user"))
        self._send(404, {"error": "not found"})


def main():
    global AGENT
    ap = argparse.ArgumentParser()
    ap.add_argument("--inproc", action="store_true", help="Run MCP tools in-process")
    ap.add_argument("--stdio", action="store_true", help="Run MCP servers over stdio subprocesses")
    ap.add_argument("--port", type=int, default=config.PORT)
    args = ap.parse_args()
    transport = "inproc" if args.inproc else ("stdio" if args.stdio else config.MCP_TRANSPORT)
    AGENT = HardwareAgent(transport=transport)
    print(f"LLM: {AGENT.llm.name}\nTools: {AGENT.hub.tool_names()}\nOpen http://127.0.0.1:{args.port}")
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        AGENT.close()


if __name__ == "__main__":
    main()
