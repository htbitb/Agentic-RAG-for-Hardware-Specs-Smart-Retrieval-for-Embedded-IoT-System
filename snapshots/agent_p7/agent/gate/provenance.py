"""G1 Provenance (P4_interfaces §2.3; nâng cấp V1–V4 của agent/verifier.py, file đó giữ nguyên).

Văn bản được kiểm: câu trả lời trừ các khối C mà G2 phân tích (mã nội tuyến và khối ```text... VẪN được kiểm), LaTeX đã chuẩn hoá, số có nhóm chữ số
('20,000', '170.000.000') và dấu phẩy thập phân tiếng Việt ('4,0 V') được đọc theo mọi cách hợp lệ; ô bảng markdown chỉ có số được gán đơn vị của
cột (tiêu đề "Value (V)" hoặc một cột "Unit"/"Đơn vị") khi đơn vị đó rõ ràng, ngược lại không kiểm.
Nguồn hợp lệ của một con số/địa chỉ:
  (a) kết quả tool tra cứu (hw-knowledge, text-manual) — cần trích dẫn [doc p.N] nếu đó là nguồn DUY NHẤT;
  (b) output solver / simulator / board-state — chỉ trường SỐ có cấu trúc, theo đơn vị (khoá *_hz, vdd, cột unit...); mọi chuỗi tự do của Board State
      (evidence, description, notes, rationale...) là chữ của agent, không phải bằng chứng;
  (c) tin nhắn người dùng; câu trả lời đã được chấp nhận ở lượt trước — chỉ đại lượng CÓ đơn vị và giá trị hex trong phần văn xuôi của chúng.
Suy ra (ghi chú "derived"): làm tròn ≤ 0,5 % so với một trường số có cấu trúc của solver/simulator/set_clock_config/Board State cùng đơn vị; hoặc
BIỂU THỨC VIẾT RA ngay trước giá trị trong cùng câu ("170 MHz / 8500 = 20 kHz", "16 MHz / 4 × 85 = 340 MHz", "f = 170e6/((0+1)(8499+1)) = 20 kHz",
"PSC = 0 ... f = 170 MHz / ((PSC+1)(ARR+1)) = ..."): biểu thức được TÍNH bằng bộ phân tích nhỏ an toàn (không eval), kết quả phải khớp ≤ 0,5 %
(hex: lệch < 1) và MỌI toán hạng phải có nguồn (hoặc là kết quả của một bước đã kiểm trước đó); ±1 chỉ khi viết rõ `X+1`/`X-1`; không phân tích
được => không suy ra. Hex: khớp đúng, hoặc trường mã hoá N-1 (PSC/ARR/PRESC/SCLL/SCLH) + 1. Mặt nạ bit liền (0x8000, 0xF0) không phải giá trị cần
nguồn. Địa chỉ (≥ 0x2000_0000) phải có trong tra cứu (a) hoặc lời người dùng; giá trị thanh ghi 32 bit ≥ 0x2000_0000 trong final_registers vẫn là
GIÁ TRỊ. Không phải bằng chứng: tool điều khiển, kết quả lỗi.
"""
from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass

from agent import verifier
from ingestion.unit_normalizer import _UNITS, eval_vdd_expr

from . import codeblocks
from .types import Finding

LOOKUP_TOOLS = frozenset({"search_manual", "naive_search", "get_chunk_context", "list_documents", "query_pin_alternate_function", "find_pins_for_signal",
                          "get_register_bitfields", "search_registers", "get_electrical_specs", "get_clock_limits", "check_logic_level_compatibility",
                          "list_chips"})
BOARD_TOOLS = frozenset({"get_board_state", "set_requirements", "allocate_pin", "release_pin", "set_target", "add_device", "connect", "rollback", "diff",
                         "set_clock_config", "run_drc", "get_power_budget"})
COMPUTED_TOOLS = frozenset({"solve_timer_config", "simulate_register_writes", "analyze_c_code", "compile_check"}) | BOARD_TOOLS
ROUNDING_TOOLS = frozenset({"solve_timer_config", "simulate_register_writes"}) | BOARD_TOOLS     # "solver/simulator/set_clock_config/board result"
AGENT_TEXT_KEYS = frozenset({"decisions", "decision", "rationale", "question", "options", "chosen", "artifacts", "waiver_reason", "evidence_text"})
NOISE_KEYS = frozenset({"page", "page_start", "page_end", "alt_pages", "match_score", "score", "rank", "version", "head", "count", "total", "n_ops", "line",
                        "col", "at_op", "bit_offset", "bit_width", "size", "seq", "next_offset", "stats", "chunk_id", "counter_bits", "duty_resolution_bits",
                        "freq_error_pct", "duty_error_pct", "restored_from"})
ADDRESS_KEYS = frozenset({"address", "addr", "base_address", "address_alias"})
MINUS_ONE_KEYS = frozenset({"psc", "arr", "presc", "scll", "sclh"})            # trường mã hoá N-1: hệ số thật = giá trị + 1
_SUFFIX_UNITS = (("_mhz", "Hz", 1e6), ("_khz", "Hz", 1e3), ("_hz", "Hz", 1.0), ("_mv", "V", 1e-3), ("_v", "V", 1.0), ("_ua", "A", 1e-6),
                 ("_ma", "A", 1e-3), ("_a", "A", 1.0), ("_ohm", "ohm", 1.0), ("_uf", "F", 1e-6), ("_nf", "F", 1e-9), ("_pf", "F", 1e-12))
