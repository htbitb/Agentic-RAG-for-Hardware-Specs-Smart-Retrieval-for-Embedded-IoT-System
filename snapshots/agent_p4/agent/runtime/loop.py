"""Agent Runtime v3 (W4): state machine có checkpoint thay cho `for step in range(MAX_STEPS)` của v1.

    INTAKE -> PLAN -> ACT <-> OBSERVE -> (CHECK) -> FINISH_GATE -> DONE        | REFUSED | ESCALATED

* LLM quyết định làm gì (chọn tool, lập kế hoạch, viết code, khi nào dừng); runtime quyết định được phép làm gì và khi nào là xong:
  mọi bản trả lời (tool `finish`, hoặc một tin nhắn văn bản không kèm tool call = finish ngầm) phải qua Gate trước khi tới người dùng.
* Lỗi CỤC BỘ của Gate/mô phỏng quay về agent dưới dạng phản hồi có kiểu {code, where, expected, actual, hint_source}; lỗi CẤU TRÚC (board từ chối
  gán chân, clock không đạt, DRC) chèn REPLAN_REQUIRED: agent phải `update_plan` trước khi hành động tiếp.
* Cùng một mã lỗi quá `max_repairs` (3) lần, hoặc hết ngân sách steps/tokens/usd/wall_s => ESCALATED: trả câu trả lời tốt nhất kèm các requirement chưa đạt
  và những gì đã thử (D32), không bao giờ một câu "step budget exhausted" trống.
* Trạng thái (AgentState) được ghi vào SQLite sau mỗi bước; `resume(run_id)` chạy tiếp một run bị kill. Tool không-read-only đang chạy lúc chết KHÔNG bị
  chạy lại (at-most-once): agent nhận một observation nói rõ hiệu ứng chưa biết.
"""
from __future__ import annotations

import json
import time
import uuid

import config
from agent import audit, guardrail
from agent.llm import parse_entities
from agent.memory import MAX_OBS_CHARS
from agent.gate.types import requirement_id
from agent.runtime import control_tools as ct
from agent.runtime import intake
from agent.runtime.checkpoint import CheckpointStore
from agent.runtime.flags import Ablations
from agent.runtime.state import AgentState, Budgets, PlanError, diff_plans
from agent.runtime.trace import clip, compact_effect, write_jsonl
from agent.tools import PERMISSIONS, ToolHub

STRUCTURAL_BOARD = {"CONFLICT", "NO_SUCH_AF", "INPUT_ONLY", "PIN_NOT_IN_PACKAGE", "SIGNAL_ALREADY_ROUTED", "LEVEL_MISMATCH", "NOT_5V_TOLERANT",
                    "ADC_RANGE", "CLOCK_LIMIT", "PIN_CONFLICT", "TIMER_SHARED"}
STATUS_OF = {"answered": "answered", "refused": "refused", "blocked": "blocked", "escalated": "escalated", "error": "error"}
WRAPUP = ("The run limit was reached before the answer could pass the verification gates. Reply now WITHOUT calling any tool, with the best complete answer you can "
          "give from what you have already established: include the code you have (in fenced code blocks), say which parts are verified and which are not, and "
          "state any conflict or unmet requirement honestly.")


class _Done(Exception):
    """Dùng nội bộ để thoát vòng lặp khi run đã tới trạng thái cuối."""


