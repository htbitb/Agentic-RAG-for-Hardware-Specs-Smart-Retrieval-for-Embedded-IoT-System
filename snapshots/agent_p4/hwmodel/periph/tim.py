"""TIM STM32G474 (TIM1/8/20 advanced, TIM2–5 general, TIM15–17): PSC/ARR/CCRx/CCMRx/CCER/BDTR/CR1 → PWM trên chân.

Công thức (RM0440 §29.3.13 p.1178–1179, Table 282 p.1261):
  f_pwm = f_TIMxCLK / ((PSC + 1) * (ARR + 1))                 (canh biên)
  PWM mode 1, đếm lên : ocxref = 1 khi CNT < CCR  => duty = CCR / (ARR + 1); CCR > ARR => 100 %; CCR = 0 => 0 %
  đếm xuống (DIR = 1)  : ocxref = 0 khi CNT > CCR => duty = (CCR + 1) / (ARR + 1)
  PWM mode 2           : ngược lại với mode 1;  CCxP = 1 đảo mức ở chân
  CHxN: tim_ocxn = NOT ocxref (khi cả CCxE và CCxNE = 1) hoặc ocxref xor CCxNP (khi chỉ CCxNE = 1); dead-time KHÔNG mô hình hoá.
Giả định (nêu trong kết quả): trạng thái ổn định sau ≥ 1 update event (thanh ghi preload đã nạp vào shadow); tim_brk không kích hoạt.
Không mô hình hoá: canh giữa (CMS ≠ 0), dithering (DITHEN), one-pulse (OPM), slave mode / clock ngoài (SMCR), PWM bất đối xứng / kết hợp, dead-time.
"""
from __future__ import annotations

import re

from . import Ctx

# peripheral -> (bus APB, độ rộng bộ đếm, có BDTR/MOE)
TIMERS = {
    "TIM1": (2, 16, True), "TIM8": (2, 16, True), "TIM20": (2, 16, True),
    "TIM2": (1, 32, False), "TIM3": (1, 16, False), "TIM4": (1, 16, False), "TIM5": (1, 32, False),
    "TIM15": (2, 16, True), "TIM16": (2, 16, True), "TIM17": (2, 16, True),
}
MODELED_REGS = {"CR1", "EGR", "PSC", "ARR", "CCR1", "CCR2", "CCR3", "CCR4", "CCMR1", "CCMR2", "CCER", "BDTR", "CNT", "RCR"}

CR1_CEN, CR1_OPM, CR1_DIR, CR1_DITHEN = 1 << 0, 1 << 3, 1 << 4, 1 << 12
BDTR_MOE, BDTR_AOE = 1 << 15, 1 << 14
_SIG = re.compile(r"^(TIM\d+)_CH([1-4])(N?)$")


def channel_fields(ch: int) -> dict:
    """Vị trí bit của kênh 1–4 trong CCMRx / CCER (RM p.1253–1260)."""
    odd = ch % 2 == 1
    return {"ccmr": "CCMR1" if ch <= 2 else "CCMR2",
            "ocm_lo": 4 if odd else 12, "ocm_hi": 16 if odd else 24, "ccs_lo": 0 if odd else 8, "ocpe": 3 if odd else 11,
            "cce": 4 * (ch - 1), "ccp": 4 * (ch - 1) + 1, "ccne": 4 * (ch - 1) + 2, "ccnp": 4 * (ch - 1) + 3}


def _bit(v: int, n: int) -> int:
    return (v >> n) & 1


def _mode_name(ocm: int) -> str | None:
    return {0b0110: "PWM1", 0b0111: "PWM2"}.get(ocm)


def effects(ctx: Ctx):
    effs: list[dict] = []
    viols: list[dict] = []
    unmodeled: list[str] = []
    assumptions: list[str] = []
    for tim, (bus, width, has_bdtr) in TIMERS.items():
        if ctx.regmap.get(f"{tim}_CR1") is None:
            continue
        channels = _channels_of(ctx, tim)
        if not channels:
            continue
        _timer_effects(ctx, tim, bus, width, has_bdtr, channels, effs, viols, unmodeled, assumptions)
    return effs, viols, unmodeled, assumptions