_VOLT_KEYS = frozenset({"vdd", "io_vdd", "vin_max", "vih_min", "vil_max", "voh_min", "vol_max", "rail", "volts"})
_LIMIT_FIELDS = ("min", "typ", "max", "value")
_HEX = re.compile(r"(?<![\w.])0[xX]([0-9A-Fa-f](?:_?[0-9A-Fa-f])*)[uUlL]*\b")
_BARE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
_PERCENT = re.compile(r"-?\d+(?:[.,]\d+)?\s*%")
_BRACKET = re.compile(r"\[([^\[\]\n]{2,200})\]")
_PAGE_REF = re.compile(r"^\s*(.*?)\s*\bp(?:p|age)?\.?\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*$", re.I)
_SECTION = re.compile(r"§\s*[\w.]+|\b(?:table|figure|fig\.|section|sec\.)\s*[\w.]+", re.I)
_TEXT_REF = re.compile(r"\b((?:RM|DS|AN|ES|UM)\d{3,5})\b[^\n\[\]()]{0,40}?\bp\.\s*(\d+)(?:\s*[-–]\s*(\d+))?")
_OPERATING = re.compile(r"\b(operat\w*|recommended|normal|nominal)\b", re.I)
_ABS_Q = re.compile(r"absolute|maximum rating|abs\.? max|damage", re.I)
_REGISTER = re.compile(r"\b([A-Z][A-Z0-9]{1,7})_([A-Z][A-Z0-9]{1,9})\b")
_UNIT_HEADERS = frozenset({"unit", "units", "đơn vị", "don vi"})
_CELL = re.compile(r"\|([^|\n]*)")
STANDARD_RAILS = (1.8, 2.5, 3.3, 5.0)
ADDRESS_MIN = 0x2000_0000
ROUND_TOL = 0.005
ABSTAIN_WINDOW = 200
MAX_EXPR_TOKENS = 40
MAX_COMBOS = 16
_DIVIDER_LABEL = re.compile(r"^(presc\w*|scldel|sdadel|scll|sclh|arr|psc|[nmrpq]|pll[nmrpq]|brr|ccr\d*|usartdiv|div\w*|prescaler\w*|divider\w*|"
                            r"count\w*|bits?|steps?|ticks?|ws|latency|wait states?|ovr\w*|over8)$", re.I)
_OWN_UNIT = frozenset({"s", "ms", "us", "µs", "μs", "ns", "ps", "%", "bit", "bits", "baud", "bps", "ticks", "lsb", "db", "msps", "ksps", "sps"})
_REL_WORDS = r"i\.e\.|gives?|yields?|becomes?|is|are|equals?|rounded to|là|được|thành|bằng|làm tròn"
_TOKEN = re.compile(
    r"(?P<hex>(?<![\w.])0[xX][0-9A-Fa-f](?:_?[0-9A-Fa-f])*[uUlL]*\b)"
    r"|(?P<rel>=>|->|≈|≃|→|⇒|=|(?<!\w)(?:" + _REL_WORDS + r")(?!\w))"
    + rf"|(?P<num>(?<![A-Za-z0-9_.,\-−^{{])-?{codeblocks.NUMBER}(?:\s*(?:{codeblocks._UNIT_PAT})(?![A-Za-z0-9_]))?)"
    + r"|(?P<op>[+\-×*·/÷])|(?P<x>(?<=[\s\d)])[xX](?=[\s(\d]))|(?P<lp>\()|(?P<rp>\))|(?P<pct>%)|(?P<id>[^\W\d]\w*)|(?P<other>\S)", re.I)
_NUM_PARTS = re.compile(rf"(-?)({codeblocks.NUMBER})(?:\s*({codeblocks._UNIT_PAT}))?", re.I)


@dataclass(frozen=True)
class _E:
    value: float
    cls: str                  # a = tra cứu | b = tool tính toán/board | c = người dùng/câu trả lời trước
    base: str | None          # đơn vị SI (V, A, Hz, ohm, F, C) hoặc None (không đơn vị)
    kind: str                 # num | hex | addr
    textual: bool             # số lấy từ văn bản tự do (chỉ dùng để khớp đúng)
    cite: str | None          # nguồn gần nhất có `doc` (để gợi ý trích dẫn)
    tool: str = "user"        # tool đã trả số này | "user" | "prior"


@dataclass
class _Source:
    doc: str
    p0: int | None
    p1: int | None


def _unit_scale(unit) -> tuple[float, str] | None:
    if not isinstance(unit, str) or unit.strip().lower() not in _UNITS:
        return None
    return _UNITS[unit.strip().lower()]


def _key_unit(key) -> tuple[str, float] | None:
    k = str(key or "").lower()
    if k in _VOLT_KEYS:
        return "V", 1.0
    for suf, base, scale in _SUFFIX_UNITS:
        if k.endswith(suf):
            return base, scale
    return None


def _cite_of(d: dict) -> str | None:
    doc = d.get("doc")
    if not isinstance(doc, str) or not doc:
        return None
    page = d.get("page") or d.get("page_start")
    return f"[{doc} p.{page}]" if page else f"[{doc}]"


