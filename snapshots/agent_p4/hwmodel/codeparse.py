"""analyze_c_code: C kiểu CMSIS → `ops` (write / set_bits / clear_bits / toggle_bits / modify / rmw) theo thứ tự thực thi.

Quy trình: kiểm chỉ thị tiền xử lý nguy hiểm → `clang -E` (chỉ với header tự sinh, `-DHWMODEL_ANALYZE`) → `pycparser` → thông dịch trừu tượng
(hằng số, biến cục bộ, hàm gọi nhau, vòng đếm, địa chỉ thanh ghi) → danh sách ops. MÃ KHÔNG BAO GIỜ ĐƯỢC CHẠY hay biên dịch ra mã máy.

Nguyên tắc KHÔNG ĐOÁN: mọi cấu trúc ngoài tập hỗ trợ (HAL/LL, rẽ nhánh phụ thuộc dữ liệu, số học trên giá trị thanh ghi, con trỏ hàm, struct,
goto, truy cập 8/16 bit, đệ quy…) dừng phân tích tại đó với `unsupported_construct` kèm dòng; ops phát sinh trước đó vẫn được trả về nhưng `complete=False`.
Được bỏ qua có ghi chú (`notes`): vòng chờ cờ (`while(!(RCC->CR & RDY));`), vòng trễ không đụng thanh ghi, thân của `while(1)` cuối chương trình,
hàm NVIC/core, inline asm, hàm ngắt (không bao giờ được gọi).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pycparser import c_ast, c_parser

try:                                    # pycparser >= 3.0 (không còn PLY)
    from pycparser.c_parser import ParseError
except ImportError:                     # pycparser 2.x
    from pycparser.plyparser import ParseError

from . import compile_check as cc
from . import header_gen
from .regmap import load_regmap

MAX_CODE_BYTES = cc.MAX_CODE_BYTES
LOOP_CAP = 4096
CALL_DEPTH_CAP = 12
STEP_CAP = 400_000
FULL = 0xFFFF_FFFF
NOOP_CALLS = {"NVIC_EnableIRQ", "NVIC_DisableIRQ", "NVIC_SetPriority", "NVIC_ClearPendingIRQ", "NVIC_SetPendingIRQ", "NVIC_GetPendingIRQ",
              "NVIC_SystemReset", "SystemInit", "SystemCoreClockUpdate", "SysTick_Config", "printf", "puts", "putchar", "fflush"}

_INT_TYPES = {  # tên kiểu → (số bit, có dấu)
    "char": (8, True), "signed char": (8, True), "unsigned char": (8, False), "short": (16, True), "unsigned short": (16, False),
    "int": (32, True), "unsigned int": (32, False), "unsigned": (32, False), "long": (32, True), "unsigned long": (32, False),
    "long long": (64, True), "unsigned long long": (64, False), "_Bool": (1, False), "bool": (1, False),
    "int8_t": (8, True), "uint8_t": (8, False), "int16_t": (16, True), "uint16_t": (16, False), "int32_t": (32, True), "uint32_t": (32, False),
    "int64_t": (64, True), "uint64_t": (64, False), "size_t": (32, False), "uintptr_t": (32, False), "intptr_t": (32, True),
}


class Unsupported(Exception):
    def __init__(self, msg: str, kind: str = "unsupported_construct", construct: str = "", line: int | None = None):
        super().__init__(msg)
        self.msg, self.kind, self.construct, self.line = msg, kind, construct, line


class DataDependent(Unsupported):
    pass


class _Stop(Exception):
    """Gặp vòng lặp vô hạn cuối chương trình: dừng thực thi (có chủ đích)."""


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Unknown:
    def __init__(self, why: str):
        self.why = why

    def __repr__(self):
        return f"<unknown: {self.why}>"


@dataclass(frozen=True)
class Ptr:
    base: int
    group: str | None
    size: int = 4              # kích thước phần tử trỏ tới (byte)


@dataclass(frozen=True)
class Snap:
    """Giá trị của một lần ĐỌC thanh ghi, sau các phép bit với hằng: ((đọc & A) | O) ^ X."""
    addr: int
    version: int
    A: int = FULL
    O: int = 0
    X: int = 0


@dataclass
class Var:
    value: object
    bits: int | None = None
    signed: bool = False
    is_ptr: bool = False


def _wrap(v, bits, signed):
    if not isinstance(v, int) or bits is None:
        return v
    v &= (1 << bits) - 1
    if signed and v >= 1 << (bits - 1):
        v -= 1 << bits
    return v


# ------------------------------------------------------------------------------------------ tiền xử lý
def _balanced(text: str, start: int) -> int:
    """Vị trí ngay sau ')' khớp với '(' tại `start`, bỏ qua chuỗi/ký tự."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            q, i = c, i + 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _strip_gnu(text: str, notes: list) -> str:
    """Bỏ inline asm và __attribute__ (pycparser không hiểu) — ghi chú lại."""
    out, i = [], 0
    pat = re.compile(r"\b(__asm__|__asm|asm|__attribute__|__extension__)\b")
    while True:
        m = pat.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        kw, j = m.group(1), m.end()
        if kw == "__extension__":
            i = j
            continue
        k = re.compile(r"\s*(volatile|__volatile__|goto|inline)?\s*").match(text, j).end()
        if k < len(text) and text[k] == "(":
            end = _balanced(text, k)
            if kw == "__attribute__":
                i = end
                continue
            line = text.count("\n", 0, m.start())          # số dòng trong đầu ra -E: chỉ để ghi chú
            notes.append({"kind": "inline_asm_ignored", "line": None, "msg": "inline assembly ignored (core instructions are not modeled)"})
            out.append("((void)0)")
            i = end
            continue
        out.append(text[m.start():j])
        i = j
    return "".join(out)


