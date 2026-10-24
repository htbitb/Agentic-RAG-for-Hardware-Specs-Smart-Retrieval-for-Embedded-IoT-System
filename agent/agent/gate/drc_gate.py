"""G3 Board DRC (P4_interfaces §2.3): `run_drc` trên Board State. Vi phạm error -> Finding chặn (code = mã luật DRC, mã con nằm trong `actual`);
unknown (vd DRC-PWR-01 khi DB không có số dòng) -> Finding severity unknown: báo, không chặn, KHÔNG tính pass; warning -> warning.
Chưa set_target -> na. kind: DRC-CLK-02 / DRC-REQ-01 local, các luật còn lại structural (cần lập lại kế hoạch)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .types import Finding, requirement_ref, tool_error

LOCAL_RULES = frozenset({"DRC-CLK-02", "DRC-REQ-01"})
_RULES = {   # luật -> (điều mong đợi, nguồn giúp sửa)
    "DRC-PIN-01": ("one owner per pin (sharing only for a declared I2C/SPI/CAN bus)", "allocate_pin / release_pin (use a free alternative pin listed by the error)"),
    "DRC-PIN-02": ("the signal in the pin's alternate-function table and the pin bonded out in the package", "find_pins_for_signal / query_pin_alternate_function"),
    "DRC-PIN-03": ("no output function on an input-only pin", "find_pins_for_signal (choose an output-capable pin) / allocate_pin"),
    "DRC-CLK-01": ("derived clock frequencies within the datasheet limits", "set_clock_config / get_clock_limits"),
    "DRC-CLK-02": ("the RCC clock enabled for every used peripheral", "set_clock_config(enabled_peripherals=[...]) and the RCC enable bit in the code"),
    "DRC-ELEC-01": ("compatible logic levels between voltage domains and no 5 V on a non-FT pin", "connect / add_device (level shifter or a 5 V tolerant pin) / get_electrical_specs"),
    "DRC-PWR-01": ("total supply current within the power budget of each mode", "get_power_budget / add_device(i_ua_by_mode=...)"),
    "DRC-REQ-01": ("every requirement satisfied (with evidence) or waived with a reason",
                   "set_requirements([{id, status: 'satisfied', evidence: 'sim#...'}]) after verifying, or status 'waived' with waiver_reason"),
}


@dataclass
class DrcResult:
    status: str                        # pass | skipped | na  ("fail" do Gate suy ra)
    findings: list[Finding]
    details: dict = field(default_factory=dict)
    drc: dict | None = None            # kết quả run_drc đầy đủ (G4 dùng phần `nets`)


def _where(v: dict) -> str:
    rule, code = v.get("rule"), str(v.get("code", ""))
    sub = code.split(":", 1)[1] if ":" in code else ""
    if code.startswith("REQ_") and sub:
        return requirement_ref(sub)
    if v.get("pin"):
        return f"board.pins.{v['pin']}"
    if v.get("net"):
        return f"board.nets[{v['net']}]"
    if rule == "DRC-PWR-01":
        return f"board.power[{v.get('mode') or sub}]"
    if v.get("peripheral") or (rule == "DRC-CLK-02" and sub):
        return f"board.peripherals.{v.get('peripheral') or sub}"
    if rule in ("DRC-CLK-01", "DRC-CLK-02"):
        return "board.clock"
    return "board"


def _evidence(v: dict) -> str:
    ev = v.get("evidence")
    items = ev if isinstance(ev, list) else [ev] if isinstance(ev, dict) else []
    refs = [f"{e.get('doc')} p.{e.get('page')}" for e in items if isinstance(e, dict) and e.get("doc") and e.get("page")]
    return f"; source: {', '.join(dict.fromkeys(refs))}" if refs else ""


def _actual(v: dict) -> str:
    out = f"{v.get('code')}: {v.get('message', '')}"
    alts = [a for a in v.get("alternatives") or [] if isinstance(a, dict) and a.get("pin")]
    if alts and "free pins that carry it" not in out:
        out += "; alternatives: " + ", ".join(f"{a['pin']}" + (f" (AF{a['af']})" if a.get("af") is not None else "") for a in alts[:6])
    return out


def _finding(v: dict) -> Finding:
    rule = str(v.get("rule") or "DRC")
    expected, hint = _RULES.get(rule, ("a clean design rule check", "run_drc"))
    severity = v.get("severity") if v.get("severity") in ("error", "warning", "unknown") else "unknown"
    return Finding(gate="G3", code=rule, where=_where(v), expected=expected, actual=_actual(v), hint_source=hint + _evidence(v), severity=severity,
                   kind="local" if rule in LOCAL_RULES else "structural")


def _tool(name: str, err: str) -> Finding:
    return Finding(gate="G3", code="G3-TOOL-ERROR", where=f"tool {name}", expected=f"a {name} result", actual=f"{name} failed: {err}",
                   hint_source=f"{name} (infrastructure problem; G3 is skipped and never counted as a pass)", severity="unknown", kind="local")


def run(call, state: dict | None, state_error: str | None) -> DrcResult:
    if state_error or not isinstance(state, dict):
        return DrcResult("skipped", [_tool("get_board_state", state_error or "no state returned")])
    if not state.get("targets"):
        return DrcResult("na", [], {"reason": "no target chip set (set_target)"})
    res = call("run_drc", {})
    err = tool_error(res) or (None if isinstance(res.get("violations"), list) else "malformed run_drc result")
    if err:
        return DrcResult("skipped", [_tool("run_drc", err)])
    findings = [_finding(v) for v in res["violations"] if isinstance(v, dict)]
    details = {"unknown_codes": [v.get("code") for v in res["violations"] if isinstance(v, dict) and v.get("severity") == "unknown"],
               "ok": res.get("ok"), "complete": res.get("complete"), "version": res.get("version")}
    return DrcResult("pass", findings, details, res)
