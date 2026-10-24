"""functional_sim (gate): code C trong câu trả lời → analyze_c_code → simulate_register_writes (bản VENDOR đóng băng, D19) → so `effects` với `expected.spec`.

expected:
  initial: "reset" | tên preset (vd sysclk_170mhz_pll_hsi16_apb_div1)    # trạng thái khởi đầu được nêu trong đề (D20)
  hse_hz: 8000000                                                       # (tuỳ chọn) tần số thạch anh nếu đề dùng HSE
  spec:                                                                  # chức năng, KHÔNG phải giá trị thanh ghi
    - {type: pwm,   pin: PA8, freq_hz: 20000, duty_pct: 25, tol_pct: 1, [signal: TIM1_CH1], [duty_tol_pp: 1.0], [forbid_pins: [PA9]]}
    - {type: uart,  instance: USART1, baud: 115200, tol_pct: 2, [tx_pin: PA9], [rx_pin: PA10], [frame: 8N1], [te: true], [re: true],
                    [over8: 0], [kernel_source: PCLK2] | [kernel_clk_hz: 85000000]}
    - {type: i2c,   instance: I2C1, scl_hz: 100000, tol_pct: 5, [scl_pin: PB8], [sda_pin: PB9], [open_drain: true], [kernel_clk_hz: 16000000],
                    [mode: Sm|Fm|Fm+  -> kiểm tLOW/tHIGH tối thiểu của Table 358]}
    - {type: clock, sysclk_hz: 170000000, [hclk_hz|pclk1_hz|pclk2_hz|tim_clk_apb1_hz|tim_clk_apb2_hz], [<khoá>_min_hz | <khoá>_max_hz: chỉ đòi cận dưới/trên], tol_pct: 0.1,
                    [hse_hz: 8000000  -> (P5, C5) thay cho expected.hse_hz]}
  Ràng buộc chân (C4, P3): uart `tx_not_in`/`rx_not_in`, i2c `scl_not_in`/`sda_not_in` (tín hiệu PHẢI được định tuyến tới một chân ngoài danh sách);
  `require_pins: true` (uart/i2c: mọi tín hiệu dùng tới phải được định tuyến tới một chân nào đó — bắt trường hợp hai chức năng tranh một chân và một trong hai mất định tuyến);
  pwm `timer_not_in: [TIM2]` (kênh không được thuộc timer đó) và `any_pin: true` (thay cho `pin`: chấp nhận PWM đạt freq/duty trên BẤT KỲ chân nào,
  kết hợp `timer_not_in` — dùng khi phương án sửa xung đột là chuyển sang timer khác; kèm `signal: TIM4_CH1` để vẫn buộc đúng kênh ↔ duty).
Khoá không có trong bảng `eval.schema.SPEC_KEYS` (gõ nhầm, vd `scl_not_n`) bị Task từ chối khi nạp.
Dung sai: tần số/baud/clock theo tỉ lệ ±tol_pct %; duty theo ĐIỂM PHẦN TRĂM tuyệt đối (±duty_tol_pp, mặc định = tol_pct).
I2C: mô hình cho dải [scl_hz_slow, scl_hz] ứng với tSYNC1+tSYNC2 từ cực tiểu (4·tI2CCLK) đến 1000 ns (lớn nhất trong ví dụ của RM); đạt khi dải này
giao với [scl_hz·(1−tol), scl_hz·(1+tol)] — nhờ vậy giá trị mẫu của chính RM (Table 360) không bị chấm trượt.
Chỉ các violation LIÊN QUAN tới spec mới làm trượt: lỗi cuối chuỗi của kênh timer/ngoại vi không nằm trong spec (vd bật CC2E cho kênh không nối chân) là vô hại.

Mã lý do (đứng đầu mỗi chuỗi lý do, dạng `mã[:mã con]: thông điệp`):
  no_code · unsupported_construct[:kind] · sim_violation:<mã mô phỏng> (mọi violation mức error) · wrong_pin · inactive:<lý do>
  · wrong_freq (PWM) · wrong_duty · wrong_baud · wrong_scl · wrong_clock · wrong_pin_config (I2C không open-drain) · wrong_config (UART: khung/TE/RE/OVER8)
  · wrong_kernel_clock · wrong_i2c_timing · forbidden_pin_used · wrong_timer · unmodeled
Cảnh báo (warning) không làm trượt. `unmodeled` chỉ làm trượt khi hiệu ứng được yêu cầu phụ thuộc phần không mô hình hoá.
"""
from __future__ import annotations