def _preprocess(code: str) -> tuple[str | None, dict | None]:
    hdr = cc.header_dir("stm32g474")
    with tempfile.TemporaryDirectory(prefix="hwmodel_pp_") as tmp:
        src = Path(tmp) / "main.c"
        src.write_text(code, encoding="utf-8")
        try:
            r = cc.run_clang(cc.clang_command(src, hdr, ["-E", "-DHWMODEL_ANALYZE", "-fno-color-diagnostics"]), tmp)
        except subprocess.TimeoutExpired:
            return None, {"kind": "preprocess_error", "line": 1, "msg": "preprocessor timed out", "construct": "preprocess"}
    if r.returncode != 0:
        errs, _ = cc.parse_diagnostics(r.stderr)
        e = errs[0] if errs else {"line": 1, "msg": (r.stderr or "preprocessor failed").strip()[:300]}
        m = re.search(r"'([^']+)' file not found", e["msg"])
        if m:
            name = m.group(1)
            why = ("HAL/LL headers are not supported: write bare-metal CMSIS register code" if re.search(r"_(hal|ll)", name)
                   else f"header {name!r} is not available to the analyzer")
            return None, {"kind": "unsupported_construct", "line": e["line"], "msg": why, "construct": "include"}
        return None, {"kind": "preprocess_error", "line": e["line"], "msg": e["msg"], "construct": "preprocess"}
    return r.stdout, None