class Evidence:
    def __init__(self, user_texts, observations, prior_answers):
        self.entries: list[_E] = []
        self.sources: list[_Source] = []
        self.categories: set[str] = set()
        self.vdds = self._vdd_candidates(user_texts, observations)
        for o in observations:
            tool = o.get("tool") if isinstance(o, dict) else None
            cls = "a" if tool in LOOKUP_TOOLS else "b" if tool in COMPUTED_TOOLS else None
            res = o.get("result") if isinstance(o, dict) else None
            if cls is None or res is None or (isinstance(res, dict) and isinstance(res.get("error"), str)):
                continue
            self._tool, self._strings = tool, tool not in BOARD_TOOLS            # Board State: chỉ trường số có kiểu
            self._walk(res, cls, None, None, None)
        for t in user_texts:
            self._text(codeblocks.normalize_text(t or ""), "user")
        for t in prior_answers:
            self._text(codeblocks.prior_prose(t or ""), "prior")

    # ------------------------------------------------------------------ thu thập
    @staticmethod
    def _vdd_candidates(user_texts, observations) -> list[float]:
        out = [3.3]
        for t in user_texts:
            out += [v for q in codeblocks.quantities(t or "") if q.base == "V" for v in q.si if 0 < v <= 60]

        def walk(x, key=None):
            if isinstance(x, dict):
                for k, v in x.items():
                    walk(v, k)
            elif isinstance(x, list):
                for v in x:
                    walk(v, key)
            elif key == "vdd" and isinstance(x, (int, float)) and not isinstance(x, bool) and 0 < x <= 60:
                out.append(float(x))
        for o in observations:
            if isinstance(o, dict):
                walk(o.get("args"))
                walk(o.get("result"))
        return sorted(set(out))

    def _add(self, value, cls, base=None, kind="num", textual=False, cite=None, tool=None):
        if isinstance(value, (int, float)) and math.isfinite(value):
            self.entries.append(_E(float(value), cls, base, kind, textual, cite, tool or self._tool))

    def _walk(self, x, cls, key, cite, unit):
        if isinstance(x, dict):
            c = _cite_of(x)
            if c:
                cite = c
                self._source(x)
            if isinstance(x.get("category"), str):
                self.categories.add(x["category"])
            row_unit = _unit_scale(x.get("unit")) or unit
            for k, v in x.items():
                if k in NOISE_KEYS or k in AGENT_TEXT_KEYS:
                    continue
                if k in _LIMIT_FIELDS and row_unit and isinstance(v, str) and self._strings:
                    self._limit(v, cls, row_unit, cite)
                self._walk(v, cls, k, cite, row_unit)
        elif isinstance(x, list):
            for v in x:
                self._walk(v, cls, key, cite, unit)
        elif isinstance(x, bool) or x is None:
            return
        elif isinstance(x, (int, float)):
            self._number(float(x), cls, key, cite, unit)
        elif isinstance(x, str) and self._strings:
            self._string(x, cls, key, cite)

    def _number(self, v, cls, key, cite, unit):
        ku = _key_unit(key)
        if key in ADDRESS_KEYS:
            self._add(v, cls, kind="addr", cite=cite)
        elif ku:
            self._add(v * ku[1], cls, base=ku[0], cite=cite)
        elif key in _LIMIT_FIELDS and unit:
            self._add(v * unit[0], cls, base=unit[1], cite=cite)
        else:
            self._add(v, cls, cite=cite)
            if key in MINUS_ONE_KEYS:
                self._add(v + 1, cls, kind="plus1", cite=cite)

    def _limit(self, s, cls, unit, cite):
        """Cột min/typ/max của dòng có cột `unit`: số thường ('170' MHz) hoặc biểu thức VDD ('VDD+4.0') -> đại lượng SI (VDD theo mọi giá trị ứng viên)."""
        if not re.search(r"vdd", s, re.I):
            try:
                self._add(float(s) * unit[0], cls, base=unit[1], cite=cite)
            except ValueError:
                pass
            return
        for vdd in self.vdds:
            val = eval_vdd_expr(s, vdd)
            if val is not None:
                self._add(val * unit[0], cls, base=unit[1], cite=cite)
                self._add(val, cls, cite=cite)

    def _string(self, s, cls, key, cite):
        """Chuỗi trong kết quả tool (không phải Board State): hex ngắn ('0x00000683') là giá trị có cấu trúc; số trong văn bản dài chỉ để khớp đúng."""
        kind = "addr" if key in ADDRESS_KEYS else "hex"
        for m in _HEX.finditer(s):
            self._add(int(m.group(1).replace("_", ""), 16), cls, kind=kind, textual=len(s) > 20, cite=cite)
        for q in codeblocks.quantities(s):
            for v in q.si:
                self._add(v, cls, base=q.base, textual=True, cite=cite)
        for b in _BARE.findall(_HEX.sub(" ", s)):
            self._add(float(b), cls, textual=True, cite=cite)
        for m in _TEXT_REF.finditer(s):                                    # "RM0440 Table 282 p.1261" trong thông điệp tool cũng là nguồn trích dẫn
            p0 = int(m.group(2))
            self.sources.append(_Source(m.group(1), p0, int(m.group(3) or p0)))

    def _text(self, t, origin):
        """Người dùng: đại lượng, hex, số trần KHÔNG thuộc đại lượng/phần trăm ('25 %' không đỡ '25 mA'). Câu trả lời trước: chỉ đại lượng và hex."""
        for m in _HEX.finditer(t):
            self._add(int(m.group(1).replace("_", ""), 16), "c", kind="hex", tool=origin)
        qs = codeblocks.quantities(t)
        for q in qs:
            for v in q.si:
                self._add(v, "c", base=q.base, tool=origin)
        if origin != "user":
            return
        rest = list(t)
        for q in qs:
            rest[q.start:q.end] = " " * (q.end - q.start)
        for b in _BARE.findall(_PERCENT.sub(" ", _HEX.sub(" ", "".join(rest)))):
            self._add(float(b), "c", tool=origin)

    def _source(self, d: dict):
        p0 = d.get("page") or d.get("page_start")
        p1 = d.get("page_end") or p0
        self.sources.append(_Source(str(d["doc"]), int(p0) if isinstance(p0, (int, float)) else None, int(p1) if isinstance(p1, (int, float)) else None))
        for p in d.get("alt_pages") or []:
            if isinstance(p, (int, float)):
                self.sources.append(_Source(str(d["doc"]), int(p), int(p)))


