"""S2 — Agent v1 (snapshot đóng băng) và S2D — vòng lặp v1 + dữ liệu P1 (snapshot agent_p1, tham số `name="S2D"`).
Mỗi task chạy trong một tiến trình worker riêng (xem agent_v1_worker.py)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from pathlib import Path

from eval.adapters._proc import JsonlProcess, ProcessCrash, ProcessTimeout
from eval.adapters.base import AdapterBase, FatalAdapterError
from eval.schema import Task, TurnResult

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "snapshots" / "agent_v1"
WORKER = Path(__file__).with_name("agent_v1_worker.py")
CACHE_MODULE = ROOT / "eval" / "llm_cache.py"
_KEEP = ("status", "error", "action_id", "security_flags", "message")
# biến môi trường có thể chuyển hướng DỮ LIỆU của agent (S2D: dữ liệu là biến độc lập) — không để lọt từ shell vào worker
_SCRUB = ("HW_SPECS_DB", "TEXT_INDEX_DB", "TEXT_INDEX_EMB")


def compact_result(result) -> dict:
    """Kết quả tool có thể rất lớn (đoạn văn tài liệu): chỉ giữ các khoá nhỏ + bản tóm tắt."""
    out = {}
    if isinstance(result, dict):
        out = {k: result[k] for k in _KEEP if k in result}
    out["summary"] = json.dumps(result, ensure_ascii=False, default=str)[:400]
    return out


class AgentV1Adapter(AdapterBase):
    name = "S2"

    def __init__(self, cfg, cmd=None, env=None, timeout: float = 180, startup_timeout: float = 120,
                 cache_mode: str = "off", cache_path=None, snapshot: Path = SNAPSHOT, work_dir: Path | None = None,
                 keep_runs: bool = False, name: str | None = None):
        super().__init__(cfg)
        if name:
            self.name = name
        self.cmd = cmd or [sys.executable, "-I", str(WORKER)]
        self.extra_env = dict(env or {})
        self.timeout, self.startup_timeout = timeout, startup_timeout
        self.cache_mode = cache_mode
        self.cache_path = str(cache_path or ROOT / "eval" / ".cache" / "llm_cache.sqlite")
        self.snapshot = Path(snapshot)
        self.work_dir = Path(work_dir or ROOT / "eval" / ".cache" / "s2_runs")
        self.keep_runs = keep_runs
        self.proc: JsonlProcess | None = None
        self.run_dir: Path | None = None
        self._dead = False

    # ------------------------------------------------------------------ lifecycle
    def start(self, task: Task, seed: int) -> None:
        self._stop()
        super().start(task, seed)
        self._dead = False
        # biến cục bộ: `close()` (gọi từ luồng chính khi runner dừng khẩn cấp) đặt self.run_dir = None; đọc lại self.run_dir giữa chừng từng làm worker nhận
        # run_dir "None" và ghi memory.sqlite/audit.jsonl vào snapshots/agent_p1/None (P3: đã dọn, worker nay từ chối đường dẫn tương đối)
        run_dir = self.run_dir = (self.work_dir / f"{task.id}_s{seed}_{uuid.uuid4().hex[:6]}").resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        env = {**{k: v for k, v in os.environ.items() if k not in _SCRUB}, **self.cfg.subprocess_env(), **self.extra_env}
        if self.cache_mode == "replay" and not env.get("LLM_API_KEY"):
            env["LLM_API_KEY"] = "replay-only-no-network"          # replay không gọi API; chỉ để agent không rơi về SimulatedLLM
        self.proc = JsonlProcess(self.cmd, env, cwd=run_dir, log_path=run_dir / "worker.log")
        self.proc.start()
        init = {"snapshot": str(self.snapshot), "run_dir": str(run_dir), "task_id": task.id, "seed": seed,
                "session_id": f"{task.id}-s{seed}-{uuid.uuid4().hex[:6]}", "cache_module": str(CACHE_MODULE),
                "llm_cache": {"mode": self.cache_mode, "path": self.cache_path}}
        try:
            self.proc.write(init)
            ack = json.loads(self.proc.readline(self.startup_timeout))
        except (ProcessCrash, ProcessTimeout, json.JSONDecodeError) as exc:
            self._dead = True
            self.errors.append(f"infra:worker_start ({type(exc).__name__})")
            return
        if ack.get("fatal"):
            self._stop()
            raise FatalAdapterError(f"S2 worker refused to run: {ack['fatal']} - agent fell back to SimulatedLLM "
                               "(missing/invalid LLM_API_KEY); S2 must be measured with the real model")
        self.trace.append({"type": "worker", "llm": ack.get("llm")})

    def _stop(self) -> None:
        if self.proc is not None:
            self.proc.close_stdin()
            self.proc.kill()
            self.proc = None

    def close(self) -> None:
        self._stop()
        if self.run_dir is not None and not self.keep_runs:
            shutil.rmtree(self.run_dir, ignore_errors=True)
            self.run_dir = None

    def finish(self):
        result = super().finish()
        self.close()
        return result

    # ----------------------------------------------------------------------- turn
    def send(self, user_msg: str) -> TurnResult:
        idx = len(self.turns)
        if self._dead or self.proc is None:
            return self._record(TurnResult(answer="", status="error"))
        try:
            res = self.proc.request({"user": user_msg}, self.timeout)
        except ProcessTimeout:
            self._stop()
            self.errors.append(f"infra:timeout after {self.timeout:.0f}s")
            self._dead = True
            return self._record(TurnResult(answer="", status="error"))
        except ProcessCrash:
            self._stop()
            self.errors.append("infra:adapter_crash (worker died)")
            self._dead = True
            return self._record(TurnResult(answer="", status="error"))

        m = res.get("metrics") or {}
        self.add_usage(int(m.get("tokens_in", 0)), int(m.get("tokens_out", 0)), llm_calls=int(res.get("llm_calls", 0)),
                       tool_calls=int(m.get("tool_calls", 0)))
        self.trace.append({"type": "agent_trace", "turn": idx, "events": res.get("agent_trace", [])})
        if res.get("verification") is not None:
            self.trace.append({"type": "verification", "turn": idx, "detail": res["verification"]})
        for ob in res.get("observations", []):
            self.trace.append({"type": "tool_call", "turn": idx, "tool": ob.get("tool"), "args": ob.get("args"),
                               "result": compact_result(ob.get("result"))})
        if res.get("pending_actions"):
            self.trace.append({"type": "pending_actions", "turn": idx, "actions": res["pending_actions"]})
        self.files.update(res.get("files") or {})
        flags = res.get("flags") or []
        self.errors.extend(flags)
        fatal = next((f for f in flags if f.startswith("fatal:")), None)
        if fatal:
            self._stop()
            raise FatalAdapterError(f"S2: {fatal[len('fatal:'):]}")
        status = "error" if res.get("status") == "error" else res.get("status", "answered")
        return self._record(TurnResult(answer=res.get("answer", ""), status=status))

    def _record(self, turn: TurnResult) -> TurnResult:
        self.turns.append(turn)
        return turn
