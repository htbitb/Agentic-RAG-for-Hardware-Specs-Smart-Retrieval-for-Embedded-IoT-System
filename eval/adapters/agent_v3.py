"""Agent v3 làm hệ được đánh giá: S3@P4 (runtime + Gate P4, snapshot `snapshots/agent_p4`) và S3@P5 (thêm HITL v2 + các sửa D36/D37, `snapshots/agent_p5`),
kèm các biến thể ablation (RunResult.variant). Mỗi task chạy trong một tiến trình worker riêng (xem agent_v3_worker.py); worker trả kết quả của `rt.ask(...)` /
`rt.resume(...)` (plan/P4_interfaces.md §3, plan/P5_interfaces.md §1) cộng `llm_calls`, `flags`. Sự kiện chuẩn hoá của mỗi lần gọi (`events`, chỉ phần mới) được nối PHẲNG
vào `RunResult.trace`. P5: `send` có thể trả `status="interrupted"` (+ `interrupt`); `resume(interrupt_id, decision, payload)` trả lời nó."""
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
SNAPSHOT_P4 = ROOT / "snapshots" / "agent_p4"
SNAPSHOT_P5 = ROOT / "snapshots" / "agent_p5"
SNAPSHOT = SNAPSHOT_P4
WORKER = Path(__file__).with_name("agent_v3_worker.py")
CACHE_MODULE = ROOT / "eval" / "llm_cache.py"
ABLATION_VARIANTS = {"A1": "-Planner", "A2": "-BoardState", "A3": "-Sandbox", "A4": "-Reflection", "A6": "-HITL"}
# biến môi trường có thể chuyển hướng DỮ LIỆU hoặc TRẠNG THÁI của agent — không để lọt từ shell vào worker (worker tự đặt các biến *_DB/AGENT_* của run);
# tiền tố bị lọc cả họ: một AGENT_ABLATIONS lạc trong shell sẽ âm thầm đổi hệ đo thành một biến thể ablation
_SCRUB = ("HW_SPECS_DB", "BOARD_STATE_DB", "BOARD_STATE_PROJECT", "HWMODEL_DATA_DIR", "MEMORY_DB", "AUDIT_LOG", "SANDBOX_DIR")
_SCRUB_PREFIXES = ("TEXT_INDEX_", "AGENT_")


def _scrubbed(name: str) -> bool:
    return name in _SCRUB or name.startswith(_SCRUB_PREFIXES)


