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
from agent.runtime.hitl import ResumeError
from agent.runtime.run_api import RunService
from agent.tools import PERMISSIONS

STATIC = Path(__file__).parent / "static"
MAX_BODY = 10_000
AGENT: HardwareAgent | None = None
RUNS: RunService | None = None  # Run API của runtime v2 (P5): tạo lười ở lần gọi /api/runs đầu tiên
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

    def _runs(self):
        global RUNS
        if RUNS is None:
            from agent.runtime.factory import build_runtime
            transport = "inproc" if AGENT is None else AGENT.hub.transport
            base = build_runtime(transport=transport)
            RUNS = RunService(base, factory=lambda codes: build_runtime(transport=transport, ablations=codes, checkpoint_db=base.store.path))
        return RUNS

    def _runs_get(self, u):
        parts = [p for p in u.path.split("/") if p]                      # api runs <id> [events]
        svc = self._runs()
        try:
            if len(parts) == 3:
                return self._send(200, svc.get(parts[2]))
            if len(parts) == 4 and parts[3] == "events":
                q = parse_qs(u.query)
                after = int(q.get("after", ["0"])[0])
                if "text/event-stream" in self.headers.get("Accept", "") or q.get("stream"):
                    return self._sse(svc, parts[2], after)
                return self._send(200, svc.events(parts[2], after))
        except KeyError as exc:
            return self._send(404, {"error": str(exc)})
        self._send(404, {"error": "not found"})

    def _sse(self, svc, run_id, after):
        """Server-Sent Events: đẩy sự kiện mới theo `seq` (đọc từ checkpoint) cho tới khi run xong / chờ người / hết 120 s."""
        import time
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        end = time.time() + 120
        while time.time() < end:
            ev = svc.events(run_id, after)
            for e in ev["events"]:
                self.wfile.write(f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False, default=str)}\n\n".encode())
            self.wfile.flush()
            after = ev["next"]
            if ev["status"] != "running":
                self.wfile.write(f"event: status\ndata: {json.dumps({'status': ev['status']})}\n\n".encode())
                self.wfile.flush()
                return
            time.sleep(0.25)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/runs/"):
            return self._runs_get(u)
        if u.path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
        if u.path in ("/demo_scenarios.json", "/api/demo_scenarios"):
            p = STATIC / "demo_scenarios.json"
            return self._send(200, p.read_bytes(), "application/json") if p.exists() else self._send(404, {"error": "demo_scenarios.json not found"})
        if u.path == "/api/workspace":
            files = []
            if config.SANDBOX_DIR.exists():
                for f in sorted(config.SANDBOX_DIR.iterdir()):
                    if f.is_file() and not f.name.startswith("."):
                        files.append({"name": f.name, "bytes": f.stat().st_size, "content": f.read_text(encoding="utf-8", errors="replace")[:20000]})
            return self._send(200, {"dir": str(config.SANDBOX_DIR), "files": files})
        if u.path == "/api/info":
            all_tools = list(dict.fromkeys([*AGENT.hub.tool_names(), *PERMISSIONS.keys()]))
            owners = {**{k: ("control" if v == "control" else ("local-guarded" if v == "irreversible-write" else "board-state" if k in ("get_board_state","get_power_budget","run_drc","diff","set_target","set_requirements","allocate_pin","release_pin","set_clock_config","add_device","connect","record_decision","rollback") else "hw-sandbox" if k in ("solve_timer_config","simulate_register_writes","analyze_c_code","compile_check") else "hw-knowledge")) for k, v in PERMISSIONS.items()}, **AGENT.hub.owner}
            return self._send(200, {"llm": AGENT.llm.name, "tools": all_tools,
                                    "owners": owners, "permissions": PERMISSIONS,
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
        if self.path == "/api/runs":
            q = str(body.get("question", "")).strip()[:4000]
            if not q:
                return self._send(400, {"error": "empty question"})
            try:
                return self._send(200, self._runs().create_run(q, project_id=(str(body["project_id"])[:64] if body.get("project_id") else None), seed=body.get("seed"),
                                                               wait=not body.get("async"), ablations=body.get("ablations")))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
        if self.path.startswith("/api/runs/") and self.path.endswith("/resume"):
            run_id = self.path.split("/")[3]
            try:
                return self._send(200, self._runs().resume(run_id, str(body.get("interrupt_id", "")), str(body.get("decision", "")), body.get("payload") or {},
                                                           wait=not body.get("async")))
            except KeyError as exc:
                return self._send(404, {"error": str(exc)})
            except ResumeError as exc:
                return self._send(409, {"error": str(exc)})
        if self.path == "/api/demo/write":
            fn = str(body.get("filename", "")).strip()
            content = str(body.get("content", ""))
            return self._send(200, approval.write_approved(fn, content, session_id="demo-d2", approver="demo-engineer", action_id="i_d217474c"))
        if self.path == "/api/demo/clear_file":
            fn = Path(str(body.get("filename", "pwm_pa8.c"))).name
            target = config.SANDBOX_DIR / fn
            if target.exists() and target.is_file():
                target.unlink()
            return self._send(200, {"status": "cleared", "filename": fn})
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