def _channels_of(ctx: Ctx, tim: str):
    """[(ch, is_n, signal)] của timer — từ tên tín hiệu có trong bảng AF của DB."""
    out = []
    for sig in ctx.sigmap.by_signal:
        m = _SIG.match(sig)
        if m and m.group(1) == tim:
            out.append((int(m.group(2)), bool(m.group(3)), sig))
    return sorted(out)


def _timer_effects(ctx, tim, bus, width, has_bdtr, channels, effs, viols, unmodeled, assumptions):
    v = lambda r: ctx.val(f"{tim}_{r}")                                   # noqa: E731
    cr1, ccer, bdtr = v("CR1"), v("CCER"), v("BDTR") if has_bdtr else 0
    psc, arr = v("PSC"), v("ARR")
    smcr = v("SMCR")
    clock_on = ctx.clock_on(tim)
    gated = ctx.gated.get(tim)
    tclk = ctx.clocks.tim_clk_apb2_hz if bus == 2 else ctx.clocks.tim_clk_apb1_hz
    cms = (cr1 >> 5) & 3 if tim not in ("TIM15", "TIM16", "TIM17") else 0

    # ---- các điều kiện toàn timer (độc lập với kênh)
    timer_reasons: list[tuple[str, str]] = []                             # (mã, thông điệp), theo thứ tự ưu tiên
    if not clock_on:
        timer_reasons.append(("SIM-CLK-GATE", f"{tim} clock is disabled (RCC enable bit = 0)"))
    if not cr1 & CR1_CEN:
        timer_reasons.append(("SIM-TIM-CEN", f"{tim}_CR1.CEN = 0: the counter is stopped"))
    if arr == 0:
        timer_reasons.append(("SIM-TIM-ARR0", f"{tim}_ARR = 0: the counter is blocked while the autoreload value is null (RM p.1263)"))
    elif width == 16 and arr > 0xFFFF:
        timer_reasons.append(("SIM-TIM-RANGE", f"{tim} has a 16-bit counter: ARR = {arr} > 65535 (increase PSC or use a 32-bit timer: TIM2/TIM5)"))
    moe_ok = True
    if has_bdtr:
        aoe = bool(bdtr & BDTR_AOE)
        moe_ok = bool(bdtr & BDTR_MOE) or aoe
        if aoe and not bdtr & BDTR_MOE:
            assumptions.append(f"{tim}_BDTR.AOE = 1: MOE is assumed to be set by hardware at the first update event")

    unm: list[str] = []
    if cms:
        unm.append(f"{tim}_CR1.CMS=0b{cms:02b} (center-aligned PWM not modeled)")
    if cr1 & CR1_DITHEN:
        unm.append(f"{tim}_CR1.DITHEN=1 (dithering not modeled)")
    if cr1 & CR1_OPM:
        unm.append(f"{tim}_CR1.OPM=1 (one-pulse mode not modeled)")
    if smcr & 0x7 or (smcr >> 14) & 1:
        unm.append(f"{tim}_SMCR (slave mode / external clock not modeled)")

    for ch, is_n, signal in channels:
        f = channel_fields(ch)
        cce_bit = _bit(ccer, f["ccne"] if is_n else f["cce"])
        routed = [p for p in ctx.pins.values() if p.mode == 2 and signal in ctx.sigmap.signals(p.pin, p.af)]
        if not cce_bit and not routed:
            continue
        reasons = list(timer_reasons)
        ccmr = v(f["ccmr"])
        ocm = ((ccmr >> f["ocm_lo"]) & 7) | (((ccmr >> f["ocm_hi"]) & 1) << 3)
        ccs = (ccmr >> f["ccs_lo"]) & 3
        unm_ch = list(unm)
        mode = _mode_name(ocm)
        if ccs != 0:
            reasons.append(("SIM-TIM-OCM", f"{tim}_{f['ccmr']}.CC{ch}S = {ccs}: channel {ch} is configured as an input, not an output"))
        elif mode is None:
            if ocm >= 0b1100:
                unm_ch.append(f"{tim}_{f['ccmr']}.OC{ch}M=0b{ocm:04b} (combined/asymmetric PWM not modeled)")
            else:
                reasons.append(("SIM-TIM-OCM", f"{tim}_{f['ccmr']}.OC{ch}M = 0b{ocm:04b}: not a PWM mode (PWM mode 1 = 0110, PWM mode 2 = 0111)"))
        if not cce_bit:
            reasons.append(("SIM-TIM-CCE", f"{tim}_CCER.CC{ch}{'N' if is_n else ''}E = 0: the channel output is disabled"))
        if has_bdtr and not moe_ok:
            reasons.append(("SIM-TIM-MOE", f"{tim} is an advanced-type timer: BDTR.MOE = 0 so OC{ch}{'N' if is_n else ''} is disabled (RM Table 282 p.1261)"))
        # duty / tần số "nếu hoạt động"
        pwm_hz = duty = None
        if tclk and arr > 0 and not (width == 16 and arr > 0xFFFF):
            pwm_hz = tclk / ((psc + 1) * (arr + 1))
            ccr = v(f"CCR{ch}")
            up = not cr1 & CR1_DIR
            high = (min(ccr, arr + 1) / (arr + 1)) if up else min(ccr + 1, arr + 1) / (arr + 1)
            if mode == "PWM2":
                high = 1 - high
            p_bit = _bit(ccer, f["ccnp"] if is_n else f["ccp"])
            comp = is_n and _bit(ccer, f["cce"])                           # cả CCxE và CCxNE: CHxN bù với ocxref
            ref_to_pin = (1 - high) if comp else high
            duty = 100.0 * ((1 - ref_to_pin) if p_bit else ref_to_pin)
        dtg = bdtr & 0xFF
        if has_bdtr and dtg and _bit(ccer, f["cce"]) and _bit(ccer, f["ccne"]):
            unm_ch.append(f"{tim}_BDTR.DTG={dtg} (dead-time insertion not modeled; duty is before dead time)")
        if unm_ch:
            unmodeled.extend(u for u in unm_ch if u not in unmodeled)
        base = {"kind": "pwm", "timer": tim, "channel": ch, "complementary": is_n, "signal": signal,
                "pwm_hz": pwm_hz, "duty_pct": duty, "mode": mode, "timer_clk_hz": tclk,
                "psc": psc, "arr": arr, "ccr": v(f"CCR{ch}"), "modeled": not unm_ch}
        if routed:
            targets = [(p.pin, p.af) for p in routed]
            route_reasons: list[tuple[str, str]] = []
        else:
            targets = [(None, None)]
            route_reasons = [_route_reason(ctx, signal)]
        for pin, af in targets:
            rs = route_reasons + reasons
            e = dict(base, pin=pin, af=af, active=not rs, reason=rs[0][0] if rs else None, reasons=[c for c, _ in rs])
            if rs:
                e["detail"] = [m for _, m in rs]
            effs.append(e)
        for code, msg in route_reasons + reasons:
            if code == "SIM-CLK-GATE":
                continue                                                    # đã báo tại op ghi bị bỏ qua
            viols.append({"code": code, "severity": "error", "at_op": None, "msg": msg, "peripheral": tim, "channel": ch,
                          "signal": signal, "pin": routed[0].pin if routed else None})