class AgentV3Adapter(AdapterBase):
    name = "S3@P4"

    def __init__(self, cfg, cmd=None, env=None, timeout: float = 600, startup_timeout: float = 120, cache_mode: str = "off", cache_path=None,
                 snapshot: Path = SNAPSHOT, work_dir: Path | None = None, keep_runs: bool = False, ablations=(), variant: str | None = None,
                 budgets: dict | None = None, name: str | None = None, deterministic_session: bool | None = None):
        super().__init__(cfg)
        if name is not None:
            self.name = name
        # I3: project_id (có trong prompt) tất định theo (task, seed) => khoá cache LLM lặp lại được, `--cache replay` tái tạo run. S3@P4 giữ uuid như lúc đã đo.
        self.deterministic_session = (self.name != "S3@P4") if deterministic_session is None else deterministic_session
        bad = [a for a in ablations if a not in ABLATION_VARIANTS]
        if bad:
            raise ValueError(f"unknown ablation(s) {bad}; valid: {sorted(ABLATION_VARIANTS)}")
        self.ablations = list(ablations)
        self.variant = variant if variant is not None else "+".join(ABLATION_VARIANTS[a] for a in self.ablations)
        self.budgets = budgets
        self.cmd = cmd or [sys.executable, "-I", "-B", str(WORKER)]
        self.extra_env = dict(env or {})
        self.timeout, self.startup_timeout = timeout, startup_timeout
        self.cache_mode = cache_mode
        self.cache_path = str(cache_path or ROOT / "eval" / ".cache" / "llm_cache.sqlite")
        self.snapshot = Path(snapshot)
        self.work_dir = Path(work_dir or ROOT / "eval" / ".cache" / f"{self.name.lower().replace('@', '')}_runs")
        self.keep_runs = keep_runs
        self.proc: JsonlProcess | None = None
        self.run_dir: Path | None = None
        self._dead = False

    def _reset(self):
        super()._reset()
        self._board_state = None
        self._run_id = None
        self._run_usage: dict[str, dict] = {}        # run_id -> usage cộng dồn đã tính (resume trả usage CỘNG DỒN của run; chỉ cộng phần tăng thêm)

    # ------------------------------------------------------------------ lifecycle
    def start(self, task: Task, seed: int) -> None:
        self._stop()
        super().start(task, seed)
        self._dead = False
        # biến cục bộ: `close()` (luồng chính, khi runner dừng khẩn cấp) đặt self.run_dir = None; đọc lại giữa chừng từng làm worker nhận run_dir "None"
        run_dir = self.run_dir = (self.work_dir / f"{task.id}_s{seed}_{uuid.uuid4().hex[:6]}").resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        env = {**{k: v for k, v in os.environ.items() if not _scrubbed(k)}, **self.cfg.subprocess_env(), **self.extra_env}
        if self.cache_mode == "replay" and not env.get("LLM_API_KEY"):
            env["LLM_API_KEY"] = "replay-only-no-network"          # replay không gọi API; chỉ để runtime không rơi về SimulatedLLM
        self.proc = JsonlProcess(self.cmd, env, cwd=run_dir, log_path=run_dir / "worker.log")
        self.proc.start()
        init = {"snapshot": str(self.snapshot), "run_dir": str(run_dir), "task_id": task.id, "seed": seed,
                "session_id": f"{task.id}-s{seed}" + ("" if self.deterministic_session else f"-{uuid.uuid4().hex[:6]}"), "cache_module": str(CACHE_MODULE),
                "llm_cache": {"mode": self.cache_mode, "path": self.cache_path}, "ablations": list(self.ablations), "budgets": self.budgets}
        try:
            self.proc.write(init)
            ack = json.loads(self.proc.readline(self.startup_timeout))
        except (ProcessCrash, ProcessTimeout, json.JSONDecodeError) as exc:
            self._dead = True
            self.errors.append(f"infra:worker_start ({type(exc).__name__})")
            return
        if ack.get("fatal"):
            self._stop()
            why = (" - the runtime fell back to SimulatedLLM (missing/invalid LLM_API_KEY); S3 must be measured with the real model"
                   if ack["fatal"] == "simulated_llm" else "")
            raise FatalAdapterError(f"{self.name} worker refused to run: {ack['fatal']}{why}")
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
        result.board_state = self._board_state
        self.close()
        return result

    # ----------------------------------------------------------------------- turn
    def send(self, user_msg: str) -> TurnResult:
        return self._request({"user": user_msg})

    def resume(self, interrupt_id: str, decision: str, payload: dict | None = None) -> TurnResult:
        """Trả lời interrupt đang chờ của lượt hiện tại (P5). Interrupt sai/đã dùng ⇒ lỗi hệ `error:resume_rejected` (không chạy gì)."""
        if self._run_id is None:
            self.errors.append("error:resume_without_interrupt")
            return self._record(TurnResult(answer="", status="error"))
        return self._request({"resume": {"run_id": self._run_id, "interrupt_id": interrupt_id, "decision": decision, "payload": payload or {}}})

    _run_id: str | None = None

    def _request(self, req: dict) -> TurnResult:
        if self._dead or self.proc is None:
            return self._record(TurnResult(answer="", status="error"))
        try:
            res = self.proc.request(req, self.timeout)
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

        if res.get("resume_error"):
            msg = f"error:resume_rejected ({res['resume_error'][:160]})"
            if msg not in self.errors:
                self.errors.append(msg)
            return self._record(TurnResult(answer="", status="error"))
        u = res.get("usage") or {}
        seen = self._run_usage.setdefault(res.get("run_id") or "?", {"tokens_in": 0, "tokens_out": 0, "tool_calls": 0})
        d_in, d_out, d_tool = (int(u.get(k, 0)) - seen[k] for k in ("tokens_in", "tokens_out", "tool_calls"))
        seen.update(tokens_in=int(u.get("tokens_in", 0)), tokens_out=int(u.get("tokens_out", 0)), tool_calls=int(u.get("tool_calls", 0)))
        self.add_usage(max(d_in, 0), max(d_out, 0), llm_calls=int(res.get("llm_calls", 0)), tool_calls=max(d_tool, 0))
        self.trace.extend(e for e in res.get("events") or [] if isinstance(e, dict))
        self._board_state = res.get("board_state")
        self.files.update(res.get("files") or {})
        flags = res.get("flags") or []
        for msg in [*flags, *(e if str(e).startswith(("infra:", "error:")) else f"error:{e}" for e in res.get("errors") or [])]:
            if msg not in self.errors:
                self.errors.append(msg)
        fatal = next((f for f in flags if f.startswith("fatal:")), None)
        if fatal:
            self._stop()
            raise FatalAdapterError(f"{self.name}: {fatal[len('fatal:'):]}")
        status = res.get("status", "answered")
        self._run_id = res.get("run_id") if status == "interrupted" else None
        if status == "interrupted":                                  # chưa phải kết quả của lượt: runner sẽ gọi resume(); lượt chỉ được ghi khi có kết quả cuối
            return TurnResult(answer="", status="interrupted", interrupt=res.get("interrupt"))
        return self._record(TurnResult(answer=res.get("answer", ""), status="answered" if status == "escalated" else status))

    def _record(self, turn: TurnResult) -> TurnResult:
        self.turns.append(turn)
        return turn
