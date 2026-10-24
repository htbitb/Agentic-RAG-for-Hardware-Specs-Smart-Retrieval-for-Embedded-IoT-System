"""G4 Safety (P4_interfaces §2.3). Mọi finding G4 là structural (trừ unknown do hạ tầng/thiếu dữ liệu).

(i)  Board State: VDD của target > Absolute Maximum (get_electrical_specs) -> G4-VDD-ABS-MAX; nguồn >= 4,0 V đẩy vào chân MCU vượt mức vào tối đa
     (đọc phần `nets` của run_drc) -> G4-5V-NON-FT, CHỈ khi G3 không báo DRC cho agent (không nhân đôi DRC-ELEC-01).
(ii) Mô phỏng của G2: violation SIM-CLK-LIMIT* -> G4-CLOCK-LIMIT (không tự mô phỏng lại khi G2 tắt).
(iii) Văn xuôi (câu không có phủ định/cảnh báo tiếng Anh hoặc tiếng Việt): luật tiếng Anh (guardrail.parse_hardware_requests + evaluate_hw), rồi luật
     không phụ thuộc ngôn ngữ cho câu luật tiếng Anh không bắt: một điện áp > Absolute Maximum của chip trong cùng câu với VDD/VBAT/nguồn/tên chip.
     Bảo thủ: error chỉ khi câu là lời khuyên/cho phép (EN: apply/connect/you can...; VI: cấp, nối, đưa, dùng, có thể, hãy...) và nhắc nguồn của MCU
     (VDD/VBAT/VREF/MCU/tên chip); chân (không biết FT hay không), thiết bị khác hoặc câu khẳng định -> warning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent import guardrail
from ingestion.unit_normalizer import eval_vdd_expr

from . import codeblocks, functional
from .types import Finding, tool_error

FIVE_VOLT_RAIL = 4.0
_MCU_SUPPLY = re.compile(r"(?<!\w)(V_?DD\w*|VBAT|VREF\+?|MCU|microcontroller|vi điều khiển|STM32\w*|ESP32\w*|nRF\w*)(?!\w)", re.I)
_SUPPLY = re.compile(r"(?<!\w)(V_?DD\w*|VBAT|VREF\+?|supply|rail|nguồn|MCU|microcontroller|vi điều khiển|STM32\w*|ESP32\w*|nRF\w*)(?!\w)", re.I)
_DRIVES = re.compile(r"drives up to ([\d.]+) V")
_CONVERSION = re.compile(r"(?<!\w)(LDO|regulators?|buck|boost|converters?|DC-?DC|dc/dc|step[- ]down|level[- ]shifters?|dividers?|hạ áp|ổn áp|"
                         r"chuyển đổi|bộ chia|mạch hạ|hạ xuống)(?!\w)", re.I)
_PIN = re.compile(r"(?<!\w)(P[A-K]\d{1,2}|pin|chân)(?!\w)", re.I)
_FT = re.compile(r"(?<!\w)(FT|FT_\w+|5\s*V[- ]tolerant|chịu\s*(?:được\s*)?5\s*V)(?!\w)", re.I)


@dataclass
class SafetyResult:
    status: str                        # pass | skipped  ("fail" do Gate suy ra)
    findings: list[Finding]
    details: dict = field(default_factory=dict)


def _F(code, where, expected, actual, hint, severity="error", kind="structural") -> Finding:
    return Finding(gate="G4", code=code, where=where, expected=expected, actual=actual, hint_source=hint, severity=severity, kind=kind)


def _tool(name, err) -> Finding:
    return _F("G4-TOOL-ERROR", f"tool {name}", f"a {name} result", f"{name} failed: {err}",
              f"{name} (infrastructure problem; the check is skipped and never counted as a pass)", severity="unknown", kind="local")


class _Limits:
    """Dòng get_electrical_specs của chip: lấy từ observations nếu đã có, ngược lại gọi tool (mỗi truy vấn một lần)."""

    def __init__(self, call, chip, observations):
        self.call, self.chip = call, chip
        self.rows = [r for o in observations if isinstance(o, dict) and o.get("tool") == "get_electrical_specs" and isinstance(o.get("result"), dict)
                     and o["result"].get("chip") in (None, chip) for r in o["result"].get("results") or [] if isinstance(r, dict)]
        self.asked: set[str] = set()
        self.errors: list[Finding] = []

    def facts(self, field_types: tuple, parameter: str) -> list[dict]:
        have = [r for r in self.rows if r.get("field_type") in field_types]
        if have or parameter in self.asked:
            return have
        self.asked.add(parameter)
        res = self.call("get_electrical_specs", {"chip": self.chip, "parameter": parameter})
        err = tool_error(res)
        if err:
            self.errors.append(_tool("get_electrical_specs", err))
            return []
        self.rows += [r for r in res.get("results") or [] if isinstance(r, dict)]
        return [r for r in self.rows if r.get("field_type") in field_types]


def _vdd_checks(state, limits: _Limits, call, observations) -> list[Finding]:
    """Mỗi target so với giới hạn của CHÍNH chip đó (bo nhiều MCU: STM32G474 4,0 V, ESP32 3,6 V...)."""
    out = []
    for t in state.get("targets") or []:
        vdd = t.get("vdd")
        if not isinstance(vdd, (int, float)):
            continue
        lim_t = limits if t.get("chip") == limits.chip else _Limits(call, t.get("chip"), observations)
        rows = [r for r in lim_t.facts(("supply_voltage",), "supply voltage") if r.get("category") == "absolute_max"]
        if lim_t is not limits:
            limits.errors += lim_t.errors
        maxima = [(eval_vdd_expr(r.get("max"), vdd), r) for r in rows if r.get("max") not in (None, "")]
        maxima = [(m, r) for m, r in maxima if m is not None]
        if not maxima:
            if not lim_t.errors:
                out.append(_F("G4-LIMIT-UNKNOWN", f"board.targets.{t.get('chip')}.vdd", "a known absolute maximum supply voltage",
                              f"the database has no absolute-maximum VDD for {t.get('chip')}", "get_electrical_specs", severity="unknown", kind="local"))
            continue
        lim, row = min(maxima, key=lambda x: x[0])
        if vdd > lim + 1e-9:
            out.append(_F("G4-VDD-ABS-MAX", f"board.targets.{t['chip']}.vdd", f"VDD <= absolute maximum {lim:g} V ({row.get('doc')} p.{row.get('page')})",
                          f"target {t['chip']} VDD = {vdd:g} V", "get_electrical_specs(chip, 'supply voltage'); set_target with a supply inside the ratings"))
    return out


def _five_volt(state, drc, report_drc) -> tuple[list[Finding], list[str]]:
    chips = {str(t.get("chip")).lower() for t in state.get("targets") or []}
    found, reported = [], []
    for net in (drc or {}).get("nets") or []:
        for chk in net.get("checks") or []:
            if chk.get("rule") != "VOH_max <= input max" or chk.get("status") != "FAIL":
                continue
            dst = str(chk.get("direction", "")).split("->")[-1].strip()
            m = _DRIVES.search(chk.get("detail", ""))
            if dst.split(".")[0].lower() not in chips or not m or float(m.group(1)) < FIVE_VOLT_RAIL:
                continue
            label = f"{net.get('from')} -> {net.get('to')}"
            if report_drc:
                reported.append(label)
                continue
            found.append(_F("G4-5V-NON-FT", f"board.nets[{label}]", f"no voltage above the input maximum of {dst} (non-FT pins accept about VDD + 0.3 V)",
                            chk.get("detail", ""), "connect to a 5 V tolerant (FT) pin, or add a level shifter / divider (connect, add_device, get_electrical_specs)"))
    return found, reported


def _clock_limits(fres, prog) -> list[Finding]:
    out = []
    raw = fres.raw if fres is not None else None
    for v in (raw or {}).get("violations") or []:
        if str(v.get("code", "")).startswith("SIM-CLK-LIMIT") and v.get("severity") == "error":
            out.append(_F("G4-CLOCK-LIMIT", functional._violation_where(v, fres.ops, prog), "clock frequencies within the datasheet limits",
                          str(v.get("msg") or v.get("limit")), "set_clock_config / get_clock_limits; RCC_PLLCFGR (PLLM/PLLN/PLLR), PWR_CR5.R1MODE"))
    return out


def _abs_max_supply(limits: _Limits, vdd: float):
    rows = [r for r in limits.facts(("supply_voltage",), "supply voltage") if r.get("category") == "absolute_max" and r.get("max") not in (None, "")]
    maxima = [(m, r) for m, r in ((eval_vdd_expr(r.get("max"), vdd), r) for r in rows) if m is not None]
    return min(maxima, key=lambda x: x[0]) if maxima else (None, None)


def _ft_pin_limit(limits: _Limits, vdd: float):
    """Giới hạn vào của chân FT (5 V tolerant) theo DB: dòng absolute_max 'Input voltage on FT_xxx pins' (VDD + 4,0 V)."""
    rows = [r for r in limits.facts(("input_voltage", "input_voltage_high"), "input voltage")
            if r.get("category") == "absolute_max" and str(r.get("applies_to") or "").startswith("FT") and r.get("max") not in (None, "")]
    maxima = [(m, r) for m, r in ((eval_vdd_expr(r.get("max"), vdd), r) for r in rows) if m is not None]
    return max(maxima, key=lambda x: x[0]) if maxima else (None, None)


def _ft_pin(s: str) -> bool:
    return bool(_PIN.search(s) and _FT.search(s))


def _any_language(s: str, chip: str, vdd: float, limits: _Limits) -> list[Finding]:
    """Luật không phụ thuộc ngôn ngữ: điện áp GẦN NHẤT với VDD/VBAT/nguồn/tên chip > Absolute Maximum, trong câu không phủ định và không phải câu
    chuyển đổi nguồn (LDO, buck, bộ chia...). Chân được mô tả là FT dùng giới hạn chân FT (VDD + 4,0 V), không phải giới hạn nguồn."""
    volts = [q for q in codeblocks.quantities(s) if q.base == "V" and not q.unknown and q.si]
    anchors = [m.start() for m in _SUPPLY.finditer(s)] + [m.start() for m in re.finditer(re.escape(chip), s, re.I)]
    if not volts or not anchors or _CONVERSION.search(s):
        return []
    nearest = min(volts, key=lambda q: min(abs(q.start - a) for a in anchors))
    lim, row = _ft_pin_limit(limits, vdd) if _ft_pin(s) else _abs_max_supply(limits, vdd)
    over = [v for v in nearest.si if lim is not None and v > lim + 1e-9]
    if not over:
        return []
    sure = codeblocks.is_advice(s) and bool(_MCU_SUPPLY.search(s) or chip.lower() in s.lower())
    src = f"{row.get('doc')} p.{row.get('page')}" if row.get("doc") else "datasheet"
    return [_F("G4-ABS-MAX", f'answer: "{s[:160]}"', f"no advice to apply more than the absolute maximum {lim:g} V ({src})",
               f"{max(over):g} V stated next to a supply/VDD/chip mention" + ("" if sure else " (not an explicit recommendation for the MCU supply: check)"),
               "get_electrical_specs(chip, 'supply voltage'); rephrase as a warning or remove the value", severity="error" if sure else "warning")]


def _prose_checks(prose, state, chip, limits: _Limits) -> list[Finding]:
    out = []
    vdd = next((float(t["vdd"]) for t in (state or {}).get("targets") or [] if isinstance(t.get("vdd"), (int, float))), 3.3)
    for _, _, s in codeblocks.sentences(prose or ""):
        if codeblocks.has_negation(s):
            continue
        reqs = guardrail.parse_hardware_requests(s)
        if reqs and _CONVERSION.search(s):
            lim, _ = _abs_max_supply(limits, vdd)                            # chuỗi nguồn (5 V -> LDO -> 3,3 V): chỉ xét khi MỌI điện áp đều vượt
            if lim is None or any(r["volts"] <= lim + 1e-9 for r in reqs):
                continue
        for req in reqs:
            if req["target"] == "supply":
                facts = limits.facts(("supply_voltage",), "supply voltage")
            else:
                facts = limits.facts(("input_voltage", "input_voltage_high"), "input voltage")
                if _ft_pin(s):
                    facts = [f for f in facts if str(f.get("applies_to") or "").startswith("FT") or f.get("category") != "absolute_max"]
            v = guardrail.evaluate_hw(req, facts, vdd)
            if v["verdict"] not in ("refuse", "warn"):
                continue
            fact = v.get("fact") or {}
            src = f"{fact.get('doc')} p.{fact.get('page')}" if fact.get("doc") else "datasheet"
            where = f'answer: "{s[:160]}"'
            if v["verdict"] == "refuse":
                sure = req["target"] == "supply" and codeblocks.is_advice(s) and bool(_MCU_SUPPLY.search(s) or chip.lower() in s.lower())
                out.append(_F("G4-ABS-MAX", where, f"no advice to apply more than the absolute maximum {v['limit']:g} V ({src})",
                              f"advises {req['text']} on a {req['target']}" + ("" if sure else " (target uncertain: check whether it is the MCU / a 5 V tolerant pin)"),
                              "get_electrical_specs(chip, 'supply voltage' / 'input voltage'); rephrase as a warning or remove the advice",
                              severity="error" if sure else "warning"))
            else:
                out.append(_F("G4-OPERATING-RANGE", where, f"within the recommended operating range (max {v['limit']:g} V, {src})", f"advises {req['text']}",
                              "get_electrical_specs(chip, 'supply voltage', category='recommended_operating')", severity="warning"))
        if not reqs:                                                          # câu luật tiếng Anh đã xét thì không xét lại
            out += _any_language(s, chip, vdd, limits)
    return out


def run(call, chip: str, prose: str, state: dict | None, drc: dict | None, fres, prog, report_drc: bool, observations: list) -> SafetyResult:
    limits = _Limits(call, chip, observations)
    findings: list[Finding] = []
    details: dict = {}
    if state is not None:
        findings += _vdd_checks(state, limits, call, observations)
        if drc is None and not report_drc and state.get("targets"):
            res = call("run_drc", {})
            err = tool_error(res)
            if err:
                findings.append(_tool("run_drc", err))
            else:
                drc = res
        five, reported = _five_volt(state, drc, report_drc)
        findings += five
        details["five_volt_reported_by_drc"] = reported
    findings += _clock_limits(fres, prog)
    details["clock_checked"] = fres is not None and fres.raw is not None
    findings += _prose_checks(prose, state, chip, limits)
    findings += limits.errors
    skipped = any(f.code == "G4-TOOL-ERROR" for f in findings)
    return SafetyResult("skipped" if skipped else "pass", findings, details)