# ------------------------------------------------------------------------------------------ thông dịch
class _Interp:
    def __init__(self, ast, model, regmap, lines: list[str], notes: list):
        self.ast, self.model, self.rm, self.lines, self.notes = ast, model, regmap, lines, notes
        self.ops: list[dict] = []
        self.versions: dict[int, int] = {}
        self.type_group = {g.type_name: g.name for g in model.groups.values()}
        self.funcs: dict[str, c_ast.FuncDef] = {}
        self.struct_types: set[str] = set()
        self.typedefs: dict[str, list[str]] = {}
        self.enums: dict[str, int] = {}
        self.globals: dict[str, Var] = {}
        self.stack: list[dict] = []                 # khung cục bộ
        self.calls: list[str] = []
        self.steps = 0
        self.poll_skipped = 0
        self.current_line = None

    # ---- tiện ích
    def line_of(self, node) -> int | None:
        c = getattr(node, "coord", None)
        return c.line if c is not None and str(c.file).endswith("main.c") else self.current_line

    def fail(self, node, msg, kind="unsupported_construct", construct="", cls=Unsupported):
        raise cls(msg, kind=kind, construct=construct, line=self.line_of(node))

    def tick(self, node):
        self.steps += 1
        if self.steps > STEP_CAP:
            self.fail(node, "execution budget exceeded (program too long to analyse)", construct="budget")

    def note(self, kind, node, msg):
        self.notes.append({"kind": kind, "line": self.line_of(node), "msg": msg})

    # ---- kiểu
    def base_names(self, names: list[str]) -> list[str]:
        out: list[str] = []
        for n in names:
            out += self.base_names(self.typedefs[n]) if n in self.typedefs else [n]
        return out

    def int_info(self, type_node) -> tuple[int | None, bool, bool]:
        """(bits, signed, is_ptr) của một node kiểu (TypeDecl / PtrDecl / Typename)."""
        t = type_node
        while isinstance(t, (c_ast.Typename, c_ast.Decl)):
            t = t.type
        if isinstance(t, c_ast.PtrDecl):
            return 32, False, True
        if isinstance(t, c_ast.TypeDecl) and isinstance(t.type, c_ast.IdentifierType):
            names = [n for n in self.base_names(t.type.names) if n not in ("volatile", "const", "static", "register", "extern")]
            key = " ".join(names)
            if key in _INT_TYPES:
                return (*_INT_TYPES[key], False)
            if key in ("float", "double", "long double"):
                return None, True, False
        return None, False, False

    def pointee(self, ptr_type) -> tuple[str | None, int]:
        t = ptr_type.type if isinstance(ptr_type, c_ast.PtrDecl) else ptr_type
        while isinstance(t, c_ast.TypeDecl):
            t = t.type
        if isinstance(t, c_ast.IdentifierType):
            names = self.base_names(t.names)
            for n in names:
                if n in self.type_group:
                    return n, 4
            key = " ".join(n for n in names if n not in ("volatile", "const"))
            if key in _INT_TYPES:
                return None, _INT_TYPES[key][0] // 8
        return None, 4

    # ---- khung biến
    def lookup(self, name):
        for fr in reversed(self.stack):
            if name in fr:
                return fr[name]
        return self.globals.get(name)

    # ================================================================= biểu thức
    def ev(self, n):
        self.tick(n)
        m = getattr(self, "e_" + type(n).__name__, None)
        if m is None:
            self.fail(n, f"unsupported expression ({type(n).__name__})", construct=type(n).__name__)
        return m(n)

    def e_Constant(self, n):
        if n.type in ("int", "unsigned int", "long int", "unsigned long int", "long long int", "unsigned long long int"):
            s = re.sub(r"[uUlL]+$", "", n.value)
            return int(s, 8) if re.fullmatch(r"0[0-7]+", s) else int(s, 0)
        if n.type in ("float", "double", "long double"):
            return float(re.sub(r"[fFlL]$", "", n.value))
        if n.type == "char":
            body = n.value[1:-1]
            return ord(body.encode().decode("unicode_escape")[0]) if body else 0
        if n.type == "string":
            return _Unknown("string literal")
        self.fail(n, f"unsupported constant ({n.type})")

    def e_ID(self, n):
        if n.name in self.enums:
            return self.enums[n.name]
        v = self.lookup(n.name)
        if v is not None:
            return v.value
        if n.name in self.funcs:
            return ("func", n.name)
        self.fail(n, f"unknown symbol '{n.name}' (not a macro, variable or function the analyzer knows; check CMSIS names)",
                  kind="unknown_symbol", construct=n.name)

    def e_ExprList(self, n):
        v = None
        for e in n.exprs:
            v = self.ev(e)
        return v

    def e_Cast(self, n):
        v = self.ev(n.expr)
        t = n.to_type.type
        if isinstance(t, c_ast.PtrDecl):
            g, sz = self.pointee(t)
            if isinstance(v, Ptr):
                return Ptr(v.base, g, sz)
            if isinstance(v, int):
                return Ptr(v & FULL, g, sz)
            return v
        bits, signed, _ = self.int_info(n.to_type)
        if isinstance(v, Ptr):
            return v.base if bits in (None, 32) else _wrap(v.base, bits, signed)
        if isinstance(v, float):
            if bits is None:
                return v
            return _wrap(int(v), bits, signed)
        if isinstance(v, Snap) and bits is not None and bits < 32:
            return Snap(v.addr, v.version, v.A & ((1 << bits) - 1), v.O & ((1 << bits) - 1), v.X & ((1 << bits) - 1))
        return _wrap(v, bits, signed) if isinstance(v, int) else v

    def e_TernaryOp(self, n):
        return self.ev(n.iftrue) if self.truthy(self.ev(n.cond), n.cond) else self.ev(n.iffalse)

    def e_UnaryOp(self, n):
        op = n.op
        if op == "sizeof":
            return self.sizeof(n.expr)
        if op in ("p++", "p--", "++", "--"):
            old = self.ev(n.expr)
            delta = 1 if "+" in op else -1
            new = self.binop("+", old, delta, n)
            self.store(n.expr, new, n)
            return old if op.startswith("p") else new
        if op == "&":
            lv = self.lvalue(n.expr)
            if lv[0] != "reg":
                self.fail(n, "address of a local variable is not supported", construct="&")
            return Ptr(lv[1], None, lv[2])
        if op == "*":
            lv = self.lvalue(n)
            return self.read_lv(lv, n)
        v = self.ev(n.expr)
        if isinstance(v, Snap):
            if op == "~":
                return Snap(v.addr, v.version, v.A, v.O, v.X ^ FULL)
            self.fail(n, "register value used in a data-dependent expression", cls=DataDependent, construct="data-dependent")
        if isinstance(v, _Unknown):
            return v
        if op == "-":
            return -v
        if op == "+":
            return v
        if op == "~":
            return ~v
        if op == "!":
            return 0 if self.truthy(v, n) else 1
        self.fail(n, f"unsupported unary operator {op}")

    def e_BinaryOp(self, n):
        op = n.op
        if op in ("&&", "||"):
            left = self.truthy(self.ev(n.left), n.left)
            if op == "&&":
                return 1 if left and self.truthy(self.ev(n.right), n.right) else 0
            return 1 if left or self.truthy(self.ev(n.right), n.right) else 0
        return self.binop(op, self.ev(n.left), self.ev(n.right), n)

    def binop(self, op, a, b, n):
        for v in (a, b):
            if isinstance(v, _Unknown):
                self.fail(n, f"value is not a compile-time constant ({v.why})", cls=DataDependent, construct="data-dependent")
        if isinstance(a, Snap) or isinstance(b, Snap):
            return self.snap_op(op, a, b, n)
        if isinstance(a, Ptr) or isinstance(b, Ptr):
            if op in ("+", "-") and isinstance(a, Ptr) and isinstance(b, int):
                if a.group is not None and b != 0:
                    self.fail(n, "pointer arithmetic on a peripheral struct pointer is not supported", construct="pointer arithmetic")
                return Ptr(a.base + (b if op == "+" else -b) * a.size, a.group, a.size)
            if op == "+" and isinstance(b, Ptr) and isinstance(a, int):
                return Ptr(b.base + a * b.size, b.group, b.size)
            self.fail(n, "unsupported pointer expression", construct="pointer")
        if isinstance(a, tuple) or isinstance(b, tuple) or isinstance(a, list) or isinstance(b, list):
            self.fail(n, "unsupported operand type", construct="operand")
        isf = isinstance(a, float) or isinstance(b, float)
        try:
            if op == "+": return a + b
            if op == "-": return a - b
            if op == "*": return a * b
            if op == "/":
                if b == 0:
                    self.fail(n, "division by zero in a constant expression")
                return a / b if isf else (abs(a) // abs(b)) * (1 if (a >= 0) == (b >= 0) else -1)
            if op == "%":
                if isf or b == 0:
                    self.fail(n, "unsupported modulo")
                return a - b * ((abs(a) // abs(b)) * (1 if (a >= 0) == (b >= 0) else -1))
            if op == "<<": return a << b
            if op == ">>": return a >> b
            if op == "&": return a & b
            if op == "|": return a | b
            if op == "^": return a ^ b
            if op == "==": return int(a == b)
            if op == "!=": return int(a != b)
            if op == "<": return int(a < b)
            if op == ">": return int(a > b)
            if op == "<=": return int(a <= b)
            if op == ">=": return int(a >= b)
        except (TypeError, ValueError):
            self.fail(n, f"unsupported operands for '{op}'")
        self.fail(n, f"unsupported binary operator {op}")

    def snap_op(self, op, a, b, n):
        if op in ("==", "!=", "<", ">", "<=", ">="):
            self.fail(n, "comparison with a register value is data-dependent (depends on the value read at run time)", cls=DataDependent,
                      construct="data-dependent")
        if op not in ("&", "|", "^"):
            self.fail(n, "arithmetic on a register value is data-dependent (the model cannot evaluate it)", construct="arithmetic")
        if isinstance(a, Snap) and isinstance(b, Snap):
            self.fail(n, "expression combines two register reads", construct="arithmetic")
        s, c = (a, b) if isinstance(a, Snap) else (b, a)
        if not isinstance(c, int):
            self.fail(n, "register value combined with a non-constant", construct="arithmetic")
        c &= FULL
        if op == "&":
            return Snap(s.addr, s.version, s.A & c, s.O & c, s.X & c)
        if op == "|":
            return Snap(s.addr, s.version, s.A, s.O | c, s.X & ~c & FULL)
        return Snap(s.addr, s.version, s.A, s.O, s.X ^ c)

    def truthy(self, v, node):
        if isinstance(v, (Snap, _Unknown)):
            self.fail(node, "data-dependent condition (depends on a register value read at run time)", cls=DataDependent, construct="data-dependent")
        if isinstance(v, Ptr):
            return True
        if isinstance(v, (list, tuple)):
            return True
        return bool(v)

    def sizeof(self, e):
        if isinstance(e, c_ast.Typename):
            if isinstance(e.type, c_ast.PtrDecl):
                return 4
            bits, _, _ = self.int_info(e)
            if bits:
                return max(1, bits // 8)
            self.fail(e, "sizeof of this type is not supported", construct="sizeof")
        v = self.ev(e)
        if isinstance(v, (Ptr,)):
            return 4
        return 4 if isinstance(v, (int, float)) else 4

    # ================================================================= lvalue / thanh ghi
    def lvalue(self, n):
        """('var', name) | ('elem', name, idx) | ('reg', addr, size)"""
        if isinstance(n, c_ast.ID):
            if self.lookup(n.name) is None:
                self.e_ID(n)
            return ("var", n.name)
        if isinstance(n, c_ast.StructRef):
            return self.struct_lv(n)
        if isinstance(n, c_ast.ArrayRef):
            if isinstance(n.name, c_ast.StructRef):                       # GPIOA->AFR[1]
                base = self.struct_lv(n.name)
                idx = self.ev(n.subscript)
                if not isinstance(idx, int):
                    self.fail(n, "register array index is not a constant", construct="index")
                return ("reg", base[1] + 4 * idx, base[2])
            base = self.ev(n.name)
            idx = self.ev(n.subscript)
            if isinstance(base, Ptr) and isinstance(idx, int):
                return ("reg", base.base + idx * base.size, base.size)
            if isinstance(base, list) and isinstance(idx, int) and isinstance(n.name, c_ast.ID):
                if not 0 <= idx < len(base):
                    self.fail(n, "array index out of range", construct="index")
                return ("elem", n.name.name, idx)
            self.fail(n, "unsupported array access", construct="array")
        if isinstance(n, c_ast.UnaryOp) and n.op == "*":
            p = self.ev(n.expr)
            if isinstance(p, Ptr):
                return ("reg", p.base, p.size)
            self.fail(n, "dereference of a pointer that is not a constant address", construct="pointer")
        self.fail(n, f"unsupported assignment target ({type(n).__name__})", construct=type(n).__name__)

    def struct_lv(self, n):
        if n.type == "->":
            p = self.ev(n.name)
        else:                                                                 # '.' trên (*ptr)
            if isinstance(n.name, c_ast.UnaryOp) and n.name.op == "*":
                p = self.ev(n.name.expr)
            else:
                self.fail(n, "struct variables are not supported", construct="struct")
        if not isinstance(p, Ptr) or p.group is None:
            self.fail(n, "member access on a pointer that is not a known peripheral base address", construct="struct pointer")
        gname = self.type_group.get(p.group) if p.group in self.type_group else p.group
        g = self.model.groups.get(gname)
        field = n.field.name
        off = g.offset_of(field) if g else None
        if off is None and field == "AFR" and g and g.offset_of("AFRL") is not None:
            off = g.offset_of("AFRL")
        if off is None:
            self.fail(n, f"{p.group} has no register member '{field}'", kind="unknown_symbol", construct=field)
        return ("reg", p.base + off, 4)

    def read_lv(self, lv, node):
        if lv[0] == "var":
            return self.lookup(lv[1]).value
        if lv[0] == "elem":
            return self.lookup(lv[1]).value[lv[2]]
        _, addr, size = lv
        if size != 4:
            self.fail(node, f"{size * 8}-bit access to a register is not modeled (only 32-bit accesses)", construct=f"{size * 8}-bit access")
        return Snap(addr, self.versions.get(addr, 0))

    def e_StructRef(self, n):
        return self.read_lv(self.struct_lv(n), n)

    def e_ArrayRef(self, n):
        return self.read_lv(self.lvalue(n), n)

    # ---- gán
    def e_Assignment(self, n):
        lv = self.lvalue(n.lvalue)
        rhs = self.ev(n.rvalue)
        if n.op == "=":
            new = rhs
        else:
            op = n.op[:-1]
            if lv[0] == "reg":
                return self.reg_compound(lv, op, rhs, n)
            new = self.binop(op, self.read_lv(lv, n), rhs, n)
        self.store_lv(lv, new, n)
        return new

    def store(self, target, value, node):
        self.store_lv(self.lvalue(target), value, node)

    def store_lv(self, lv, value, node):
        if lv[0] == "reg":
            self.reg_write(lv, value, node)
        elif lv[0] == "var":
            v = self.lookup(lv[1])
            v.value = _wrap(value, v.bits, v.signed) if isinstance(value, int) else value
        else:
            arr = self.lookup(lv[1]).value
            arr[lv[2]] = value

    def emit(self, op, addr, node, **kw):
        reg = self.rm.by_address(addr)
        line = self.line_of(node)
        src = (self.lines[line - 1].strip() if line and line <= len(self.lines) else "").rstrip(";").strip()
        rec = {"op": op, **({"reg": reg.rid} if reg else {}), "addr": addr, **kw, "line": line, "src": src[:200]}
        self.ops.append(rec)
        self.versions[addr] = self.versions.get(addr, 0) + 1

    def reg_compound(self, lv, op, rhs, node):
        _, addr, size = lv
        if size != 4:
            self.fail(node, f"{size * 8}-bit access to a register is not modeled (only 32-bit accesses)", construct=f"{size * 8}-bit access")
        if isinstance(rhs, (Snap, _Unknown, Ptr)):
            self.fail(node, "compound assignment with a value that is not a compile-time constant", cls=DataDependent, construct="data-dependent")
        if not isinstance(rhs, int):
            self.fail(node, "register updated with a non-integer constant", construct="operand")
        if op == "|":
            self.emit("set_bits", addr, node, mask=rhs & FULL)
        elif op == "&":
            self.emit("clear_bits", addr, node, mask=~rhs & FULL)
        elif op == "^":
            self.emit("toggle_bits", addr, node, mask=rhs & FULL)
        else:
            self.fail(node, f"arithmetic '{op}=' on a register depends on its current value (not modeled)", construct="arithmetic")
        return Snap(addr, self.versions[addr])

    def reg_write(self, lv, value, node):
        _, addr, size = lv
        if size != 4:
            self.fail(node, f"{size * 8}-bit access to a register is not modeled (only 32-bit accesses)", construct=f"{size * 8}-bit access")
        if isinstance(value, Snap):
            if value.addr != addr:
                self.fail(node, "register written with a value read from another register (data-dependent)", cls=DataDependent, construct="data-dependent")
            if value.version != self.versions.get(addr, 0):
                self.fail(node, "register written with a stale read of itself (the register changed since it was read)", construct="stale snapshot")
            A, O, X = value.A, value.O, value.X
            if X == 0 and A == FULL:
                self.emit("set_bits", addr, node, mask=O)
            elif X == 0 and O == 0:
                self.emit("clear_bits", addr, node, mask=~A & FULL)
            elif X == 0:
                self.emit("modify", addr, node, mask=~(A & ~O) & FULL, value=O)
            elif A == FULL and O == 0:
                self.emit("toggle_bits", addr, node, mask=X)
            else:
                self.emit("rmw", addr, node, **{"and": A, "or": O, "xor": X})
            return
        if isinstance(value, (_Unknown, Ptr)) or not isinstance(value, (int, float)):
            why = value.why if isinstance(value, _Unknown) else "not an integer"
            self.fail(node, f"register written with a value that is not a compile-time constant ({why})", cls=DataDependent, construct="data-dependent")
        self.emit("write", addr, node, value=int(value) & FULL)

    # ---- gọi hàm
    def e_FuncCall(self, n):
        name = n.name.name if isinstance(n.name, c_ast.ID) else None
        if name is None:
            self.fail(n, "call through a function pointer is not supported", construct="function pointer")
        if name not in self.funcs:
            if self.lookup(name) is not None:
                self.fail(n, f"call through function pointer '{name}' is not supported", construct="function pointer")
            if name.startswith("HAL_") or name.startswith("__HAL"):
                self.fail(n, f"HAL function {name}() is not supported: write bare-metal CMSIS register code", construct=name)
            if name.startswith("LL_"):
                self.fail(n, f"LL driver function {name}() is not supported: write bare-metal CMSIS register code", construct=name)
        args = [self.ev(a) for a in (n.args.exprs if n.args else [])]
        if name in self.funcs:
            return self.call(name, args, n)
        if name in NOOP_CALLS:
            self.note("no_op_call", n, f"call to {name}() ignored (core/NVIC/startup function, not modeled)")
            return 0
        self.fail(n, f"call to unknown function {name}() is not supported", construct=name)

    def call(self, name, args, node):
        if name in self.calls:
            self.fail(node, f"recursion ({name}) is not supported", construct="recursion")
        if len(self.calls) >= CALL_DEPTH_CAP:
            self.fail(node, "call depth exceeded", construct="call depth")
        f = self.funcs[name]
        params = list(f.decl.type.args.params) if f.decl.type.args else []
        frame: dict[str, Var] = {}
        params = [p for p in params if isinstance(p, c_ast.Decl) and p.name]
        for p, a in zip(params, args):
            bits, signed, is_ptr = self.int_info(p.type)
            frame[p.name] = Var(_wrap(a, bits, signed) if isinstance(a, int) else a, bits, signed, is_ptr)
        for p in params[len(args):]:
            frame[p.name] = Var(_Unknown("missing argument"))
        self.stack.append(frame)
        self.calls.append(name)
        try:
            self.exec_stmt(f.body)
            return 0
        except _Return as r:
            return r.value
        finally:
            self.stack.pop()
            self.calls.pop()

    # ================================================================= câu lệnh
    def exec_stmt(self, n):
        self.tick(n)
        if n is None or isinstance(n, c_ast.EmptyStatement):
            return
        m = getattr(self, "s_" + type(n).__name__, None)
        if m is None:
            self.fail(n, f"unsupported statement ({type(n).__name__})", construct=type(n).__name__)
        self.current_line = self.line_of(n) or self.current_line
        m(n)

    def s_Compound(self, n):
        for item in n.block_items or []:
            self.exec_stmt(item) if not isinstance(item, c_ast.Decl) else self.s_Decl(item)

    def s_Pragma(self, n):
        pass

    def s_Typedef(self, n):
        self.register_typedef(n)

    def s_Return(self, n):
        raise _Return(self.ev(n.expr) if n.expr is not None else 0)

    def s_Break(self, n):
        raise _Break()

    def s_Continue(self, n):
        raise _Continue()

    def s_Goto(self, n):
        self.fail(n, "goto statement is not supported", construct="goto")

    def s_Label(self, n):
        self.fail(n, "labels/goto are not supported", construct="goto")

    def s_FuncCall(self, n):
        self.ev(n)

    s_Assignment = s_UnaryOp = s_BinaryOp = s_ExprList = s_TernaryOp = s_Cast = s_ID = s_Constant = s_StructRef = s_ArrayRef = \
        lambda self, n: self.ev(n)

    def s_If(self, n):
        if self.truthy(self.ev(n.cond), n.cond):
            self.exec_stmt(n.iftrue)
        elif n.iffalse is not None:
            self.exec_stmt(n.iffalse)

    def s_Switch(self, n):
        sel = self.ev(n.cond)
        if not isinstance(sel, int):
            self.fail(n, "switch on a value that is not a compile-time constant", cls=DataDependent, construct="data-dependent")
        items = n.stmt.block_items if isinstance(n.stmt, c_ast.Compound) else [n.stmt]
        run = False
        try:
            for it in items:
                if isinstance(it, c_ast.Case):
                    if not run and self.ev(it.expr) == sel:
                        run = True
                elif isinstance(it, c_ast.Default):
                    run = run or not any(isinstance(o, c_ast.Case) and self.ev(o.expr) == sel for o in items)
                if run:
                    for st in (it.stmts if isinstance(it, (c_ast.Case, c_ast.Default)) else [it]):
                        self.exec_stmt(st)
        except _Break:
            pass

    # ---- vòng lặp
    def has_effects(self, n) -> bool:
        """Thân vòng có ghi thanh ghi / gọi hàm (ngoài hàm no-op) không?"""
        found = []

        class V(c_ast.NodeVisitor):
            def visit_FuncCall(s, f):
                name = f.name.name if isinstance(f.name, c_ast.ID) else "?"
                if name not in NOOP_CALLS:
                    found.append(f)
                s.generic_visit(f)

            def visit_Assignment(s, a):
                if not isinstance(a.lvalue, c_ast.ID):
                    found.append(a)
                s.generic_visit(a)

            def visit_UnaryOp(s, u):
                if u.op in ("p++", "p--", "++", "--") and not isinstance(u.expr, c_ast.ID):
                    found.append(u)
                s.generic_visit(u)

        if n is not None:
            V().visit(n)
        return bool(found)

    def contains_break(self, n) -> bool:
        class V(c_ast.NodeVisitor):
            hit = False

            def visit_Break(s, _b):
                s.hit = True

            def visit_Return(s, _r):
                s.hit = True

            def visit_While(s, _w): pass
            def visit_For(s, _f): pass
            def visit_DoWhile(s, _d): pass
            def visit_Switch(s, _d): pass

        v = V()
        if n is not None:
            v.visit(n)
        return v.hit

    def run_loop(self, n, cond, body, nxt=None, post=False):
        iters = 0
        first = True
        while True:
            if not (post and first):
                try:
                    c = True if cond is None else self.truthy(self.ev(cond), cond)
                except DataDependent:
                    if self.has_effects(body):
                        self.fail(cond, "loop with side effects whose condition depends on a register value is not supported",
                                  cls=DataDependent, construct="data-dependent")
                    self.poll_skipped += 1
                    self.note("poll_loop_skipped", n, "polling loop on a register flag skipped: the awaited condition is assumed to become true "
                                                      "(RDY flags rise immediately in this model)")
                    return
            else:
                c = True
            first = False
            if not c:
                return
            const_true = cond is None or (isinstance(cond, c_ast.Constant) and self.truthy(self.ev(cond), cond))
            if const_true and not self.contains_break(body):
                self.note("terminal_loop_not_executed", n, "infinite loop reached: analysis stops here; the loop body is not executed")
                raise _Stop()
            try:
                self.exec_stmt(body)
            except _Break:
                return
            except _Continue:
                pass
            if nxt is not None:
                self.ev(nxt)
            iters += 1
            if iters > LOOP_CAP:
                if self.has_effects(body):
                    self.fail(n, f"loop exceeds {LOOP_CAP} iterations and writes registers: not unrolled", construct="loop")
                self.note("delay_loop_skipped", n, f"loop of more than {LOOP_CAP} iterations with no register access skipped (delay loop)")
                return

    def s_While(self, n):
        self.run_loop(n, n.cond, n.stmt)

    def s_DoWhile(self, n):
        self.run_loop(n, n.cond, n.stmt, post=True)

    def s_For(self, n):
        if n.init is not None:
            if isinstance(n.init, c_ast.DeclList):
                for d in n.init.decls:
                    self.s_Decl(d)
            else:
                self.ev(n.init)
        self.run_loop(n, n.cond, n.stmt, n.next)

    # ---- khai báo
    def register_typedef(self, n):
        t = n.type
        if isinstance(t, c_ast.TypeDecl) and isinstance(t.type, c_ast.Enum):
            self.collect_enum(t.type)
            self.typedefs[n.name] = ["int"]
        elif isinstance(t, c_ast.TypeDecl) and isinstance(t.type, c_ast.IdentifierType):
            self.typedefs[n.name] = list(t.type.names)
        elif isinstance(t, c_ast.TypeDecl) and isinstance(t.type, (c_ast.Struct, c_ast.Union)):
            self.struct_types.add(n.name)

    def s_Decl(self, n, glob=False):
        t = n.type
        if isinstance(t, c_ast.FuncDecl) or n.name is None:
            if isinstance(t, c_ast.Enum) or (isinstance(t, c_ast.TypeDecl) and isinstance(t.type, c_ast.Enum)):
                self.collect_enum(t.type if isinstance(t, c_ast.TypeDecl) else t)
            return
        frame = self.globals if glob or not self.stack else self.stack[-1]
        if isinstance(t, c_ast.TypeDecl) and isinstance(t.type, c_ast.Enum):
            self.collect_enum(t.type)
        if isinstance(t, c_ast.TypeDecl) and isinstance(t.type, (c_ast.Struct, c_ast.Union)):
            self.fail(n, "struct/union variables are not supported", construct="struct")
        if isinstance(t, c_ast.TypeDecl) and isinstance(t.type, c_ast.IdentifierType) and any(x in self.struct_types for x in t.type.names):
            self.fail(n, "struct variables are not supported", construct="struct")
        if isinstance(t, c_ast.PtrDecl) and isinstance(t.type, c_ast.FuncDecl):
            self.fail(n, "function pointers are not supported", construct="function pointer")
        if isinstance(t, c_ast.PtrDecl) and isinstance(t.type, c_ast.PtrDecl):
            frame[n.name] = Var(_Unknown("pointer to pointer"), None, False, True)
            return
        if "extern" in (n.storage or []):
            frame[n.name] = Var(_Unknown(f"extern variable '{n.name}' (runtime value, not modeled)"))
            return
        if isinstance(t, c_ast.ArrayDecl):
            frame[n.name] = Var(self.array_init(n, t))
            return
        bits, signed, is_ptr = self.int_info(t)
        if n.init is None:
            val = 0 if glob or "static" in (n.storage or []) else _Unknown(f"uninitialised variable '{n.name}'")
        else:
            val = self.ev(n.init)
            if isinstance(t, c_ast.PtrDecl):
                g, sz = self.pointee(t)
                if isinstance(val, Ptr):
                    val = Ptr(val.base, val.group or g, val.size if val.group else sz)
                elif isinstance(val, int):
                    val = Ptr(val & FULL, g, sz)
            elif isinstance(val, int):
                val = _wrap(val, bits, signed)
            elif isinstance(val, float) and bits:
                val = _wrap(int(val), bits, signed)
        frame[n.name] = Var(val, bits, signed, is_ptr)

    def array_init(self, n, t):
        size = self.ev(t.dim) if t.dim is not None else None
        if n.init is None:
            return [0] * (size or 0)
        if not isinstance(n.init, c_ast.InitList):
            self.fail(n, "unsupported array initialiser", construct="array")
        vals = [self.ev(e) for e in n.init.exprs]
        if size is not None and len(vals) < size:
            vals += [0] * (size - len(vals))
        return vals

    def collect_enum(self, e):
        if not isinstance(e, c_ast.Enum) or e.values is None:
            return
        nxt = 0
        for en in e.values.enumerators:
            if en.value is not None:
                nxt = self.ev(en.value)
            self.enums[en.name] = nxt
            nxt += 1

    # ================================================================= chạy chương trình
    def load_globals(self):
        for ext in self.ast.ext:
            if isinstance(ext, c_ast.FuncDef) and str(getattr(ext.coord, "file", "")).endswith("main.c"):
                self.funcs[ext.decl.name] = ext
        for ext in self.ast.ext:
            if isinstance(ext, c_ast.Typedef):
                self.register_typedef(ext)
            elif isinstance(ext, c_ast.Decl) and not isinstance(ext.type, c_ast.FuncDecl):
                if str(getattr(ext.coord, "file", "")).endswith("main.c") or "extern" in (ext.storage or []):
                    self.s_Decl(ext, glob=True)

    def entry_points(self) -> tuple[list[str], str | None]:
        if "main" in self.funcs:
            return ["main"], None
        plain = [name for name, f in self.funcs.items()
                 if not re.search(r"(_IRQHandler|_Handler|Handler)$", name)
                 and not [p for p in (f.decl.type.args.params if f.decl.type.args else []) if isinstance(p, c_ast.Decl) and p.name]]
        return plain, "no_main"


def _syntax_line(msg: str) -> int | None:
    m = re.search(r"main\.c:(\d+):(\d+)", msg)
    return int(m.group(1)) if m else None


def _syntax_problem(code: str, chip: str, exc: Exception) -> dict:
    """Thông điệp pycparser thường không có dòng: hỏi clang (-fsyntax-only) để có vị trí chính xác.
    Nếu clang chấp nhận mã thì đó là giới hạn của bộ phân tích, không phải lỗi của chương trình."""
    r = cc.compile_check(code, chip)
    if r["status"] == "error" and r["errors"] and r["errors"][0].get("kind") == "compile":
        e = r["errors"][0]
        return {"kind": "syntax_error", "line": e["line"], "msg": e["msg"][:200], "construct": "syntax"}
    return {"kind": "unsupported_construct", "line": _syntax_line(str(exc)), "construct": "syntax",
            "msg": f"the analyzer's C parser does not support this syntax ({str(exc).split(': ', 1)[-1][:120]})"}


def analyze_c_code(code: str, chip: str = "stm32g474") -> dict:
    res: dict = {"ok": False, "chip": chip, "ops": [], "unsupported": [], "notes": [], "complete": False, "stats": {}}

    def finish(interp=None, extra=None):
        if extra:
            res["unsupported"].append(extra)
        res["ok"] = not res["unsupported"]
        res["complete"] = res["ok"]
        res["stats"] = {"ops": len(res["ops"]), "unsupported": len(res["unsupported"]), "notes": len(res["notes"]),
                        "poll_loops_skipped": sum(1 for n in res["notes"] if n["kind"] == "poll_loop_skipped"),
                        "delay_loops_skipped": sum(1 for n in res["notes"] if n["kind"] == "delay_loop_skipped")}
        return res

    if chip != "stm32g474":
        return finish(extra={"kind": "unsupported_chip", "line": None, "msg": f"analyze_c_code supports stm32g474 only (got {chip!r})", "construct": chip})
    if len(code.encode("utf-8", "replace")) > MAX_CODE_BYTES:
        return finish(extra={"kind": "too_large", "line": 1, "msg": f"code exceeds {MAX_CODE_BYTES} bytes", "construct": "size"})
    bad = cc.scan_directives(code)
    if bad:
        return finish(extra={"kind": "forbidden_directive", "line": bad[0]["line"], "msg": bad[0]["msg"], "construct": "preprocessor"})
    if shutil.which("clang") is None:
        return finish(extra={"kind": "no_toolchain", "line": None, "msg": "clang (preprocessor) is not installed", "construct": "clang"})
    text, err = _preprocess(code)
    if err:
        return finish(extra=err)
    text = _strip_gnu(text, res["notes"])
    try:
        ast = c_parser.CParser().parse(text, filename="main.c")
    except Exception as e:                                                       # ParseError hoặc lỗi khác của pycparser với C lạ
        return finish(extra=_syntax_problem(code, chip, e))
    model = _model()
    rm = load_regmap("stm32g474")
    it = _Interp(ast, model, rm, code.split("\n"), res["notes"])
    try:
        it.load_globals()
        entries, why = it.entry_points()
        if why:
            res["notes"].append({"kind": why, "line": None, "msg": "no main(): running the parameterless functions in source order"})
        if not entries:
            return finish(extra={"kind": "no_entry", "line": None, "msg": "the code defines no main() and no parameterless function to run", "construct": "entry"})
        try:
            for name in entries:
                it.call(name, [], it.funcs[name])
        except _Stop:
            pass
    except Unsupported as u:
        res["ops"] = it.ops
        return finish(extra={"kind": u.kind, "line": u.line, "msg": u.msg, "construct": u.construct})
    except (_Return, _Break, _Continue):
        pass
    res["ops"] = it.ops
    return finish(it)


_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        _MODEL = header_gen.build_model("stm32g474")
    return _MODEL
