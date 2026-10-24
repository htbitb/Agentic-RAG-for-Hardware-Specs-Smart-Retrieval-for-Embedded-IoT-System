"""Gate v3 — cổng kết thúc (P4_interfaces §2): G1 provenance, G2 functional, G3 board DRC, G4 safety, G5 compile.

`Gate(call, flags).run(ctx) -> GateReport`. `call(tool, args) -> dict` là cầu nối tới ToolHub. Gate chỉ gọi tool CHỈ ĐỌC (danh sách READ_ONLY_TOOLS;
lời gọi khác bị từ chối), không import `config`, không đọc env, không ghi file. Tool lỗi / ném ngoại lệ không bao giờ làm Gate ném: thành finding
severity "unknown" + gate "skipped" (không bao giờ là pass). Kết quả tất định với cùng output của tool (mỗi lời gọi giống nhau chỉ thực hiện một lần).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Callable

from . import codeblocks, compile_gate, drc_gate, functional, provenance, safety
from .types import Finding, GateReport, requirement_id, tool_error

__all__ = ["Gate", "GateContext", "GateFlags", "GateReport", "Finding", "READ_ONLY_TOOLS"]

GATES = ("G1", "G2", "G3", "G4", "G5")
READ_ONLY_TOOLS = frozenset({"get_board_state", "run_drc", "analyze_c_code", "simulate_register_writes", "compile_check", "get_electrical_specs",
                             "get_clock_limits"})
DEFAULT_CHIP = "stm32g474"


@dataclass
class GateFlags:
    g1: bool = True
    g2: bool = True
    g3: bool = True
    g4: bool = True
    g5: bool = True
    board: bool = True                       # False (A2): không đọc Board State -> G3 off, G2 không có requirement
    strict_v1_provenance: bool = False       # True (A3): G1 = agent/verifier.py::verify
    waivable: tuple[str, ...] = ("G2-UNMODELED", "G5-SKIPPED")


@dataclass
class GateContext:
    answer: str
    user_texts: list[str]
    observations: list[dict]
    prior_answers: list[str] = ()
    waived: list[dict] = ()
    chip: str | None = None
    initial: str | dict = "reset"
    hse_hz: int | None = None
    start: dict | None = None                # D36: trạng thái khởi đầu do INTAKE trích từ lời người dùng/Board State {initial, hse_hz, source}


def _short(args: dict) -> dict:
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) > 80:
            out[k] = f"<{len(v)} chars>"
        elif isinstance(v, (list, dict)) and len(json.dumps(v, default=str)) > 200:
            out[k] = f"<{len(v)} items>"
        else:
            out[k] = v
    return out


class _Caller:
    """`call` an toàn: chỉ tool đọc, bắt ngoại lệ, chuẩn hoá kết quả không phải dict, ghi nhật ký, nhớ kết quả theo (tool, args)."""

    def __init__(self, call: Callable[[str, dict], dict]):
        self._call = call
        self.memo: dict = {}
        self.log: list[dict] = []

    def __call__(self, name: str, args: dict) -> dict:
        if name not in READ_ONLY_TOOLS:
            return {"error": f"the gate may only call read-only tools; {name!r} refused"}
        key = (name, json.dumps(args, sort_keys=True, default=str))
        if key not in self.memo:
            try:
                res = self._call(name, dict(args))
            except Exception as exc:                                         # noqa: BLE001 — lỗi tool không bao giờ làm Gate ném
                res = {"error": f"{type(exc).__name__}: {exc}"}
            if not isinstance(res, dict):
                res = {"error": f"unexpected result type {type(res).__name__}"}
            self.memo[key] = res
            err = tool_error(res)
            self.log.append({"tool": name, "args": _short(args), "ok": err is None, "error": err})
        return self.memo[key]


def _internal(gate: str, exc: Exception, closed: bool = False) -> Finding:
    """closed=True (cổng có thứ phải kiểm: claim/trích dẫn cho G1, code + requirement cho G2, target cho G3, điện áp/target/code cho G4, code cho G5):
    lỗi nội bộ là ERROR — câu trả lời không được coi là đã kiểm (fail closed)."""
    return Finding(gate=gate, code=f"{gate}-INTERNAL-ERROR", where=f"gate {gate}", expected=f"{gate} evaluated", actual=f"{type(exc).__name__}: {exc}",
                   hint_source="Gate implementation (report this bug); " + ("the answer cannot be verified and is not accepted" if closed
                                                                             else "the gate is skipped and never counted as a pass"),
                   severity="error" if closed else "unknown", kind="local")


def _material(fn) -> bool:
    """Câu trả lời có thứ mà cổng phải kiểm? Nếu chính việc xác định ném lỗi thì coi như CÓ (đóng khi lỗi)."""
    try:
        return bool(fn())
    except Exception:                                                           # noqa: BLE001
        return True


def _apply_waivers(findings: list[Finding], waived, allowed: tuple) -> tuple[list[Finding], list[dict], list[dict]]:
    """`waivable` theo cờ; miễn (finish waived_requirements) theo id requirement (`where` = 'requirement <id>' hoặc 'requirement "<id có khoảng trắng>"');
    id là mã finding chỉ áp cho finding KHÔNG gắn với requirement (vd G5-SKIPPED); lý do phải không rỗng."""
    waivers = [w for w in (waived or []) if isinstance(w, dict) and w.get("id")]
    applied, rejected, out = [], [], []
    for w in waivers:
        if not str(w.get("reason") or "").strip():
            rejected.append({"id": str(w["id"]), "code": None, "why": "a waiver needs a non-empty reason"})
    good = {str(w["id"]): str(w["reason"]).strip() for w in waivers if str(w.get("reason") or "").strip()}
    for f in findings:
        f = replace(f, waivable=f.code in allowed)
        req = requirement_id(f.where)
        rid = req if req in good else (f.code if f.code in good and req is None else None)
        if rid is None and req is not None and f.code in good and f.severity == "error" and not any(r["id"] == f.code for r in rejected):
            rejected.append({"id": f.code, "code": f.code, "why": f"{f.code} belongs to requirement {req}: waive it by the requirement id, not by the code"})
        if rid is not None and f.severity in ("error", "unknown"):
            if f.waivable:
                applied.append({"id": rid, "code": f.code, "where": f.where, "reason": good[rid], "gate": f.gate})
                f = replace(f, severity="warning")
            elif f.severity == "error":
                rejected.append({"id": rid, "code": f.code, "why": f"{f.code} cannot be waived (allowed: {', '.join(allowed) or 'none'})"})
                f = replace(f, actual=f"{f.actual} [waiver for {rid} not applied: {f.code} cannot be waived]")
        out.append(f)
    return out, applied, rejected


class Gate:
    def __init__(self, call: Callable[[str, dict], dict], flags: GateFlags | None = None):
        self.call = call
        self.flags = flags or GateFlags()

    def safety_only(self, ctx: GateContext) -> GateReport:
        """Chỉ cổng an toàn G4 (I5): dùng cho văn bản wrap-up khi leo thang, nơi chạy cả Gate sẽ vô nghĩa nhưng không được để lọt lời khuyên không an toàn."""
        return Gate(self.call, replace(self.flags, g1=False, g2=False, g3=False, g5=False)).run(ctx)

    def run(self, ctx: GateContext) -> GateReport:
        fl = self.flags
        call = _Caller(self.call)
        status = {g: "off" for g in GATES}
        found: dict[str, list[Finding]] = {g: [] for g in GATES}
        details: dict = {"calls": call.log, "requirements_checked": 0, "unknown_codes": []}
        sim = None

        def guarded(g, fn, closed=False):
            try:
                fn()
            except Exception as exc:                                         # noqa: BLE001 — một cổng lỗi không làm hỏng các cổng khác
                status[g], found[g] = "skipped", [_internal(g, exc, closed)]
                details.setdefault("internal_errors", []).append(f"{g}: {type(exc).__name__}: {exc}")

        state = state_err = reqs = req_err = None
        if fl.board and (fl.g3 or fl.g4 or (fl.g2 and not ctx.chip)):
            r = call("get_board_state", {})
            state_err = tool_error(r) or (None if isinstance(r.get("state"), dict) else "no state in the result")
            state = None if state_err else r["state"]
        if fl.board and fl.g2:
            r = call("get_board_state", {"section": "requirements"})
            req_err = tool_error(r) or (None if isinstance(r.get("data"), list) else "no requirement list in the result")
            reqs = None if req_err else r["data"]
        chip = ctx.chip or next((t.get("chip") for t in (state or {}).get("targets") or [] if t.get("chip")), None) or DEFAULT_CHIP
        prog = codeblocks.program(ctx.answer)
        fres = drc = None
        has_targets = bool((state or {}).get("targets"))
        prose_volts = _material(lambda: any(q.base == "V" for q in codeblocks.quantities(codeblocks.prose(ctx.answer))))

        if fl.g1:
            def g1():
                st, fs, d = provenance.check(ctx.answer, list(ctx.user_texts), list(ctx.observations), list(ctx.prior_answers), fl.strict_v1_provenance)
                status["G1"], found["G1"], details["G1"] = st, fs, d
                details["claims_checked"] = d.get("claims_checked", 0)
                details["supported_by"] = d.get("supported_by", {})
            p = codeblocks.prose
            guarded("G1", g1, _material(lambda: provenance._claims(p(ctx.answer)) or provenance._citations(p(ctx.answer))))
        if fl.g2:
            def g2():
                nonlocal fres, sim
                fres = functional.run(call, prog, reqs, req_err, chip, ctx.initial, ctx.hse_hz, list(ctx.observations), ctx.start)
                status["G2"], found["G2"], sim = fres.status, fres.findings, fres.sim
                details["G2"] = fres.details
                details["start"] = fres.details.get("start")
                details["requirements_checked"] = fres.details.get("requirements_checked", 0)
                details["not_rechecked"] = fres.details.get("not_rechecked", [])
            closed = prog is not None and any(isinstance(r, dict) and str(r.get("type") or "").strip().lower() in functional.SIM_TYPES for r in reqs or [])
            guarded("G2", g2, closed)
        if fl.g3 and fl.board:
            def g3():
                nonlocal drc
                res = drc_gate.run(call, state, state_err)
                status["G3"], found["G3"], drc = res.status, res.findings, res.drc
                details["G3"] = res.details
                details["unknown_codes"] = res.details.get("unknown_codes", [])
            guarded("G3", g3, has_targets)
        if fl.g4:
            def g4():
                report_drc = status["G3"] not in ("off", "skipped") and drc is not None
                res = safety.run(call, chip, codeblocks.prose(ctx.answer), state if fl.board else None, drc, fres, prog, report_drc, list(ctx.observations))
                status["G4"], found["G4"] = res.status, res.findings
                details["G4"] = res.details
            guarded("G4", g4, has_targets or prog is not None or prose_volts)
        if fl.g5:
            def g5():
                res = compile_gate.run(call, prog, chip)
                status["G5"], found["G5"] = res.status, res.findings
                details["G5"] = res.details
            guarded("G5", g5, prog is not None)

        findings, applied, rejected = _apply_waivers([f for g in GATES for f in found[g]], ctx.waived, tuple(fl.waivable))
        details["waived"], details["waivers_rejected"] = applied, rejected
        for g in GATES:
            if status[g] == "off":
                continue
            if any(f.gate == g and f.severity == "error" for f in findings):
                status[g] = "fail"
            elif any(w["gate"] == g for w in applied) or status[g] == "fail":
                status[g] = "skipped"                                           # miễn trừ: câu trả lời có thể qua, nhưng cổng KHÔNG "pass" (I7)
        for w in applied:
            w.pop("gate", None)
        return GateReport(gates=status, findings=findings, sim=sim, details=details)
