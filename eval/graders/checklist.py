"""checklist (C5, gate, TẤT ĐỊNH — plan/P5_interfaces.md §3): mọi mục của `expected.checklist` áp trên TOÀN BỘ câu trả lời cuối (kể cả khối code),
không phân biệt hoa/thường, SAU khi `normalize_answer` đưa LaTeX/markdown về văn bản thường (P5, lượt C5 thật đầu tiên; khối code giữ nguyên).
mentions / forbids / one_of_groups còn thử thêm biến thể bỏ gạch nối giữa hai chữ cái ("logic-level" ≡ "logic level"). Kết quả: {"pass": mọi mục đạt, "score": tỷ lệ mục đạt, "reasons": ["item <id>: <lý do>"], "details": {"items": {id: bool}, ...}}.

Mục (khoá được Task kiểm khi nạp, eval/schema.py CHECKLIST_KEYS):
  mentions      {any_of: [regex]}            đạt khi >= 1 regex khớp (muốn loại câu phủ định thì viết regex đòi dạng khẳng định, vd lookbehind `(?<!not )`)
  forbids       {patterns: [regex]}          đạt khi không regex nào khớp
  quantity      {patterns: [regex có (?P<v>số) và tuỳ chọn (?P<u>đơn vị)], unit, min, max, unit_out, match: all|any, required: true}
                giá trị đổi về đơn vị cơ sở (Hz, V, A, bps, s, W...; bảng eval.textnorm.QTY_UNITS); min/max tính theo đơn vị cơ sở, hoặc theo
                `unit_out` nếu có. Đơn vị bắt được mà không đổi được (hoặc khác loại với `unit`) ⇒ bỏ khớp đó. Không có giá trị dùng được ⇒ trượt nếu
                required (mặc định). Số '2,5' là thập phân, '115,200' là phân cách hàng nghìn.
  pll           {hse_hz, sysclk_hz, tol_pct=0.1, source=HSE|HSI16}  SYSCLK = hse_hz / M × N / R trong ±tol_pct %, <= 170 MHz, nguồn PLL = `source`
                (mặc định HSE; HSI16 cho bo không có thạch anh, khi đó hse_hz = 16 MHz là đầu vào PLL; văn xuôi không nêu nguồn thì không xét), trường hợp lệ
                (M 1–16, N 8–127, R ∈ {2,4,6,8} — RM0440 §7.4.4 RCC_PLLCFGR) và giới hạn VCO (vào 2,66–16 MHz, ra 96–344 MHz — DS12288, cũng là
                bảng clock_limits của DB P1). Nguồn cấu hình, theo thứ tự ưu tiên (code là sản phẩm, D25):
                  1. ghi thanh ghi `RCC->PLLCFGR` trong code (`=`, `|=`, `&=`, `^=`, WRITE_REG/SET_BIT/CLEAR_BIT/MODIFY_REG, _VAL2FLD, #define cục bộ),
                     mô phỏng giá trị từ reset 0x00001000 (PLLN = 16 còn lại nếu chỉ `|=`), giải mã PLLSRC[1:0] (11 = HSE), PLLM[7:4] = M−1,
                     PLLN[14:8], PLLR[26:25] (00/01/10/11 = /2 /4 /6 /8). Biểu thức được tính bằng bộ đánh giá an toàn (không dùng simulator, D19);
                  2. dạng trường trong code (HAL `PLL.PLLM = RCC_PLLM_DIV2`, LL `LL_RCC_PLL_ConfigDomain_SYS(...)`, `PLLN = 85`): giá trị CUỐI mỗi tham số;
                  biến cục bộ `uint32_t cfg = …; cfg |= …; RCC->PLLCFGR = cfg;` được theo dõi;
                  3. văn xuôi (`PLLM = 2`, `PLLM=/2`, `PLLN = x85`, `PLLR to 2`, `M = 2` / `/M = 2` khi 'PLL'/'VCO' nằm trên cùng dòng hoặc
                     <= 6 dòng phía trên, bộ ba `PLL M/N/R = 5/60/2`,
                     `PLL (M, N, R) = (5, 60, 2)`, bảng dọc `| PLLM | /5 |` và bảng ngang có cột PLLM/PLLN/PLLR): mỗi tham số phải có ĐÚNG MỘT giá
                     trị (nhiều giá trị khác nhau ⇒ mơ hồ ⇒ trượt). `PLLR = 0/1/3` hiểu là mã trường (/2 /4 /8), `PLLM = 0` là mã của /1;
                     chú thích `(/2)` ngay sau giá trị thắng. Số theo sau là đơn vị tần số (`PLLN = 85 MHz`) không phải hệ số.
                PLLREN không bắt buộc ở đây (functional_sim kiểm đường clock thật), chỉ ghi vào details.
  one_of_groups {groups: [[regex]], min_groups}  >= min_groups nhóm có ít nhất một regex khớp (đưa >= 2 phương án / đánh đổi)
  bullets_min   {count}                      số dòng là bước đánh số (`1.`, `2)`, `### 3.`, `**Step 4:**`) hoặc gạch đầu dòng (`-`, `*`, `+`, `•`)
                                             >= count; dòng trong khối code ``` KHÔNG tính (dấu `*` của chú thích C).
"""
from __future__ import annotations