import re

from eval import sandbox

_C_TAGS = {"c", "cpp", "c++", "cc", "h", "hpp", "embedded-c", "arm", "cmsis", "stm32", "clike", "c11", "c99"}
_FENCE = re.compile(r"```([^\n`]*)\n(.*?)(?:```|\Z)", re.S)
_C_HINT = re.compile(r"[;{}]|#\s*include|->|\bvoid\b|\bint\b|\buint\d+_t\b")
_PROSE = re.compile(r"^[A-Za-z][A-Za-z ,.:'\-]+$")


_MAIN = re.compile(r"\bmain\s*\([^)]*\)\s*\{")
_FUNC_DEF = re.compile(r"\)\s*\{")
_REG_STMT = re.compile(r"(?m)^[ \t]*[A-Za-z_]\w*(?:->|\.)\w+(?:\[[^\]]*\])?\s*(?:\|=|&=|\^=|=)(?!=)")


def _is_fragment(body: str) -> bool:
    """Khối chỉ là đoạn lệnh ghi thanh ghi ở mức tệp (không có định nghĩa hàm nào): không thể biên dịch riêng."""
    return not _FUNC_DEF.search(body) and bool(_REG_STMT.search(body))


def extract_c_code(answer: str) -> str:
    """Nối (theo thứ tự) các khối code C của câu trả lời. Khối không có thẻ chỉ được giữ nếu trông như C; khối giống hệt không lặp lại."""
    blocks: list[str] = []
    for m in _FENCE.finditer(answer or ""):
        lang = m.group(1).strip().split()[0].lower() if m.group(1).strip() else ""
        body = m.group(2).strip("\n")
        if not body.strip():
            continue
        if lang and lang not in _C_TAGS:
            continue
        if not lang and not (_C_HINT.search(body) and not all(_PROSE.match(l.strip()) for l in body.splitlines() if l.strip())):
            continue
        if body not in blocks:
            blocks.append(body)
    if len(blocks) > 1 and any(_MAIN.search(b) for b in blocks):
        blocks = [b for b in blocks if not _is_fragment(b)]            # "đừng làm thế này: RCC->... ;" nằm cạnh chương trình đầy đủ không được ghép vào chương trình
    return "\n\n".join(blocks)


def _res(ok: bool, reasons: list[str], details: dict) -> dict:
    return {"pass": ok, "score": 1.0 if ok else 0.0, "reasons": reasons, "details": details}


def _rel(actual, target) -> float:
    return abs(actual - target) / target * 100.0


def _forbidden(spec, res, reasons):
    for pin in spec.get("forbid_pins", []):
        used = [e for e in res["effects"] if e.get("pin") == pin and e["kind"] in ("pwm", "pin_af")]
        if used:
            e = used[0]
            reasons.append(f"forbidden_pin_used: {pin} must stay unused but is configured ({e.get('signal') or 'AF%s' % e.get('af')})")


def _not_in(spec, e, role, reasons):
    """`<role>_not_in`: tín hiệu phải được định tuyến tới một chân và chân đó không nằm trong danh sách cấm."""
    banned = spec.get(f"{role}_not_in")
    if not banned:
        return
    pin = e.get(f"{role}_pin")
    if pin is None:
        reasons.append(f"wrong_pin: {role.upper()} is not routed to any pin (it must be on a pin other than {', '.join(banned)})")
    elif pin in banned:
        reasons.append(f"forbidden_pin_used: {role.upper()} is on {pin}, which must not be used for it")


def _require_pins(spec, e, roles, reasons):
    """`require_pins: true`: mọi tín hiệu của giao tiếp (uart: TX nếu TE, RX nếu RE; i2c: SCL và SDA) phải được định tuyến tới một chân."""
    if not spec.get("require_pins"):
        return
    for role in roles:
        if e.get(f"{role}_pin") is None:
            reasons.append(f"wrong_pin: {role.upper()} of {spec['instance']} is not routed to any pin")


def _pwm_duty_freq(spec, e, pin, reasons):
    tol = float(spec.get("tol_pct", 1.0))
    if _rel(e["pwm_hz"], spec["freq_hz"]) > tol:
        reasons.append(f"wrong_freq: {pin} outputs {e['pwm_hz']:.6g} Hz, expected {spec['freq_hz']} Hz ±{tol}%")
    if "duty_pct" in spec and abs(e["duty_pct"] - spec["duty_pct"]) > float(spec.get("duty_tol_pp", tol)):
        reasons.append(f"wrong_duty: {pin} duty is {e['duty_pct']:.4g}%, expected {spec['duty_pct']}% ±{spec.get('duty_tol_pp', tol)} pp")


