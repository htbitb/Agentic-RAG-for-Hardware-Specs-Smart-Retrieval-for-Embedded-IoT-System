"""Trạng thái khởi đầu của G2 (D36): do INTAKE trích từ lời người dùng (hoặc cấu hình clock đã có trong Board State), KHÔNG do agent tự chọn.

`extract_start(user_texts, board, human_answers)` -> {"initial": tên preset của simulator | None, "hse_hz": int | None, "source": "user_text" | "board_clock" | None,
"hse_source": ..., "evidence": câu gốc}. Quy tắc tổng quát (không theo task): chỉ câu có dấu hiệu MÔ TẢ TRẠNG THÁI HIỆN CÓ ("initial state", "already",
"out of reset", "currently"...) mới được coi là trạng thái khởi đầu; một tần số SYSCLK là mục tiêu thiết kế ("configure the PLL so that SYSCLK = 170 MHz") thì không.
Câu mô tả được ánh xạ sang preset của simulator (reset / 170 MHz / 80 MHz, PLL từ HSI16, prescaler APB); không ánh xạ được thì không có preset (Gate mô phỏng từ reset).
"""
from __future__ import annotations

import re

_CUE = re.compile(r"initial state|initially|already|out of reset|from reset|reset state|power[- ]?on|currently|is running|are running|has been configured|have been configured|just (?:come|came)",
                  re.I)
_CUE_FREQ = re.compile(r"(?:STM32\w*|MCU|chip|board|device|clocked|running|runs|operating)\b[^.;()]{0,25}?\bat\s+\d+(?:\.\d+)?\s*MHz", re.I)    # "an STM32G474 at 170 MHz (PLL from HSI16 ...)"
_GOAL = re.compile(r"\b(?:configure|set up|program|bring|switch|raise|reach|achieve|make|target|so that|in order to|must|should|at most|up to|maximum|limit)\b", re.I)   # mục tiêu thiết kế, không phải trạng thái
_AT_FREQ = re.compile(r"\bat\s+(\d+(?:\.\d+)?)\s*MHz", re.I)
_CLOCK_WORD = re.compile(r"SYSCLK|HCLK|PCLK|system clock|\bHSI|\bPLL\b", re.I)          # câu chỉ nói "peripheral clock ... reset state" (GPIO, bật clock ngoại vi) không mô tả clock hệ thống
_RESET_CUE = re.compile(r"out of reset|from reset|reset state|power[- ]?on reset|reset values?\b", re.I)
_SYSCLK = re.compile(r"(?:SYSCLK|system clock)\b(?:\s*=\s*[A-Za-z]+\d?)*\s*(?:=|of|at|is|to)?\s*(\d+(?:\.\d+)?)\s*MHz", re.I)
_SYSCLK_AFTER = re.compile(r"(\d+(?:\.\d+)?)\s*MHz\s*(?:SYSCLK|system clock)", re.I)
_PCLK = re.compile(r"PCLK([12])\s*=\s*(\d+(?:\.\d+)?)\s*MHz", re.I)
_APB = re.compile(r"APB([12])\s*(?:prescaler|divider)s?\s*(?:is|=|of|set to|equals?)?\s*(\d+)", re.I)
_AHB = re.compile(r"\bAHB\s*(?:prescaler|divider)s?\s*(?:is|=|of|set to|equals?)?\s*(\d+)", re.I)
_HSE_AFTER = re.compile(r"HSE\s*(?:clock|crystal|oscillator|frequency|input)?\s*(?:=|:|of|is|at|runs at|\()\s*(\d+(?:\.\d+)?)\s*MHz", re.I)
_HSE_BEFORE = re.compile(r"(\d+(?:\.\d+)?)\s*MHz\s*(?:external\s*)?(?:crystal|oscillator|xtal|resonator)", re.I)
_HSE_NEAR = re.compile(r"(?:crystal|oscillator|xtal)\s*(?:of|is|at|=|:)\s*(\d+(?:\.\d+)?)\s*MHz", re.I)

_P170, _P80 = "sysclk_170mhz_pll_hsi16_apb_div1", "sysclk_80mhz_pll_hsi16_apb_div1"
_PRESET_BY_SYSCLK = {
    (170, 1, 1): _P170, (170, 2, 1): "sysclk_170mhz_pll_hsi16_apb1_div2", (170, 1, 2): "sysclk_170mhz_pll_hsi16_apb2_div2", (80, 1, 1): _P80}


