"""I2C STM32G474: I2C_TIMINGR (+ DNF) + nguồn clock (RCC_CCIPR.I2CxSEL) → tSCL, f_SCL xấp xỉ.

RM0440 §39.4.9 p.1645:  tSCL = tSYNC1 + tSYNC2 + {[(SCLH + 1) + (SCLL + 1)] x (PRESC + 1) x tI2CCLK}.
  tSYNC1 + tSYNC2 >= 4 x tI2CCLK (bảng 359/360 p.1657, chú thích); mỗi tSYNC cộng thêm DNF[3:0] x tI2CCLK (bộ lọc số).
XẤP XỈ (ghi trong kết quả): dùng tSYNC1 + tSYNC2 = 4 x tI2CCLK (+ 2 x DNF x tI2CCLK); bỏ qua thời gian sườn lên/xuống và trễ bộ lọc analog,
nên f_SCL thật thấp hơn con số này (RM ví dụ 'tSYNC = 1000 ns' cho 100 kHz). Giá trị không-tSYNC (`scl_hz_upper_bound`) và giá trị với tSYNC = 1000 ns, lớn nhất trong các ví dụ của RM (`scl_hz_slow`), cũng được trả về:
f_SCL thực nằm gần khoảng [scl_hz_slow, scl_hz].
TIMINGR (p.1672): PRESC[31:28], SCLDEL[23:20], SDADEL[19:16], SCLH[15:8], SCLL[7:0].  Nguồn clock: 00 PCLK1, 01 SYSCLK, 10 HSI16.
"""
from __future__ import annotations

from . import Ctx

I2CS = {"I2C1": ("RCC_CCIPR", 12), "I2C2": ("RCC_CCIPR", 14), "I2C3": ("RCC_CCIPR", 16), "I2C4": ("RCC_CCIPR2", 0)}
MODELED_REGS = {"CR1", "TIMINGR"}
WRITE_LOCKED = {"TIMINGR": 0xFFFF_FFFF}              # RM0440 p.1681: 'This register must be configured when the I2C peripheral is disabled (PE = 0)'
TSYNC_SLOW_NS = 1000.0                               # tSYNC1 + tSYNC2 lớn nhất trong các ví dụ của RM (Table 359/360, p.1657–1658)
APPROXIMATION = "tSYNC1+tSYNC2 = 4 x tI2CCLK (RM minimum); rise/fall time and analog filter delay ignored"


def effects(ctx: Ctx):
    effs, viols = [], []
    for inst, (selreg, lo) in I2CS.items():
        if ctx.regmap.get(f"{inst}_CR1") is None:
            continue
        used = any(ctx.regmap.get(f"{inst}_{r}").address in ctx.rf.touched for r in ("CR1", "TIMINGR")) or inst in ctx.gated
        if not used:
            continue
        cr1, tm = ctx.val(f"{inst}_CR1"), ctx.val(f"{inst}_TIMINGR")
        presc, scldel, sdadel = tm >> 28, (tm >> 20) & 0xF, (tm >> 16) & 0xF
        sclh, scll = (tm >> 8) & 0xFF, tm & 0xFF
        dnf = (cr1 >> 8) & 0xF
        sel = (ctx.val(selreg) >> lo) & 3
        kernel = {0: ctx.clocks.pclk1_hz, 1: ctx.clocks.sysclk_hz, 2: 16_000_000}.get(sel)
        reasons: list[tuple[str, str]] = []
        if not ctx.clock_on(inst):
            reasons.append(("SIM-CLK-GATE", f"{inst} clock is disabled (RCC enable bit = 0)"))
        if not cr1 & 1:
            reasons.append(("SIM-I2C-PE", f"{inst}_CR1.PE = 0: the peripheral is disabled"))
        if tm == 0:
            reasons.append(("SIM-I2C-TIMING", f"{inst}_TIMINGR was never programmed (0x00000000)"))
        e = {"kind": "i2c", "instance": inst, "i2cclk_hz": kernel, "presc": presc, "scll": scll, "sclh": sclh, "sdadel": sdadel,
             "scldel": scldel, "dnf": dnf, "timingr": tm, "approximation": APPROXIMATION,
             "scl_pin": _pin(ctx, f"{inst}_SCL"), "sda_pin": _pin(ctx, f"{inst}_SDA"), "modeled": kernel is not None}
        e["open_drain"] = {p: bool(ctx.pins[p].otype) for p in (e["scl_pin"], e["sda_pin"]) if p}
        if not e["open_drain"]:
            e["open_drain"] = _candidate_open_drain(ctx, inst)
        if kernel:
            t_clk = 1e9 / kernel                                         # ns
            t_presc = (presc + 1) * t_clk
            e["t_scll_ns"], e["t_sclh_ns"] = (scll + 1) * t_presc, (sclh + 1) * t_presc
            t_sync = (4 + 2 * dnf) * t_clk
            tsum = e["t_scll_ns"] + e["t_sclh_ns"]
            e["scl_hz"] = 1e9 / (tsum + t_sync)
            e["scl_hz_slow"] = 1e9 / (tsum + max(t_sync, TSYNC_SLOW_NS))
            # ước lượng tLOW/tHIGH của bus để so với Table 358 (p.1647): tLOW ~ tSCLL + tSYNC1, tHIGH ~ tSCLH + tSYNC2, mỗi tSYNC >= (2 + DNF) x tI2CCLK
            e["t_low_ns"], e["t_high_ns"] = e["t_scll_ns"] + (2 + dnf) * t_clk, e["t_sclh_ns"] + (2 + dnf) * t_clk
            e["scl_hz_upper_bound"] = 1e9 / tsum
        else:
            e["scl_hz"] = e["scl_hz_upper_bound"] = e["scl_hz_slow"] = e["t_low_ns"] = e["t_high_ns"] = None
            e["t_scll_ns"] = e["t_sclh_ns"] = None
        e["active"] = not reasons and kernel is not None
        e["reason"] = reasons[0][0] if reasons else None
        e["reasons"] = [c for c, _ in reasons]
        if reasons:
            e["detail"] = [m for _, m in reasons]
        effs.append(e)
        for code, msg in reasons:
            if code != "SIM-CLK-GATE":
                viols.append({"code": code, "severity": "error", "at_op": None, "msg": msg, "peripheral": inst})
    return effs, viols


def _pin(ctx: Ctx, signal: str) -> str | None:
    for p in ctx.pins.values():
        if p.mode == 2 and signal in ctx.sigmap.signals(p.pin, p.af):
            return p.pin
    return None


def _candidate_open_drain(ctx: Ctx, inst: str) -> dict:
    """Không chân nào được định tuyến: báo OTYPER của các chân ứng viên đã cấu hình (để thấy lỗi push-pull)."""
    out = {}
    for sig in (f"{inst}_SCL", f"{inst}_SDA"):
        for pin, _af in ctx.sigmap.candidates(sig):
            ps = ctx.pins.get(pin)
            if ps is not None and ps.configured:
                out[pin] = bool(ps.otype)
    return out