def _pwm_any_pin(spec, res, errors, reasons, matched):
    """PWM `any_pin`: đạt nếu MỘT kênh PWM đang chạy ở bất kỳ chân nào có tần số/duty đúng và timer không bị cấm."""
    banned = spec.get("timer_not_in", [])
    claimed = set(spec.get("_claimed_pins", []))                        # chân đã thuộc mục PWM `pin:` khác: không được tính cho mục any_pin
    _forbidden(spec, res, reasons)
    cands = [e for e in res["effects"] if e["kind"] == "pwm" and e.get("pin") and e["pin"] not in claimed
             and (not spec.get("signal") or e.get("signal") == spec["signal"])]      # `signal` giữ ràng buộc kênh ↔ duty khi dùng any_pin (vd TIM4_CH1 = 30 %, TIM4_CH2 = 60 %)
    live = [e for e in cands if e["active"] and e["modeled"]]
    allowed = [e for e in live if e.get("timer") not in banned]
    for e in allowed:
        trial: list[str] = []
        _pwm_duty_freq(spec, e, e["pin"], trial)
        if not trial:
            matched.append({k: e.get(k) for k in ("pin", "signal", "timer", "channel", "pwm_hz", "duty_pct", "active", "reason", "modeled")})
            return
    label = f"{spec['freq_hz']} Hz" + (f" / {spec['duty_pct']}%" if "duty_pct" in spec else "")
    if allowed:                                                            # có kênh hợp lệ về timer nhưng sai tần số / duty
        best = min(allowed, key=lambda e: _rel(e["pwm_hz"], spec["freq_hz"]))
        matched.append({k: best.get(k) for k in ("pin", "signal", "timer", "channel", "pwm_hz", "duty_pct", "active", "reason", "modeled")})
        _pwm_duty_freq(spec, best, best["pin"], reasons)
    elif live:
        reasons.append(f"wrong_timer: no {label} PWM runs outside {', '.join(banned) or 'the forbidden timers'}; the PWM channels found are on "
                       f"{', '.join(sorted({e['pin'] + '/' + str(e.get('timer')) for e in live}))}")
    elif not any(e["pin"] for e in cands if e["reasons"] and e["reasons"][0] in errors):
        reasons.append(f"inactive:no_effect: no {label} PWM output was found on any pin")


def _pwm_item(spec, res, errors, reasons, matched):
    if spec.get("any_pin"):
        return _pwm_any_pin(spec, res, errors, reasons, matched)
    _forbidden(spec, res, reasons)
    pin = spec["pin"]
    effs = [e for e in res["effects"] if e["kind"] == "pwm" and e.get("pin") == pin]
    if spec.get("signal"):
        effs = [e for e in effs if e["signal"] == spec["signal"]]
    if not effs:
        other = [e for e in res["effects"] if e["kind"] == "pwm" and e.get("pin") and e["pin"] != pin and e["active"]]
        af = [e for e in res["effects"] if e["kind"] == "pin_af" and e["pin"] == pin]
        if other:
            reasons.append(f"wrong_pin: PWM is generated on {', '.join(sorted({e['pin'] for e in other}))} ({other[0]['signal']}), not on {pin}")
        elif af:
            reasons.append(f"wrong_pin: {pin} carries {af[0]['signal'] or 'AF%d' % af[0]['af']}, not {spec.get('signal') or 'a PWM output'}")
        else:
            unrouted = [e for e in res["effects"] if e["kind"] == "pwm" and not e.get("pin")]
            if unrouted and unrouted[0]["reasons"] and unrouted[0]["reasons"][0] in errors:
                return                                                  # đã được báo bằng sim_violation
            reasons.append(f"inactive:no_effect: no PWM output was found on {pin}")
        return
    e = effs[0]
    matched.append({k: e.get(k) for k in ("pin", "signal", "timer", "channel", "pwm_hz", "duty_pct", "active", "reason", "modeled")})
    if not e["active"]:
        if e["reason"] not in errors:
            reasons.append(f"inactive:{e['reason']}: {pin} produces no PWM ({'; '.join(e.get('detail', []))})")
        return
    if not e["modeled"]:
        reasons.append(f"unmodeled: the PWM on {pin} depends on a feature the model does not simulate")
        return
    if e.get("timer") in spec.get("timer_not_in", []):
        reasons.append(f"wrong_timer: the PWM on {pin} comes from {e['timer']}, which must not be used for it")
        return
    _pwm_duty_freq(spec, e, pin, reasons)


