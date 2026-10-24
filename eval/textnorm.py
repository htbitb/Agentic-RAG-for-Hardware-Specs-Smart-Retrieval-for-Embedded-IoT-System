"""Chuẩn hoá văn bản cho graders: hex, khoảng bit, đại lượng có đơn vị, kiểu truy cập.

Bảng đơn vị và `quantities` được sao chép/điều chỉnh từ agent/ingestion/unit_normalizer.py
(không import từ agent để eval độc lập với phiên bản agent).
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- hex
_HEX = re.compile(
    r"0[xX]([0-9A-Fa-f]{4})((?: (?:(?=[A-Fa-f]*\d)[0-9A-Fa-f]{4}|[A-F]{4})(?![0-9A-Za-z_]))+)"   # 0x4800 0000 / 0xABFF FFFF (ST)
    r"|0[xX]([0-9A-Fa-f]+(?:_[0-9A-Fa-f]+)*)"                                      # 0x48000000 / 0x4800_0000
)
_CITATION = re.compile(r"\[[^\]]{0,80}?\bp\.\s*\d+(?:\s*[-–]\s*\d+)?[^\]]*\]|\(\s*[A-Za-z0-9_]+\s+p\.\s*\d+\s*\)")


def hex_tokens_at(text: str) -> list[tuple[int, int, int]]:
    """[(đầu, cuối, giá trị)] cho mọi literal hex (D34: cần vị trí để gán giá trị cho thuộc tính đứng cạnh)."""
    out = []
    for m in _HEX.finditer(text or ""):
        digits = (m.group(1) + m.group(2)) if m.group(1) else m.group(3)
        out.append((m.start(), m.end(), int(digits.replace(" ", "").replace("_", ""), 16)))
    return out


def hex_tokens(text: str) -> list[int]:
    return [h for _, _, h in hex_tokens_at(text)]


def strip_hex_and_citations(text: str) -> str:
    return _HEX.sub(" ", _CITATION.sub(" ", text or ""))


_NUM = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])")


def number_tokens(text: str) -> list[float]:
    """Số thập phân trong văn bản, bỏ qua số trong hex và trong trích dẫn [doc p.N]."""
    return [float(m.group(0)) for m in _NUM.finditer(strip_hex_and_citations(text))]


# ----------------------------------------------------------------------- bit ranges
_SEP = r"(?:-|–|\.\.|:|to|through)"
_BR_BRACKET = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]|(?<=\w)\[\s*(\d+)\s*\]")   # [6:4] | OTYPE[3] (không tính chú thích ' [1]')
_BR_WORD = re.compile(rf"\bbits?(?:\s+positions?)?\s+(\d+)(?:\s*{_SEP}\s*(\d+))?", re.I)
_BR_WORD_BRACKET = re.compile(r"\bbits?\s*:?\s*\[\s*(\d+)\s*\]", re.I)               # 'bit [17]', 'Bit: [17]'
_BR_OFFSET = re.compile(r"\bbit\s+offset\s+(\d+)(?:\s*[,;]?\s*(?:and\s+)?(?:bit\s+)?width\s+(\d+))?", re.I)  # 'bit offset 4, bit width 3'
_MD = re.compile(r"[*`]+")                                                                # nhấn mạnh / code markdown


def bit_ranges(text: str) -> set[tuple[int, int]]:
    """Các khoảng bit (lo, hi) xuất hiện trong văn bản: [6:4], bits 4-6, bit 4..6, bit 5, bit [5], bit offset 4 + width 3."""
    out = set()
    text = _MD.sub("", text or "")
    for m in _BR_WORD_BRACKET.finditer(text):
        out.add((int(m.group(1)), int(m.group(1))))
    for m in _BR_OFFSET.finditer(text):
        lo = int(m.group(1))
        out.add((lo, lo + int(m.group(2)) - 1 if m.group(2) else lo))
    for m in _BR_BRACKET.finditer(text):
        a = int(m.group(1) if m.group(1) is not None else m.group(3))
        b = int(m.group(2)) if m.group(2) is not None else a
        out.add((min(a, b), max(a, b)))
    for m in _BR_WORD.finditer(text):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) is not None else a
        out.add((min(a, b), max(a, b)))
    return out


# ------------------------------------------------------------------------- access
def canonical_access(text: str) -> set[str]:
    t = (text or "").lower()
    found = set()
    if re.search(r"read\s*[-/ ]?\s*write|\br\s*/\s*w\b|\brw\b", t):
        found.add("rw")
    # tránh nhầm 'read-only' khi nằm trong 'read-only/write-only' hiếm gặp: đủ cho C1
    if re.search(r"read\s*[-/ ]?\s*only|\bro\b", t):
        found.add("ro")
    if re.search(r"write\s*[-/ ]?\s*only|\bwo\b", t):
        found.add("wo")
    return found


# ------------------------------------------------------------------- quantities
_UNITS: dict[str, tuple[float, str]] = {
    "kv": (1e3, "V"), "v": (1.0, "V"), "volt": (1.0, "V"), "volts": (1.0, "V"), "mv": (1e-3, "V"),
    "uv": (1e-6, "V"), "µv": (1e-6, "V"), "μv": (1e-6, "V"),
    "a": (1.0, "A"), "ma": (1e-3, "A"), "ua": (1e-6, "A"), "µa": (1e-6, "A"), "μa": (1e-6, "A"), "na": (1e-9, "A"),
    "ghz": (1e9, "Hz"), "mhz": (1e6, "Hz"), "khz": (1e3, "Hz"), "hz": (1.0, "Hz"),
    "mohm": (1e6, "ohm"), "mω": (1e6, "ohm"), "kohm": (1e3, "ohm"), "kω": (1e3, "ohm"), "ohm": (1.0, "ohm"), "ω": (1.0, "ohm"),
    "mf": (1e-3, "F"), "uf": (1e-6, "F"), "µf": (1e-6, "F"), "μf": (1e-6, "F"), "nf": (1e-9, "F"), "pf": (1e-12, "F"),
    "°c": (1.0, "C"), "degc": (1.0, "C"),
}
_UNIT_PAT = "|".join(sorted((re.escape(k) for k in _UNITS), key=len, reverse=True))
_QTY = re.compile(rf"(?<![A-Za-z0-9_.\-])(-?\d+(?:\.\d+)?)\s*({_UNIT_PAT})(?![A-Za-z0-9_])", re.I)
# Khoảng / danh sách có đơn vị ở số CUỐI: "2.3-3.6 V", "2.3–3.6 V", "1.7 to 3.6 V", "between 2.3 and 3.6 V", "80/160/240 MHz".
# Mỗi số trong danh sách đều mang đơn vị đó (review D12). Biên trái giống _QTY nên "VDD-0.3 V" không bị coi là khoảng.
_NUM_ = r"\d+(?:\.\d+)?"
_QTY_LIST = re.compile(
    rf"(?<![A-Za-z0-9_.\-])(-?{_NUM_})((?:\s*[-–—/]\s*{_NUM_}|\s+(?:to|and|or)\s+{_NUM_}){{1,8}})\s*({_UNIT_PAT})(?![A-Za-z0-9_])", re.I)   # {1,8}: tránh backtracking bậc hai


_MD_MARK = re.compile(r"[*`_$]|\\text\{|\}")
_BARE_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
_UNIT_CELL_SKIP = {"a", "s"}                          # 'A'/'s' đơn lẻ trong một ô bảng thường là chữ cái / giây ngẫu nhiên, không đủ tin để gán đơn vị
_OTHER_UNIT_CELLS = {"s", "ms", "µs", "μs", "us", "ns", "%", "bit", "bits", "baud", "bps", "kbps", "mbps", "ksps", "msps", "db", "lsb", "ppm", "kb", "mb", "a"}  # đơn vị `quantities` không hiểu: hàng có chúng là mơ hồ


def carry_row_units(text: str) -> str:
    """D18 (P4): trong một HÀNG bảng markdown có đúng MỘT ô chỉ chứa một đơn vị (V, mA, MHz, µs...), mọi ô chỉ chứa số trong hàng đó mang đơn vị ấy
    ("| VDD | **1.7** | **3.6** | V |" => 1.7 V, 3.6 V). Hàng có hai ô đơn vị, ô số đã có đơn vị, hay dòng không bắt đầu bằng '|' được giữ nguyên."""
    if "|" not in (text or ""):
        return text
    out = []
    for line in text.split("\n"):
        if not line.lstrip().startswith("|") or line.count("|") < 3:
            out.append(line)
            continue
        cells = line.strip().strip("|").split("|")
        plain = [_MD_MARK.sub("", c).strip() for c in cells]
        units = [i for i, c in enumerate(plain) if c.lower() in _UNITS and c.lower() not in _UNIT_CELL_SKIP]
        if len(units) != 1 or any(c.lower() in _OTHER_UNIT_CELLS for c in plain):
            out.append(line)
            continue
        unit = plain[units[0]]
        out.append("| " + " | ".join(f"{p} {unit}" if i != units[0] and _BARE_NUM.match(p) else c.strip() for i, (c, p) in enumerate(zip(cells, plain))) + " |")
    return "\n".join(out)


def quantities_at(text: str) -> list[tuple[int, int, tuple[float, str, float, str]]]:
    """Như `quantities` nhưng kèm (đầu, cuối) của cụm khớp; mọi số của một khoảng/danh sách "A-B unit" chung một cụm.
    Vị trí tính trên `carry_row_units(text)` (hàm này luỹ đẳng: truyền văn bản đã chuyển vào thì vị trí khớp chính văn bản đó)."""
    text = carry_row_units(text or "")
    found: list[tuple[int, int, float, str]] = []    # (đầu, cuối, giá trị, đơn vị)
    spans = []
    for m in _QTY_LIST.finditer(text or ""):
        spans.append(m.span())
        nums = [float(m.group(1))] + [float(x) for x in re.findall(_NUM_, m.group(2))]
        found += [(m.start(), m.end(), v, m.group(3)) for v in nums]
    for m in _QTY.finditer(text or ""):
        if any(a <= m.start() < b for a, b in spans):
            continue
        found.append((m.start(), m.end(), float(m.group(1)), m.group(2)))
    out = []
    for start, end, val, unit in sorted(found, key=lambda x: x[0]):
        if unit == "a":                      # 'a' thường là mạo từ ("section 3 a register"); ampere phải viết 'A'
            continue
        scale, base = _UNITS[unit.lower()]
        out.append((start, end, (val, unit, val * scale, base)))
    return out


def quantities(text: str) -> list[tuple[float, str, float, str]]:
    """(giá_trị_thô, đơn_vị_thô, giá_trị_SI, đơn_vị_cơ_sở) cho mọi đại lượng có đơn vị (kể cả khoảng/danh sách "A-B unit")."""
    return [q for _, _, q in quantities_at(text)]


# Đơn vị của mục checklist `quantity` (C5, P5): bảng trên + tốc độ truyền, thời gian, công suất, dung lượng pin. Khoá viết thường.
QTY_UNITS: dict[str, tuple[float, str]] = {
    **_UNITS,
    "bps": (1.0, "bps"), "kbps": (1e3, "bps"), "mbps": (1e6, "bps"), "baud": (1.0, "bps"), "kbaud": (1e3, "bps"), "bd": (1.0, "bps"),
    "s": (1.0, "s"), "ms": (1e-3, "s"), "us": (1e-6, "s"), "µs": (1e-6, "s"), "μs": (1e-6, "s"), "ns": (1e-9, "s"),
    "w": (1.0, "W"), "mw": (1e-3, "W"), "uw": (1e-6, "W"), "µw": (1e-6, "W"), "μw": (1e-6, "W"),
    "ah": (1.0, "Ah"), "mah": (1e-3, "Ah"), "%": (1.0, "%"),
    # thời gian dài (tuổi thọ pin, C5): tháng = 365,25/12 ngày, năm = 365,25 ngày
    "min": (60.0, "s"), "mins": (60.0, "s"), "minute": (60.0, "s"), "minutes": (60.0, "s"),
    "h": (3600.0, "s"), "hr": (3600.0, "s"), "hrs": (3600.0, "s"), "hour": (3600.0, "s"), "hours": (3600.0, "s"),
    "d": (86400.0, "s"), "day": (86400.0, "s"), "days": (86400.0, "s"), "week": (604800.0, "s"), "weeks": (604800.0, "s"),
    "month": (2629800.0, "s"), "months": (2629800.0, "s"), "year": (31557600.0, "s"), "years": (31557600.0, "s"), "yr": (31557600.0, "s"),
    "yrs": (31557600.0, "s"),
    # đơn vị viết bằng chữ (review C5 G9: "11.7 microamps")
    **{f"{pre}{base}{pl}": (scale, si) for base, si in (("amp", "A"), ("ampere", "A"), ("volt", "V"), ("watt", "W"))
       for pre, scale in (("", 1.0), ("milli", 1e-3), ("micro", 1e-6), ("nano", 1e-9)) for pl in ("", "s")},
    **{f"{pre}hertz": (scale, "Hz") for pre, scale in (("", 1.0), ("kilo", 1e3), ("mega", 1e6), ("giga", 1e9))},
    **{f"{pre}second{pl}": (scale, "s") for pre, scale in (("", 1.0), ("milli", 1e-3), ("micro", 1e-6), ("nano", 1e-9)) for pl in ("", "s")},
    "sec": (1.0, "s"), "secs": (1.0, "s"),
}


def qty_unit(unit: str) -> tuple[float, str] | None:
    """(hệ số về đơn vị cơ sở, đơn vị cơ sở) của một đơn vị viết tự do ('MHz', 'uA', 'µA', 'kbps'...); None nếu không biết."""
    return QTY_UNITS.get(str(unit or "").strip().lower())


def close(a: float, b: float, rel: float = 1e-6, abs_: float = 1e-12) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


# ---------------------------------------------------------- numeric tokens + positions
_ANY_NUM = re.compile(_HEX.pattern + r"|(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])")


def numeric_tokens_kinds(text: str) -> list[tuple[int, float, bool]]:
    """[(vị trí, giá trị, là_hex)] cho cả hex lẫn thập phân (trích dẫn [doc p.N] bị bỏ qua)."""
    text = _CITATION.sub(lambda m: " " * len(m.group(0)), text or "")
    out = []
    for m in _ANY_NUM.finditer(text):
        s_ = m.group(0)
        if s_[:2].lower() == "0x":
            digits = (m.group(1) + m.group(2)) if m.group(1) else m.group(3)
            out.append((m.start(), float(int(digits.replace(" ", "").replace("_", ""), 16)), True))
        else:
            out.append((m.start(), float(s_), False))
    return out


def numeric_tokens_at(text: str) -> list[tuple[int, float]]:
    """[(vị trí, giá trị)] cho cả hex lẫn thập phân."""
    return [(p, v) for p, v, _ in numeric_tokens_kinds(text)]


def numeric_after(text: str, keywords: list[str], window: int = 45, stop: list[str] | None = None) -> list[float]:
    """Giá trị được nêu sau từ khoá, trong cùng câu và trước từ khoá thuộc tính khác (`stop`).
    Ưu tiên hex: lấy hex ĐẦU TIÊN trong 120 ký tự (đọc trọn literal). Không có hex thì lấy số thập phân đầu tiên
    BẮT ĐẦU trong `window` ký tự ('Register 1' chỉ là nhiễu khi phía sau có hex)."""
    vals: list[float] = []
    stop_rx = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in (stop or [])) + r")\b", re.I) if stop else None
    for kw in keywords:
        for m in re.finditer(rf"\b{re.escape(kw)}\b", text or "", re.I):
            seg = text[m.end():m.end() + 160]
            seg = re.split(r"[.;\n](?!\d)", seg)[0]                  # dừng ở hết câu
            if stop_rx:
                cut = stop_rx.search(seg)
                if cut:
                    seg = seg[:cut.start()]
            toks = numeric_tokens_kinds(seg)
            hexes = [v for pos, v, is_hex in toks if is_hex and pos < 120]
            decs = [v for pos, v, is_hex in toks if not is_hex and pos < window]
            if hexes:
                vals.append(hexes[0])
            elif decs:
                vals.append(decs[0])
    return vals
