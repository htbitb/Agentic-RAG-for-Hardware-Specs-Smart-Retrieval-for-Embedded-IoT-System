"""Tách khối code C của câu trả lời (cho G2/G5) và phần văn xuôi (cho G1/G4). Viết độc lập với eval/graders (không import `eval`).

Quy tắc: khối ``` có thẻ c/cpp/h/arm/cmsis/stm32... hoặc không thẻ nhưng trông như C (có dòng kết thúc bằng ';' hoặc #include/#define);
nối theo thứ tự, bỏ khối trùng; nếu có chương trình đầy đủ (main) thì bỏ các đoạn lệnh ghi thanh ghi rời (thường là ví dụ "đừng làm thế này").
Câu trả lời chỉ gồm đoạn lệnh rời (không có định nghĩa hàm nào) được bọc vào một hàm để phân tích/biên dịch được; `locate` đổi số dòng về khối gốc.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ingestion.unit_normalizer import _UNITS

C_TAGS = {"c", "cpp", "c++", "cc", "h", "hpp", "embedded-c", "arm", "cmsis", "stm32", "clike", "c11", "c99"}
_FENCE = re.compile(r"```([^\n`]*)\n(.*?)(?:```|\Z)", re.S)
_INLINE = re.compile(r"`[^`\n]+`")
_C_SIGNAL = re.compile(r";[ \t]*(?://.*|/\*.*)?$|^[ \t]*#[ \t]*(?:include|define)\b", re.M)
_MAIN = re.compile(r"\bmain\s*\([^)]*\)\s*\{")
_FUNC_DEF = re.compile(r"\)\s*\{")
_REG_STMT = re.compile(r"(?m)^[ \t]*[A-Za-z_]\w*(?:->|\.)\w+(?:\[[^\]]*\])?\s*(?:\|=|&=|\^=|=)(?!=)")
_INCLUDE = re.compile(r"^[ \t]*#[ \t]*include\b")
WRAPPER = "gate_snippet"


@dataclass(frozen=True)
class CodeBlock:
    n: int              # vị trí (1-based) trong mọi khối ``` của câu trả lời
    lang: str
    body: str


@dataclass(frozen=True)
class Program:
    code: str
    blocks: tuple[CodeBlock, ...]
    wrapped: bool
    origin: tuple[tuple[int, int] | None, ...]     # dòng i (1-based) của `code` -> (khối, dòng trong khối)

    def locate(self, line: int | None) -> str:
        if not line or not 0 < line <= len(self.origin) or self.origin[line - 1] is None:
            return f"code line {line}" if line else "code"
        n, ln = self.origin[line - 1]
        return f"code block {n}, line {ln}"


def _is_fragment(body: str) -> bool:
    return not _FUNC_DEF.search(body) and bool(_REG_STMT.search(body))


def extract_c_blocks(answer: str) -> list[CodeBlock]:
    blocks: list[CodeBlock] = []
    for n, m in enumerate(_FENCE.finditer(answer or ""), 1):
        info = m.group(1).strip()
        lang = info.split()[0].lower() if info else ""
        body = m.group(2).strip("\n")
        if not body.strip() or (lang and lang not in C_TAGS) or (not lang and not _C_SIGNAL.search(body)):
            continue
        if any(b.body == body for b in blocks):
            continue
        blocks.append(CodeBlock(n, lang, body))
    if len(blocks) > 1 and any(_MAIN.search(b.body) for b in blocks):
        blocks = [b for b in blocks if not _is_fragment(b.body)]
    return blocks


def extract_c_code(answer: str) -> str:
    return "\n\n".join(b.body for b in extract_c_blocks(answer))


def program(answer: str) -> Program | None:
    blocks = extract_c_blocks(answer)
    if not blocks:
        return None
    lines: list[str] = []
    origin: list[tuple[int, int] | None] = []
    wrapped = not any(_FUNC_DEF.search(b.body) for b in blocks)
    if wrapped:
        includes = [(b.n, i, line) for b in blocks for i, line in enumerate(b.body.split("\n"), 1) if _INCLUDE.match(line)]
        if not any("stm32g4xx" in line for _, _, line in includes):
            lines.append('#include "stm32g4xx.h"')
            origin.append(None)
        for n, i, line in includes:
            lines.append(line.strip())
            origin.append((n, i))
        lines += [f"void {WRAPPER}(void)", "{"]
        origin += [None, None]
    for k, b in enumerate(blocks):
        if k:
            lines.append("")
            origin.append(None)
        for i, line in enumerate(b.body.split("\n"), 1):
            lines.append("" if wrapped and _INCLUDE.match(line) else line)
            origin.append((b.n, i))
    if wrapped:
        lines.append("}")
        origin.append(None)
    return Program("\n".join(lines), tuple(blocks), wrapped, tuple(origin))


def prose(answer: str) -> str:
    """Văn bản G1/G4 kiểm: bỏ CHỈ các khối C mà G2 phân tích; giữ nội dung mã nội tuyến và khối không phải C (```text...); LaTeX đã chuẩn hoá."""
    analysed = {b.body for b in extract_c_blocks(answer)}

    def fence(m):
        body = m.group(2).strip("\n")
        return "\n" if body in analysed else f"\n{body}\n"
    text = _FENCE.sub(fence, answer or "")
    return normalize_text(_INLINE.sub(lambda m: f" {m.group(0)[1:-1]} ", text))


def prior_prose(answer: str) -> str:
    """Câu trả lời của lượt trước dùng làm bằng chứng: chỉ phần văn xuôi (bỏ mọi khối ``` và mã nội tuyến), LaTeX đã chuẩn hoá."""
    return normalize_text(_INLINE.sub(" ", _FENCE.sub("\n", answer or "")))


# ------------------------------------------------------------------------------------------------ LaTeX, số, câu, ngôn ngữ (EN + VI)
_LATEX_SYMBOLS = [(re.compile(r"\\(?:times|cdot)(?![A-Za-z])"), " × "), (re.compile(r"\\approx(?![A-Za-z])"), " ≈ "),
                  (re.compile(r"\\mu(?![A-Za-z])"), "µ"), (re.compile(r"\\Omega(?![A-Za-z])"), "Ω"), (re.compile(r"\\%"), "%"),
                  (re.compile(r"\\(?:leq?|leqslant)(?![A-Za-z])"), " ≤ "), (re.compile(r"\\(?:geq?|geqslant)(?![A-Za-z])"), " ≥ "),
                  (re.compile(r"\\pm(?![A-Za-z])"), " ± "), (re.compile(r"\\(?:Rightarrow|implies|rightarrow|to|longrightarrow)(?![A-Za-z])"), " ⇒ "),
                  (re.compile(r"\\[,;: ]"), " "), (re.compile(r"\\!"), "")]
_LATEX_WRAP = re.compile(r"\\(?:text|textrm|textbf|textit|texttt|mathrm|mathbf|mathit|mathtt|operatorname|mbox|rm|bf)\s*\{([^{}]*)\}")
_SCI = re.compile(r"(?<![\w.,])(?:(\d+(?:[.,]\d+)?)\s*(?:[×x·*]\s*)?)?10\s*\^\s*(?:\(\s*([-+−]?\d+)\s*\)|([-+−]?\d+))")
_LATEX_SCRIPT = re.compile(r"([_^])\{([^{}]*)\}")
_LATEX_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")


def normalize_text(s: str) -> str:
    """LaTeX -> văn bản thường để trích số: $..$, \\text{..}, \\mathrm{..}, \\frac{a}{b} -> (a) / (b), \\, \\  ~ -> khoảng trắng, \\mu -> µ, \\times -> ×."""
    for rx, rep in _LATEX_SYMBOLS:
        s = rx.sub(rep, s)
    prev = None
    while prev != s:
        prev = s
        s = _LATEX_WRAP.sub(lambda m: m.group(1), s)
        s = _LATEX_SCRIPT.sub(lambda m: m.group(1) + m.group(2), s)
        s = _LATEX_FRAC.sub(lambda m: f"({m.group(1)}) / ({m.group(2)})", s)
    s = _SCI.sub(lambda m: f"{m.group(1) or '1'}e{(m.group(2) or m.group(3)).replace('−', '-')}", s)     # a × 10^n, a·10^n, 10^n -> aen (một số)
    s = re.sub(r"\\[A-Za-z]+", " ", s)
    return s.replace("$", " ").replace("{", "").replace("}", "").replace("~", " ").replace("−", "-")


_UNIT_PAT = "|".join(sorted((re.escape(k) for k in _UNITS), key=len, reverse=True))
_GROUP = r"\d{1,3}(?:(?:,\d{3})+|(?:\.\d{3})+|(?:[ \u00a0\u202f\u2009]\d{3})+)(?:[.,]\d+)?"
NUMBER = rf"(?:{_GROUP}|\d+(?:[.,]\d+)?)(?:[eE][+-]?\d+)?"
_QTY = re.compile(rf"(?<![A-Za-z0-9_.,\-−^{{])([-−]?)({NUMBER})\s*({_UNIT_PAT})(?![A-Za-z0-9_])", re.I)
_GLUED = re.compile(rf"\d[.,](\d+)\s*({_UNIT_PAT})(?![A-Za-z0-9_])", re.I)


def number_values(s: str) -> list[float]:
    """Mọi cách đọc hợp lệ của một chuỗi số: '20,000' -> 20000 (EN) hoặc 20.0 (dấu phẩy thập phân VI); '20.000' -> 20.0 hoặc 20000 (VI);
    '170.000.000' / '170,000,000' / '170 000 000' -> 170e6; '4,0' -> 4.0; '1.7e8' -> 1.7e8. Chuỗi không đọc được -> []."""
    s = re.sub(r"[ \u00a0\u202f\u2009]", "", s)
    m = re.fullmatch(r"(.*?)([eE][+-]?\d+)?", s)
    s, exp = m.group(1), int(m.group(2)[1:]) if m.group(2) else 0
    out: set[float] = set()
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):
        out.add(float(s.replace(",", "")))
        if s.count(",") == 1:
            out.add(float(s.replace(",", ".")))
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        out.add(float(s.replace(".", "")))
        if s.count(".") == 1:
            out.add(float(s))
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d+", s):
        out.add(float(s.replace(",", "")))
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d+", s):
        out.add(float(s.replace(".", "").replace(",", ".")))
    elif re.fullmatch(r"\d+,\d+", s):
        out.add(float(s.replace(",", ".")))
    elif re.fullmatch(r"\d+(?:\.\d+)?", s):
        out.add(float(s))
    vals = (float(f"{v!r}e{exp}") for v in out) if exp else iter(out)
    return sorted(v for v in vals if math.isfinite(v))


@dataclass(frozen=True)
class Quantity:
    text: str
    start: int
    end: int
    values: tuple[float, ...]      # các cách đọc của số (đơn vị gốc của chuỗi, vd 20 cho "20 kHz")
    unit: str
    scale: float
    base: str                      # đơn vị SI: V, A, Hz, ohm, F, C
    unknown: bool = False          # số dính vào một số khác không chuẩn hoá được ("1,2,3 V"): không kết luận

    @property
    def si(self) -> tuple[float, ...]:
        return tuple(v * self.scale for v in self.values)


def quantities(text: str) -> list[Quantity]:
    """Đại lượng có đơn vị trong văn bản, chấp nhận nhóm chữ số và dấu phẩy thập phân tiếng Việt."""
    out: list[Quantity] = []
    for m in _QTY.finditer(text):
        scale, base = _UNITS[m.group(3).lower()]
        sign = -1.0 if m.group(1) else 1.0
        vals = tuple(sign * v for v in number_values(m.group(2)))
        out.append(Quantity(" ".join(m.group(0).split()), m.start(), m.end(), vals, m.group(3), scale, base, unknown=not vals))
    taken = [(q.start, q.end) for q in out]
    for m in _GLUED.finditer(text):
        if not any(a < m.end() and m.start() < b for a, b in taken):
            scale, base = _UNITS[m.group(2).lower()]
            out.append(Quantity(m.group(0).strip(), m.start(), m.end(), (), m.group(2), scale, base, unknown=True))
    return sorted(out, key=lambda q: q.start)


_SENT_END = re.compile(r"(?<=[.!?;])\s+|\n+")


def sentences(text: str) -> list[tuple[int, int, str]]:
    """Câu / mệnh đề (tách ở . ! ? ; + khoảng trắng và ở xuống dòng; dấu chấm thập phân không tách)."""
    out, pos = [], 0
    for m in list(_SENT_END.finditer(text)) + [None]:
        end = m.start() if m else len(text)
        seg = text[pos:end]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            out.append((pos + lead, pos + len(seg.rstrip()), seg.strip()))
        pos = m.end() if m else end
    return out


_ADVICE_EN = re.compile(r"^\s*(?:[-*•]|\d+[.)])?\s*(?:please\s+)?(apply|connect|feed|power|drive|tie|wire|hook|raise|increase|boost|set|use|put|"
                        r"overclock|inject|force|supply|add|choose|select|pick|run|keep)\b", re.I)
_ADVICE_MODAL = re.compile(r"\b(you (?:can|could|should|may|must)|it is (?:safe|ok|fine) to|safe to)\b", re.I)
_ADVICE_VI = re.compile(r"(?<!\w)(hãy|nên|có thể|cấp|nối|đưa|dùng|sử dụng|cắm|đấu)(?!\w)", re.I)
_NEGATION = re.compile(
    r"(?<!\w)(not|never|don'?t|doesn'?t|avoid|must not|should not|cannot|can'?t|exceed\w*|above|beyond|damag\w*|destroy\w*|warning|caution|"
    r"unsafe|danger\w*|risk\w*|instead|rather than|absolute maximum|abs\.? max\w*|maximum rating|max|maximum|limit\w*|no more than|up to|"
    r"toleran\w*|không|chẳng|chưa|tránh|vượt|tối đa|cấm|đừng|chớ|nguy hiểm|hỏng|hư hại|cảnh báo|giới hạn|chịu được)(?!\w)", re.I)


def is_advice(sentence: str) -> bool:
    """Câu khuyên/cho phép (mệnh lệnh hoặc 'you can...', tiếng Việt: hãy, nên, có thể, cấp, nối, đưa, dùng...)."""
    return any(_ADVICE_EN.match(part) for part in re.split(r"[,;:]", sentence)) or bool(_ADVICE_MODAL.search(sentence) or _ADVICE_VI.search(sentence))


def has_negation(sentence: str) -> bool:
    """Câu có phủ định / cảnh báo (EN + VI): không dùng để kết luận một lời khuyên nguy hiểm."""
    return bool(_NEGATION.search(sentence))