def _uart_item(spec, res, errors, reasons, matched):
    effs = [e for e in res["effects"] if e["kind"] == "uart" and e["instance"] == spec["instance"]]
    if not effs:
        reasons.append(f"inactive:no_effect: {spec['instance']} was never configured")
        return
    e = effs[0]
    matched.append({k: e.get(k) for k in ("instance", "baud", "over8", "usartdiv", "kernel_clk_hz", "kernel_source", "data_bits", "parity", "stop_bits", "te", "re",
                                          "active", "reason", "tx_pin", "rx_pin")})
    if not e["active"]:
        if e["reason"] not in errors:
            reasons.append(f"inactive:{e['reason']}: {spec['instance']} is not operational ({'; '.join(e.get('detail', []))})")
        return
    if not e["modeled"] and e.get("kernel_clk_hz"):
        reasons.append(f"unmodeled: {spec['instance']} uses a feature the model does not simulate (CR2 SWAP/TXINV/RXINV/LINEN/CLKEN)")
        return
    tol = float(spec.get("tol_pct", 2.0))
    if _rel(e["baud"], spec["baud"]) > tol:
        reasons.append(f"wrong_baud: {spec['instance']} runs at {e['baud']:.6g} baud, expected {spec['baud']} ±{tol}%")
    for key in ("tx_pin", "rx_pin"):
        if spec.get(key) and e.get(key) != spec[key]:
            reasons.append(f"wrong_pin: {key.replace('_', ' ')} is {e.get(key) or 'not routed'}, expected {spec[key]}")
    if spec.get("frame"):
        want = _parse_frame(spec["frame"])
        got = (e["data_bits"], {"none": "N", "even": "E", "odd": "O"}[e["parity"]], e["stop_bits"])
        if got != want:
            reasons.append(f"wrong_config: frame is {got[0]}{got[1]}{got[2]:g}, expected {spec['frame']}")
    for key in ("te", "re"):
        if key in spec and bool(e[key]) != bool(spec[key]):
            reasons.append(f"wrong_config: CR1.{key.upper()} is {int(e[key])}, expected {int(bool(spec[key]))}")
    if "over8" in spec and e["over8"] != spec["over8"]:
        reasons.append(f"wrong_config: oversampling by {8 if e['over8'] else 16}, expected by {8 if spec['over8'] else 16} (CR1.OVER8)")
    for role in ("tx", "rx"):
        _not_in(spec, e, role, reasons)
    _require_pins(spec, e, [r for r, on in (("tx", e.get("te")), ("rx", e.get("re"))) if on], reasons)
    _kernel(spec, e, "kernel_clk_hz", reasons)
    if spec.get("kernel_source") and e["kernel_source"] != spec["kernel_source"]:
        reasons.append(f"wrong_kernel_clock: kernel clock source is {e['kernel_source']}, expected {spec['kernel_source']}")


def _parse_frame(frame: str):
    """'8N1' -> (8, 'N', 1.0)"""
    m = re.fullmatch(r"([5-9])([NEO])(0\.5|1\.5|1|2)", frame.strip().upper())
    if not m:
        raise ValueError(f"bad frame spec {frame!r} (expected e.g. 8N1)")
    return int(m.group(1)), m.group(2), float(m.group(3))


def _kernel(spec, e, key, reasons):
    field = "kernel_clk_hz" if "kernel_clk_hz" in e else "i2cclk_hz"
    if spec.get(key) and (e.get(field) is None or _rel(e[field], spec[key]) > 0.1):
        reasons.append(f"wrong_kernel_clock: kernel clock is {e.get(field)} Hz, expected {spec[key]} Hz")


# RM0440 Table 358 (p.1647): tLOW / tHIGH tối thiểu (µs) theo chế độ bus
BUS_MIN_US = {"Sm": (4.7, 4.0), "Fm": (1.3, 0.6), "Fm+": (0.5, 0.26)}