def _exact(x: float, e: float) -> bool:
    return abs(x - e) <= 1e-9 + 1e-6 * abs(e)


def _near(x: float, e: float, tol: float = ROUND_TOL) -> bool:
    return e != 0 and abs(x - e) <= tol * abs(e)


def _fmt(v: float) -> str:
    return f"{v:.6g}"


@dataclass
class _Claim:
    text: str
    start: int
    end: int
    values: tuple[float, ...] = ()           # cách đọc của số (đơn vị gốc)
    scale: float = 1.0
    base: str | None = None
    hex_value: int | None = None
    unknown: bool = False

    @property
    def si(self) -> tuple[float, ...]:
        return tuple(v * self.scale for v in self.values)


@dataclass
class _Support:
    by: str                   # computed | user | lookup | derived
    how: str = ""
    cite: str | None = None


_BY_CLS = {"a": "lookup", "b": "computed", "c": "user"}


def _unit_support(c: _Claim, ev: Evidence) -> _Support | None:
    direct = []
    for e in ev.entries:
        if e.kind == "addr":
            continue
        blind = e.base is None and ((e.cls == "c" and e.tool == "user") or (e.cls == "a" and e.textual))   # số không đơn vị: ô bảng tra cứu, lời người dùng
        if any((e.base == c.base and _exact(si, e.value)) or (blind and (_exact(v, e.value) or _exact(si, e.value))) for v, si in zip(c.values, c.si)):
            direct.append(e)
    for cls in "bca":
        hit = next((e for e in direct if e.cls == cls), None)
        if hit:
            return _Support(_BY_CLS[cls], cite=hit.cite)
    near = next((e for e in ev.entries if e.cls == "b" and e.tool in ROUNDING_TOOLS and e.base == c.base and not e.textual
                 and any(_near(si, e.value) for si in c.si)), None)
    return _Support("derived", f"≈ {_fmt(near.value)} {c.base} ({near.tool}, rounded)") if near else None


def _hex_support(c: _Claim, ev: Evidence) -> _Support | None:
    h = c.hex_value
    if h >= ADDRESS_MIN:
        hit = next((e for e in ev.entries if e.cls in "ac" and e.value == h), None) or \
            next((e for e in ev.entries if e.cls == "b" and e.kind == "hex" and not e.textual and e.value == h), None)
        return _Support(_BY_CLS[hit.cls], cite=hit.cite) if hit else None
    direct = [e for e in ev.entries if e.value == h]
    for cls in "bca":
        hit = next((e for e in direct if e.cls == cls), None)
        if hit:
            return _Support("derived", f"{_fmt(h - 1)} + 1 (N-1 encoded field of {hit.tool})") if hit.kind == "plus1" else _Support(_BY_CLS[cls], cite=hit.cite)
    return None


@dataclass(frozen=True)
class _Tok:
    kind: str                 # hex | rel | num | op | x | lp | rp | pct | id | other
    start: int
    end: int
    text: str
    vals: tuple = ()          # giá trị (SI nếu có đơn vị) — mọi cách đọc


def _tokens(text: str, offset: int) -> list[_Tok]:
    out = []
    for m in _TOKEN.finditer(text):
        kind, vals = m.lastgroup, ()
        if kind == "hex":
            vals = (float(int(m.group(0).rstrip("uUlL"), 16)),)
        elif kind == "num":
            q = _NUM_PARTS.fullmatch(m.group(0))
            scale = _UNITS[q.group(3).lower()][0] if q and q.group(3) else 1.0
            sign = -1.0 if q and q.group(1) else 1.0
            vals = tuple(sign * v * scale for v in codeblocks.number_values(q.group(2))) if q else ()
            kind = kind if vals else "other"
        out.append(_Tok(kind, offset + m.start(), offset + m.end(), m.group(0), vals))
    return out