def _route_reason(ctx: Ctx, signal: str) -> tuple[str, str]:
    cands = ctx.sigmap.candidates(signal)
    names = ", ".join(f"{p} (AF{af})" for p, af in cands[:6]) or "none in the datasheet AF table"
    for pin, af in cands:
        ps = ctx.pins.get(pin)
        if ps is not None and ps.configured and ps.mode != 2:
            return "SIM-GPIO-MODE", (f"{pin}: MODER = {ps.mode} ({_mode(ps.mode)}), not alternate function (10); {signal} needs {pin} in AF{af}. "
                                     f"Candidates: {names}")
    for pin, af in cands:
        ps = ctx.pins.get(pin)
        if ps is not None and ps.configured and ps.mode == 2 and ps.af != af:
            actual = ctx.sigmap.signals(pin, ps.af)
            return "SIM-GPIO-AF", (f"{pin} is in AF{ps.af} ({', '.join(actual) or 'no signal'}), but {signal} is AF{af} on {pin}. Candidates: {names}")
    for pin, af in cands:
        if ctx.gated.get(f"GPIO{pin[1]}"):
            return "SIM-CLK-GATE", f"GPIO{pin[1]} clock is disabled: the pin configuration was lost, so {signal} is not routed to {pin}"
    return "SIM-GPIO-AF", f"no pin is configured to carry {signal}. Candidates: {names}"


def _mode(m: int) -> str:
    return {0: "input", 1: "output", 2: "alternate function", 3: "analog"}[m]
