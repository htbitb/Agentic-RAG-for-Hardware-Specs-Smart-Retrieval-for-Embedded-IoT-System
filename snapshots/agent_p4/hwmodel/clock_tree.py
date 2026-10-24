"""Cây clock STM32G474 (RM0440 §7.2): HSI16 / HSE / PLL → SYSCLK → AHB / APB1 / APB2 → TIMxCLK, và giới hạn từ `clock_limits`.

Hàm thuần: nhận giá trị các thanh ghi RCC/PWR/FLASH, trả `ClockState` + danh sách giới hạn bị vi phạm.
Giả định (ghi trong kết quả mô phỏng): các cờ *RDY lên ngay khi bật nguồn; không mô phỏng thời gian ổn định.

Vị trí bit (RM0440): RCC_CR p.287, RCC_CFGR p.289–290, RCC_PLLCFGR p.291–293, PWR_CR1.VOS p.253, PWR_CR5.R1MODE p.267, FLASH_ACR p.130.
`test_hwmodel_rcc_layout` đối chiếu các hằng số này với trường SVD trong DB.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import data

HSI16_HZ = 16_000_000

CR_HSION, CR_HSEON, CR_PLLON = 1 << 8, 1 << 16, 1 << 24
CR_HSIRDY, CR_HSERDY, CR_PLLRDY = 1 << 10, 1 << 17, 1 << 25
SW_HSI16, SW_HSE, SW_PLL = 0b01, 0b10, 0b11

_HPRE = {0b1000: 2, 0b1001: 4, 0b1010: 8, 0b1011: 16, 0b1100: 64, 0b1101: 128, 0b1110: 256, 0b1111: 512}
_PPRE = {0b100: 2, 0b101: 4, 0b110: 8, 0b111: 16}
_PLLR = {0b00: 2, 0b01: 4, 0b10: 6, 0b11: 8}
_SRC = {0b10: "HSI16", 0b11: "HSE"}


def bits(value: int, lo: int, width: int) -> int:
    return (value >> lo) & ((1 << width) - 1)


def _num(v: float):
    return int(v) if float(v).is_integer() else v


@dataclass
class ClockState:
    sysclk_hz: float | None
    sysclk_source: str                          # HSI16 | HSE | PLL
    hclk_hz: float | None
    pclk1_hz: float | None
    pclk2_hz: float | None
    tim_clk_apb1_hz: float | None
    tim_clk_apb2_hz: float | None
    hpre_div: int
    ppre1_div: int
    ppre2_div: int
    pll: dict
    hsi16_on: bool
    hse_on: bool
    hse_hz: int | None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"sysclk_hz": self.sysclk_hz, "sysclk_source": self.sysclk_source, "hclk_hz": self.hclk_hz,
                "pclk1_hz": self.pclk1_hz, "pclk2_hz": self.pclk2_hz,
                "tim_clk_apb1_hz": self.tim_clk_apb1_hz, "tim_clk_apb2_hz": self.tim_clk_apb2_hz, "pll": self.pll}


def decode(cr: int, cfgr: int, pllcfgr: int, hse_hz: int | None) -> ClockState:
    """Cây clock từ giá trị thanh ghi. `hse_hz` do bo mạch cung cấp (thạch anh); None = chưa biết, không đoán."""
    notes: list[str] = []
    pllsrc = bits(pllcfgr, 0, 2)
    m, n, r = bits(pllcfgr, 4, 4) + 1, bits(pllcfgr, 8, 7), _PLLR[bits(pllcfgr, 25, 2)]
    src_name = _SRC.get(pllsrc, "none")
    src_hz = HSI16_HZ if src_name == "HSI16" else (hse_hz if src_name == "HSE" else None)
    vco_in = src_hz / m if src_hz else None
    vco = vco_in * n if vco_in else None
    r_hz = vco / r if vco else None
    pll = {"source": src_name, "m": m, "n": n, "r": r,
           "vco_in_hz": _num(vco_in) if vco_in else None, "vco_hz": _num(vco) if vco else None,
           "r_hz": _num(r_hz) if r_hz else None, "on": bool(cr & CR_PLLON)}
    sw = bits(cfgr, 2, 2)                      # SWS (nguồn đang thực sự dùng), không phải SW: nguồn chưa sẵn sàng thì chưa chuyển
    if sw == SW_PLL:
        source, sysclk = "PLL", r_hz
    elif sw == SW_HSE:
        source, sysclk = "HSE", hse_hz
        if hse_hz is None:
            notes.append("SYSCLK = HSE but the board's HSE frequency (hse_hz) is unknown: not guessed")
    else:
        source, sysclk = "HSI16", HSI16_HZ
    if src_name == "HSE" and hse_hz is None and (sw == SW_PLL):
        notes.append("PLL source is HSE but the board's HSE frequency (hse_hz) is unknown: not guessed")
    hpre = _HPRE.get(bits(cfgr, 4, 4), 1)
    p1, p2 = _PPRE.get(bits(cfgr, 8, 3), 1), _PPRE.get(bits(cfgr, 11, 3), 1)
    hclk = sysclk / hpre if sysclk else None
    pclk1 = hclk / p1 if hclk else None
    pclk2 = hclk / p2 if hclk else None
    t1 = None if pclk1 is None else pclk1 * (1 if p1 == 1 else 2)           # RM p.281 §7.2.13
    t2 = None if pclk2 is None else pclk2 * (1 if p2 == 1 else 2)
    return ClockState(
        sysclk_hz=_num(sysclk) if sysclk else None, sysclk_source=source, hclk_hz=_num(hclk) if hclk else None,
        pclk1_hz=_num(pclk1) if pclk1 else None, pclk2_hz=_num(pclk2) if pclk2 else None,
        tim_clk_apb1_hz=_num(t1) if t1 else None, tim_clk_apb2_hz=_num(t2) if t2 else None,
        hpre_div=hpre, ppre1_div=p1, ppre2_div=p2, pll=pll, hsi16_on=bool(cr & CR_HSION), hse_on=bool(cr & CR_HSEON),
        hse_hz=hse_hz, notes=notes)


# ------------------------------------------------------------------------------------------ giới hạn
@dataclass
class Limits:
    hclk_max: float
    pll_in: tuple[float, float]
    vco: dict[str, tuple[float, float]]                      # "range1" | "range2"
    pllr_max: dict[str, float]                               # "boost" | "normal" | "range2"
    flash_ws: dict[str, list[tuple[int, float]]]             # mode -> [(latency, max HCLK)]

    @staticmethod
    def mode(vos: int, r1mode: int) -> str:
        if vos == 0b10:
            return "range2"
        return "normal" if r1mode else "boost"

    def sysclk_max(self, mode: str) -> float:
        return {"boost": self.hclk_max, "normal": 150e6, "range2": 26e6}[mode]

    def needed_ws(self, hclk: float, mode: str) -> int | None:
        for ws, fmax in sorted(self.flash_ws[mode]):
            if hclk <= fmax:
                return ws
        return None

    def max_hclk_for(self, latency: int, mode: str) -> float | None:
        table = dict(self.flash_ws[mode])
        ws = [w for w in table if w <= latency]
        return table[max(ws)] if ws else None


_LIM_CACHE: dict = {}


def load_limits(chip: str = "stm32g474", db_path: str | Path | None = None) -> Limits:
    db = Path(db_path) if db_path else data.default_db()
    key = (chip, str(db), db.stat().st_mtime_ns)
    if key in _LIM_CACHE:
        return _LIM_CACHE[key]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT parameter, symbol, min, max, condition FROM clock_limits WHERE chip=?", (chip,)).fetchall()
    finally:
        con.close()

    def f(x):
        return float(x) * 1e6 if x not in (None, "") else None

    hclk_max = pll_in = None
    vco: dict[str, tuple[float, float]] = {}
    pllr: dict[str, float] = {"boost": 0.0}
    ws: dict[str, list[tuple[int, float]]] = {"boost": [], "normal": [], "range2": []}
    for parameter, symbol, lo, hi, cond in rows:
        cond = cond or ""
        if parameter.startswith("AHB clock frequency"):
            hclk_max = f(hi)
        elif symbol == "fPLL_IN":
            pll_in = (f(lo), f(hi))
        elif symbol == "fVCO_OUT":
            vco["range2" if "Range 2" in cond else "range1"] = (f(lo), f(hi))
        elif symbol == "fPLL_R_OUT":
            pllr["range2" if "Range 2" in cond else "normal"] = f(hi)
        else:
            m = re.match(r"Flash wait states: (\d) WS", parameter)
            if m:
                mode = "range2" if "Range 2" in cond else ("normal" if "normal" in cond else "boost")
                ws[mode].append((int(m.group(1)), f(hi)))
    pllr["boost"] = hclk_max
    if None in (hclk_max, pll_in) or set(vco) != {"range1", "range2"} or not all(ws.values()):
        raise RuntimeError("clock_limits is missing rows hwmodel needs (HCLK, PLL input, VCO ranges, Flash wait states)")
    _LIM_CACHE[key] = Limits(hclk_max=hclk_max, pll_in=pll_in, vco=vco, pllr_max=pllr, flash_ws=ws)
    return _LIM_CACHE[key]