class _Parser:
    """Bộ phân tích đệ quy cho biểu thức viết ra: số (có đơn vị), hex, biến đã gán trong câu, + - × · * / ÷ x, ngoặc, %, nhân ngầm ")(" và "2(".
    Không eval/exec; phải tiêu thụ hết token, nếu không => ValueError (không đoán)."""

    def __init__(self, toks: list[_Tok], seq: list[int], variables: dict):
        self.toks, self.seq, self.vars, self.i, self.exempt = toks, seq, variables, 0, set()

    def peek(self):
        return self.toks[self.seq[self.i]] if self.i < len(self.seq) else None

    def take(self):
        self.i += 1
        return self.toks[self.seq[self.i - 1]]

    def parse(self):
        node = self.expr()
        if self.i != len(self.seq):
            raise ValueError("trailing tokens")
        return node

    def expr(self):
        node = self.term()
        while self.peek() is not None and self.peek().kind == "op" and self.peek().text in "+-":
            op = self.take().text
            rhs = self.term()
            if rhs[0] == "leaf" and self.toks[rhs[1]].vals == (1.0,):        # X+1 / X-1 viết rõ: hằng 1 không cần nguồn
                self.exempt.add(rhs[1])
            node = (op, node, rhs)
        return node

    def term(self):
        node = self.factor()
        while True:
            p, prev = self.peek(), self.toks[self.seq[self.i - 1]]
            if p is not None and (p.kind == "x" or (p.kind == "op" and p.text in "×*·/÷")):
                op = "/" if self.take().text in "/÷" else "*"
                node = (op, node, self.factor())
            elif p is not None and ((prev.kind == "rp" and p.kind in ("lp", "num", "hex", "id")) or (prev.kind in ("num", "hex") and p.kind == "lp")):
                node = ("*", node, self.factor())
            else:
                return node

    def factor(self):
        p = self.peek()
        if p is not None and p.kind == "op" and p.text in "+-":
            self.take()
            node = self.factor()
            return ("neg", node) if p.text == "-" else node
        node = self.primary()
        if self.peek() is not None and self.peek().kind == "pct":
            self.take()
            node = ("pct", node)
        return node

    def primary(self):
        p = self.peek()
        if p is None:
            raise ValueError("missing operand")
        if p.kind in ("num", "hex"):
            self.take()
            return ("leaf", self.seq[self.i - 1])
        if p.kind == "id" and p.text in self.vars:
            self.take()
            return ("var", self.seq[self.i - 1])
        if p.kind == "lp":
            self.take()
            node = self.expr()
            if self.peek() is None or self.peek().kind != "rp":
                raise ValueError("unbalanced")
            self.take()
            return node
        raise ValueError(f"unexpected {p.text!r}")


def _leaves(node) -> list:
    if node[0] in ("leaf", "var"):
        return [node]
    return [x for child in node[1:] for x in _leaves(child)]


def _evaluate(node, value_of) -> float:
    k = node[0]
    if k in ("leaf", "var"):
        return value_of[node]
    if k == "neg":
        return -_evaluate(node[1], value_of)
    if k == "pct":
        return _evaluate(node[1], value_of) / 100.0
    a, b = _evaluate(node[1], value_of), _evaluate(node[2], value_of)
    if k == "/":
        if b == 0:
            raise ZeroDivisionError
        return a / b
    return a * b if k == "*" else a + b if k == "+" else a - b


class _Sentence:
    """Một câu đã tách token: biến gán trong câu (`PSC = 0`), và kiểm 'giá trị = biểu thức viết ra trước nó' với toán hạng có nguồn (đệ quy sang trái)."""

    def __init__(self, start: int, text: str, resolve):
        self.toks = _tokens(text, start)
        self.resolve = resolve                 # token số -> True/False/None (None: không phải claim và không có trong bằng chứng)
        self.memo: dict[int, bool] = {}
        self.vars: dict[str, int] = {}
        for i in range(len(self.toks) - 2):
            a, r, n = self.toks[i:i + 3]
            nxt = self.toks[i + 3] if i + 3 < len(self.toks) else None
            if a.kind == "id" and r.kind == "rel" and r.text == "=" and n.kind in ("num", "hex") and (nxt is None or nxt.kind not in ("op", "x", "lp", "pct")):
                self.vars.setdefault(a.text, i + 2)

    def index_at(self, pos: int) -> int | None:
        return next((i for i, t in enumerate(self.toks) if t.start == pos and t.kind in ("num", "hex")), None)

    def _lhs(self, r: int) -> list[int] | None:
        k = r - 1
        while k >= 0 and self.toks[k].kind == "other" and self.toks[k].text in ",;:":
            k -= 1
        run = []
        while k >= 0:
            t = self.toks[k]
            if t.kind in ("num", "hex", "op", "x", "lp", "rp", "pct") or (t.kind == "id" and self.vars.get(t.text, k) < k):
                run.append(k)
                k -= 1
            else:
                break
        run.reverse()
        if not run:
            return None
        first = self.toks[run[0]]
        if first.kind == "x" or (first.kind == "op" and first.text not in "+-"):        # tiếp nối: "340 MHz, then / 2 = ..."
            j = k
            while j >= 0 and self.toks[j].kind not in ("num", "hex", "rel"):
                j -= 1
            if j < 0 or self.toks[j].kind == "rel":
                return None
            run = [j] + run
        return run if len(run) <= MAX_EXPR_TOKENS else None

    def supported(self, i: int) -> bool:
        if i not in self.memo:
            self.memo[i] = False                                               # chặn vòng lặp
            res = self.resolve(self.toks[i])
            self.memo[i] = bool(res) or (res is None and self.witness(i, self.toks[i].vals, self.toks[i].kind == "hex") is not None)
        return self.memo[i]

    def witness(self, i: int, targets, is_hex: bool) -> str | None:
        """Giá trị ở token i = biểu thức viết ngay trước quan hệ (=, ≈, ⇒, i.e., gives, là, được...) đứng liền trước nó?"""
        if i == 0 or self.toks[i - 1].kind != "rel" or not targets:
            return None
        run = self._lhs(i - 1)
        if run is None:
            return None
        try:
            parser = _Parser(self.toks, run, self.vars)
            node = parser.parse()
        except (ValueError, RecursionError):
            return None
        leaves = _leaves(node)
        for kind, idx in leaves:
            src = self.vars[self.toks[idx].text] if kind == "var" else idx
            if idx not in parser.exempt and not self.supported(src):
                return None
        cands = [self.toks[self.vars[self.toks[idx].text] if kind == "var" else idx].vals for kind, idx in leaves]
        for combo in itertools.islice(itertools.product(*cands), MAX_COMBOS):
            try:
                x = _evaluate(node, dict(zip(leaves, combo)))
            except (ZeroDivisionError, OverflowError):
                continue
            if any(abs(x - t) < 1 if is_hex else _near(x, t) for t in targets):
                return f"{' '.join(self.toks[j].text for j in run)} = {_fmt(x)}"
        return None


