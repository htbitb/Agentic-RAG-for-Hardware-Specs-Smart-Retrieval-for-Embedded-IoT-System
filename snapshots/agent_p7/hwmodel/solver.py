"""solve_timer_config: (PSC, ARR, CCR) cho PWM edge-aligned với sai số tần số nhỏ nhất, rồi độ phân giải duty lớn nhất.

f = f_TIMxCLK / ((PSC + 1) * (ARR + 1));  duty = CCR / (ARR + 1)  (RM0440 §29.3.13 p.1179).  PSC 16 bit; ARR 16 bit (TIM2/TIM5: 32 bit).
TIMxCLK = PCLK x (1 nếu prescaler APB = 1, ngược lại 2) — RM p.281 §7.2.13.
Chỉ STM32G474. Không đoán: thiếu `clock_state` thì giả định 170 MHz và NÓI RÕ trong `assumptions`.
"""
from __future__ import annotations

import math
from fractions import Fraction

from .periph.tim import TIMERS

_CHANNELS = {"TIM1": 4, "TIM8": 4, "TIM20": 4, "TIM2": 4, "TIM3": 4, "TIM4": 4, "TIM5": 4, "TIM15": 2, "TIM16": 1, "TIM17": 1}
DEFAULT_TIM_CLK = 170_000_000


def _err(msg: str, **kw) -> dict:
    return {"ok": False, "error": msg, **kw}


def tim_clk_from(clock_state: dict | None):
    """(tim_clk_hz, assumptions, error)."""
    if not clock_state:
        return DEFAULT_TIM_CLK, ["no clock_state given: assumed TIMxCLK = 170 MHz (SYSCLK 170 MHz, APB prescaler 1)"], None
    cs = clock_state
    if cs.get("tim_clk_hz"):
        return Fraction(cs["tim_clk_hz"]), [], None
    if cs.get("pclk_hz") and cs.get("apb_prescaler"):
        return Fraction(cs["pclk_hz"]) * (1 if cs["apb_prescaler"] == 1 else 2), [], None
    if cs.get("sysclk_hz") and cs.get("apb_div"):
        pclk = Fraction(cs["sysclk_hz"]) / (cs.get("hclk_div") or 1) / cs["apb_div"]
        return pclk * (1 if cs["apb_div"] == 1 else 2), [], None
    return None, [], "clock_state needs 'tim_clk_hz', or 'pclk_hz' + 'apb_prescaler', or 'sysclk_hz' + 'apb_div' (+ optional 'hclk_div')"


def solve_timer_config(chip: str, timer: str, target_hz: float, duty_pct: float, channel: int = 1, clock_state: dict | None = None,
                       max_alternatives: int = 3) -> dict:
    if chip != "stm32g474":
        return _err(f"solve_timer_config supports stm32g474 only (got {chip!r})")
    timer = str(timer).upper()
    if timer not in _CHANNELS:
        return _err(f"{timer} cannot generate PWM on STM32G474 (use one of {', '.join(sorted(_CHANNELS))})")
    if not 1 <= int(channel) <= _CHANNELS[timer]:
        return _err(f"{timer} has channels 1..{_CHANNELS[timer]} with an output pin; got channel {channel}")
    if not target_hz or target_hz <= 0:
        return _err("target_hz must be positive")
    if not 0 <= duty_pct <= 100:
        return _err("duty_pct must be within 0..100")
    clk, assumptions, bad = tim_clk_from(clock_state)
    if bad:
        return _err(bad)
    width = TIMERS[timer][1]
    nmax = 1 << width                                            # ARR + 1 tối đa
    target = Fraction(target_hz).limit_denominator(10**9)
    if clk / target < 2:
        return _err(f"target_hz too high: TIMxCLK {float(clk):g} Hz / {target_hz:g} Hz < 2 counts per period (need ARR >= 1)")
    if clk / (target * 65536 * nmax) > 1:
        return _err(f"target_hz too low: even PSC = 65535 and ARR = {nmax - 1} give {float(clk / (65536 * nmax)):g} Hz; use a 32-bit timer (TIM2/TIM5) or a slower clock")
    cands: dict[tuple[int, int], tuple] = {}
    for psc1 in range(1, 65537):
        x = clk / (psc1 * target)
        if x < 2 and psc1 > 1:
            break
        lo = x.numerator // x.denominator
        for n in {lo, lo + 1}:
            if 2 <= n <= nmax:
                f = clk / (psc1 * n)
                cands[(psc1, n)] = (abs(f - target) / target, -n, psc1, f)
    if not cands:
        return _err("no (PSC, ARR) pair fits the 16/32-bit counter limits for this frequency")
    ranked = sorted(cands.values())

    def pack(item):
        err, neg_n, psc1, f = item
        n = -neg_n
        ccr = min(n, max(0, int(Fraction(duty_pct) * n / 100 + Fraction(1, 2))))
        duty = float(Fraction(ccr, n) * 100)
        return {"psc": psc1 - 1, "arr": n - 1, "ccr": ccr, "freq_hz": float(f), "freq_error_pct": float(err * 100),
                "duty_pct": duty, "duty_error_pct": float(duty_pct) - duty, "duty_steps": n, "duty_resolution_bits": math.log2(n)}

    best = pack(ranked[0])
    alts, seen = [], {(best["psc"], best["arr"])}
    for item in ranked[1:]:
        p = pack(item)
        if (p["psc"], p["arr"]) not in seen:
            seen.add((p["psc"], p["arr"]))
            alts.append(p)
        if len(alts) >= max_alternatives:
            break
    ch = int(channel)
    return {"ok": True, "chip": chip, "timer": timer, "channel": ch, "tim_clk_hz": int(clk) if clk.denominator == 1 else float(clk),
            "counter_bits": width, "target_hz": target_hz, "target_duty_pct": duty_pct, "best": best, "alternatives": alts,
            "registers": {f"{timer}_PSC": best["psc"], f"{timer}_ARR": best["arr"], f"{timer}_CCR{ch}": best["ccr"]},
            "assumptions": assumptions + ["edge-aligned, up-counting PWM mode 1 (duty = CCR / (ARR + 1)); no dead time"]}