def _i2c_item(spec, res, errors, reasons, matched):
    effs = [e for e in res["effects"] if e["kind"] == "i2c" and e["instance"] == spec["instance"]]
    if not effs:
        reasons.append(f"inactive:no_effect: {spec['instance']} was never configured")
        return
    e = effs[0]
    matched.append({k: e.get(k) for k in ("instance", "scl_hz", "scl_hz_slow", "t_scll_ns", "t_sclh_ns", "i2cclk_hz", "active", "reason", "scl_pin", "sda_pin")})
    if not e["active"]:
        if e["reason"] not in errors:
            reasons.append(f"inactive:{e['reason']}: {spec['instance']} is not operational ({'; '.join(e.get('detail', []))})")
        return
    tol = float(spec.get("tol_pct", 5.0)) / 100.0
    lo, hi = e["scl_hz_slow"], e["scl_hz"]
    if lo > spec["scl_hz"] * (1 + tol) or hi < spec["scl_hz"] * (1 - tol):
        reasons.append(f"wrong_scl: {spec['instance']} SCL is between {lo:.6g} Hz (tSYNC = 1000 ns) and {hi:.6g} Hz (tSYNC = RM minimum), "
                       f"which does not reach {spec['scl_hz']} Hz ±{tol * 100:g}%")
    _kernel(spec, e, "kernel_clk_hz", reasons)
    if spec.get("mode"):
        lo_min, hi_min = (x * 1000.0 for x in BUS_MIN_US[spec["mode"]])
        if e["t_low_ns"] < lo_min or e["t_high_ns"] < hi_min:
            reasons.append(f"wrong_i2c_timing: tLOW ~ {e['t_low_ns']:.0f} ns / tHIGH ~ {e['t_high_ns']:.0f} ns, {spec['mode']} needs >= {lo_min:.0f} / {hi_min:.0f} ns "
                           f"(RM0440 Table 358; tLOW ~ tSCLL + tSYNC1, tHIGH ~ tSCLH + tSYNC2 with tSYNC1 = tSYNC2 = 2 x tI2CCLK)")
    for key in ("scl_pin", "sda_pin"):
        if spec.get(key) and e.get(key) != spec[key]:
            reasons.append(f"wrong_pin: {key.replace('_', ' ')} is {e.get(key) or 'not routed'}, expected {spec[key]}")
    for role in ("scl", "sda"):
        _not_in(spec, e, role, reasons)
    _require_pins(spec, e, ("scl", "sda"), reasons)
    if spec.get("open_drain"):
        for pin in (e.get("scl_pin"), e.get("sda_pin")):
            if pin and not e["open_drain"].get(pin):
                reasons.append(f"wrong_pin_config: {pin} must be open-drain (GPIOx_OTYPER) for I2C")


def _clock_item(spec, res, errors, reasons, matched):
    clocks = res["clocks"]
    tol = float(spec.get("tol_pct", 0.1))
    for key in ("sysclk_hz", "hclk_hz", "pclk1_hz", "pclk2_hz", "tim_clk_apb1_hz", "tim_clk_apb2_hz"):
        base = key[: -len("_hz")]
        bounds = [(spec[k], k) for k in (key, f"{base}_min_hz", f"{base}_max_hz") if k in spec]
        if not bounds:
            continue
        actual = clocks.get(key)
        matched.append({"clock": key, "actual": actual, **{k: v for v, k in bounds}})
        if actual is None:
            reasons.append(f"inactive:SIM-CLK-UNKNOWN: {key} cannot be determined (e.g. the HSE frequency is unknown)")
            continue
        for value, k in bounds:
            if k.endswith("_min_hz"):                      # chấp nhận mọi cách sửa xung đột hợp lệ: chỉ đòi tối thiểu
                if actual < value * (1 - tol / 100.0):
                    reasons.append(f"wrong_clock: {key} is {actual:.6g} Hz, expected at least {value} Hz (-{tol}%)")
            elif k.endswith("_max_hz"):
                if actual > value * (1 + tol / 100.0):
                    reasons.append(f"wrong_clock: {key} is {actual:.6g} Hz, expected at most {value} Hz (+{tol}%)")
            elif _rel(actual, value) > tol:
                reasons.append(f"wrong_clock: {key} is {actual:.6g} Hz, expected {value} Hz ±{tol}%")


_ITEMS = {"pwm": _pwm_item, "uart": _uart_item, "i2c": _i2c_item, "clock": _clock_item}