def _table_claims(prose: str) -> list[_Claim]:
    """Ô bảng markdown chỉ chứa một số: gán đơn vị của tiêu đề cột ("Value (V)") hoặc của cột "Unit"/"Đơn vị" cùng hàng, nếu rõ ràng."""
    out: list[_Claim] = []
    lines, pos = [], 0
    for line in prose.split("\n"):
        lines.append((pos, line))
        pos += len(line) + 1
    i = 0
    while i < len(lines):
        j = i
        while j < len(lines) and lines[j][1].strip().startswith("|"):
            j += 1
        block = lines[i:j]
        i = j + 1 if j == i else j
        if len(block) < 3:
            continue
        rows = [[(off + m.start(1), m.group(1)) for m in _CELL.finditer(line)] for off, line in block]
        if not all(re.fullmatch(r"\s*:?-{2,}:?\s*", t) or not t.strip() for _, t in rows[1]):
            continue
        header = [t.strip().lower() for _, t in rows[0]]
        col_unit = {}
        for k, (_, h) in enumerate(rows[0]):
            m = re.search(r"[\(\[]\s*([^\)\]]+?)\s*[\)\]]", h)
            if m and m.group(1).lower() in _UNITS:
                col_unit[k] = m.group(1)
        unit_cols = [k for k, h in enumerate(header) if h in _UNIT_HEADERS]
        for row in rows[2:]:
            label = row[0][1].strip().strip("*").strip() if row else ""
            own_unit = any(t.strip().lower() in _OWN_UNIT or t.strip().lower() in _UNITS for kk, (_, t) in enumerate(row) if kk not in unit_cols)
            for k, (start, cell) in enumerate(row):
                if k in unit_cols:
                    continue
                text = cell.strip().strip("*").strip()
                vals = codeblocks.number_values(text.lstrip("-−"))
                if not vals or not re.fullmatch(rf"[-−]?{codeblocks.NUMBER}", text):
                    continue
                units = {col_unit[k]} if k in col_unit and not own_unit and not _DIVIDER_LABEL.match(label) else set()
                if len(unit_cols) == 1 and unit_cols[0] < len(row) and row[unit_cols[0]][1].strip().lower() in _UNITS:
                    units.add(row[unit_cols[0]][1].strip())
                if len({u.lower() for u in units}) != 1:
                    continue
                unit = units.pop()
                scale, base = _UNITS[unit.lower()]
                sign = -1.0 if text[0] in "-−" else 1.0
                off = start + cell.index(text)
                out.append(_Claim(f"{text} {unit}", off, off + len(text), tuple(sign * v for v in vals), scale, base))
    return out


def _claims(prose: str) -> list[_Claim]:
    out = [_Claim(q.text, q.start, q.end, q.values, q.scale, q.base, unknown=q.unknown) for q in codeblocks.quantities(prose)]
    for m in _HEX.finditer(prose):
        digits = m.group(1).replace("_", "")
        value = int(digits, 16) if 2 <= len(digits) <= 16 else None
        if value is not None and not (value < ADDRESS_MIN and _is_mask(value)):
            out.append(_Claim(m.group(0), m.start(), m.end(), hex_value=value))
    taken = [(c.start, c.end) for c in out]
    out += [c for c in _table_claims(prose) if not any(a < c.end and c.start < b for a, b in taken)]
    return sorted(out, key=lambda c: c.start)


def _is_mask(v: int) -> bool:
    """Dãy bit 1 liền nhau (0x8000, 0x800, 0xF0, 1 << k): mặt nạ trường, không phải giá trị cần nguồn."""
    if v <= 0:
        return False
    v //= v & -v
    return v & (v + 1) == 0


def _key(c: _Claim):
    return ("hex", c.hex_value) if c.hex_value is not None else (c.base, tuple(float(f"{v:.6g}") for v in c.si))


def _vkey(v: float) -> float:
    return float(f"{v:.6g}")


def _excerpt(prose: str, start: int, end: int, pad: int = 40) -> str:
    a, b = max(0, start - pad), min(len(prose), end + pad)
    text = " ".join(prose[a:b].split())
    return ("…" if a else "") + text + ("…" if b < len(prose) else "")


def _clean_doc(s: str) -> str:
    return _SECTION.sub(" ", s).strip(" ,;:\t")


def _citations(prose: str) -> list[tuple[str, str, int | None, int | None]]:
    """[(văn bản, doc, trang đầu, trang cuối)]; nhận [doc p.N], [doc, p. N], [doc §x.y, p.N], [doc p.N–M], [doc page N]; trang None = tài liệu
    không có trang (thanh ghi svd_only)."""
    out = []
    for m in _BRACKET.finditer(prose):
        body = m.group(1)
        if re.search(r"\bp(?:p|age)?\.?\s*\d", body, re.I):
            doc = ""
            for part in re.split(r"[;,]", body):
                pm = _PAGE_REF.match(part)
                if not pm:
                    doc = _clean_doc(part) or doc
                    continue
                doc = _clean_doc(pm.group(1)) or doc
                if doc:
                    p0 = int(pm.group(2))
                    out.append((m.group(0), doc, p0, int(pm.group(3) or p0)))
        elif re.search(r"svd\b", body, re.I):
            out.append((m.group(0), body.strip(), None, None))
    return out