class AgentRuntime:
    def __init__(self, hub: ToolHub, llm, store: CheckpointStore, gate, *, ablations: Ablations | None = None, budgets: Budgets | dict | None = None,
                 system_prompt: str = "", trace_dir=None, max_repairs: int = 3, allow_scripted: bool = False, escalate_wrapup: bool = True,
                 compact_keep: int | None = 12, compact_chars: int = 1500):
        if getattr(llm, "simulated", False) and not allow_scripted:
            raise ValueError("refusing to run the v3 runtime with a simulated/scripted LLM: every claim about agentic behaviour must use the real model "
                             "(ScriptedPolicy is for tests only)")
        self.hub, self.llm, self.store, self.gate = hub, llm, store, gate
        self.ablations = ablations or Ablations()
        self.budgets = budgets if isinstance(budgets, Budgets) else Budgets.from_overrides(budgets)
        self.system_prompt = system_prompt
        self.trace_dir = trace_dir
        self.max_repairs = self.ablations.max_repairs(max_repairs)
        self.escalate_wrapup = escalate_wrapup
        self.compact_keep, self.compact_chars = compact_keep, compact_chars       # kết quả tool cũ hơn `compact_keep` tin nhắn tool bị rút còn `compact_chars` ký tự khi gửi LLM
        self.current_run_id: str | None = None
        self._state: AgentState | None = None
        self._tick = time.monotonic()

    def gate_call(self, name: str, args: dict) -> dict:
        """Cầu nối tool cho Gate: gọi qua hub (cùng quyền, cùng project) và ghi sự kiện `tool_call` internal=True (không tính vào tool call của agent)."""
        res = self.hub.call(name, args, internal=True)
        if self._state is not None:
            self._emit(self._state, "tool_call", tool=name, server=self.hub.owner.get(name), permission=PERMISSIONS.get(name), args=clip(args, 200),
                       ok="error" not in res and res.get("ok") is not False, error=res.get("error") if isinstance(res.get("error"), str) else None,
                       summary=clip(res, 200), security_flags=res.get("security_flags"), internal=True)
        return res

    def close(self) -> None:
        try:
            self.hub.close()
        finally:
            self.store.close()

    # ================================================================== API
    def ask(self, question: str, session_id: str = "default", seed: int | None = None) -> dict:
        self.hub.session_id = self.hub.project_id = session_id
        sess = self.store.session(session_id)
        state = AgentState.new(run_id=uuid.uuid4().hex[:12], project_id=session_id, goal=question, turn=len(sess["history"]), budgets=self.budgets, seed=seed)
        state.plan = list(sess["plan"])
        self.current_run_id = state.run_id
        self._tick = time.monotonic()
        audit.log("question", qid=state.run_id, session=session_id, config="v3" + self.ablations.variant(), question=question)
        self._emit(state, "run_started", goal=question, project_id=session_id, ablations=list(self.ablations.codes()), budgets=dict(state.budgets))
        self._checkpoint(state)
        return self._run(state)

    def resume(self, run_id: str) -> dict:
        state = self.store.load(run_id)
        if state is None:
            raise KeyError(f"no checkpoint for run {run_id!r}")
        self.hub.session_id = self.hub.project_id = state.project_id
        self.current_run_id = run_id
        self._tick = time.monotonic()
        if not state.terminal:
            self._emit(state, "resumed", from_seq=state.seq)
            if state.in_flight:
                self._interrupt_in_flight(state)
        return self._run(state)

    # ================================================================== chạy
    def _run(self, state: AgentState) -> dict:
        self._state = state
        try:
            if not state.terminal:
                if not state.messages and not self._intake(state):
                    pass
                else:
                    self._drive(state)
        except _Done:
            pass
        finally:
            self._state = None
        return self._finalize(state)

    def _drive(self, state: AgentState) -> None:
        while not state.terminal:
            if state.pending_calls:
                self._run_pending(state)
                continue
            exceeded = state.budget_exceeded()
            if exceeded:
                self._escalate(state, f"budget:{exceeded}")
                break
            self._maybe_notice(state)
            resp = self._llm_step(state)
            if resp is None:
                break
            if resp.tool_calls:
                state.pending_calls = [{"id": c["id"], "name": c["name"], "arguments": c["arguments"], "batch": len(resp.tool_calls)} for c in resp.tool_calls]
                state.status = "ACT"
                self._checkpoint(state)
            else:
                self._on_text(state, (resp.content or "").strip())

    def _maybe_notice(self, state: AgentState) -> None:
        """Khi đã dùng ≥ 75 % một chiều ngân sách (steps/wall_s/tokens): nhắc agent chốt câu trả lời tốt nhất thay vì tiếp tục tra cứu (một lần mỗi run)."""
        if state.notice_sent:
            return
        hit = state.budget_pressure(0.75)
        if hit is None:
            return
        dim, used, limit = hit
        state.notice_sent = True
        self._emit(state, "budget_notice", dimension=dim, used=round(used, 2), limit=limit)
        state.messages.append({"role": "user", "content": f"BUDGET NOTICE: about 75% of this run's {dim} budget is used ({round(used)} of {round(limit)}). Stop exploring: finish now with your best "
                                                          "answer (call finish), including the code you have; state clearly anything you could not verify."})
        self._checkpoint(state)

    # ------------------------------------------------------------------ INTAKE
    def _intake(self, state: AgentState) -> bool:
        g = guardrail.check_user_input(state.goal)
        self._emit(state, "guardrail", stage="input", blocked=g["blocked"], flags=g["flags"])
        if g["blocked"]:
            audit.log("direct_injection_blocked", qid=state.run_id, flags=g["flags"])
            self._terminate(state, "blocked", "Request blocked by the security guardrail (flags: " + ", ".join(g["flags"]) +
                            "). I can only answer hardware-documentation questions and never reveal system instructions or secrets, nor bypass approvals.",
                            "REFUSED", reason="input_guardrail")
            return False
        sess = self.store.session(state.project_id)
        ent = parse_entities(state.goal)
        chips = ent["chips"] or next((h["chips"] for h in reversed(sess["history"]) if h.get("chips")), [])
        refusal = intake.hardware_check(self.hub, state.goal, chips, ent, lambda t, **kw: self._emit(state, t, **kw))
        if refusal:
            self._terminate(state, "refused", refusal, "REFUSED", reason="hardware_safety")
            return False
        msgs = [{"role": "system", "content": self.system_prompt}]
        for h in sess["history"]:
            msgs += [{"role": "user", "content": h["user"]}, {"role": "assistant", "content": h["answer"]}]
        board = self._board_state()
        ctx = intake.project_context(state.project_id, board, state.plan)
        if ctx:
            msgs.append({"role": "system", "content": ctx})
        msgs.append({"role": "user", "content": state.goal})
        state.messages = msgs
        state.status = "PLAN"
        self._checkpoint(state)
        return True

    def _board_state(self) -> dict | None:
        """Board State hiện tại của project (lời gọi nội bộ), hoặc None khi server board-state bị tắt (A2) hay lỗi."""
        if "get_board_state" not in self.hub.owner:
            return None
        res = self.hub.call("get_board_state", {}, internal=True)
        return res.get("state") if res.get("ok") else None

    # ------------------------------------------------------------------ LLM
    def _tools(self) -> list[dict]:
        hidden = set(self.ablations.hidden_control_tools())
        return list(self.hub.specs) + [s for n, s in ct.CONTROL_SPECS.items() if n not in hidden]

    def _llm_step(self, state: AgentState):
        try:
            resp = self.llm.chat(self._view(state.messages), self._tools(), seed=state.seed)
        except Exception as exc:                                    # sự cố LLM/API -> kết thúc an toàn, không sập (AT2); BaseException (kill) đi xuyên qua
            audit.log("llm_error", qid=state.run_id, error=str(exc))
            state.errors.append(f"{type(exc).__name__}: {exc}")
            self._terminate(state, "error", f"Insufficient evidence: language model unavailable ({type(exc).__name__}).", "DONE", reason="llm_error")
            return None
        self._count_usage(state, resp)
        self._emit(state, "llm_call", tokens_in=resp.usage["in"], tokens_out=resp.usage["out"])
        msg = {"role": "assistant", "content": resp.content or ""}
        if resp.tool_calls:
            msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                                 | ({"extra_content": c["extra_content"]} if c.get("extra_content") else {}) for c in resp.tool_calls]
        state.messages.append(msg)
        return resp

    def _view(self, messages: list) -> list:
        """Bản nhìn gửi cho LLM: kết quả tool cũ được rút gọn để ngữ cảnh không phình theo số bước (state.messages giữ nguyên đầy đủ để resume/trace)."""
        if self.compact_keep is None:
            return messages
        idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        old = set(idx[:max(0, len(idx) - self.compact_keep)])
        if not old:
            return messages
        note = " ...[earlier observation shortened to save context; call the tool again if you need the rest]"
        return [({**m, "content": m["content"][:self.compact_chars] + note} if i in old and len(m["content"]) > self.compact_chars else m) for i, m in enumerate(messages)]

    def _count_usage(self, state: AgentState, resp) -> None:
        u = state.used
        u["steps"] += 1
        u["llm_calls"] += 1
        u["tokens_in"] += resp.usage["in"]
        u["tokens_out"] += resp.usage["out"]
        u["usd"] = round(u["tokens_in"] / 1e6 * config.PRICE_IN_PER_M + u["tokens_out"] / 1e6 * config.PRICE_OUT_PER_M, 8)

    # ------------------------------------------------------------------ văn bản không kèm tool call = finish ngầm
    def _on_text(self, state: AgentState, text: str) -> None:
        if not text:
            state.messages.append({"role": "user", "content": "Your reply was empty. Continue working with the tools, or give the complete final answer."})
            self._checkpoint(state)
            return
        accepted, fb = self._finish(state, ct.FinishRequest(answer=text, implicit=True), trigger="draft")
        if not state.terminal:
            state.messages.append({"role": "user", "content": self._feedback_message(state, fb)})
            self._checkpoint(state)

    # ------------------------------------------------------------------ thực thi tool call
    def _run_pending(self, state: AgentState) -> None:
        while state.pending_calls and not state.terminal:
            call = state.pending_calls[0]
            content = self._exec_call(state, call)
            state.messages.append({"role": "tool", "tool_call_id": call["id"], "content": self._trunc(content)})
            state.pending_calls = state.pending_calls[1:]
            self._checkpoint(state)
        if state.terminal:
            state.pending_calls = []
            self._checkpoint(state)
            return
        rp = state.replan_pending
        if rp and not rp.get("announced"):
            rp["announced"] = True
            state.messages.append({"role": "user", "content": f"REPLAN_REQUIRED: {rp['reason']} Call update_plan to revise your plan (add, drop or change steps "
                                                              "accordingly) before taking any other action."})
            self._checkpoint(state)

    @staticmethod
    def _trunc(content: str) -> str:
        return content if len(content) <= MAX_OBS_CHARS else content[:MAX_OBS_CHARS] + " ...[truncated]"

    def _exec_call(self, state: AgentState, call: dict) -> str:
        name, args = call["name"], call["arguments"]
        if "__malformed__" in args:
            return self._emit_call(state, name, args, {"error": "malformed JSON arguments - resend valid JSON"})
        if name in ct.CONTROL_SPECS and name not in self.ablations.hidden_control_tools():
            return self._exec_control(state, call)
        if state.replan_pending and name != "update_plan":
            res = {"error": f"REPLAN_REQUIRED: {state.replan_pending['reason']} The call {name} was NOT executed; call update_plan first."}
            return self._emit_call(state, name, args, res)
        perm = PERMISSIONS.get(name)
        if perm not in (None, "read-only"):
            state.in_flight = {"call_id": call["id"], "tool": name}
            self._checkpoint(state)
        res = self.hub.call(name, args)
        state.in_flight = None
        if name in self.hub.owner:
            state.used["tool_calls"] += 1
            state.observations.append({"tool": name, "args": args, "result": res})
        text = self._emit_call(state, name, args, res)
        if name in self.hub.owner:
            self._classify(state, name, args, res)
        return text

    def _emit_call(self, state: AgentState, name: str, args: dict, res: dict) -> str:
        ok = "error" not in res and res.get("ok") is not False
        self._emit(state, "tool_call", tool=name, server=self.hub.owner.get(name, "control" if name in ct.CONTROL_SPECS else None), permission=PERMISSIONS.get(name),
                   args=clip(args), ok=ok, error=(res.get("error") if isinstance(res.get("error"), str) else (res.get("error") or {}).get("code") if res.get("error") else None),
                   summary=clip(res), security_flags=res.get("security_flags"), internal=False)
        return json.dumps(res, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------ tool điều khiển
    def _exec_control(self, state: AgentState, call: dict) -> str:
        name, args = call["name"], call["arguments"]
        if name == "update_plan":
            try:
                plan, why = ct.parse_update_plan(args)
            except PlanError as exc:
                return self._emit_call(state, name, args, {"error": f"invalid plan: {exc}"})
            diff = diff_plans(state.plan, plan)
            state.plan = plan
            after_replan = state.replan_pending is not None
            state.replan_pending = None
            self._emit(state, "plan_updated", rationale=why, diff=diff, plan=plan, after_replan=after_replan)
            return self._emit_call(state, name, args, {"ok": True, "plan": plan, "diff": diff})
        # finish
        if call.get("batch", 1) > 1:
            return self._emit_call(state, name, args, {"error": "finish must be called alone: wait for the results of your other tool calls, then call finish by itself"})
        try:
            req = ct.parse_finish(args)
        except ct.FinishError as exc:
            return self._emit_call(state, name, args, {"error": str(exc)})
        accepted, fb = self._finish(state, req, trigger="finish")
        res = {"accepted": accepted, **fb} if not accepted else {"accepted": True, "gates": fb["gates"]}
        text = self._emit_call(state, name, args, res)
        if not accepted and state.replan_pending and not state.terminal:
            pass                                                    # REPLAN_REQUIRED được chèn sau khi mọi tool call của tin nhắn đã có kết quả (_run_pending)
        return text

    # ------------------------------------------------------------------ FINISH_GATE
    def _finish(self, state: AgentState, req: ct.FinishRequest, trigger: str):
        from agent.gate import GateContext
        state.status = "FINISH_GATE"
        state.finish_attempts += 1
        state.waived = list(req.waived)
        artifact = f"draft#{state.finish_attempts}"
        board = self._board_state()
        chip = self._infer_chip(state, board)
        sess = self.store.session(state.project_id)
        ctx = GateContext(answer=req.answer, user_texts=[h["user"] for h in sess["history"]] + [state.goal], observations=list(state.observations),
                          prior_answers=[h["answer"] for h in sess["history"] if h.get("status") in ("answered",)], waived=list(req.waived), chip=chip,
                          initial=state.sim_context.get("initial") or "reset", hse_hz=state.sim_context.get("hse_hz"))
        try:
            report = self.gate.run(ctx)
        except Exception as exc:                                    # Gate hỏng không được âm thầm chấp nhận câu trả lời: coi là fail (đóng)
            audit.log("gate_error", qid=state.run_id, error=f"{type(exc).__name__}: {exc}")
            report = _InternalFailure(f"{type(exc).__name__}: {exc}")
        state.gate_attempts += 1
        failed = report.failed_codes()
        if report.sim:
            self._emit(state, "sim_result", tool="gate", source="gate", **{"pass": bool(report.sim.get("ok", not report.sim.get("violations")))},
                       violations=list(report.sim.get("violations", [])), effects=[compact_effect(e) for e in report.sim.get("effects", [])][:12],
                       unmodeled=list(report.sim.get("unmodeled", [])), artifact=artifact)
        self._emit(state, "gate_result", trigger=trigger, attempt=state.finish_attempts, gates=dict(report.gates), passed=report.passed, artifact=artifact,
                   start=(report.details or {}).get("start"),
                   findings=[{"gate": f.gate, "code": f.code, "severity": f.severity, "kind": f.kind, "where": f.where} for f in report.findings])
        state.artifacts.append({"id": artifact, "text": req.answer, "passed": report.passed, "failed_codes": failed, "gate": report.to_dict()})
        self._emit(state, "finish", implicit=req.implicit, accepted=report.passed, gate=dict(report.gates), waived=[w["id"] for w in req.waived], attempt=state.finish_attempts)
        if report.passed:
            state.answer = req.answer
            self._terminate(state, "answered", req.answer, "DONE", reason="gate_passed", gate=report.to_dict())
            return True, {"gates": dict(report.gates)}
        # ---- gate fail: đếm lỗi theo mã, REPLAN cho lỗi cấu trúc, ESCALATED khi lặp quá ngân sách tự sửa
        worst_code, worst_n = None, 0
        for code in self._error_keys(report):
            n = state.count_error(code)
            if n > worst_n:
                worst_code, worst_n = code, n
        structural = [f for f in report.errors() if f.kind == "structural"]
        if structural and self.ablations.planner:
            codes = ", ".join(sorted({f.code for f in structural}))
            state.replan_pending = {"reason": f"the design violates structural rules ({codes}); fixing the wording or the code is not enough.", "code": structural[0].code}
            self._emit(state, "replan_required", reason=state.replan_pending["reason"], code=structural[0].code)
        if worst_n > self.max_repairs:
            self._escalate(state, "repeated_error", code=worst_code)
            return False, report.feedback()
        state.status = "ACT"
        return False, report.feedback()

    @staticmethod
    def _infer_chip(state: AgentState, board: dict | None) -> str | None:
        """Chip mà mã/yêu cầu nhắm tới: target của Board State; nếu chưa có thì tham số `chip` của lần gọi tool gần nhất; không có dấu hiệu nào thì None (Gate dùng mặc định)."""
        if board and board.get("targets"):
            return board["targets"][0]["chip"]
        for o in reversed(state.observations):
            chip = o["args"].get("chip") if isinstance(o.get("args"), dict) else None
            if isinstance(chip, str) and chip.strip():
                return chip.strip().lower()
        return None

    @staticmethod
    def _error_keys(report) -> list[str]:
        """Khoá đếm lặp lỗi: mã lỗi; riêng G1 theo TỪNG lời khẳng định (`G1-V1:answer: "4.0 V"`) để sửa xong lời khẳng định này rồi vướng lời khẳng định khác
        không bị coi là cùng một lỗi lặp lại. Vị trí của G2 (dòng/op) đổi theo mỗi lần viết lại nên G2 chỉ theo mã."""
        keys: list[str] = []
        for f in report.errors():
            k = f"{f.code}:{f.where}" if f.gate == "G1" and f.code.startswith("G1-V") else f.code
            if k not in keys:
                keys.append(k)
        return keys

    def _feedback_message(self, state: AgentState, fb: dict) -> str:
        msg = (f"FINISH GATE FAILED (attempt {state.finish_attempts}). Typed findings, each {{code, where, expected, actual, hint_source}}:\n"
               f"{json.dumps(fb, ensure_ascii=False, default=str)}\n"
               "Fix the problems in your answer (use the tools if needed) and reply with the complete corrected final answer. If a finding cannot be fixed, "
               "say so explicitly in the answer.")
        rp = state.replan_pending
        if rp and not rp.get("announced"):
            rp["announced"] = True
            msg += f"\nREPLAN_REQUIRED: {rp['reason']} Call update_plan to revise your plan before taking any other action."
        return msg

    # ------------------------------------------------------------------ OBSERVE: phân loại kết quả tool
    def _classify(self, state: AgentState, name: str, args: dict, res: dict) -> None:
        server = self.hub.owner.get(name)
        keys: list[str] = []
        structural: list[str] = []
        if name == "simulate_register_writes" and "error" not in res:
            n = 1 + sum(1 for e in state.events if e["type"] == "sim_result" and e.get("source") == "agent")
            viol = sorted({v["code"] for v in res.get("violations", []) if v.get("severity") == "error"})
            init = args.get("initial", "reset")
            # chỉ tên preset + hse_hz được kế thừa cho Gate (không bao giờ `ops` thêm do agent tự đặt vào trạng thái khởi đầu); simulate lỗi thì "error" in res nên không tới đây
            state.sim_context = {"initial": init.get("preset", "reset") if isinstance(init, dict) else init,
                                 "hse_hz": (init.get("hse_hz") if isinstance(init, dict) else None) or args.get("hse_hz")}
            self._emit(state, "sim_result", tool=name, source="agent", **{"pass": bool(res.get("ok")) and not viol}, violations=viol,
                       effects=[compact_effect(e) for e in res.get("effects", [])][:12], unmodeled=list(res.get("unmodeled", [])), artifact=f"sim#{n}")
            keys += viol
        elif server == "board-state" and PERMISSIONS.get(name) == "state-mutating":
            err = res.get("error") if isinstance(res.get("error"), dict) else {}
            code = err.get("code")
            viol = [v.get("code", "") for v in res.get("violations", [])] if name == "set_clock_config" else []
            contra = [c.get("code", "") for c in res.get("contradictions", [])] if name == "set_requirements" else []
            self._emit(state, "board_mutation", tool=name, ok=bool(res.get("ok")), version=res.get("version"), code=code or (viol or contra or [None])[0])
            for c in ([f"{code}:{err['pin']}" if err.get("pin") else code] if code else []) + viol + contra:
                if c and c.split(":", 1)[0] in STRUCTURAL_BOARD:
                    structural.append(c)
            keys += structural
        worst_code, worst_n = None, 0
        for k in dict.fromkeys(keys):
            n = state.count_error(k)
            if n > worst_n:
                worst_code, worst_n = k, n
        if structural and self.ablations.planner and not state.replan_pending:
            state.replan_pending = {"reason": f"the Board State rejected or flagged the design ({', '.join(dict.fromkeys(structural))}); a different pin, signal, clock or "
                                              "structure is needed.", "code": structural[0]}
            self._emit(state, "replan_required", reason=state.replan_pending["reason"], code=structural[0])
        if worst_n > self.max_repairs:
            self._escalate(state, "repeated_error", code=worst_code)

    # ------------------------------------------------------------------ ESCALATED
    def _escalate(self, state: AgentState, reason: str, code: str | None = None) -> None:
        best = self._best_artifact(state)
        unmet = self._unmet_requirements(state, best)
        tried = self._tried(state)
        body = best["text"] if best else self._wrapup(state, reason)
        if body is None:
            body = self._fallback_body(state, reason, unmet)
        why = (f"the same problem ({code}) kept recurring after {self.max_repairs} repair attempt(s)" if reason == "repeated_error"
               else f"the {reason.split(':', 1)[1]} limit of this run was reached")
        lines = [body.rstrip(), "", "---", f"**Not fully verified (escalated: {why}).** This answer did not pass every verification gate.", ""]
        if unmet:
            lines.append("Requirements not yet met:")
            lines += [f"- {u['id']}: {u['summary']}" + (f" — {', '.join(u['codes'])}" if u["codes"] else "") for u in unmet]
        elif best and not best["passed"]:
            lines.append("Failed checks: " + ", ".join(best["failed_codes"]))
        lines += ["", "What was tried: " + "; ".join(tried)]
        answer = "\n".join(lines)
        state.escalation = {"reason": reason, "code": code, "unmet_requirements": unmet, "tried": tried, "max_repairs": self.max_repairs}
        self._emit(state, "escalated", reason=reason, code=code, unmet_requirements=[u["id"] for u in unmet], tried=tried)
        self._terminate(state, "escalated", answer, "ESCALATED", reason=reason)

    @staticmethod
    def _best_artifact(state: AgentState) -> dict | None:
        cands = [a for a in state.artifacts if a.get("text")]
        if not cands:
            return None
        return min(enumerate(cands), key=lambda ia: (len(ia[1]["failed_codes"]), -ia[0]))[1]

    def _unmet_requirements(self, state: AgentState, best: dict | None) -> list[dict]:
        failing: dict[str, list[str]] = {}
        for f in ((best or {}).get("gate") or {}).get("findings", []):
            rid = requirement_id(str(f.get("where", ""))) if f.get("severity") == "error" else None
            if rid is not None:
                failing.setdefault(rid, []).append(f["code"])
        board = self._board_state() or {}
        gate = (best or {}).get("gate") or {}
        g2_codes = [f["code"] for f in gate.get("findings", []) if f.get("gate") == "G2" and f.get("severity") == "error"]
        g2_failed = (gate.get("gates") or {}).get("G2") == "fail"
        out = []
        for r in board.get("requirements", []):
            # requirement mà mô phỏng của chính câu trả lời này đã trượt (vd lỗi cấp lệnh không gắn với requirement nào) thì chưa được kiểm chứng dù đã đánh dấu satisfied
            if g2_failed and r.get("type") in ("pwm", "uart", "i2c", "clock") and r["id"] not in failing:
                failing[r["id"]] = g2_codes
            if r.get("status") not in ("satisfied", "waived") or r["id"] in failing:
                spec = ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("id", "status", "evidence") and v not in (None, ""))
                out.append({"id": r["id"], "summary": spec, "status": r.get("status"), "codes": failing.get(r["id"], [])})
        known = {u["id"] for u in out}
        out += [{"id": rid, "summary": "(requirement named by a failed check)", "status": "unknown", "codes": codes} for rid, codes in failing.items() if rid not in known]
        return out

    @staticmethod
    def _tried(state: AgentState) -> list[str]:
        tools = {}
        for o in state.observations:
            tools[o["tool"]] = tools.get(o["tool"], 0) + 1
        out = [f"{state.finish_attempts} answer attempt(s) submitted to the gates", f"{state.used['llm_calls']} model step(s), {state.used['tool_calls']} tool call(s)"]
        if state.iteration_counters:
            out.append("recurring problems: " + ", ".join(f"{c} x{n}" for c, n in sorted(state.iteration_counters.items(), key=lambda kv: -kv[1])[:6]))
        if state.plan:
            out.append("plan: " + ", ".join(f"{p['id']}={p['status']}" for p in state.plan))
        return out

    def _wrapup(self, state: AgentState, reason: str) -> str | None:
        """Một lời gọi cuối KHÔNG tool để viết câu trả lời tốt nhất khi chưa có bản nháp nào (bỏ qua nếu hết thời gian)."""
        if not self.escalate_wrapup or reason == "budget:wall_s":
            return None
        state.messages.append({"role": "user", "content": WRAPUP})
        try:
            resp = self.llm.chat(state.messages, [], seed=state.seed)
        except Exception as exc:
            state.errors.append(f"wrapup {type(exc).__name__}: {exc}")
            state.messages.pop()
            return None
        self._count_usage(state, resp)
        self._emit(state, "llm_call", tokens_in=resp.usage["in"], tokens_out=resp.usage["out"], wrapup=True)
        state.messages.append({"role": "assistant", "content": resp.content or ""})
        return (resp.content or "").strip() or None

    def _fallback_body(self, state: AgentState, reason: str, unmet: list[dict]) -> str:
        parts = ["I could not produce a verified answer within the limits of this run."]
        if state.plan:
            parts.append("Plan status:\n" + intake.plan_summary(state.plan))
        board = self._board_state()
        if board:
            parts.append(intake.board_summary(board))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ resume: tool dang chạy lúc chết
    def _interrupt_in_flight(self, state: AgentState) -> None:
        fl = state.in_flight
        call = next((c for c in state.pending_calls if c["id"] == fl["call_id"]), None)
        state.in_flight = None
        if call is None:
            return
        res = {"error": f"interrupted: the process stopped while {fl['tool']} was running, so its effect is unknown. It was NOT run again; read the state "
                        "(for example get_board_state) before deciding whether to repeat it."}
        text = self._emit_call(state, call["name"], call["arguments"], res)
        state.messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
        state.pending_calls = [c for c in state.pending_calls if c["id"] != call["id"]]
        self._checkpoint(state)

    # ================================================================== tiện ích
    def _emit(self, state: AgentState, type_: str, **fields) -> dict:
        state.seq += 1
        ev = {"type": type_, "run_id": state.run_id, "turn": state.turn, "step": state.used["steps"], "seq": state.seq, "ts": round(time.time(), 3), **fields}
        state.events.append(ev)
        return ev

    def _checkpoint(self, state: AgentState) -> None:
        now = time.monotonic()
        state.used["wall_s"] = round(state.used["wall_s"] + (now - self._tick), 3)
        self._tick = now
        self.store.save(state)

    def _terminate(self, state: AgentState, outcome: str, answer: str, status: str, reason: str = "", gate: dict | None = None) -> None:
        state.outcome, state.answer, state.status = outcome, answer, status
        state.pending_calls = []
        if outcome in ("blocked", "refused"):
            self._emit(state, "refused", reason=reason)
        self._emit(state, "done", status=outcome, answer_chars=len(answer))
        self._checkpoint(state)

    def _finalize(self, state: AgentState) -> dict:
        """Idempotent: lưu phiên (lịch sử + kế hoạch), ghi trace JSONL, dựng kết quả."""
        sess = self.store.session(state.project_id)
        if state.terminal and len(sess["history"]) == state.turn:
            ent = parse_entities(state.goal)
            sess["history"].append({"turn": state.turn, "user": state.goal, "answer": state.answer or "", "status": state.outcome, "chips": ent["chips"]})
            self.store.save_session(state.project_id, sess["history"], state.plan)
        if self.trace_dir:
            write_jsonl(self.trace_dir, state.run_id, state.events)
        u = state.used
        last_gate = next((a["gate"] for a in reversed(state.artifacts) if a.get("gate")), None)
        audit.log("answer", qid=state.run_id, session=state.project_id, status=state.outcome, answer=(state.answer or "")[:500])
        return {"run_id": state.run_id, "project_id": state.project_id, "turn": state.turn, "question": state.goal, "answer": state.answer or "",
                "status": STATUS_OF.get(state.outcome or "error", "error"), "events": list(state.events),
                "usage": {"tokens_in": u["tokens_in"], "tokens_out": u["tokens_out"], "usd": u["usd"], "llm_calls": u["llm_calls"], "tool_calls": u["tool_calls"], "steps": u["steps"]},
                "plan": list(state.plan), "board_state": self._board_state(), "gate": last_gate, "escalation": state.escalation, "files": {}, "errors": list(state.errors)}


class _InternalFailure:
    """Báo cáo thay thế khi Gate ném ngoại lệ: fail đóng (không bao giờ pass)."""

    passed = False
    sim = None

    def __init__(self, msg: str):
        from agent.gate.types import Finding
        self.findings = [Finding(gate="G1", code="GATE-INTERNAL-ERROR", where="gate", expected="the gate runs", actual=msg, hint_source="retry; if it persists the answer cannot be verified")]
        self.gates = {"G1": "fail", "G2": "na", "G3": "na", "G4": "na", "G5": "na"}
        self.details = {}

    def errors(self):
        return self.findings

    def failed_codes(self):
        return ["GATE-INTERNAL-ERROR"]

    def feedback(self):
        return {"passed": False, "gates": self.gates, "findings": [f.to_dict() for f in self.findings], "hint": "the gate failed internally; try again"}

    def to_dict(self):
        return {"passed": False, "gates": self.gates, "findings": [f.to_dict() for f in self.findings], "sim": None, "details": {}}