def _relevant_violations(V, spec, violations) -> list[dict]:
    """Violation mức error làm trượt: mọi lỗi tại một lệnh (at_op) và lỗi cuối chuỗi gắn với tín hiệu / ngoại vi CỦA SPEC. Lỗi cuối chuỗi của kênh timer
    hay ngoại vi không nằm trong spec (vd CC2E bật cho kênh không nối chân) vô hại trên phần cứng nên không tính."""
    sigmap = V.gpio.signal_map("stm32g474")
    signals: set[str] = set()
    pins: set[str] = set()
    instances: set[str] = set()
    for item in spec:
        if item["type"] == "pwm" and item.get("pin"):
            pins.add(item["pin"])
            signals |= {sig for (p, _af), sigs in sigmap.by_pin.items() if p == item["pin"] for sig in sigs}
            if item.get("signal"):
                signals.add(item["signal"])
        elif item["type"] == "pwm":
            pass
        elif item["type"] in ("uart", "i2c"):
            instances.add(item["instance"])
    out = []
    any_timer = any(i["type"] == "pwm" and i.get("any_pin") for i in spec)
    for v in violations:
        if v["severity"] != "error":
            continue
        if v.get("at_op") is not None or (not v.get("signal") and not v.get("peripheral")):
            out.append(v)
        elif v.get("signal"):
            if v["signal"] in signals or v.get("pin") in pins or (any_timer and str(v["signal"]).startswith("TIM")):
                out.append(v)
        elif v["peripheral"] in instances or not str(v["peripheral"]).startswith(("USART", "UART", "I2C")):
            out.append(v)
    return out


def hse_hz(exp: dict):
    """Tần số HSE cho mô phỏng: `expected.hse_hz`, hoặc `hse_hz` của mục spec clock (P5, task C5; Task đã kiểm hai nơi không mâu thuẫn)."""
    if exp.get("hse_hz"):
        return exp["hse_hz"]
    return next((i["hse_hz"] for i in exp.get("spec") or [] if isinstance(i, dict) and i.get("type") == "clock" and i.get("hse_hz")), None)


def grade(task, run, ctx) -> dict:
    exp = task.expected
    spec = exp.get("spec")
    if not spec:
        raise ValueError(f"{task.id}: expected.spec is required for functional_sim")
    code = extract_c_code(run.final_answer)
    if not code.strip():
        return _res(False, ["no_code: the answer contains no C code block"], {"blocks": 0})
    V = sandbox.load()
    blocks = len(_FENCE.findall(run.final_answer or ""))
    an = V.codeparse.analyze_c_code(code, exp.get("chip", "stm32g474"))
    notes = {}
    for n in an["notes"]:
        notes[n["kind"]] = notes.get(n["kind"], 0) + 1
    details = {"blocks": blocks, "ops": len(an["ops"]), "analysis_ok": an["ok"], "notes": notes, "initial": exp.get("initial", "reset")}
    if not an["ok"]:
        u = an["unsupported"][0]
        sub = "" if u["kind"] == "unsupported_construct" else f":{u['kind']}"
        details["unsupported"] = {"kind": u["kind"], "line": u.get("line"), "construct": u.get("construct"), "msg": u["msg"]}
        return _res(False, [f"unsupported_construct{sub}: line {u.get('line')}: {u['msg']}"], details)
    initial = exp.get("initial", "reset")
    res = V.sim.simulate_register_writes(exp.get("chip", "stm32g474"), an["ops"], initial=initial, hse_hz=hse_hz(exp))
    relevant = _relevant_violations(V, spec, res["violations"])
    errors = sorted({v["code"] for v in relevant})
    reasons: list[str] = []
    for v in relevant:
        if not any(r.startswith(f"sim_violation:{v['code']}:") for r in reasons):
            reasons.append(f"sim_violation:{v['code']}: {v['msg']}")
    matched: list[dict] = []
    claimed = sorted({i["pin"] for i in spec if i["type"] == "pwm" and i.get("pin")})
    for item in spec:
        if item["type"] == "pwm" and item.get("any_pin"):
            item = {**item, "_claimed_pins": claimed}
        _ITEMS[item["type"]](item, res, set(errors), reasons, matched)
    details.update({"violations": sorted({(v["code"], v["severity"]) for v in res["violations"]}), "ignored_violations": sorted(
        {v["code"] for v in res["violations"] if v["severity"] == "error" and v not in relevant}), "matched": matched, "unmodeled": res["unmodeled"],
                    "clocks": {k: res["clocks"].get(k) for k in ("sysclk_hz", "hclk_hz", "pclk1_hz", "pclk2_hz")}})
    details["violations"] = [list(v) for v in details["violations"]]
    return _res(not reasons, reasons, details)
