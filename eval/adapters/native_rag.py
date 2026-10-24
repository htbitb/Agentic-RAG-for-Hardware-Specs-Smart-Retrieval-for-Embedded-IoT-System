"""S1 — Native RAG: spawn `native-RAG/.venv/bin/python native-RAG/eval_adapter.py` một lần/worker, giao tiếp JSONL.

Mỗi câu hỏi có timeout; tiến trình chết -> khởi động lại và thử lại đúng một lần; lỗi API/timeout/crash gắn nhãn
`infra:` (không tính vào TSR nhưng được đếm trong report).
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import time
from pathlib import Path

from eval.adapters.base import AdapterBase, FatalAdapterError
from eval.schema import Task, TurnResult

ROOT = Path(__file__).resolve().parents[2]
RAG_DIR = ROOT / "native-RAG"


def _label_error(err: str) -> str:
    """Lỗi từ eval_adapter.py: cache_miss và infra:* là lỗi hạ tầng; còn lại là lỗi của hệ."""
    if err == "cache_miss":
        return "infra:cache_miss"
    return err if err.startswith(("infra:", "error:")) else f"error:{err}"


class _Crash(Exception):
    pass


class _Timeout(Exception):
    pass


class NativeRAGAdapter(AdapterBase):
    name = "S1"

    def __init__(self, cfg, cmd=None, env=None, timeout: float = 120, startup_timeout: float = 300,
                 cache_mode: str = "off", cache_path: str | Path | None = None, log_dir: Path | None = None):
        super().__init__(cfg)
        self.cmd = cmd or [str(RAG_DIR / ".venv" / "bin" / "python"), str(RAG_DIR / "eval_adapter.py")]
        self.extra_env = dict(env or {})
        self.timeout, self.startup_timeout = timeout, startup_timeout
        self.cache_mode, self.cache_path = cache_mode, cache_path
        self.log_dir = Path(log_dir or ROOT / "eval" / ".cache")
        self._proc: subprocess.Popen | None = None
        self._warm = False
        self._buf = b""
        self.history: list[dict] = []

    # ------------------------------------------------------------------ process
    def _spawn(self) -> None:
        self.close()
        env = {**os.environ, **self.cfg.subprocess_env(), **self.extra_env}
        if self.cache_mode in ("record", "replay"):
            env["LLM_CACHE"] = self.cache_mode
            if self.cache_path:
                env["LLM_CACHE_PATH"] = str(self.cache_path)
        else:
            env.pop("LLM_CACHE", None)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = open(self.log_dir / f"native_rag_adapter_{os.getpid()}.log", "ab")
        self._proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, bufsize=0,
                                      cwd=str(RAG_DIR), env=env)
        self._warm, self._buf = False, b""

    def close(self) -> None:
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass

    def _readline(self, timeout: float) -> str:
        fd = self._proc.stdout.fileno()
        deadline = time.time() + timeout
        while b"\n" not in self._buf:
            left = deadline - time.time()
            if left <= 0:
                raise _Timeout()
            ready, _, _ = select.select([fd], [], [], min(left, 1.0))
            if not ready:
                if self._proc.poll() is not None:
                    raise _Crash()
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                raise _Crash()
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("utf-8", "replace")

    def _request(self, payload: dict) -> dict:
        if self._proc is None or self._proc.poll() is not None:
            self._spawn()
        try:
            self._proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        except (BrokenPipeError, OSError):
            raise _Crash()
        timeout = self.timeout if self._warm else self.startup_timeout
        resp = json.loads(self._readline(timeout))
        self._warm = True
        return resp

    # -------------------------------------------------------------------- API
    def start(self, task: Task, seed: int) -> None:
        super().start(task, seed)
        self.history = []

    def send(self, user_msg: str) -> TurnResult:
        idx = len(self.turns)
        payload = {"id": f"{self.task.id}:{self.seed}:{idx}", "question": user_msg, "history": self.history, "seed": self.seed}
        resp = None
        for attempt in (1, 2):
            try:
                resp = self._request(payload)
                break
            except _Timeout:
                self.close()
                self.errors.append(f"infra:timeout after {self.timeout:.0f}s")
                return self._record(TurnResult(answer="", status="error"))
            except (_Crash, json.JSONDecodeError):
                self.close()
                if attempt == 2:
                    self.errors.append("infra:adapter_crash (process died twice)")
                    return self._record(TurnResult(answer="", status="error"))
        err = resp.get("error")
        if err and err.startswith("fatal:"):
            self.close()
            raise FatalAdapterError(f"S1: {err[len('fatal:'):]}")
        if err:
            self.errors.append(_label_error(err))
            return self._record(TurnResult(answer="", status="error"))
        u = resp.get("usage") or {}
        self.add_usage(int(u.get("in", 0)), int(u.get("out", 0)), llm_calls=1)
        self.trace.append({"type": "sources", "turn": idx, "sources": resp.get("sources", [])})
        self.trace.append({"type": "llm_call", "turn": idx, "tokens_in": int(u.get("in", 0)), "tokens_out": int(u.get("out", 0)),
                           "latency_s": resp.get("latency_s")})
        answer = (resp.get("answer") or "").strip()
        self.history.append({"user": user_msg, "assistant": answer})
        return self._record(TurnResult(answer=answer, status="answered"))

    def _record(self, turn: TurnResult) -> TurnResult:
        self.turns.append(turn)
        return turn