def _sentences(text: str) -> list[str]:
    """Tách câu ở dấu chấm (không tách số thập phân) — đủ cho các câu mô tả trạng thái dài có dấu chấm phẩy và ngoặc."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'`])", text.replace("\n", " ")) if s.strip()]


def _num(x: str) -> float:
    return float(x)


def _map_description(seg: str) -> str | None:
    """Preset của simulator mô tả đúng câu `seg`, hoặc None."""
    sysclk = None
    for rx in (_SYSCLK, _SYSCLK_AFTER, _AT_FREQ):
        m = rx.search(seg)
        if m:
            sysclk = _num(m.group(1))
            break
    if _RESET_CUE.search(seg) and (sysclk is None or sysclk == 16):
        return "reset"
    if sysclk is None:
        return "reset" if re.search(r"\bHSI16?\b", seg, re.I) and not re.search(r"\bPLL\b", seg) and _RESET_CUE.search(seg) else None
    if not re.search(r"\bPLL\b", seg):
        return "reset" if sysclk == 16 and re.search(r"HSI", seg, re.I) else None
    if re.search(r"HSE", seg, re.I) and not re.search(r"HSI", seg, re.I):
        return None                                                    # PLL từ HSE: các preset đều từ HSI16
    ahb = _AHB.search(seg)
    if ahb and int(ahb.group(1)) != 1:
        return None
    div = {"1": 1, "2": 1}
    for m in _APB.finditer(seg):
        div[m.group(1)] = int(m.group(2))
    for m in _PCLK.finditer(seg):                                       # "so PCLK1 = 85 MHz" => prescaler 2 khi chưa nêu tường minh
        k = m.group(1)
        if k not in {x.group(1) for x in _APB.finditer(seg)} and _num(m.group(2)) > 0 and abs(sysclk / _num(m.group(2)) - round(sysclk / _num(m.group(2)))) < 0.05:
            div[k] = int(round(sysclk / _num(m.group(2))))
    return _PRESET_BY_SYSCLK.get((int(sysclk) if sysclk == int(sysclk) else -1, div["1"], div["2"]))


def preset_from_derived(derived: dict) -> str | None:
    """Preset tương ứng với tần số dẫn xuất của cấu hình clock trên Board State (hoặc None)."""
    if not isinstance(derived, dict):
        return None
    mhz = lambda k: round((derived.get(k) or 0) / 1e6, 3)
    sysclk, hclk, p1, p2 = mhz("sysclk_hz"), mhz("hclk_hz"), mhz("pclk1_hz"), mhz("pclk2_hz")
    pll = derived.get("pll") if isinstance(derived.get("pll"), dict) else {}
    if derived.get("sysclk_source") != "PLL":
        return "reset" if (sysclk, hclk, p1, p2) == (16, 16, 16, 16) and derived.get("sysclk_source") in (None, "HSI16") else None
    if pll.get("source") not in (None, "HSI16") or sysclk != hclk:
        return None
    if sysclk not in (170, 80) or p1 not in (sysclk, sysclk / 2) or p2 not in (sysclk, sysclk / 2):
        return None
    return _PRESET_BY_SYSCLK.get((int(sysclk), 1 if p1 == sysclk else 2, 1 if p2 == sysclk else 2))


def _hse(text: str) -> int | None:
    for rx in (_HSE_AFTER, _HSE_BEFORE, _HSE_NEAR):
        m = rx.search(text)
        if m and float(m.group(1)) > 0:
            return int(round(float(m.group(1)) * 1e6))
    return None


def extract_start(user_texts, board: dict | None = None, human_answers=()) -> dict:
    out = {"initial": None, "hse_hz": None, "source": None, "hse_source": None, "evidence": None}
    texts = [t for t in [*(user_texts or []), *(human_answers or [])] if isinstance(t, str)]
    for t in texts:                                                     # văn bản sau ghi đè văn bản trước
        for seg in _sentences(t):
            strong = bool(_CUE.search(seg))
            if (strong or (_CUE_FREQ.search(seg) and not _GOAL.search(seg))) and _CLOCK_WORD.search(seg):
                preset = _map_description(seg)
                if preset or strong:
                    out.update(initial=preset, source="user_text" if preset else "user_text_unmapped", evidence=seg[:300])
        h = _hse(t)
        if h:
            out.update(hse_hz=h, hse_source="user_text")
    clock = (board or {}).get("clock") or {}
    if out["initial"] is None and clock.get("derived"):
        preset = preset_from_derived(clock["derived"])
        if preset:
            out.update(initial=preset, source="board_clock", evidence="Board State clock: " + str({k: clock["derived"].get(k) for k in ("sysclk_hz", "pclk1_hz", "pclk2_hz")}))
    if out["hse_hz"] is None and isinstance(clock.get("cfg"), dict) and clock["cfg"].get("hse_hz"):
        out.update(hse_hz=int(clock["cfg"]["hse_hz"]), hse_source="board_clock")
    return out