def _norm_doc(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _citation_ok(doc: str, p0: int | None, p1: int | None, sources: list[_Source]) -> bool:
    if p0 is None:
        want = _norm_doc(doc)
        return any(s.p0 is None and want in (_norm_doc(s.doc), _norm_doc(s.doc) + "svd") for s in sources)
    d0 = doc.lower().strip()
    return any(s.p0 is not None and (d0 in s.doc.lower() or s.doc.lower() in d0) and s.p0 <= p1 and p0 <= (s.p1 or s.p0) for s in sources)


def _hint_for_unit(base: str | None) -> str:
    return {"V": "get_electrical_specs (datasheet limits) or the user's message",
            "A": "get_electrical_specs / get_power_budget",
            "C": "get_electrical_specs",
            "Hz": "simulate_register_writes / set_clock_config / solve_timer_config (computed) or get_clock_limits (limits)",
            }.get(base, "search_manual / get_electrical_specs") + "; or write the computation in the sentence (e.g. '170 MHz / 8500 = 20 kHz'); otherwise remove the number"


def _register_hint(text: str) -> str:
    m = _REGISTER.search(text)
    return f"get_register_bitfields(chip, '{m.group(1)}', '{m.group(2)}')" if m else "get_register_bitfields / search_registers"


def _G(code, where, expected, actual, hint, severity="error") -> Finding:
    return Finding(gate="G1", code=code, where=where, expected=expected, actual=actual, hint_source=hint, severity=severity)


def _closest(c: _Claim, ev: Evidence) -> str:
    same = [e for e in ev.entries if e.base == c.base and e.value > 0]
    si = [v for v in c.si if v > 0]
    if not same or not si:
        return ""
    e = min(same, key=lambda e: abs(math.log(e.value / si[0])))
    return f"; closest {c.base} value in the evidence: {_fmt(e.value)} {c.base} ({_BY_CLS[e.cls]})"


def _sources_text(sources: list[_Source]) -> str:
    seen = []
    for s in sources:
        label = s.doc if s.p0 is None else f"{s.doc} p.{s.p0}" + (f"-{s.p1}" if s.p1 and s.p1 != s.p0 else "")
        if label not in seen:
            seen.append(label)
    return ", ".join(seen[:6]) + (" ..." if len(seen) > 6 else "") if seen else "none"


def _sentence_of(spans, pos: int) -> tuple[int, int, str]:
    return next((s for s in spans if s[0] <= pos < s[1]), (pos, pos, ""))


# ------------------------------------------------------------------------------------------------ điểm vào
def check(answer: str, user_texts: list[str], observations: list[dict], prior_answers: list[str] = (), strict_v1: bool = False):
    """-> (trạng thái "pass"|"fail", findings, details)."""
    if strict_v1:
        return _check_v1(answer, user_texts, observations)
    prose = codeblocks.prose(answer)
    details: dict = {"mode": "v3", "claims_checked": 0, "supported_by": {"computed": 0, "user": 0, "lookup": 0, "derived": 0}, "derived": [],
                     "unsupported": [], "citations": {"valid": [], "invalid": []}, "abstained": False}
    claims = _claims(prose)
    head = " ".join(prose.split())[:ABSTAIN_WINDOW].lower()
    if not claims and any(a in head for a in verifier.ABSTAIN):
        details["abstained"] = True
        return "pass", [], details
    ev = Evidence(user_texts, observations, prior_answers)
    spans = codeblocks.sentences(prose)
    ev_values = {_vkey(e.value) for e in ev.entries if e.kind != "addr"}
    status: dict[int, bool] = {}                                                   # vị trí claim -> có nguồn
    established_keys: set = set()
    established_values: set[float] = set()
    sentences: dict[int, _Sentence] = {}

    def resolve(tok: _Tok):
        if tok.start in status:
            return status[tok.start]
        if any(_vkey(v) in ev_values or _vkey(v) in established_values for v in tok.vals):
            return True
        return None

    def sentence_ctx(pos: int) -> _Sentence:
        s0, _, text = _sentence_of(spans, pos)
        if s0 not in sentences:
            sentences[s0] = _Sentence(s0, text, resolve)
        return sentences[s0]
    findings: list[Finding] = []
    lookup_only: list[tuple[str, str | None]] = []
    reported: set = set()
    for c in claims:
        details["claims_checked"] += 1
        where = f'answer: "{c.text}"'
        context = f' (context: "{_excerpt(prose, c.start, c.end)}")'
        if c.unknown:
            if c.text not in reported:
                reported.add(c.text)
                findings.append(_G("G1-V1", where, "a number that can be read unambiguously (e.g. 4.0 V, 4,0 V, 20,000 Hz)",
                                   f"the number before the unit could not be normalised{context}", "rewrite the number without stray separators",
                                   severity="unknown"))
            continue
        sup = _hex_support(c, ev) if c.hex_value is not None else _unit_support(c, ev)
        if sup is None and _key(c) in established_keys:
            sup = _Support("derived", "stated earlier in the answer")
        if sup is None:
            sent = sentence_ctx(c.start)
            idx = sent.index_at(c.start)
            how = sent.witness(idx, [float(c.hex_value)] if c.hex_value is not None else list(c.si), c.hex_value is not None) if idx is not None else None
            if how:
                sup = _Support("derived", f"written out: {how}")
        status[c.start] = sup is not None
        if sup:
            established_keys.add(_key(c))
            established_values.update(_vkey(v) for v in ([float(c.hex_value)] if c.hex_value is not None else c.si))
            details["supported_by"][sup.by] += 1
            if sup.by == "derived":
                details["derived"].append({"claim": c.text, "how": sup.how})
            if sup.by == "lookup":
                lookup_only.append((c.text, sup.cite))
            continue
        details["unsupported"].append(c.text)
        if c.text in reported:
            continue
        reported.add(c.text)
        if c.hex_value is None:
            sentence = _sentence_of(spans, c.start)[2]
            rail = c.base == "V" and any(abs(v - r) < 1e-9 for v in c.si for r in STANDARD_RAILS) and codeblocks.is_advice(sentence)
            findings.append(_G("G1-V1", where,
                               "a value returned by a tool (lookup, solver, simulator, board state) or given by the user, or a computation written out "
                               "in the same sentence (e.g. '170 MHz / 8500 = 20 kHz')",
                               f"{c.text} has no source in this turn's evidence{context}{_closest(c, ev)}"
                               + ("; standard supply rail in a recommendation: warning only" if rail else ""),
                               _hint_for_unit(c.base), severity="warning" if rail else "error"))
        elif c.hex_value >= ADDRESS_MIN:
            findings.append(_G("G1-V2", where, "a register/peripheral address returned by a documentation lookup",
                               f"address {c.text} is not in any lookup result{context}", _register_hint(prose[max(0, c.start - 60): c.end + 60])))
        else:
            findings.append(_G("G1-V2", where,
                               "a register value equal to a simulator/solver/board output (final_registers, effects), a lookup field or the user's "
                               "message (±1 count), or a computation written out in the same sentence",
                               f"{c.text} (= {c.hex_value}) has no source in this turn's evidence{context}",
                               "simulate_register_writes (final_registers) / solve_timer_config / get_register_bitfields"))
    cites = _citations(prose)
    for text, doc, p0, p1 in cites:
        if _citation_ok(doc, p0, p1, ev.sources):
            details["citations"]["valid"].append(text)
            continue
        details["citations"]["invalid"].append(text)
        findings.append(_G("G1-V3", f"answer: citation {text}", "citations [doc p.N] (or [<chip>_SVD] for svd_only registers) returned by a tool in this turn",
                           f"{text} was not returned by any tool; returned sources: {_sources_text(ev.sources)}",
                           "search_manual / get_register_bitfields / get_electrical_specs (cite the doc and page they return)"))
    if lookup_only and not cites:
        refs = list(dict.fromkeys(c for _, c in lookup_only if c))
        findings.append(_G("G1-V3", "answer", "at least one [doc p.N] citation when a value comes only from a documentation lookup",
                           f"no citation; documentation-only values: {', '.join(dict.fromkeys(t for t, _ in lookup_only))}",
                           f"cite the source returned by the lookup: {', '.join(refs[:3])}" if refs else "cite the doc and page returned by the lookup"))
    question = (user_texts[-1] if user_texts else "") or ""
    if _OPERATING.search(question) and not _ABS_Q.search(question) and ev.categories and ev.categories <= {"absolute_max"}:
        findings.append(_G("G1-V4", "answer", "recommended/operating values for a question about operating conditions",
                           "only absolute-maximum facts were retrieved (categories: absolute_max)",
                           "get_electrical_specs(chip, parameter, category='recommended_operating')"))
    order = {"G1-V1": 0, "G1-V2": 1, "G1-V3": 2, "G1-V4": 3}
    findings.sort(key=lambda f: order[f.code])
    return ("fail" if any(f.severity == "error" for f in findings) else "pass"), findings, details


_V1_TEXT = {
    "G1-V1": ("every value with a unit present in a tool observation or the question (v1 rule)", "quote the value from a tool result (search_manual / get_electrical_specs)"),
    "G1-V2": ("every hex value literally present in a tool observation (v1 rule)", "get_register_bitfields / search_registers"),
    "G1-V3": ("at least one [doc p.N] citation returned by a tool (v1 rule)", "cite the doc and page returned by search_manual / get_register_bitfields"),
    "G1-V4": ("operating values for an operating question (v1 rule)", "get_electrical_specs(category='recommended_operating')"),
}


def _check_v1(answer: str, user_texts: list[str], observations: list[dict]):
    """A3 (strict_v1_provenance): đúng verifier v1 (agent/verifier.py::verify), mỗi issue V1..V4 thành Finding G1-V1..G1-V4."""
    res = verifier.verify("\n".join(t or "" for t in user_texts), answer, [o.get("result") if isinstance(o, dict) else None for o in observations])
    findings = []
    for issue in res["issues"]:
        code = "G1-" + issue.split(" ", 1)[0]
        expected, hint = _V1_TEXT.get(code, ("v1 provenance rule", "agent.verifier"))
        findings.append(_G(code, "answer", expected, issue, hint))
    details = {"mode": "v1", "claims_checked": res["checked_claims"], "abstained": res["abstained"], "issues": list(res["issues"])}
    return ("pass" if res["passed"] else "fail"), findings, details
