"""G2 Functional (P4_interfaces §2.3): code C của câu trả lời -> analyze_c_code -> simulate_register_writes -> so `effects` với requirement.

Quy ước dung sai (viết lại độc lập, cùng nghĩa với grader functional_sim — không import `eval`): tần số/baud/clock theo tỉ lệ ±tol_pct %, duty theo
điểm phần trăm tuyệt đối ±duty_tol_pp (mặc định = tol_pct); I2C đạt khi dải [scl_hz_slow, scl_hz] của mô phỏng giao với scl_hz ±tol_pct %.
Violation chỉ tính khi LIÊN QUAN: mọi lỗi tại một lệnh (at_op) hoặc toàn cục, và lỗi cuối chuỗi gắn với tín hiệu/chân/ngoại vi của requirement.
Không có requirement (hoặc tắt Board State): lỗi tại lệnh + lỗi của kênh/ngoại vi ĐÃ NỐI CHÂN (đang được dùng thật); với đoạn lệnh rời (không có
hàm, được Gate bọc lại) thì lỗi cuối chuỗi và SIM-CLK-GATE chỉ là cảnh báo. Hệ quả của một ngoại vi bị khoá clock (SIM-CLK-GATE tại lệnh) không báo
lặp lại. `unmodeled` không bao giờ là pass: G2-UNMODELED (error, có thể xin miễn theo id requirement).
Đóng khi lỗi (fail closed): có code + requirement mô phỏng được mà G2 không chạy xong (preset sai, quá nhiều op, lỗi/timeout của tool) => finding ERROR;
unknown + skipped chỉ khi không có gì để kiểm (không code, không requirement mô phỏng được, chip không có mô hình).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from .codeblocks import Program
from .types import Finding, requirement_ref, tool_error

SIM_TYPES = frozenset({"pwm", "uart", "i2c", "clock"})
UNMODELED_TYPES = frozenset({"spi", "adc", "dac", "can", "gpio_out", "gpio_in"})
CLOCK_REGS = frozenset({"RCC_CR", "RCC_CFGR", "RCC_PLLCFGR", "FLASH_ACR", "PWR_CR1", "PWR_CR5"})
CLOCK_KEYS = ("sysclk_hz", "hclk_hz", "pclk1_hz", "pclk2_hz", "tim_clk_apb1_hz", "tim_clk_apb2_hz")
SERIAL = ("USART", "UART", "I2C")
FINAL_REGISTERS_MAX = 40
MAX_SIM_OPS = 2000                     # = mcp_servers.hw_sandbox_server.MAX_OPS (không import: server đó import `config`)
PLL_CLOCK_FIELDS = 0b11 | (0xF << 4) | (0x7F << 8) | (1 << 24) | (0b11 << 25)     # RCC_PLLCFGR: PLLSRC, PLLM, PLLN, PLLREN, PLLR (không phải PLLP/PLLQ)
STATUS_KEYS = frozenset({"status", "evidence", "waiver_reason"})                 # không phải trường đặc tả của requirement
_EFFECT_KEYS = ("kind", "pin", "signal", "timer", "channel", "pwm_hz", "duty_pct", "instance", "baud", "tx_pin", "rx_pin", "scl_hz", "scl_hz_slow",
                "scl_pin", "sda_pin", "active", "reason", "modeled")
_WAIVE = 'finish(waived_requirements=[{{"id": "{rid}", "reason": "<why it cannot be simulated>"}}])'

# mã mô phỏng -> (điều mong đợi, nguồn giúp sửa); {p} = ngoại vi
_SIM = {
    "SIM-CLK-GATE": ("{p} clock enabled in RCC before its first register access", "get_register_bitfields(RCC, <bus>ENR) for the {p}EN bit; RM0440 p.285"),
    "SIM-TIM-MOE": ("{p}_BDTR.MOE = 1 (advanced-timer main output enable)", "get_register_bitfields({p}, BDTR); RM0440 Table 282 p.1261"),
    "SIM-TIM-CEN": ("{p}_CR1.CEN = 1 (counter running)", "get_register_bitfields({p}, CR1)"),
    "SIM-TIM-CCE": ("{p}_CCER.CCxE = 1 for the output channel", "get_register_bitfields({p}, CCER)"),
    "SIM-TIM-OCM": ("{p}_CCMRx: CCxS = 00 and OCxM = 0110 (PWM mode 1) or 0111 (PWM mode 2)", "get_register_bitfields({p}, CCMR1)"),
    "SIM-TIM-ARR0": ("{p}_ARR > 0", "solve_timer_config"),
    "SIM-TIM-RANGE": ("ARR within the 16-bit counter of {p} (<= 65535)", "solve_timer_config (raises PSC) or a 32-bit timer (TIM2/TIM5)"),
    "SIM-GPIO-AF": ("the pin in alternate-function mode (MODER = 10) with the AF number of the signal", "query_pin_alternate_function / find_pins_for_signal"),
    "SIM-GPIO-MODE": ("the pin in alternate-function mode (MODER = 10) with the AF number of the signal", "query_pin_alternate_function / find_pins_for_signal"),
    "SIM-USART-UE": ("{p}_CR1.UE = 1", "get_register_bitfields({p}, CR1)"),
    "SIM-USART-TXRX": ("{p}_CR1.TE and/or RE = 1", "get_register_bitfields({p}, CR1)"),
    "SIM-USART-BRR": ("a valid {p}_BRR (USARTDIV >= 16; BRR[3] = 0 when OVER8 = 1)", "RM0440 §40.5.7 p.1707 (baud = f_ck / USARTDIV)"),
    "SIM-I2C-PE": ("{p}_CR1.PE = 1", "get_register_bitfields({p}, CR1)"),
    "SIM-I2C-TIMING": ("{p}_TIMINGR programmed before PE = 1", "RM0440 §39.4.9 p.1645 and Table 359/360 (TIMINGR examples)"),
    "SIM-WRITE-LOCKED": ("locked fields written while the peripheral is disabled (UE = 0 / PE = 0)", "write those fields before setting UE/PE (RM0440 p.1755, p.1681)"),
    "SIM-RCC-LOCKED": ("RCC_PLLCFGR written while PLLON = 0, and the SYSCLK source never switched off", "RM0440 p.292-293 (RCC_PLLCFGR, RCC_CR)"),
    "SIM-CLK-LIMIT": ("clock frequencies within the datasheet limits", "set_clock_config / get_clock_limits"),
    "SIM-CLK-NOSRC": ("SYSCLK switched only to a running, ready source (PLLREN = 1 for the PLL)", "get_register_bitfields(RCC, PLLCFGR); set_clock_config"),
    "SIM-FLASH-WS": ("FLASH_ACR.LATENCY high enough for HCLK", "RM0440 Table 9 p.98 (flash wait states)"),
    "SIM-CLK-PROC": ("the RM0440 clock-switch procedure (HPRE /2 before switching to a PLL above 80 MHz)", "RM0440 p.279-280"),
    "SIM-BADADDR": ("an existing, writable register", "search_registers / get_register_bitfields"),
}


@dataclass
class FunctionalResult:
    status: str                       # pass | skipped | na  ("fail" do Gate suy ra từ finding error)
    findings: list[Finding]
    sim: dict | None = None           # tóm tắt gọn, JSON-serializable (GateReport.sim)
    raw: dict | None = None           # kết quả mô phỏng đầy đủ (G4 dùng)
    details: dict = field(default_factory=dict)
    ops: list = field(default_factory=list)   # ops của analyze_c_code (để định vị violation trong code)


def _F(code, where, expected, actual, hint, severity="error", waivable=False) -> Finding:
    return Finding(gate="G2", code=code, where=where, expected=expected, actual=actual, hint_source=hint, severity=severity, kind="local", waivable=waivable)


def _num(x) -> str:
    x = float(x)
    return str(int(x)) if x.is_integer() else (f"{x:.1f}" if abs(x) >= 1e5 else f"{x:.6g}")


def _type(r: dict) -> str:
    return str(r.get("type") or "").strip().lower()


def _norm_pin(p) -> str:
    return str(p).strip().split(".")[-1].upper()


def _pins(r: dict) -> list[str]:
    ps = r.get("pins") if isinstance(r.get("pins"), (list, tuple)) else ([r["pin"]] if r.get("pin") else [])
    return [_norm_pin(p) for p in ps if isinstance(p, str) and p.strip()]


def _label(r: dict) -> str:
    typ = _type(r)
    if typ == "pwm":
        return f"{'/'.join(_pins(r)) or 'any pin'} PWM"
    if typ == "clock":
        return "clock tree"
    return f"{r.get('instance') or typ.upper()} {typ.upper() if typ in ('uart', 'i2c') else ''}".strip()


def _where(r: dict) -> str:
    return f"{requirement_ref(r.get('id'))} ({_label(r)})"


def _opt(r: dict, key: str, default=None, positive: bool = False):
    """Trường số tuỳ chọn của requirement / đối số tool: thiếu, null, sai kiểu hay không hữu hạn => giá trị mặc định (không bao giờ ném)."""
    v = r.get(key) if isinstance(r, dict) else None
    if v is None or isinstance(v, bool):
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x) or (positive and x <= 0):
        return default
    return x


def _periph(v: dict) -> str:
    if v.get("peripheral"):
        return str(v["peripheral"])
    for k in ("signal", "reg"):
        if v.get(k):
            return str(v[k]).split("_")[0]
    return "the peripheral"


def _preset(x) -> tuple[str | None, int | None]:
    """Tên preset (chuỗi) hoặc {"preset", "hse_hz"} — `ops` của một trạng thái khởi đầu dạng dict không bao giờ được dùng."""
    if isinstance(x, str) and x.strip():
        return x.strip(), None
    if isinstance(x, dict) and isinstance(x.get("preset"), str) and x["preset"].strip():
        hse = _opt(x, "hse_hz", positive=True)
        return x["preset"].strip(), int(hse) if hse else None
    return None, None


def _configures_clock(ops: list) -> bool:
    """Code tự cấu hình clock: ghi trường SW (bit 1:0) của RCC_CFGR, hoặc PLLSRC/PLLM/PLLN/PLLREN/PLLR của RCC_PLLCFGR (bật PLLQ/PLLP thì không)."""
    for op in ops or []:
        if not isinstance(op, dict) or op.get("op") == "read" or op.get("reg") not in ("RCC_CFGR", "RCC_PLLCFGR"):
            continue
        fields = 0b11 if op["reg"] == "RCC_CFGR" else PLL_CLOCK_FIELDS
        kind = op.get("op")
        if kind == "write" or op.get("field") in ("SW", "PLLSRC", "PLLM", "PLLN", "PLLREN", "PLLR"):
            return True
        if kind == "rmw":
            touched = (~int(op.get("and", 0xFFFF_FFFF)) | int(op.get("or", 0)) | int(op.get("xor", 0))) & fields
        else:
            touched = int(op.get("mask") or 0) & fields
        if touched:
            return True
    return False


def _last_agent_simulation(observations):
    """Đối số của lần simulate_register_writes THÀNH CÔNG gần nhất của agent mà `initial` là tên preset (dict bị bỏ qua hoàn toàn)."""
    for o in reversed(list(observations or [])):
        if not isinstance(o, dict) or o.get("tool") != "simulate_register_writes" or not isinstance(o.get("args"), dict):
            continue
        if tool_error(o.get("result")) is not None:
            continue
        initial = o["args"].get("initial", "reset")
        if isinstance(initial, str) and initial.strip():
            return initial.strip(), _opt(o["args"], "hse_hz", positive=True)
    return None


def resolve_start(reqs, ops, observations, ctx_initial, ctx_hse) -> tuple[str, int | None, str]:
    """Trạng thái khởi đầu: requirement (`initial`/`hse_hz`) > code tự cấu hình clock ("reset") > lần simulate THÀNH CÔNG gần nhất của agent
    > ctx.initial nếu khác "reset" > "reset". -> (initial, hse_hz, nguồn)."""
    req_init = req_hse = None
    for r in reqs or []:
        if isinstance(r, dict):
            name, hse = _preset(r.get("initial"))
            req_init = req_init or name
            req_hse = req_hse or hse or _opt(r, "hse_hz", positive=True)
    agent = _last_agent_simulation(observations)
    ctx_name, ctx_dict_hse = _preset(ctx_initial) if isinstance(ctx_initial, str) else (None, None)
    hse = req_hse or (agent[1] if agent else None) or _opt({"h": ctx_hse}, "h", positive=True) or ctx_dict_hse
    hse = int(hse) if hse else None
    if req_init:
        return req_init, hse, "requirement"
    if _configures_clock(ops):
        return "reset", hse, "code_configures_clock"
    if agent:
        return agent[0], hse, "agent_simulation"
    if ctx_name and ctx_name != "reset":
        return ctx_name, hse, "context"
    return "reset", hse, "default"


def _summary(sim: dict, initial) -> dict:
    out = {"ok": bool(sim.get("ok")), "violations": list(dict.fromkeys(v.get("code") for v in sim.get("violations", []))),
           "effects": [{k: e[k] for k in _EFFECT_KEYS if e.get(k) is not None} for e in sim.get("effects", [])],
           "unmodeled": list(sim.get("unmodeled") or []), "initial": sim.get("initial", initial), "n_ops": sim.get("n_ops"),
           "clocks": {k: (sim.get("clocks") or {}).get(k) for k in ("sysclk_hz", "hclk_hz", "pclk1_hz", "pclk2_hz") if k in (sim.get("clocks") or {})}}
    regs = sim.get("final_registers") or {}
    if len(regs) <= FINAL_REGISTERS_MAX:
        out["final_registers"] = dict(regs)
    return out


@dataclass
class _Scope:
    pins: set
    signals: set
    instances: set
    any_timer: bool


def _scope(reqs: list[dict], sim: dict) -> _Scope:
    s = _Scope(set(), set(), set(), False)
    effects = sim.get("effects", [])
    for r in reqs:
        typ = _type(r)
        if typ == "pwm":
            ps = set(_pins(r))
            if not ps:
                s.any_timer = True
            s.pins |= ps
            s.signals |= {e["signal"] for e in effects if e.get("pin") in ps and e.get("signal")}
            s.signals |= {sig for e in effects if e["kind"] == "pin_af" and e.get("pin") in ps for sig in e.get("signals", [])}
            if r.get("signal"):
                s.signals.add(r["signal"])
        elif typ in ("uart", "i2c"):
            s.instances |= {r["instance"]} if r.get("instance") else {e["instance"] for e in effects if e["kind"] == typ}
    return s


def _relevant(v: dict, scope: _Scope | None, sim: dict) -> bool:
    if v.get("severity") not in ("error", "warning"):
        return False
    if v.get("at_op") is not None or (not v.get("signal") and not v.get("peripheral")):
        return True
    if scope is None:                                                  # không requirement: chỉ kênh/ngoại vi đang được dùng thật (đã nối chân)
        if v.get("signal"):
            return bool(v.get("pin"))
        p = str(v["peripheral"])
        return not p.startswith(SERIAL) or any(e.get("instance") == p and any(e.get(k) for k in ("tx_pin", "rx_pin", "scl_pin", "sda_pin"))
                                               for e in sim.get("effects", []))
    if v.get("signal"):
        return v["signal"] in scope.signals or v.get("pin") in scope.pins or (scope.any_timer and str(v["signal"]).startswith("TIM"))
    return v["peripheral"] in scope.instances or not str(v["peripheral"]).startswith(SERIAL)


def _violation_where(v: dict, ops: list, prog: Program) -> str:
    i = v.get("at_op")
    if i is not None:
        op = ops[i] if isinstance(i, int) and 0 <= i < len(ops) else {}
        src = f" ({op['src']})" if op.get("src") else ""
        return f"{prog.locate(op.get('line'))}, op {i}{src}"
    if v.get("signal"):
        return f"{v['signal']} on {v['pin']} (end of program)" if v.get("pin") else f"{v['signal']}, not routed to any pin (end of program)"
    if v.get("peripheral"):
        return f"{v['peripheral']} (end of program)"
    return "clock tree (end of program)"


def _violation_finding(v: dict, ops: list, prog: Program) -> Finding:
    expected, hint = _SIM.get(v["code"], ("no simulator violation", "simulate_register_writes"))
    p = _periph(v)
    return _F(f"G2-{v['code']}", _violation_where(v, ops, prog), expected.format(p=p), str(v.get("msg") or v["code"]), hint.format(p=p),
              severity="error" if v["severity"] == "error" else "warning")


def _reason_hint(reason: str | None, p: str) -> str:
    return _SIM.get(reason or "", ("", "simulate_register_writes (effects)"))[1].format(p=p)


# ------------------------------------------------------------------------------------------------ từng loại requirement
def _pwm(r, sim, reported) -> list[Finding]:
    out: list[Finding] = []
    sig = r.get("signal")
    tol = _opt(r, "tol_pct", 1.0)
    dtol = _opt(r, "duty_tol_pp", tol)
    freq, duty = _opt(r, "freq_hz", positive=True), _opt(r, "duty_pct")
    effects = sim.get("effects", [])
    pwm = [e for e in effects if e["kind"] == "pwm"]
    where = _where(r)
    pins = _pins(r)

    def check_live(e, pin):
        found = []
        if freq is not None and e.get("pwm_hz") is None:
            found.append(_F("G2-FREQ", where, f"{_num(freq)} Hz ±{tol:g}%", f"the PWM frequency on {pin} cannot be determined (timer clock unknown, e.g. hse_hz)",
                            "simulate_register_writes with hse_hz / set_clock_config"))
        elif freq is not None and abs(e["pwm_hz"] - freq) / freq * 100 > tol:
            err = (e["pwm_hz"] - freq) / freq * 100
            found.append(_F("G2-FREQ", where, f"{_num(freq)} Hz ±{tol:g}%",
                            f"{_num(e['pwm_hz'])} Hz on {pin} ({e['signal']}: TIMxCLK {_num(e['timer_clk_hz'])} Hz, PSC = {e['psc']}, ARR = {e['arr']}; "
                            f"error {err:+.2f}%)", "solve_timer_config / formula f_TIM/((PSC+1)(ARR+1))"))
        if duty is not None and e.get("duty_pct") is not None and abs(e["duty_pct"] - duty) > dtol:
            found.append(_F("G2-DUTY", where, f"{duty:g}% ±{dtol:g} pp",
                            f"{e['duty_pct']:.4g}% on {pin} (CCR{e['channel']} = {e['ccr']}, ARR = {e['arr']})",
                            "solve_timer_config / duty = CCRx/(ARR+1) in PWM mode 1"))
        return found

    def check_effect(e, pin):
        if not e["active"]:
            if e.get("reason") not in reported:
                return [_F("G2-INACTIVE", where, f"PWM running on {pin}", f"inactive ({e.get('reason')}): {'; '.join(e.get('detail', []))}",
                           _reason_hint(e.get("reason"), e.get("timer") or ""))]
            return []
        if not e["modeled"]:
            feats = [u for u in sim.get("unmodeled", []) if str(u).startswith(f"{e.get('timer')}_")] or list(sim.get("unmodeled", []))
            return [_F("G2-UNMODELED", where, f"a simulated PWM on {pin} that can be compared with the requirement",
                       f"the PWM on {pin} depends on features the simulator does not model: {'; '.join(feats)}",
                       "simulate_register_writes (unmodeled): remove the unmodeled feature, or " + _WAIVE.format(rid=r.get("id")), waivable=True)]
        return check_live(e, pin)

    if not pins:                                                         # requirement không nêu chân: chấp nhận bất kỳ chân nào
        cands = [e for e in pwm if e.get("pin") and (not sig or e["signal"] == sig)]
        live = [e for e in cands if e["active"] and e["modeled"]]
        if any(not check_live(e, e["pin"]) for e in live):
            return []
        if live:
            best = min(live, key=lambda e: abs((e.get("pwm_hz") or 0) - (freq or e.get("pwm_hz") or 0)))
            return check_live(best, best["pin"])
        if cands:
            return check_effect(cands[0], cands[0]["pin"])
        return [_F("G2-NO-EFFECT", where, f"a PWM output{' (' + sig + ')' if sig else ''} on some pin", "no PWM output was found on any pin",
                   "simulate_register_writes (effects): enable the timer clock, route the channel to a pin (AF) and start the counter")]
    for pin in pins:
        effs = [e for e in pwm if e.get("pin") == pin and (not sig or e["signal"] == sig)]
        if effs:
            out += check_effect(effs[0], pin)
            continue
        same_pin = [e for e in pwm if e.get("pin") == pin]
        other = [e for e in pwm if e.get("pin") and e["pin"] not in pins and e["active"]]
        af = [e for e in effects if e["kind"] == "pin_af" and e.get("pin") == pin]
        expected = f"PWM ({sig or 'a timer channel'}) on {pin}"
        hint = "query_pin_alternate_function / find_pins_for_signal (pin <-> AF table)"
        if same_pin:
            out.append(_F("G2-PIN", where, expected, f"{pin} carries {same_pin[0]['signal']}, not {sig}", hint))
        elif other:
            out.append(_F("G2-PIN", where, expected, f"PWM is generated on {', '.join(sorted({e['pin'] for e in other}))} "
                                                     f"({other[0]['signal']}), not on {pin}", hint))
        elif af:
            out.append(_F("G2-PIN", where, expected, f"{pin} carries {af[0].get('signal') or 'AF%s' % af[0].get('af')} (AF{af[0].get('af')}), "
                                                     f"not {sig or 'a PWM output'}", hint))
        else:
            unrouted = [e for e in pwm if not e.get("pin") and (not sig or e["signal"] == sig)]
            if unrouted and unrouted[0].get("reasons") and unrouted[0]["reasons"][0] in reported:
                continue                                                 # đã báo bằng violation của simulator
            extra = "; ".join(f"{e['signal']}: {(e.get('detail') or [''])[0]}" for e in unrouted[:3])
            out.append(_F("G2-NO-EFFECT", where, expected, f"no PWM output was found on {pin}" + (f" (unrouted channels: {extra})" if extra else ""),
                          "simulate_register_writes (effects): enable the timer clock, set the pin AF and the channel output"))
    return out


def _serial_effect(r, sim, kind):
    inst = r.get("instance")
    effs = [e for e in sim.get("effects", []) if e["kind"] == kind and (not inst or e.get("instance") == inst)]
    return sorted(effs, key=lambda e: not e.get("active"))[0] if effs else None


def _inactive(r, e, reported, kind) -> list[Finding]:
    reason = e.get("reason")
    where = _where(r)
    inst = e.get("instance")
    if (kind == "uart" and reason == "SIM-CLK-UNKNOWN") or (kind == "i2c" and reason is None and not e.get("modeled")):
        return [_F("G2-UNMODELED", where, f"a simulated {inst} that can be compared with the requirement",
                   f"{inst} kernel clock source is not modeled ({e.get('kernel_source') or 'reserved selection'})",
                   "select a modeled kernel clock (PCLK/SYSCLK/HSI16), or " + _WAIVE.format(rid=r.get("id")), waivable=True)]
    if reason in reported:
        return []
    return [_F("G2-INACTIVE", where, f"{inst} enabled and running", f"inactive ({reason}): {'; '.join(e.get('detail', []))}",
               _reason_hint(reason, inst or ""))]


def _pin_checks(r, e, keys) -> list[Finding]:
    out = []
    for key in keys:
        want = r.get(key)
        if want and e.get(key) != _norm_pin(want):
            out.append(_F("G2-PIN", _where(r), f"{key.replace('_', ' ')} = {_norm_pin(want)}", f"{key.replace('_', ' ')} is {e.get(key) or 'not routed'}",
                          "query_pin_alternate_function / find_pins_for_signal (pin <-> AF table)"))
    return out


def _uart(r, sim, reported) -> list[Finding]:
    e = _serial_effect(r, sim, "uart")
    if e is None:
        return [_F("G2-NO-EFFECT", _where(r), f"{r.get('instance') or 'a USART'} configured and running", f"{r.get('instance') or 'no USART'} was never configured",
                   "simulate_register_writes (effects): enable the USART clock, program BRR and set UE/TE/RE")]
    if not e["active"]:
        return _inactive(r, e, reported, "uart")
    if not e["modeled"]:
        return [_F("G2-UNMODELED", _where(r), f"a simulated {e['instance']} that can be compared with the requirement",
                   f"{e['instance']} uses features the simulator does not model: {'; '.join(u for u in sim.get('unmodeled', []) if e['instance'] in u)}",
                   "simulate_register_writes (unmodeled): remove the feature, or " + _WAIVE.format(rid=r.get("id")), waivable=True)]
    out = []
    tol = _opt(r, "tol_pct", 2.0)
    baud = _opt(r, "baud", positive=True)
    if baud and abs(e["baud"] - baud) / baud * 100 > tol:
        out.append(_F("G2-BAUD", _where(r), f"{_num(baud)} baud ±{tol:g}%",
                      f"{_num(e['baud'])} baud ({e['instance']}: USARTDIV = {e['usartdiv']}, kernel {e['kernel_source']} = {_num(e['kernel_clk_hz'])} Hz, "
                      f"OVER8 = {e['over8']})", "RM0440 §40.5.7 p.1707: BRR = f_ck / baud (OVER8 = 0); simulate_register_writes"))
    return out + _pin_checks(r, e, ("tx_pin", "rx_pin"))


def _i2c(r, sim, reported) -> list[Finding]:
    e = _serial_effect(r, sim, "i2c")
    if e is None:
        return [_F("G2-NO-EFFECT", _where(r), f"{r.get('instance') or 'an I2C'} configured and running", f"{r.get('instance') or 'no I2C'} was never configured",
                   "simulate_register_writes (effects): enable the I2C clock, program TIMINGR and set PE")]
    if not e["active"]:
        return _inactive(r, e, reported, "i2c")
    out = []
    tol = _opt(r, "tol_pct", 5.0)
    target = _opt(r, "scl_hz", positive=True)
    if target and e.get("scl_hz_slow") is not None and e.get("scl_hz") is not None:
        lo, hi = e["scl_hz_slow"], e["scl_hz"]
        if lo > target * (1 + tol / 100) or hi < target * (1 - tol / 100):
            out.append(_F("G2-SCL", _where(r), f"{_num(target)} Hz ±{tol:g}%",
                          f"SCL between {_num(lo)} Hz (tSYNC = 1000 ns) and {_num(hi)} Hz (minimum tSYNC) (TIMINGR = 0x{e['timingr']:08X}, "
                          f"I2CCLK = {_num(e['i2cclk_hz'])} Hz)", "RM0440 §39.4.9 p.1645 and Table 359/360 (TIMINGR examples)"))
    return out + _pin_checks(r, e, ("scl_pin", "sda_pin"))


def _clock(r, sim, reported) -> list[Finding]:
    out = []
    clocks = sim.get("clocks") or {}
    tol = _opt(r, "tol_pct", 0.1)
    for key in CLOCK_KEYS:
        base = key[: -len("_hz")]
        bounds = [(k, _opt(r, k, positive=True)) for k in (key, f"{base}_min_hz", f"{base}_max_hz")]
        bounds = [(k, v) for k, v in bounds if v is not None]
        actual = clocks.get(key)
        for k, value in bounds:
            if k.endswith("_min_hz"):
                expected, bad = f"{key} at least {_num(value)} Hz (-{tol:g}%)", actual is None or actual < value * (1 - tol / 100)
            elif k.endswith("_max_hz"):
                expected, bad = f"{key} at most {_num(value)} Hz (+{tol:g}%)", actual is None or actual > value * (1 + tol / 100)
            else:
                expected, bad = f"{key} = {_num(value)} Hz ±{tol:g}%", actual is None or abs(actual - value) / value * 100 > tol
            if bad:
                out.append(_F("G2-CLOCK", _where(r), expected,
                              f"{key} = {_num(actual)} Hz" if actual is not None else f"{key} cannot be determined (e.g. hse_hz is unknown)",
                              "set_clock_config / get_clock_limits; RCC_PLLCFGR, RCC_CFGR (or the start state 'initial' of the simulation)"))
    return out


_CHECKS = {"pwm": _pwm, "uart": _uart, "i2c": _i2c, "clock": _clock}


def _kind_effect(r, sim, ops, code) -> bool:
    """Code của câu trả lời có hiệu ứng CÙNG LOẠI với requirement (có PWM / USART / I2C nào đó, hoặc ghi thanh ghi clock)."""
    typ = _type(r)
    if typ in ("pwm", "uart", "i2c"):
        return any(e.get("kind") == typ for e in sim.get("effects", []))
    if typ == "clock":
        return any(isinstance(op, dict) and op.get("reg") in CLOCK_REGS for op in ops)
    name = str(r.get("instance") or typ).upper()
    return bool(name) and name in code.upper()


def _spec(r: dict) -> str:
    return json.dumps({k: v for k, v in r.items() if k not in STATUS_KEYS and k != "id"}, sort_keys=True, default=str)


def _sent_requirements(o: dict) -> list[dict]:
    reqs = (o.get("args") or {}).get("requirements")
    if isinstance(reqs, str):
        try:
            reqs = json.loads(reqs)
        except ValueError:
            reqs = []
    return [r for r in reqs or [] if isinstance(r, dict) and r.get("id") is not None]


def _requirements_before(call, observations: list, first: int) -> dict | None:
    """Requirement ở ĐẦU lượt: phiên bản Board State ngay trước set_requirements đầu tiên của lượt (get_board_state(version=v-1), chỉ đọc);
    nếu không được thì một get_board_state đọc trước đó trong lượt; không biết => None."""
    version = (observations[first].get("result") or {}).get("version")
    if isinstance(version, int) and not isinstance(version, bool) and version > 0:
        r = call("get_board_state", {"section": "requirements", "version": version - 1})
        if tool_error(r) is None and isinstance(r.get("data"), list):
            return {str(x.get("id")).strip(): x for x in r["data"] if isinstance(x, dict)}
    for o in reversed(observations[:first]):
        if isinstance(o, dict) and o.get("tool") == "get_board_state" and tool_error(o.get("result")) is None:
            res = o["result"]
            data = res.get("data") if res.get("section") == "requirements" else (res.get("state") or {}).get("requirements")
            if isinstance(data, list):
                return {str(x.get("id")).strip(): x for x in data if isinstance(x, dict)}
    return None


def _set_this_turn(call, observations) -> set[str]:
    """Id của requirement MỚI hoặc có trường đặc tả (mọi trường trừ status/evidence/waiver_reason) THAY ĐỔI bởi một set_requirements thành công
    trong lượt này. Gửi lại nguyên vẹn chỉ để đổi status/evidence không tính. Không biết trạng thái đầu lượt => mọi id đã gửi đều tính (kiểm lại)."""
    observations = [o for o in observations or [] if isinstance(o, dict)]
    sets = [i for i, o in enumerate(observations) if o.get("tool") == "set_requirements" and tool_error(o.get("result")) is None]
    if not sets:
        return set()
    before = _requirements_before(call, observations, sets[0])
    ids: set[str] = set()
    for i in sets:
        for r in _sent_requirements(observations[i]):
            rid = str(r.get("id")).strip()
            if before is None or rid not in before or _spec(before[rid]) != _spec(r):
                ids.add(rid)
    return ids


def _unmodeled_type(r, why) -> Finding:
    return _F("G2-UNMODELED", _where(r), f"a simulated effect proving {r.get('id')} ({_type(r)})", why,
              "verify it another way, or " + _WAIVE.format(rid=r.get("id")), waivable=True)


def _tool_finding(name, err, closed: bool = False) -> Finding:
    """closed=True (code + requirement mô phỏng được): G2 không kiểm được requirement => ERROR (fail closed), không phải unknown."""
    if closed:
        return _F("G2-TOOL-ERROR", f"tool {name}", f"a completed {name} run, so that the code can be checked against the requirements",
                  f"{name} failed: {err}",
                  "the gate could not verify this code: simplify it (shorter loops, plain CMSIS register writes) and finish again; "
                  "if the failure persists it is an infrastructure problem (it will escalate)")
    return _F("G2-TOOL-ERROR", f"tool {name}", f"a {name} result", f"{name} failed: {err}",
              f"{name} (infrastructure problem; nothing G2 must verify: skipped, never counted as a pass)", severity="unknown")


def _too_many_ops(n: int) -> Finding:
    return _F("G2-UNSUPPORTED", "code", f"at most {MAX_SIM_OPS} register operations after unrolling the loops (simulator limit)",
              f"the code unrolls to {n} register operations (> {MAX_SIM_OPS})",
              "shorten or remove register-writing loops (write the final value once; delay loops without register access are fine)")


def _initial_finding(err: str, source: str, reqs: list, closed: bool) -> Finding:
    rid = next((str(r.get("id")) for r in reqs if isinstance(r, dict) and r.get("initial")), None)
    hint = (f"fix `initial` of requirement {rid} with set_requirements (a preset name such as 'reset' or 'sysclk_170mhz_pll_hsi16_apb_div1', or remove it)"
            if source == "requirement" and rid else "use a known preset name for the start state of the simulation (simulate_register_writes initial)")
    return _F("G2-INITIAL", f"start state ({source})", "a start-state preset the simulator knows (reset, sysclk_170mhz_pll_hsi16_apb_div1, ...)",
              err, hint, severity="error" if closed else "unknown")


# ------------------------------------------------------------------------------------------------ điểm vào
def run(call, prog: Program | None, reqs: list | None, req_error: str | None, chip: str, ctx_initial="reset", ctx_hse=None,
        observations=()) -> FunctionalResult:
    reqs_list = [r for r in (reqs or []) if isinstance(r, dict)]
    details: dict = {"requirements_checked": 0, "chip": chip, "start": None, "not_rechecked": []}
    findings: list[Finding] = []
    if prog is None:
        modelable = [str(r.get("id")) for r in reqs_list if _type(r) in SIM_TYPES]
        if modelable:
            findings.append(_F("G2-NO-CODE", "answer", f"a C code block implementing {', '.join(modelable)}", "the answer has no C code block",
                               "write the code and check it with simulate_register_writes", severity="warning"))
        return FunctionalResult("na", findings, details=details)
    closed = any(_type(r) in SIM_TYPES for r in reqs_list)           # fail closed: code + requirement mô phỏng được
    if req_error:
        findings.append(_tool_finding("get_board_state(section='requirements')", req_error))
    an = call("analyze_c_code", {"code": prog.code, "chip": chip})
    err = tool_error(an)
    if err is None and not an.get("ok"):
        u = (an.get("unsupported") or [{}])[0]
        if u.get("kind") == "no_toolchain":
            err = u.get("msg") or "no toolchain"
        elif u.get("kind") == "unsupported_chip":
            targets = [r for r in reqs_list if _type(r) in SIM_TYPES | UNMODELED_TYPES]
            details["requirements_checked"] = len(targets)
            findings += [_unmodeled_type(r, f"the register simulator has no model for {chip}; {r.get('id')} cannot be verified") for r in targets]
            if not targets:
                findings.append(_F("G2-SKIPPED", "code", "a chip with a register simulator model (stm32g474)", f"no simulator model for {chip}: nothing was verified",
                                   "analyze_c_code / simulate_register_writes support stm32g474 only", severity="unknown"))
            return FunctionalResult("skipped" if not targets else "pass", findings, details=details)
        else:
            findings.append(_F("G2-UNSUPPORTED", prog.locate(u.get("line")),
                               "bare-metal CMSIS register code the analyzer can follow (constants, read-modify-write, helper functions, counted loops)",
                               f"{u.get('kind')}: {u.get('msg')}" + (f" (construct: {u['construct']})" if u.get("construct") else ""), "analyze_c_code"))
            return FunctionalResult("skipped" if req_error else "pass", findings, details=details)
    if err is not None:
        return FunctionalResult("skipped", findings + [_tool_finding("analyze_c_code", err, closed)], details=details)
    ops = an.get("ops") or []
    if len(ops) > MAX_SIM_OPS:
        return FunctionalResult("skipped" if req_error else "pass", findings + [_too_many_ops(len(ops))], details=details, ops=ops)
    initial, hse_hz, source = resolve_start(reqs_list, ops, observations, ctx_initial, ctx_hse)
    details["start"] = {"initial": initial, "hse_hz": hse_hz, "source": source}
    sim = call("simulate_register_writes", {"chip": chip, "ops": ops, "initial": initial, "hse_hz": hse_hz})
    err = tool_error(sim) or (None if isinstance(sim.get("effects"), list) and isinstance(sim.get("violations"), list) else "malformed simulation result")
    if err is not None:
        if "unknown initial state" in err:
            f = _initial_finding(err, source, reqs_list, closed)
        elif "too many ops" in err:
            f = _too_many_ops(len(ops))
        else:
            f = _tool_finding("simulate_register_writes", err, closed)
        return FunctionalResult("skipped", findings + [f], details=details, ops=ops)
    checked = [r for r in reqs_list if _type(r) in SIM_TYPES | UNMODELED_TYPES]
    scope = _scope(checked, sim) if checked and not req_error else None
    relevant = [v for v in sim["violations"] if _relevant(v, scope, sim)]
    gated = {v.get("peripheral") for v in relevant if v["code"] == "SIM-CLK-GATE" and v.get("at_op") is not None}
    shown = [v for v in relevant if not (v.get("at_op") is None and v.get("peripheral") in gated)]
    details["suppressed"] = [v["code"] for v in relevant if v not in shown]
    reported = {v["code"] for v in relevant if v["severity"] == "error"}
    snippet = prog.wrapped and scope is None                         # đoạn lệnh rời, không requirement: không phải chương trình hoàn chỉnh
    seen = set()
    for v in shown:
        f = _violation_finding(v, ops, prog)
        if snippet and f.severity == "error" and (v.get("at_op") is None or v["code"] == "SIM-CLK-GATE"):
            f = _F(f.code, f.where, f.expected, f.actual + " [register snippet, not a complete program: warning only]", f.hint_source, severity="warning")
        if (f.code, f.where) not in seen:
            seen.add((f.code, f.where))
            findings.append(f)
    if scope is not None:
        this_turn = _set_this_turn(call, observations)
        for r in checked:
            typ, rid = _type(r), str(r.get("id"))
            if r.get("status") == "satisfied" and rid not in this_turn and not _kind_effect(r, sim, ops, prog.code):
                details["not_rechecked"].append(rid)
                findings.append(_F("G2-NOT-IN-CODE", _where(r), f"code implementing {rid}, or {rid} kept by earlier code",
                                   f"{rid} was satisfied in an earlier turn and this answer's code has no {typ} effect at all: not re-checked",
                                   "include the complete program if the earlier code changed", severity="warning"))
                continue
            details["requirements_checked"] += 1
            if typ in UNMODELED_TYPES:
                findings.append(_unmodeled_type(r, f"the register simulator does not model {typ} requirements; {r.get('id')} cannot be verified by G2"))
            else:
                findings += _CHECKS[typ](r, sim, reported)
    status = "skipped" if req_error or details["not_rechecked"] else "pass"
    return FunctionalResult(status, findings, _summary(sim, initial), sim, details, ops)