import ast
import functools
import re

from eval.graders.functional_sim import _FENCE, extract_c_code
from eval.textnorm import qty_unit

SYSCLK_MAX_HZ = 170_000_000
VCO_IN_HZ = (2.66e6, 16e6)
VCO_OUT_HZ = (96e6, 344e6)


def _res(ok: bool, why: str = "", extra=None) -> tuple:
    return ok, why, extra


# ------------------------------------------------------------------ chuẩn hoá câu trả lời (P5, sau lượt C5 thật): LaTeX / markdown → văn bản thường
# Tổng quát, không theo task, áp cho MỌI hệ trước mọi mục; khối code ``` và code inline `…` giữ NGUYÊN (đường ghi thanh ghi của `pll` đọc code).
_LATEX_SYM = {"mu": "µ", "micro": "µ", "Omega": "Ω", "ohm": "Ω", "times": "×", "cdot": "·", "approx": "≈", "simeq": "≈", "sim": "~", "le": "≤", "leq": "≤",
              "leqslant": "≤", "ge": "≥", "geq": "≥", "geqslant": "≥", "lt": "<", "gt": ">", "ll": "≪", "gg": "≫", "ne": "≠", "neq": "≠", "pm": "±",
              "div": "÷", "to": "→", "rightarrow": "→", "longrightarrow": "→", "Rightarrow": "⇒", "Longrightarrow": "⇒", "implies": "⇒",
              "leftarrow": "←", "degree": "°", "circ": "°", "infty": "∞", "percent": "%", "quad": " ", "qquad": " ", "Delta": "Δ", "alpha": "α",
              "tau": "τ", "lambda": "λ", "pi": "π", "sum": "Σ"}
_ARG1 = re.compile(r"\\(?:text|textrm|textbf|textit|texttt|textsf|mathrm|mathbf|mathit|mathsf|mathtt|operatorname|boldsymbol|bm|mbox|hbox|emph|"
                   r"underline|overline|unit|SI|si)\s*\{([^{}]*)\}")
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_SUB = re.compile(r"_\{([^{}]*)\}")
_SUP = re.compile(r"\^\{([^{}]*)\}")
_MATH = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$([^$\n]+?)\$", re.S)
_HTML = {"&nbsp;": " ", "&mu;": "µ", "&micro;": "µ", "&times;": "×", "&le;": "≤", "&ge;": "≥", "&lt;": "<", "&gt;": ">", "&asymp;": "≈",
         "&plusmn;": "±", "&deg;": "°", "&amp;": "&"}
_INLINE_CODE = re.compile(r"`[^`\n]*`")


_SYM_RX = re.compile(r"\\(" + "|".join(sorted(_LATEX_SYM, key=len, reverse=True)) + r")(?![A-Za-z])( ?)")


def _latex(s: str, math: bool) -> str:
    """Bỏ lệnh LaTeX: \\mu → µ, \\times → × (trước, để '\\mu\\text{A}' không dính thành '\\muA'), \\text{X} → X, \\frac{a}{b} → 'a / b',
    X_{ab} → 'X ab', ^{…} → '^…', \\, \\ \\; → khoảng trắng, \\% → %, lệnh lạ → bỏ tên lệnh. Trong đoạn toán ($…$) dấu ngoặc nhọn thừa cũng bị bỏ."""
    s = re.sub(r"\\([%$&#_{}])", lambda m: {"{": "\x01", "}": "\x02"}.get(m.group(1), m.group(1)), s)
    s = _SYM_RX.sub(lambda m: _LATEX_SYM[m.group(1)] + m.group(2), s)
    for _ in range(12):
        new = _SUP.sub(r"^\1", _SUB.sub(r" \1", _SQRT.sub(r"sqrt(\1)", _FRAC.sub(r"\1 / \2", _ARG1.sub(r"\1", s)))))
        if new == s:
            break
        s = new
    s = re.sub(r"\\[,;:> ]", " ", re.sub(r"\\!", "", s))
    s = re.sub(r"\\[A-Za-z]+\s?", "", s)                                      # \\left, \\displaystyle, lệnh lạ
    if math:
        s = s.replace("{", "").replace("}", "")
    return s.replace("\x01", "{").replace("\x02", "}")


def _plain(s: str) -> str:
    for k, v in _HTML.items():
        s = s.replace(k, v)
    s = _MATH.sub(lambda m: _latex(next(g for g in m.groups() if g is not None), True), s)
    s = _latex(s, False)
    s = re.sub(r"\*\*|__", "", s)
    s = re.sub(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])", r"\1", s)        # *nhấn mạnh* (không đụng '* mục' hay '2 * 3')
    return "\n".join(re.sub(r"(?<=\S)[ \t]{2,}", " ", line) for line in s.split("\n"))


