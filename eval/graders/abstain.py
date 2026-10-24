"""abstain (C8): phải abstain đúng lúc và không bịa số liệu.

Giá trị (đại lượng có đơn vị / hex / số tiền / ước lượng bằng chữ) chỉ bị coi là bịa khi nó được nêu CHO đối tượng/thuộc tính được hỏi.
(1) Thực thể khác (review A-2): bỏ qua mệnh đề nhắc chip khác đã được index, hoặc chỉ nhắc định danh (DAC_CR, SPIM3, PLL_D2_CLK...)
    không có trong câu hỏi và không nhắc định danh nào của câu hỏi. Giá trị nêu cho chính đối tượng được hỏi ("but typically
    72 MHz", "SPIM4 is at 0x...") vẫn là bịa dù đã abstain.
(2) Thuộc tính khác (D34 a): thuộc tính được hỏi đọc từ câu hỏi (address, price, current...). Giá trị mà câu trả lời GHI RÕ là của một
    thuộc tính khác — từ chỉ thuộc tính cùng chiều đứng sát giá trị, không có giá trị khác chen giữa ("temperature range, -40 to 85 °C",
    "stride of 0x14") — là dữ kiện về thuộc tính/thực thể khác, không phải câu trả lời. Giá trị không có nhãn vẫn tính (bảo thủ).
    Chỉ áp dụng khi câu hỏi nêu chip đã index (thuộc tính khác của nó tra được) và đọc được thuộc tính được hỏi.
(3) Ước lượng bằng chữ (D34 b): lượng từ + đơn vị ("single-digit USD", "sub-two microamps", "a few mA", "low-microampere range") chỉ
    tính khi đơn vị cùng chiều với thuộc tính được hỏi (hoặc không đọc được thuộc tính được hỏi). Số tiền ("$4.80", "5 USD") là giá trị.
Mọi luật áp dụng như nhau cho mọi hệ (D18). Kiểm bằng nhãn mù dev v2 là kiểm TRONG MẪU — P9 lặp lại nhãn mù trên `test`.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from eval import markers
from eval.textnorm import carry_row_units, close, hex_tokens, hex_tokens_at, quantities, quantities_at

KNOWN_CHIPS = re.compile(r"(?:esp32|stm32g474|nrf52840|freertos)(?:-[a-z0-9]+)?", re.I)       # kể cả hậu tố: ESP32-S3 != ESP32
INDEXED_CHIPS = {"esp32", "stm32g474", "nrf52840", "freertos"}                                   # đúng các tên trên, KHÔNG kèm hậu tố
# định danh: snake_case (DAC3_FOOBAR_CR, PLL_D2_CLK) hoặc chữ+số (SPIM4, TIM1, STM32G474, nRF9160, I2S)
_IDENT = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+|(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z][A-Za-z0-9]{2,})(?![A-Za-z0-9_])")
_CLAUSE = re.compile(r"(?<=[.!?])\s+|\n|\s*;\s*|,?\s+(?:but|however|whereas|while|though)\s+", re.I)
# D34: lời từ chối dạng 'not available in the offline technical documentation' (≤ 3 từ bổ nghĩa trước danh từ chỉ tài liệu)
_ABSTAIN_MORE = re.compile(
    r"\bnot (?:available|contained|found|included|covered|present|listed|provided|published)(?: (?:in|within|from|by))? "
    r"(?:the |my |these |this |any )?(?:[\w\-]+ ){0,3}(?:documents?|documentation|datasheets?|manuals?|corpus|sources?)\b", re.I)

# D34 (a): lớp thuộc tính -> (chiều của giá trị, từ chỉ thuộc tính). Chiều 'hex': địa chỉ, giá trị reset, khoảng cách/kích thước.
_ATTRS = {
    "address": ("hex", r"address(?:es)?|offsets?|located|mapped"),
    "reset": ("hex", r"reset"),                  # không gồm 'default' ('by default it maps to 0x...' là câu trả lời về địa chỉ)
    "stride": ("hex", r"strides?|spacing|spaced|apart|increments?|steps?|size|width|length"),
    "price": ("USD", r"prices?|priced|pricing|costs?|retail|sells?|msrp"),
    "current": ("A", r"currents?|consumption|draws?|drawn|quiescent|leakage"),
    "voltage": ("V", r"voltages?|supply|vdd\w*|vcc|vbat"),
    "frequency": ("Hz", r"frequenc(?:y|ies)|clocks?|speed|sysclk|hclk"),
    "temperature": ("C", r"temperatures?|junction|ambient|thermal"),
    "resistance": ("ohm", r"resistance|impedance|resistors?|pull-?(?:up|down)"),
    "capacitance": ("F", r"capacitance|capacitors?"),
}
_ATTR_RX = re.compile("|".join(rf"(?P<{k}>\b(?:{w})\b)" for k, (_, w) in _ATTRS.items()), re.I)
_BEFORE, _AFTER = 40, 15                     # nhãn đứng trước giá trị ('stride of 0x14') / sau giá trị ('105 °C junction'), tính bằng ký tự
_JOIN = re.compile(r"\s*(?:[-–—/,~]|to|and|or|through)\s*", re.I)    # khoảng/danh sách: các giá trị dùng chung nhãn

# D34 (b): ước lượng bằng chữ = lượng từ + đơn vị (ký hiệu đơn vị phân biệt hoa thường)
_NUMW = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|hundred|thousand|dozen)"
_QUANT = (r"(?:(?:low|high|mid|upper|lower)[- ])?(?:single|double|triple)[- ]digits?"
          r"|an? (?:few|couple(?: of)?|handful of|dozen|hundred|thousand)|several|tens of|dozens of|hundreds of|thousands of"
          r"|(?:an? )?fractions? of an?|half an?"
          rf"|sub[- ](?:{_NUMW}|\d+(?:\.\d+)?|an?)"
          r"|(?:under|below|less than|more than|over|above|about|around|roughly|approximately|nearly|almost|up to|at most|at least|only|just)"
          rf"\s+(?:an?|{_NUMW})"
          rf"|{_NUMW}")
_UNIT_WORDS = {
    "A": r"(?:micro|milli|nano)?amp(?:ere)?s?|(?-i:[mµuμn]A)",
    "V": r"(?:milli|micro)?volts?|(?-i:[mµuμ]?V)",
    "Hz": r"(?:kilo|mega|giga)?hertz|(?-i:[kMG]?Hz)",
    "C": r"degrees? (?:C|Celsius)|°C",
    "USD": r"(?:US )?dollars?|bucks|cents?|euros?|(?-i:USD|EUR)",
    "ohm": r"(?:kilo|mega)?ohms?|(?-i:[kM]?Ω)",
    "F": r"(?:pico|nano|micro)farads?|(?-i:[pnµuμ]F)",
}
_UNITW = "|".join(f"(?:{u})" for u in _UNIT_WORDS.values())
_WORDY = re.compile(
    rf"(?<![\w-])(?:(?:{_QUANT})[- ](?:(?:{_QUANT})[- ])?(?:of )?(?P<u1>{_UNITW})"     # 'a few mA', 'sub-two microamps', 'low single-digit microampere'
    rf"|sub[- ](?P<u2>{_UNITW})"                                                         # 'sub-microamp'
    rf"|(?:(?:low|high|mid)[- ])?(?P<u3>{_UNITW})[- ](?:range|level|region))(?!\w)",   # 'low-microampere range', 'nanoamp range'
    re.I)
_UNIT_DIM = [(d, re.compile(u, re.I)) for d, u in _UNIT_WORDS.items()]
# số tiền: '$4.80', 'US$ 5', '€3', '5 USD', 'USD 5', '5 dollars' (không bắt công thức LaTeX '$8$', '$2^{10}$', '$20 \times 8$')
_MONEY = re.compile(
    r"(?<![\w$\\])(?:US\s?)?[$€£]\s?(\d+(?:[.,]\d+)?)(?!\d|[.,]\d|\s*[$^{}=+*/\\]|\w)"
    r"|(?<![\w.])(\d+(?:\.\d+)?)\s?(?:(?-i:USD|EUR)|US dollars?|dollars?|euros?|(?P<cents>cents?))(?!\w)"
    r"|(?<!\w)(?-i:USD|EUR)\s?(\d+(?:\.\d+)?)(?!\w)", re.I)


class _Val(NamedTuple):
    start: int
    end: int
    dim: str                  # 'V', 'A', 'Hz', 'C', 'ohm', 'F', 'USD' hoặc 'hex'
    text: str
    key: tuple | None         # để so với giá trị đã có trong câu hỏi; None = ước lượng bằng chữ


def _idents(text: str) -> set[str]:
    return {m.group(0).lower() for m in _IDENT.finditer(text or "")}


def asked_attributes(question: str) -> set[str]:
    """Lớp thuộc tính được hỏi. 'current' đứng ngay trước một từ thuộc tính khác là tính từ ('current retail price')."""
    ms = list(_ATTR_RX.finditer(question or ""))
    out = set()
    for i, m in enumerate(ms):
        nxt = ms[i + 1] if i + 1 < len(ms) else None
        if m.lastgroup == "current" and nxt and nxt.lastgroup != "current" and not question[m.end():nxt.start()].strip():
            continue
        out.add(m.lastgroup)
    return out


def _money(m: re.Match) -> float:
    amount = float((m.group(1) or m.group(2) or m.group(3)).replace(",", ""))
    return amount / 100 if m.group("cents") else amount


def _values(text: str) -> list[_Val]:
    words = []
    for m in _WORDY.finditer(text):
        unit = m.group("u1") or m.group("u2") or m.group("u3")
        words.append(_Val(m.start(), m.end(), next(d for d, rx in _UNIT_DIM if rx.fullmatch(unit)), m.group(0), None))
    inside = lambda s: any(w.start <= s < w.end for w in words)                     # 'sub 3 µA': chỉ tính một lần (dạng chữ)
    out = list(words)
    out += [_Val(s, e, q[3], f"{q[0]:g} {q[1]}", ("q", q[3], q[2])) for s, e, q in quantities_at(text) if not inside(s)]
    out += [_Val(s, e, "hex", f"0x{h:x}", ("hex", h)) for s, e, h in hex_tokens_at(text)]
    out += [_Val(m.start(), m.end(), "USD", m.group(0).strip(), ("q", "USD", _money(m))) for m in _MONEY.finditer(text) if not inside(m.start())]
    return sorted(out, key=lambda v: (v.start, v.end))


def _groups(vals: list[_Val], text: str) -> list[list[_Val]]:
    """Gom giá trị cùng chiều nối bằng 'to', '–', '/', ',', 'and'... ('-40 °C to 85 °C') thành một cụm dùng chung nhãn."""
    groups: list[list[_Val]] = []
    for v in vals:
        last = groups[-1][-1] if groups else None
        if last and (v.start < last.end or (v.dim == last.dim and _JOIN.fullmatch(re.sub(r"[`*]", "", text[last.end:v.start])))):
            groups[-1].append(v)
        else:
            groups.append([v])
    return groups


def _label(group: list[_Val], vals: list[_Val], words: list[tuple[int, int, str]]) -> str | None:
    """Lớp thuộc tính mà câu trả lời gán cho cụm giá trị: từ chỉ thuộc tính (`words`) CÙNG CHIỀU gần nhất, ngay trước (≤ _BEFORE) hoặc
    ngay sau (≤ _AFTER) cụm, không có giá trị khác chen giữa. None nếu không có."""
    gs, ge, dim, best = group[0].start, max(v.end for v in group), group[0].dim, None
    for ws, we, cls in words:
        if _ATTRS[cls][0] != dim:
            continue
        if we <= gs and gs - we <= _BEFORE:
            dist, lo, hi = gs - we, we, gs
        elif ws >= ge and ws - ge <= _AFTER:
            dist, lo, hi = ws - ge, ge, ws
        else:
            continue
        if any(lo <= v.start < hi for v in vals):
            continue
        if best is None or dist < best[0]:
            best = (dist, cls)
    return best[1] if best else None


def grade(task, run, ctx) -> dict:
    spec = task.expected.get("abstain")
    if not spec:
        raise ValueError(f"{task.id}: expected.abstain is required")
    answer = run.final_answer or ""
    known_hex, known_q = set(), []
    for text in [t.get("user", "") for t in task.turns] + list(spec.get("allowed_numbers", [])):
        known_hex.update(hex_tokens(text))
        known_q += [(q[3], q[2]) for q in quantities(text)] + [("USD", _money(m)) for m in _MONEY.finditer(text)]
    question = " ".join(t.get("user", "") for t in task.turns)
    q_chips, q_idents = {c.lower() for c in KNOWN_CHIPS.findall(question)}, _idents(question)
    asked = asked_attributes(question)
    asked_dims = {_ATTRS[a][0] for a in asked}
    # luật thuộc tính chỉ áp dụng khi đối tượng được hỏi thuộc chip ĐÃ index: thuộc tính khác của nó là dữ kiện tra được.
    # Chip ngoài corpus (nRF9160, STM32F103, ESP32-S3...): mọi giá trị gán cho nó đều không có nguồn => vẫn tính, bất kể thuộc tính.
    by_attr = bool(asked) and bool(q_chips & INDEXED_CHIPS)
    fabricated, other = [], []
    for clause in _CLAUSE.split(answer):
        # chip KHÁC đã được index (không có trong câu hỏi) là đối chiếu, không phải bịa số cho đối tượng được hỏi
        if {c.lower() for c in KNOWN_CHIPS.findall(clause)} - q_chips:
            continue
        ids = _idents(clause)
        if ids and not ids & q_idents:               # chỉ nói về thực thể khác (DAC_CR, SPIM3...)
            continue
        text = carry_row_units(clause)
        vals = _values(text)
        words = [(m.start(), m.end(), m.lastgroup) for m in _ATTR_RX.finditer(text)] if by_attr else []
        for group in _groups(vals, text):
            label = _label(group, vals, words) if by_attr else None
            for v in group:
                if v.key and (v.key[0] == "hex" and v.key[1] in known_hex
                              or v.key[0] == "q" and any(b == v.key[1] and close(s, v.key[2], rel=1e-3) for b, s in known_q)):
                    continue                         # nhắc lại số của câu hỏi / số được phép
                if v.key is None and asked and v.dim not in asked_dims:
                    other.append(f"{v.text} ({v.dim})")         # ước lượng bằng chữ của đại lượng khác thuộc tính được hỏi
                elif v.key is not None and label and label not in asked:
                    other.append(f"{v.text} ({label})")         # giá trị được ghi rõ là của thuộc tính khác
                else:
                    fabricated.append(v.text)
    abstained = markers.is_abstention(answer) or bool(_ABSTAIN_MORE.search(answer))
    reasons = []
    if not abstained:
        reasons.append("hallucinated_answer: answered an unanswerable question instead of abstaining")
    if fabricated:
        reasons.append(f"hallucinated_value: {', '.join(fabricated)}")
    return {"pass": abstained and not fabricated, "score": 1.0 if (abstained and not fabricated) else 0.0,
            "reasons": reasons, "details": {"abstained": abstained, "fabricated": fabricated, "other_attribute": other,
                                            "asked_attributes": sorted(asked)}}
