"""Run API tối thiểu (W7): lớp Python dùng chung cho UI (HTTP trong `ui/server.py`) và eval (adapter gọi thẳng, không qua HTTP).

    svc = RunService(build_runtime(...))
    svc.create_run(question, project_id=None, seed=None, wait=True) -> {"run_id", "status", "interrupt"?, "answer"?, ...}
    svc.resume(run_id, interrupt_id, decision, payload)             -> như create_run (hoặc ném ResumeError)
    svc.events(run_id, after=0)                                     -> {"run_id", "status", "events": [seq > after], "next": seq cuối}
    svc.get(run_id)                                                 -> trạng thái hiện tại của run (từ checkpoint)

Sự kiện đọc từ checkpoint SQLite nên polling theo `seq` chạy được cả khi run đang chạy ở luồng khác hoặc tiến trình khác. Mỗi lần chỉ một run hoạt động
(runtime dùng chung một ToolHub / Board State theo project): các lời gọi create_run / resume được tuần tự hoá.
"""
from __future__ import annotations

import threading
import time
import uuid

from agent.runtime.hitl import ResumeError  # noqa: F401  (re-export cho tầng HTTP)

PUBLIC_KEYS = ("run_id", "project_id", "turn", "status", "answer", "interrupt", "usage", "plan", "gate", "escalation", "files", "errors")


def _public(res: dict) -> dict:
    out = {k: res.get(k) for k in PUBLIC_KEYS if k in res}
    out["board_version"] = (res.get("board_state") or {}).get("version")
    return out


class RunService:
    def __init__(self, runtime, factory=None):
        """`factory(ablations: tuple[str]) -> AgentRuntime` (dùng CÙNG checkpoint DB) cho phép chọn ablation theo từng run; không có thì chỉ nhận ablation trùng cấu hình của `runtime`."""
        self.rt = runtime
        self.factory = factory
        self._rts: dict[tuple, object] = {tuple(runtime.ablations.codes()): runtime}
        self._rt_of: dict[str, object] = {}
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._results: dict[str, dict] = {}
        self._errors: dict[str, str] = {}

    # ------------------------------------------------------------------ tạo / resume
    def _runtime_for(self, ablations) -> object:
        codes = tuple(sorted(str(a).strip().upper() for a in (ablations or ()) if str(a).strip()))
        if codes not in self._rts:
            if self.factory is None:
                raise ValueError(f"this service was built without a runtime factory: ablations {list(codes)} are not available")
            self._rts[codes] = self.factory(codes)
        return self._rts[codes]

    def create_run(self, question: str, project_id: str | None = None, seed: int | None = None, wait: bool = True, ablations=None) -> dict:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        project = (project_id or "p-" + uuid.uuid4().hex[:8]).strip()
        run_id = uuid.uuid4().hex[:12]
        rt = self._runtime_for(ablations)
        self._rt_of[run_id] = rt
        if wait:
            return self._run(lambda: rt.ask(question.strip(), session_id=project, seed=seed, run_id=run_id))
        t = threading.Thread(target=self._run_bg, args=(run_id, lambda: rt.ask(question.strip(), session_id=project, seed=seed, run_id=run_id)), daemon=True)
        self._threads[run_id] = t
        t.start()
        self._wait_for_checkpoint(run_id)
        return {"run_id": run_id, "project_id": project, "status": "running"}

    def resume(self, run_id: str, interrupt_id: str, decision: str, payload: dict | None = None, wait: bool = True) -> dict:
        self.get(run_id)                                                     # KeyError nếu không có run
        rt = self._rt_of.get(run_id, self.rt)
        if wait:
            return self._run(lambda: rt.resume(run_id, interrupt_id, decision, payload))
        self._results.pop(run_id, None)
        # validate đồng bộ để lỗi (interrupt sai/đã dùng) trả về ngay chứ không chìm trong luồng nền
        from agent.runtime import hitl
        st = rt.store.load(run_id)
        pending = st.pending_interrupt if st.waiting else None
        if pending is None or pending["id"] != interrupt_id:
            raise ResumeError(f"interrupt {interrupt_id!r} is not pending on run {run_id}")
        hitl.validate_resolution(pending, decision, payload)
        t = threading.Thread(target=self._run_bg, args=(run_id, lambda: rt.resume(run_id, interrupt_id, decision, payload)), daemon=True)
        self._threads[run_id] = t
        t.start()
        return {"run_id": run_id, "status": "running"}

    def _run(self, fn) -> dict:
        with self._lock:
            res = fn()
        self._results[res["run_id"]] = res
        return _public(res)

    def _run_bg(self, run_id: str, fn) -> None:
        try:
            self._run(fn)
        except Exception as exc:                                             # noqa: BLE001 — lỗi của luồng nền được trả qua get()
            self._errors[run_id] = f"{type(exc).__name__}: {exc}"

    def _wait_for_checkpoint(self, run_id: str, timeout: float = 5.0) -> None:
        end = time.time() + timeout
        while time.time() < end and self.rt.store.load(run_id) is None and run_id not in self._errors:
            time.sleep(0.01)

    # ------------------------------------------------------------------ đọc
    def get(self, run_id: str) -> dict:
        st = self.rt.store.load(run_id)
        if st is None:
            raise KeyError(f"no run {run_id!r}")
        t = self._threads.get(run_id)
        running = bool(t and t.is_alive())
        status = "running" if running else ("interrupted" if st.waiting else ("error" if run_id in self._errors else (st.outcome or st.status.lower())))
        out = {"run_id": run_id, "project_id": st.project_id, "turn": st.turn, "status": status, "state": st.status, "answer": st.answer or "" if st.terminal else "",
               "interrupt": st.pending_interrupt if st.waiting else None, "usage": {k: st.used.get(k) for k in ("steps", "llm_calls", "tool_calls", "asks", "tokens_in", "tokens_out", "usd")},
               "plan": st.plan}
        if run_id in self._errors:
            out["error"] = self._errors[run_id]
        return out

    def events(self, run_id: str, after: int = 0) -> dict:
        st = self.rt.store.load(run_id)
        if st is None:
            raise KeyError(f"no run {run_id!r}")
        evs = [e for e in st.events if e["seq"] > after]
        return {"run_id": run_id, "status": self.get(run_id)["status"], "events": evs, "next": evs[-1]["seq"] if evs else after}