def normalize_answer(text: str) -> str:
    """Câu trả lời ở dạng văn bản thường cho các mục checklist: LaTeX ($…$, $$…$$, \\(…\\), \\[…\\], \\text, \\mu, \\times, \\approx, \\frac, chỉ số dưới,
    khoảng trắng \\, \\ ), nhấn mạnh markdown (**, __, *…*), vài thực thể HTML. Khối code ``` và code inline `…` giữ nguyên từng byte."""
    out, pos = [], 0
    for m in _FENCE.finditer(text or ""):
        out.append(_plain_keep_inline(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_plain_keep_inline((text or "")[pos:]))
    return "".join(out)


def _plain_keep_inline(s: str) -> str:
    parts, pos = [], 0
    for m in _INLINE_CODE.finditer(s):
        parts.append(_plain(s[pos:m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(_plain(s[pos:]))
    return "".join(parts)


# ------------------------------------------------------------------ mentions / forbids / one_of_groups
@functools.lru_cache(maxsize=64)
def _dehyphen(text: str) -> str:
    """Biến thể có từ ghép gạch nối thành khoảng trắng ("voltage-level compatible" ≡ "voltage level compatible")."""
    return re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", " ", text)


def _hits(pats, text) -> list[str]:
    """Regex khớp văn bản HOẶC biến thể bỏ gạch nối của nó (mentions: dễ đạt hơn; forbids: chặt hơn — đối xứng)."""
    return [p for p in pats if re.search(p, text, re.I) or re.search(p, _dehyphen(text), re.I)]


def _mentions(it, text):
    return _res(True) if _hits(it["any_of"], text) else _res(False, f"none of {it['any_of']} found ({it['desc']})")


def _forbids(it, text):
    bad = _hits(it["patterns"], text)
    return _res(not bad, f"forbidden pattern(s) {bad} found ({it['desc']})" if bad else "")


def _one_of_groups(it, text):
    hit = [i for i, g in enumerate(it["groups"]) if _hits(g, text)]
    ok = len(hit) >= it["min_groups"]
    return _res(ok, "" if ok else f"only {len(hit)}/{len(it['groups'])} groups matched (groups {hit}), need {it['min_groups']} ({it['desc']})")


# ------------------------------------------------------------------ bullets_min
_STEP = re.compile(r"^\s*(?:#{1,6}\s+)?(?:\*\*|__)?(?:step\s+)?\d{1,2}[.):](?:\*\*|__)?\s+\S", re.I)
_BULLET = re.compile(r"^\s*[-*+•]\s+\S")


def count_steps(text: str) -> int:
    prose = _FENCE.sub("\n", text or "")
    return sum(1 for line in prose.splitlines() if _STEP.match(line) or _BULLET.match(line))


def _bullets_min(it, text):
    n = count_steps(text)
    return _res(n >= it["count"], f"{n} numbered/bulleted steps, need >= {it['count']} ({it['desc']})")


# ------------------------------------------------------------------ quantity
def _number(s: str) -> float:
    s = re.sub(r"[\s\u00a0\u2009\u202f_]", "", s).rstrip(",")              # mọi khoảng trắng (kể cả nbsp, thin space) và "_" là phân cách
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        s = s.replace(",", "")                                    # 115,200 / 1,000.5: phân cách hàng nghìn
    return float(s.replace(",", "."))                             # 2,5 µA: dấu phẩy thập phân


def _quantity(it, text):
    default = qty_unit(it["unit"]) if "unit" in it else None
    scale_out = qty_unit(it["unit_out"])[0] if "unit_out" in it else 1.0
    lo = it["min"] * scale_out if "min" in it else None
    hi = it["max"] * scale_out if "max" in it else None
    vals, base = [], default[1] if default else None
    for p in it["patterns"]:
        for m in re.finditer(p, text, re.I):
            raw, u = m.group("v"), m.groupdict().get("u")
            conv = qty_unit(u) if u else default
            if raw is None or conv is None or (default and conv[1] != default[1]):
                continue
            try:
                vals.append((_number(raw) * conv[0], m.group(0).strip()))
            except ValueError:
                continue
            base = conv[1]
    if not vals:
        ok = not it.get("required", True)
        return _res(ok, "" if ok else f"no usable value matched {it['patterns']} ({it['desc']})", [])
    eps = lambda x: abs(x) * 1e-9 + 1e-15
    inside = [(lo is None or v >= lo - eps(lo)) and (hi is None or v <= hi + eps(hi)) for v, _ in vals]
    ok = all(inside) if it.get("match", "all") == "all" else any(inside)
    bounds = f"[{'-inf' if lo is None else f'{lo:g}'}, {'inf' if hi is None else f'{hi:g}'}] {base}"
    bad = [f"'{s}' = {v:g} {base}" for (v, s), good in zip(vals, inside) if not good]
    why = "" if ok else f"value(s) {', '.join(bad)} outside {bounds} (match={it.get('match', 'all')}; {it['desc']})"
    return _res(ok, why, [v for v, _ in vals])


# ------------------------------------------------------------------ pll: biểu thức C an toàn
def _field_macros() -> dict[str, int]:
    """Macro RCC_PLLCFGR_* như CMSIS stm32g474xx.h (RM0440 §7.4.4); test so với header đóng băng của eval/vendor."""
    out: dict[str, int] = {}
    for name, (pos, width) in {"PLLSRC": (0, 2), "PLLM": (4, 4), "PLLN": (8, 7), "PLLPEN": (16, 1), "PLLP": (17, 1), "PLLQEN": (20, 1),
                               "PLLQ": (21, 2), "PLLREN": (24, 1), "PLLR": (25, 2), "PLLPDIV": (27, 5)}.items():
        msk = ((1 << width) - 1) << pos
        out.update({f"RCC_PLLCFGR_{name}_Pos": pos, f"RCC_PLLCFGR_{name}_Msk": msk, f"RCC_PLLCFGR_{name}": msk})
        if width > 1:
            out.update({f"RCC_PLLCFGR_{name}_{i}": 1 << (pos + i) for i in range(width)})
    out.update({"RCC_PLLCFGR_PLLSRC_HSI_Pos": 1, "RCC_PLLCFGR_PLLSRC_HSI_Msk": 0x2, "RCC_PLLCFGR_PLLSRC_HSI": 0x2,
                "RCC_PLLCFGR_PLLSRC_HSE_Pos": 0, "RCC_PLLCFGR_PLLSRC_HSE_Msk": 0x3, "RCC_PLLCFGR_PLLSRC_HSE": 0x3})
    return out


PLLCFGR_MACROS = _field_macros()
PLLCFGR_RESET = 0x00001000                       # RM0440: PLLN = 16 sau reset (cũng là reset_value của DB P1)

_CAST = re.compile(r"\(\s*(?:const\s+)?(?:volatile\s+)?(?:u?int(?:8|16|32|64)_t|unsigned(?:\s+(?:int|long|short|char))*|signed(?:\s+\w+)?|int|long|short|char|"
                   r"size_t|u8|u16|u32)\s*\)")
_TOKEN = re.compile(r"\s*(?:(?P<num>0[xX][0-9a-fA-F]+|0[bB][01]+|\d+)[uUlL]*|(?P<id>[A-Za-z_]\w*)|(?P<op><<|>>|[-+*/%&|^~()]))")
_BIN = {ast.BitOr: lambda a, b: a | b, ast.BitAnd: lambda a, b: a & b, ast.BitXor: lambda a, b: a ^ b, ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
        ast.LShift: lambda a, b: a << b, ast.RShift: lambda a, b: a >> b}
_UN = {ast.Invert: lambda a: ~a, ast.USub: lambda a: -a, ast.UAdd: lambda a: a}


def _call_args(text: str, open_idx: int) -> tuple[list[str], int]:
    """Tách đối số (ở mức ngoặc 0) của lời gọi có '(' tại open_idx; trả (đối số, vị trí sau ')')."""
    depth, start, args = 0, open_idx + 1, []
    for i in range(open_idx, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                args.append(text[start:i])
                return [a.strip() for a in args], i + 1
        elif c == "," and depth == 1:
            args.append(text[start:i])
            start = i + 1
    raise ValueError("unbalanced parentheses")


def _expand_helpers(expr: str) -> str:
    """_VAL2FLD(F, v) -> (((v) << F_Pos) & F_Msk); READ_REG(x) -> (x); READ_BIT(r, m) -> ((r) & (m))."""
    for _ in range(50):
        m = re.search(r"\b(_VAL2FLD|READ_REG|READ_BIT)\s*\(", expr)
        if not m:
            return expr
        args, end = _call_args(expr, m.end() - 1)
        if m.group(1) == "_VAL2FLD" and len(args) == 2:
            rep = f"((({args[1]}) << {args[0]}_Pos) & {args[0]}_Msk)"
        elif m.group(1) == "READ_REG" and len(args) == 1:
            rep = f"({args[0]})"
        elif m.group(1) == "READ_BIT" and len(args) == 2:
            rep = f"(({args[0]}) & ({args[1]}))"
        else:
            raise ValueError(f"bad {m.group(1)} call")
        expr = expr[:m.start()] + rep + expr[end:]
    raise ValueError("macro expansion too deep")


def _eval_ast(node) -> int:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval_ast(node.left), _eval_ast(node.right)
        if isinstance(node.op, (ast.LShift, ast.RShift)) and not 0 <= b <= 64:
            raise ValueError("shift out of range")
        if isinstance(node.op, (ast.FloorDiv, ast.Mod)) and b == 0:
            raise ValueError("division by zero")
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_eval_ast(node.operand))
    raise ValueError(f"unsupported construct {type(node).__name__}")


def eval_c_expr(expr: str, macros: dict, _depth: int = 0) -> int:
    """Giá trị 32 bit của một biểu thức hằng C (số có hậu tố U/L, | & ^ ~ << >> + - * / %, ép kiểu nguyên, _VAL2FLD/READ_REG/READ_BIT).
    Định danh lấy từ `macros` (int hoặc chuỗi biểu thức, giải đệ quy); định danh lạ ⇒ ValueError. Không dùng eval()."""
    if _depth > 20:
        raise ValueError("macro recursion too deep")
    s = _expand_helpers(_CAST.sub(" ", expr))
    out, pos = [], 0
    while pos < len(s):
        if not s[pos:].strip():
            break
        m = _TOKEN.match(s, pos)
        if not m:
            raise ValueError(f"cannot parse {s[pos:pos + 20]!r}")
        pos = m.end()
        if m.group("num"):
            out.append(str(int(m.group("num"), 0)))
        elif m.group("id"):
            name = m.group("id")
            if name not in macros:
                raise ValueError(f"unknown identifier {name}")
            val = macros[name]
            out.append(str(val if isinstance(val, int) else eval_c_expr(str(val), macros, _depth + 1)))
        else:
            out.append("//" if m.group("op") == "/" else m.group("op"))
    if not out:
        raise ValueError("empty expression")
    try:
        tree = ast.parse(" ".join(out), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"syntax error ({exc.msg})") from None
    return _eval_ast(tree) & 0xFFFFFFFF


_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_DEFINE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+([^\n]+)$", re.M)
_REG = r"RCC\s*->\s*PLLCFGR"
_ASSIGN = re.compile(rf"{_REG}\s*(\|=|&=|\^=|=)(?!=)")
_MACRO = re.compile(rf"\b(WRITE_REG|SET_BIT|CLEAR_BIT|MODIFY_REG)\s*\(\s*{_REG}\s*,")
# biến cục bộ (review C5 G8: `uint32_t cfg = ...; cfg |= ...; RCC->PLLCFGR = cfg;`): khai báo có khởi tạo, rồi gán lại cho chính biến đó
_VAR_DECL = re.compile(r"\b(?:(?:const|volatile|static|register)\s+)*(?:u?int(?:8|16|32|64)_t|unsigned(?:\s+(?:int|long))*|int|long|u32)\s+([A-Za-z_]\w*)\s*=(?!=)\s*([^;{}]+);")
_VAR_SET = re.compile(r"(?<![\w>.])([A-Za-z_]\w*)\s*(\|=|&=|\^=|=)(?!=)\s*([^;{}]+);")


def pllcfgr_from_code(code: str) -> tuple[int | None, str | None]:
    """(giá trị cuối của RCC->PLLCFGR, lỗi) sau mọi lệnh ghi theo thứ tự xuất hiện; (None, None) nếu code không ghi PLLCFGR."""
    code = _COMMENT.sub(" ", code or "")
    local = {n: b.strip() for n, b in _DEFINE.findall(code)}            # macro dạng đối tượng; macro dạng hàm không khớp mẫu
    macros = {**PLLCFGR_MACROS, **local}
    events = sorted([(m.start(), "assign", m) for m in _ASSIGN.finditer(code)] + [(m.start(), "macro", m) for m in _MACRO.finditer(code)],
                    key=lambda e: e[0])
    if not events:
        return None, None
    decls = [(m.start(), "decl", m) for m in _VAR_DECL.finditer(code)]
    names = {m.group(1) for _, _, m in decls}
    spans = [(m.start(), m.end()) for _, _, m in decls]
    sets = [(m.start(), "set", m) for m in _VAR_SET.finditer(code) if m.group(1) in names and not any(a <= m.start() < b for a, b in spans)]
    events = sorted(events + decls + sets, key=lambda e: e[0])
    val = PLLCFGR_RESET
    reg = re.compile(_REG)
    try:
        for _, kind, m in events:
            cur = lambda e: eval_c_expr(reg.sub(str(val), e), macros)
            if kind in ("decl", "set"):
                name = m.group(1)
                try:
                    rhs = cur(m.group(2) if kind == "decl" else m.group(3))
                except ValueError:
                    macros.pop(name, None)                      # biến không tính được: dùng nó cho PLLCFGR sẽ báo "unknown identifier"
                    continue
                op, old = ("=" if kind == "decl" else m.group(2)), macros.get(name, 0)
                old = old if isinstance(old, int) else 0
                macros[name] = rhs if op == "=" else old | rhs if op == "|=" else old & rhs if op == "&=" else old ^ rhs
                continue
            if kind == "assign":
                end = code.find(";", m.end())
                rhs = cur(code[m.end(): end if end >= 0 else len(code)])
                op = m.group(1)
                val = rhs if op == "=" else val | rhs if op == "|=" else val & rhs if op == "&=" else val ^ rhs
            else:
                args, _ = _call_args(code, code.index("(", m.start()))
                name = m.group(1)
                if name == "WRITE_REG":
                    val = cur(args[1])
                elif name == "SET_BIT":
                    val |= cur(args[1])
                elif name == "CLEAR_BIT":
                    val &= ~cur(args[1]) & 0xFFFFFFFF
                elif name == "MODIFY_REG" and len(args) == 3:
                    val = (val & ~cur(args[1]) & 0xFFFFFFFF) | cur(args[2])
                else:
                    raise ValueError(f"bad {name} call")
    except ValueError as exc:
        return None, f"a RCC->PLLCFGR write could not be evaluated ({exc})"
    return val, None


def decode_pllcfgr(v: int) -> dict:
    return {"source": {3: "HSE", 2: "HSI16", 0: "none (PLLSRC = 00)", 1: "reserved (PLLSRC = 01)"}[v & 3], "m": ((v >> 4) & 0xF) + 1,
            "n": (v >> 8) & 0x7F, "r": ((v >> 25) & 3) * 2 + 2, "pllren": bool((v >> 24) & 1), "pllcfgr": f"0x{v:08X}"}


# ------------------------------------------------------------------ pll: dạng trường / văn xuôi
_FREQ_AFTER = r"(?!\s*[kKmMgG]?[hH][zZ]\b)(?![.,]\d)"
_PAREN_DIV = r"(?:\s*\(\s*(?:/|÷|div(?:ided)?(?:\s+by)?)\s*(?P<pd>\d{1,2})\s*\))?"
_SEP_ = r"\s*(?:=|:|\||\bis\b|\bof\b|\bto\b|\bset\s+to\b)?\s*"        # '|': ô bảng markdown dọc ("| PLLM | 5 |")
_NOTE = r"(?:\s*\([^)\n]{0,40}\))?"                                                # chú thích sau tên: "PLLM (input divider) | 5"
_TEXT_RX = {
    "m": [re.compile(rf"\bPLL_?M\b{_NOTE}(?:\s+(?:divider|division|factor|prescaler|value))?{_SEP_}(?:/|÷|(?:LL_)?RCC_PLLM_DIV_?)?\s*(?P<v>\d{{1,2}})(?:[uU][lL]{{0,2}})?\b{_FREQ_AFTER}{_PAREN_DIV}", re.I),
          re.compile(r"\b(?:LL_)?RCC_PLLM_DIV_?(?P<v>\d{1,2})\b")],
    "n": [re.compile(rf"\bPLL_?N\b{_NOTE}(?:\s+(?:multiplier|multiplication|factor|value))?{_SEP_}[x×*]?\s*(?P<v>\d{{1,3}})(?:[uU][lL]{{0,2}})?\b{_FREQ_AFTER}", re.I),
          re.compile(r"\bLL_RCC_PLL_ConfigDomain_SYS\s*\(\s*\w+\s*,\s*\w+\s*,\s*(?P<v>\d{1,3})[uUlL]*\s*,")],
    "r": [re.compile(rf"\bPLL_?R\b{_NOTE}(?:\s+(?:divider|division|factor|prescaler|value))?{_SEP_}(?:/|÷|(?:LL_)?RCC_PLLR_DIV_?)?\s*(?P<v>\d{{1,2}})(?:[uU][lL]{{0,2}})?\b{_FREQ_AFTER}{_PAREN_DIV}", re.I),
          re.compile(r"\b(?:LL_)?RCC_PLLR_DIV_?(?P<v>\d)\b")],
}
_BARE_RX = {"m": re.compile(rf"(?<!\w)M\s*=\s*/?\s*(?P<v>\d{{1,2}})\b{_FREQ_AFTER}"), "n": re.compile(rf"(?<!\w)N\s*=\s*[x×*]?\s*(?P<v>\d{{1,3}})\b{_FREQ_AFTER}"),
            "r": re.compile(rf"(?<!\w)R\s*=\s*/?\s*(?P<v>\d)\b{_FREQ_AFTER}")}
_PLL_LINE = re.compile(r"PLL|VCO", re.I)
PLL_CONTEXT_LINES = 6        # chữ cái trần (M = 4) cần 'PLL'/'VCO' trên cùng dòng hoặc <= 6 dòng phía trên ("**PLL Calculation**:" rồi "- Prescaler M = 4:")
# bộ ba (review C5 G8): "PLL M/N/R = 5/60/2", "PLL (M, N, R) = (5, 60, 2)", "PLLM/PLLN/PLLR = 5/60/2" — chỉ trên dòng có PLL/VCO
_TRIPLE = re.compile(r"(?<!\w)(?:PLL_?)?M\s*([/,])\s*(?:PLL_?)?N\s*\1\s*(?:PLL_?)?R\s*\)?\s*(?:=|:|\bare\b|\bis\b)\s*\(?\s*"
                     r"(?P<m>\d{1,2})\s*[/,]\s*(?P<n>\d{1,3})\s*[/,]\s*(?P<r>\d)\b", re.I)
_HEAD_CELL = re.compile(r"^PLL_?([MNR])\b", re.I)
_CELL_VAL = re.compile(r"^(?:/|÷|x|×|\*)?\s*(\d{1,3})(?:[uU][lL]{0,2})?\b(?!\s*[kKmMgG]?[hH][zZ])")


def _table_values(text: str) -> list[tuple[int, str, int]]:
    """Bảng markdown NGANG có tiêu đề cột PLLM/PLLN/PLLR: [(vị trí dòng dữ liệu, tham số, giá trị)] (bảng dọc do _SEP_ '|' xử lý)."""
    lines, out, pos, offset = text.splitlines(keepends=True), [], [], 0
    for line in lines:
        pos.append(offset)
        offset += len(line)
    cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].lstrip().startswith("|"):
            j += 1
        head = {k: _HEAD_CELL.match(c).group(1).lower() for k, c in enumerate(cells(lines[i])) if _HEAD_CELL.match(c)}
        if len(head) >= 2:
            for r in range(i + 1, j):
                row = cells(lines[r])
                for k, param in head.items():
                    m = _CELL_VAL.match(row[k]) if k < len(row) else None
                    if m:
                        out.append((pos[r] + k, param, _divider(param, int(m.group(1)), None)))
        i = j
    return out
_SRC_RX = re.compile(r"\bPLL_?(?:SRC|source)\s*(?:=|:|\bis\b|\bto\b)?\s*(?:(?:LL_)?RCC_PLLSOURCE_)?(?P<s>HSE|HSI(?:16)?)\b|\b(?:LL_)?RCC_PLLSOURCE_(?P<s2>HSE|HSI)\b", re.I)


def _divider(param: str, v: int, paren) -> int:
    if paren:
        return int(paren)
    if param == "r":
        return {0: 2, 1: 4, 3: 8}.get(v, v)                     # 0/1/3 chỉ có thể là mã trường PLLR (/2 /4 /8)
    if param == "m" and v == 0:
        return 1                                                # mã trường PLLM 0000 = /1
    return v


def text_values(text: str) -> tuple[dict, str | None]:
    """{tham số: [giá trị theo thứ tự xuất hiện]} cho M/N/R (đã đổi về số chia/nhân) + nguồn PLL được nêu (HSE/HSI16) cuối cùng."""
    text = re.sub(r"\*\*|__|`", "", text or "")              # nhấn mạnh markdown: "| **PLLM** | 5 |"
    triples = []
    for m in _TRIPLE.finditer(text):
        start, end = text.rfind("\n", 0, m.start()) + 1, text.find("\n", m.end())
        if _PLL_LINE.search(text[start: end if end >= 0 else len(text)]):
            triples.append((m.start(), m.end(), {"m": int(m.group("m")), "n": int(m.group("n")), "r": int(m.group("r"))}))
    table = _table_values(text)
    found = {k: [] for k in ("m", "n", "r")}
    for k in found:
        spans: list[tuple[int, int, int]] = [(a, b, _divider(k, v[k], None)) for a, b, v in triples]
        spans += [(p, p + 1, v) for p, param, v in table if param == k]
        for rx in _TEXT_RX[k]:
            for m in rx.finditer(text):
                if any(a < m.end() and m.start() < b for a, b, _ in spans):
                    continue                                    # 'PLLM = RCC_PLLM_DIV2' khớp cả hai mẫu: tính một lần
                spans.append((m.start(), m.end(), _divider(k, int(m.group("v")), m.groupdict().get("pd"))))
        offset, lines = 0, text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if any(_PLL_LINE.search(l) for l in lines[max(0, i - PLL_CONTEXT_LINES): i + 1]):
                for m in _BARE_RX[k].finditer(line):
                    a = offset + m.start()
                    if not any(x <= a < y for x, y, _ in spans):
                        spans.append((a, offset + m.end(), _divider(k, int(m.group("v")), None)))
            offset += len(line)
        found[k] = [v for _, _, v in sorted(spans)]
    srcs = [(m.group("s") or m.group("s2")).upper() for m in _SRC_RX.finditer(text)]
    src = ("HSE" if srcs[-1] == "HSE" else "HSI16") if srcs else None
    return found, src


def _prose(answer: str) -> str:
    """Câu trả lời bỏ các khối code C (khối code không phải C vẫn là văn bản)."""
    return _FENCE.sub(lambda m: "\n" if extract_c_code(m.group(0)).strip() else m.group(0), answer or "")


def _check_config(cfg: dict, hse: float, target: float, tol: float, want_src: str = "HSE") -> list[str]:
    m, n, r = cfg["m"], cfg["n"], cfg["r"]
    problems = []
    if cfg.get("source") not in (None, want_src):
        problems.append(f"PLL source is {cfg['source']}, expected {want_src}")
    if not 1 <= m <= 16:
        problems.append(f"PLLM = {m} is outside 1..16")
    if not 8 <= n <= 127:
        problems.append(f"PLLN = {n} is outside 8..127")
    if r not in (2, 4, 6, 8):
        problems.append(f"PLLR = {r} is not one of 2, 4, 6, 8")
    if m <= 0 or r <= 0:
        return problems
    fin, vco = hse / m, hse / m * n
    sysclk = vco / r
    cfg.update(fin_hz=fin, vco_hz=vco, sysclk_hz=round(sysclk, 3))
    if not VCO_IN_HZ[0] <= fin <= VCO_IN_HZ[1]:
        problems.append(f"VCO input {fin / 1e6:.4g} MHz is outside 2.66-16 MHz")
    if not VCO_OUT_HZ[0] <= vco <= VCO_OUT_HZ[1]:
        problems.append(f"VCO output {vco / 1e6:.4g} MHz is outside 96-344 MHz")
    if sysclk > SYSCLK_MAX_HZ * (1 + 1e-9):
        problems.append(f"SYSCLK {sysclk / 1e6:.6g} MHz exceeds the 170 MHz maximum")
    if abs(sysclk - target) / target * 100.0 > tol:
        problems.append(f"SYSCLK = {hse / 1e6:g} MHz / {m} x {n} / {r} = {sysclk / 1e6:.6g} MHz, expected {target / 1e6:g} MHz ±{tol:g}%")
    return problems


def _pll(it, text):
    hse, target, tol = it["hse_hz"], it["sysclk_hz"], float(it.get("tol_pct", 0.1))
    code = extract_c_code(text)
    val, err = pllcfgr_from_code(code if code.strip() else text)
    if val is not None:
        cfg = {"source_of_config": "register", **decode_pllcfgr(val)}
    else:
        code_vals, code_src = text_values(_COMMENT.sub(" ", code)) if code.strip() else ({"m": [], "n": [], "r": []}, None)
        if any(code_vals.values()):
            missing = [k for k, v in code_vals.items() if not v]
            if missing:
                return _res(False, f"incomplete PLL configuration in the code: {', '.join('PLL' + k.upper() for k in missing)} not stated"
                            + (f"; {err}" if err else ""), {"source": "code", **{k: (v[-1] if v else None) for k, v in code_vals.items()}})
            cfg = {"source_of_config": "code", "source": code_src, **{k: v[-1] for k, v in code_vals.items()}}
        else:
            vals, src = text_values(_prose(text))
            if not any(vals.values()):
                return _res(False, err or f"no PLL configuration (PLLM/PLLN/PLLR or a RCC->PLLCFGR write) found ({it['desc']})", {"source": None})
            missing = [k for k, v in vals.items() if not v]
            if missing:
                return _res(False, f"incomplete PLL configuration in the text: {', '.join('PLL' + k.upper() for k in missing)} not stated", {"source": "text"})
            ambiguous = {k: sorted(set(v)) for k, v in vals.items() if len(set(v)) > 1}
            if ambiguous:
                return _res(False, f"ambiguous PLL figures in the text: {', '.join(f'PLL{k.upper()} = {v}' for k, v in ambiguous.items())}", {"source": "text"})
            cfg = {"source_of_config": "text", "source": src, **{k: v[0] for k, v in vals.items()}}
    problems = _check_config(cfg, hse, target, tol, it.get("source", "HSE"))
    out = {"source": cfg.pop("source_of_config"), **{k: v for k, v in cfg.items() if k != "source"}, "pll_source": cfg.get("source")}
    return _res(not problems, "; ".join(problems) + f" ({it['desc']})" if problems else "", out)


_ITEMS = {"mentions": _mentions, "forbids": _forbids, "quantity": _quantity, "pll": _pll, "one_of_groups": _one_of_groups, "bullets_min": _bullets_min}


def grade(task, run, ctx) -> dict:
    items = task.expected.get("checklist") or []
    if not items:
        raise ValueError(f"{task.id}: expected.checklist is required for checklist")
    text = normalize_answer(run.final_answer or "")
    reasons, details = [], {"items": {}, "pll": {}, "quantity": {}}
    for it in items:
        ok, why, extra = _ITEMS[it["type"]](it, text)
        details["items"][it["id"]] = bool(ok)
        if it["type"] in ("pll", "quantity"):
            details[it["type"]][it["id"]] = extra
        if not ok:
            reasons.append(f"item {it['id']}: {why}")
    passed = sum(details["items"].values())
    return {"pass": not reasons, "score": passed / len(items), "reasons": reasons, "details": details}
