"""Đối chiếu header CMSIS SINH TỰ ĐỘNG (`agent/hwmodel/header_gen.py`) với header CHÍNH THỨC của ST (D24).

    eval/.venv/bin/python -m eval.tools.check_header_parity                       # ST: corpus/headers (ghim trong manifest); sinh: agent/hwmodel
    eval/.venv/bin/python -m eval.tools.check_header_parity --generated-from vendor --out <thư mục> [--strict] [--no-clang]

Bốn phép so, theo tên ĐẦY ĐỦ của macro (không chuẩn hoá, không bỏ qua hoa/thường):
  (a) macro `*_Pos` / `*_Msk` / tên bit (`TIM_CR1_CEN`, `_0.._n`, macro giá trị) và tên instance (`TIM1`, `TIM1_BASE`) có ở ST mà header sinh THIẾU;
  (b) macro header sinh có mà ST KHÔNG có — kèm phân loại lý do (tên SVD khác tên ST, tên theo thể hiện `I2C3_CR1_PE`, macro lõi Cortex...);
  (c) offset từng thành viên của từng struct `*_TypeDef`, theo TỪNG instance (`TIM1->PSC`), đo bằng clang `__builtin_offsetof` trên CẢ HAI header;
  (d) giá trị của macro trùng tên (`_Pos`, `_Msk`, bit, macro giá trị) và địa chỉ cơ sở của instance, cũng do clang tính.

An toàn: header (kể cả header ST tải về) là DỮ LIỆU KHÔNG TIN CẬY — chỉ đọc/parse và chạy `clang -fsyntax-only -ast-dump`; không biên dịch ra mã, không chạy gì;
`-nostdinc` (chỉ include trong thư mục header + stub tối thiểu của `stdint.h`/`core_cm4.h` do công cụ dựng), môi trường con tối thiểu, có timeout;
trước khi gọi clang quét chỉ thị tiền xử lý (chặn #include đường dẫn tuyệt đối/`..`/dạng macro, #include_next, #import, #embed). Header ST không kèm `core_cm4.h`
(thuộc CMSIS-Core của ARM, không có trong repo ST) nên stub chỉ định nghĩa `__I/__O/__IO/...`: đủ để biên dịch phần struct/macro thiết bị; mọi thứ khác của lõi
Cortex-M (NVIC_*, SCB_*, SysTick_*...) KHÔNG được mô phỏng ở đây.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
MANIFEST_DOC_ID = "STM32G4_CMSIS_Device_Headers"
MAIN_HEADER = "stm32g474xx.h"
PPB_RANGE = (0xE000_0000, 0xE004_0000)      # ARMv7-M PPB nội bộ: NVIC/SCB/SysTick/MPU/FPU... thuộc CMSIS-Core (core_cm4.h), không thuộc header thiết bị của ST;
                                            # PPB ngoài (>= 0xE0040000, vd DBGMCU 0xE0042000) là của nhà sản xuất nên header ST có định nghĩa
CLANG_TIMEOUT_S = 180
CLANG_FLAGS = ["--target=thumbv7em-none-eabi", "-mcpu=cortex-m4", "-ffreestanding", "-nostdinc", "-std=gnu11", "-fsyntax-only", "-w",
               "-fno-color-diagnostics", "-ferror-limit=0"]

INT_KINDS = ("pos", "msk", "field", "field_bit", "value")           # macro số nguyên có thể so giá trị
FIELDLIKE = INT_KINDS                                               # macro "tên-bit" theo nghĩa rộng: tách được <nhóm>_<thanh ghi>_<trường>
KINDS = ("pos", "msk", "field", "field_bit", "value", "instance", "base", "function_like", "other")

STUB_FILES = {
    "stdint.h": ("#ifndef PARITY_STDINT_H\n#define PARITY_STDINT_H\ntypedef signed char int8_t;\ntypedef unsigned char uint8_t;\ntypedef short int16_t;\n"
                 "typedef unsigned short uint16_t;\ntypedef int int32_t;\ntypedef unsigned int uint32_t;\ntypedef long long int64_t;\n"
                 "typedef unsigned long long uint64_t;\n#endif\n"),
    "stddef.h": "#ifndef PARITY_STDDEF_H\n#define PARITY_STDDEF_H\ntypedef unsigned int size_t;\n#define NULL ((void *)0)\n#endif\n",
    "core_cm4.h": ("#ifndef PARITY_CORE_CM4_H\n#define PARITY_CORE_CM4_H\n#include <stdint.h>\n#define __I volatile const\n#define __O volatile\n"
                   "#define __IO volatile\n#define __IM volatile const\n#define __OM volatile\n#define __IOM volatile\n#endif\n"),
}


class UnsafeHeader(RuntimeError):
    """Header chứa chỉ thị tiền xử lý bị cấm."""


class ManifestMismatch(RuntimeError):
    """File header không khớp sha256 ghim trong corpus/manifest.yaml."""


# ------------------------------------------------------------------------------------------------ manifest
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_entry(doc_id: str = MANIFEST_DOC_ID, corpus: Path = CORPUS) -> dict | None:
    import yaml
    entries = yaml.safe_load((Path(corpus) / "manifest.yaml").read_text(encoding="utf-8")) or []
    return next((e for e in entries if e.get("doc_id") == doc_id), None)


def verify_manifest_files(entry: dict, corpus: Path = CORPUS) -> None:
    for f in entry["files"]:
        got = sha256_file(Path(corpus) / f["path"])
        if got != f["sha256"]:
            raise ManifestMismatch(f"{f['path']}: sha256 {got} != manifest {f['sha256']}")


# ------------------------------------------------------------------------------------------------ parse #define
@dataclass
class Define:
    name: str
    params: tuple | None
    body: str
    line: int


_LEXEME = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|/\*.*?\*/|//[^\n]*', re.S)
_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)(\(([^)]*)\))?(.*)$", re.S)
_UNDEF = re.compile(r"^\s*#\s*undef\s+([A-Za-z_]\w*)")


def strip_comments(text: str) -> str:
    """Bỏ chú thích /* */ và // (giữ nguyên xuống dòng để số dòng không đổi); chuỗi/ký tự được giữ nguyên."""
    def repl(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith("/*"):
            return " " + "\n" * s.count("\n")
        return " " if s.startswith("//") else s
    return _LEXEME.sub(repl, text)


def parse_defines(text: str) -> dict[str, Define]:
    """Mọi `#define` (bỏ qua #if/#ifdef: lấy tất cả nhánh), nối dòng `\\`, `#undef` xoá. Định nghĩa sau ghi đè định nghĩa trước."""
    out: dict[str, Define] = {}
    lines = strip_comments(text).split("\n")
    i = 0
    while i < len(lines):
        start, buf = i + 1, lines[i]
        while buf.endswith("\\") and i + 1 < len(lines):
            i += 1
            buf = buf[:-1] + " " + lines[i]
        i += 1
        m = _DEFINE.match(buf)
        if m:
            params = tuple(p.strip() for p in m.group(3).split(",")) if m.group(2) is not None and m.group(3).strip() else (() if m.group(2) is not None else None)
            out[m.group(1)] = Define(m.group(1), params, m.group(4).strip(), start)
            continue
        u = _UNDEF.match(buf)
        if u:
            out.pop(u.group(1), None)
    return out


_INSTANCE = re.compile(r"^\(\(\s*([A-Za-z_]\w*)\s*\*\s*\)\s*(.+?)\s*\)$")
_GUARD = re.compile(r"^_*[A-Za-z0-9_]+_H_*$")
_TOKEN = re.compile(r"\s*(?:(0[xX][0-9a-fA-F]+|\d+)[uUlL]*|([A-Za-z_]\w*)|(<<|>>|[-+*/|&^~()]))")
_CAST_TYPES = {"uint8_t", "uint16_t", "uint32_t", "int8_t", "int16_t", "int32_t", "int", "unsigned", "long", "short", "char", "signed"}
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+$")


def parse_instances(defs: dict[str, Define]) -> dict[str, tuple[str, str]]:
    """{tên instance: (kiểu struct, biểu thức địa chỉ)} từ `#define TIM1 ((TIM_TypeDef *) TIM1_BASE)`."""
    out = {}
    for n, d in defs.items():
        if d.params is None:
            m = _INSTANCE.match(d.body)
            if m:
                out[n] = (m.group(1), m.group(2).strip())
    return out


def _tokens(body: str):
    """Danh sách token (số / định danh / toán tử) hoặc None nếu thân macro có ký tự lạ (chuỗi, dấu phẩy, `?`, `.`...)."""
    pos, out = 0, []
    body = body.strip()
    while pos < len(body):
        m = _TOKEN.match(body, pos)
        if not m:
            return None
        out.append(m.group(0).strip())
        pos = m.end()
    return out


def _int_like(defs: dict[str, Define], kinds_hint: set[str]) -> set[str]:
    """Bao đóng: macro đối tượng chỉ gồm số, toán tử số học/bit và macro số nguyên khác (cast kiểu số nguyên chuẩn được chấp nhận)."""
    cand: dict[str, list[str]] = {}
    for n, d in defs.items():
        if d.params is not None or n in kinds_hint or not d.body:
            continue
        toks = _tokens(d.body)
        if toks:
            cand[n] = [t for t in toks if re.match(r"[A-Za-z_]", t) and t not in _CAST_TYPES]
    ok: set[str] = set()
    changed = True
    while changed:
        changed = False
        for n, deps in cand.items():
            if n not in ok and all(x in ok for x in deps):
                ok.add(n)
                changed = True
    return ok


def macro_kinds(defs: dict[str, Define]) -> dict[str, str]:
    """Phân loại macro: guard | function_like | instance | base | pos | msk | field | field_bit | value | other."""
    inst = set(parse_instances(defs))
    ints = _int_like(defs, inst)
    kinds: dict[str, str] = {}
    for n, d in defs.items():
        if d.params is not None:
            kinds[n] = "function_like"
        elif not d.body and _GUARD.match(n):
            kinds[n] = "guard"
        elif n in inst:
            kinds[n] = "instance"
        elif n.endswith("_BASE"):
            kinds[n] = "base"
        elif n.endswith("_Pos") and n in ints:
            kinds[n] = "pos"
        elif n.endswith("_Msk") and n in ints:
            kinds[n] = "msk"
        elif n in ints:
            kinds[n] = "value"
        else:
            kinds[n] = "other"
    names = set(kinds)
    for n, k in list(kinds.items()):
        if k == "value":
            if n + "_Pos" in names and n + "_Msk" in names:
                kinds[n] = "field"
            else:
                m = re.match(r"^(.+)_(\d+)$", n)
                if m and m.group(1) + "_Pos" in names and m.group(1) + "_Msk" in names:
                    kinds[n] = "field_bit"
    return kinds


# ------------------------------------------------------------------------------------------------ đánh giá số nguyên bằng Python (an toàn, chỉ để phân loại)
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.LShift, ast.RShift, ast.BitOr, ast.BitAnd,
            ast.BitXor, ast.Invert, ast.USub, ast.UAdd, ast.FloorDiv)


def eval_int_expr(expr: str, defs: dict[str, Define], _seen: tuple = (), _depth: int = 0) -> int | None:
    """Giá trị nguyên của một biểu thức macro, hoặc None nếu không phải biểu thức số nguyên thuần (hàm, con trỏ, chuỗi, vòng...)."""
    if _depth > 40:
        return None
    toks = _tokens(expr)
    if not toks:
        return None
    parts, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t == "(" and i + 2 < len(toks) and toks[i + 1] in _CAST_TYPES and toks[i + 2] == ")":      # (uint32_t) — bỏ cast
            i += 3
            continue
        if re.match(r"[A-Za-z_]", t):
            if t in _seen or t not in defs or defs[t].params is not None:
                return None
            v = eval_int_expr(defs[t].body, defs, _seen + (t,), _depth + 1)
            if v is None:
                return None
            parts.append(f"({v})")
        elif re.match(r"\d|0[xX]", t):
            parts.append(str(int(re.match(r"0[xX][0-9a-fA-F]+|\d+", t).group(0), 0)))
        else:
            parts.append(t.replace("/", "//"))
        i += 1
    try:
        tree = ast.parse(" ".join(parts), mode="eval")
        if not all(isinstance(n, _ALLOWED) for n in ast.walk(tree)):
            return None
        return int(eval(compile(tree, "<macro>", "eval"), {"__builtins__": {}}, {})) & 0xFFFF_FFFF_FFFF_FFFF      # noqa: S307 — chỉ các nút số học đã lọc
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None


def eval_int_macro(name: str, defs: dict[str, Define]) -> int | None:
    d = defs.get(name)
    if d is None or d.params is not None:
        return None
    return eval_int_expr(d.body, defs, (name,))


# ------------------------------------------------------------------------------------------------ (a)(b) so tên macro
def _tok0(name: str) -> str | None:
    return name.split("_")[0] if _NAME.match(name) else None


def _tok01(name: str) -> str | None:
    return "_".join(name.split("_")[:2]) if _NAME.match(name) else None


def _group_of_type(type_name: str) -> str:
    return re.sub(r"_TypeDef$|_Type$", "", type_name)


def _core_instances(inst: dict[str, tuple[str, str]], defs: dict[str, Define]) -> tuple[set[str], set[str]]:
    """Instance nằm trong PPB nội bộ (0xE0000000-0xE003FFFF) và tiền tố nhóm của chúng (từ tên kiểu: STK_TypeDef -> STK)."""
    names, groups = set(), set()
    for n, (t, base) in inst.items():
        a = eval_int_expr(base, defs)
        if a is not None and PPB_RANGE[0] <= a < PPB_RANGE[1]:
            names.add(n)
            groups.add(_group_of_type(t))
            groups.add(n)
    return names, groups


def compare_macros(st: dict[str, Define], gen: dict[str, Define]) -> dict:
    kst, kgen = macro_kinds(st), macro_kinds(gen)
    names_st = {n for n, k in kst.items() if k != "guard"}
    names_gen = {n for n, k in kgen.items() if k != "guard"}
    common, miss, extra = names_st & names_gen, names_st - names_gen, names_gen - names_st

    def prefixes(kinds: dict[str, str]):
        p0, p01 = set(), set()
        for n, k in kinds.items():
            if k in FIELDLIKE:
                if _tok0(n):
                    p0.add(_tok0(n))
                    p01.add(_tok01(n))
        return p0, p01

    st0, st01 = prefixes(kst)
    gen0, gen01 = prefixes(kgen)
    inst_st, inst_gen = parse_instances(st), parse_instances(gen)
    core_names, core_groups = _core_instances(inst_gen, gen)
    st_inst_group = {n: _group_of_type(t) for n, (t, _) in inst_st.items()}

    def inst_group(t0: str) -> str | None:
        """Nhóm macro của một tên thể hiện: theo ST nếu ST có thể hiện đó, không thì theo header sinh (None nếu không phải thể hiện)."""
        if t0 in inst_st:
            return _group_of_type(inst_st[t0][0])
        return _group_of_type(inst_gen[t0][0]) if t0 in inst_gen else None

    def cat_missing(n: str) -> str:
        k = kst[n]
        if k in FIELDLIKE and _tok0(n):
            if _tok0(n) not in gen0:
                return "group_absent"
            return "register_absent" if _tok01(n) not in gen01 else "field_absent"
        return k if k in ("instance", "base", "function_like") else "other"

    def cat_extra(n: str) -> str:
        k = kgen[n]
        if k == "instance" and n in core_names or k == "base" and n[:-5] in core_names:
            return "core_peripheral"
        if k in FIELDLIKE and _tok0(n):
            t0 = _tok0(n)
            if t0 in core_groups:
                return "core_peripheral"
            if t0 not in st0 and inst_group(t0) not in (None, t0):
                return "per_instance"
            if t0 not in st0:
                return "group_not_in_st"
            return "register_not_in_st" if _tok01(n) not in st01 else "field_not_in_st"
        return k if k in ("instance", "base", "function_like") else "other"

    missing, extras = defaultdict(list), defaultdict(list)
    for n in sorted(miss):
        missing[cat_missing(n)].append(n)
    for n in sorted(extra):
        extras[cat_extra(n)].append(n)

    st_by_reg = defaultdict(list)
    for n in names_st:
        if kst[n] in FIELDLIKE and _tok01(n):
            st_by_reg[_tok01(n)].append(n)
    detail = {}
    for n in extras.get("field_not_in_st", []):
        pool = st_by_reg.get(_tok01(n), [])
        close = difflib.get_close_matches(n, pool, n=1, cutoff=0.6) if len(pool) <= 600 else []
        detail[n] = {"category": "field_not_in_st", "closest_st": close[0] if close else None}
    for n in extras.get("per_instance", []):
        t0 = _tok0(n)
        grp = st_inst_group.get(t0)
        alt = f"{grp}{n[len(t0):]}" if grp else None
        detail[n] = {"category": "per_instance", "st_group_name": alt if alt in names_st else None}

    by_kind = {}
    for k in KINDS:
        s_ = {n for n in names_st if kst[n] == k}
        g_ = {n for n in names_gen if kgen[n] == k}
        c_ = {n for n in s_ if n in names_gen and kgen[n] == k}
        by_kind[k] = {"st": len(s_), "generated": len(g_), "common": len(c_), "missing": len(s_) - len(c_), "extra": len(g_) - len(c_),
                      "coverage": (len(c_) / len(s_)) if s_ else None}
    return {"counts": {"st": len(names_st), "generated": len(names_gen), "common": len(common), "missing": len(miss), "extra": len(extra),
                       "coverage": len(common) / len(names_st) if names_st else None},
            "by_kind": by_kind, "missing": dict(missing), "extra": dict(extras), "extra_detail": detail}


def compare_instances(st: dict[str, tuple[str, str]], gen: dict[str, tuple[str, str]]) -> dict:
    common = sorted(set(st) & set(gen))
    return {"st": len(st), "generated": len(gen), "common": len(common), "coverage": len(common) / len(st) if st else None,
            "missing": sorted(set(st) - set(gen)), "extra": sorted(set(gen) - set(st)),
            "type_differs": [{"instance": n, "st": st[n][0], "generated": gen[n][0]} for n in common if st[n][0] != gen[n][0]]}


# ------------------------------------------------------------------------------------------------ an toàn + clang
_INC = re.compile(r'^\s*#\s*include\s*(?:<[^>\n]*>|"[^"\n]*")\s*$')
_DIRECTIVE = re.compile(r"^\s*#\s*(include_next|import|embed|include)\b(.*)$")


def check_header_safe(path: Path) -> None:
    """Từ chối header có #include đường dẫn tuyệt đối / `..` / dạng macro, #include_next, #import, #embed."""
    text = strip_comments(Path(path).read_text(encoding="utf-8", errors="replace"))
    lines, i = text.split("\n"), 0
    while i < len(lines):
        start, buf = i + 1, lines[i]
        while buf.endswith("\\") and i + 1 < len(lines):
            i += 1
            buf = buf[:-1] + " " + lines[i]
        i += 1
        m = _DIRECTIVE.match(buf)
        if not m:
            continue
        if m.group(1) != "include":
            raise UnsafeHeader(f"{path}:{start}: #{m.group(1)} is not allowed")
        if not _INC.match(buf):
            raise UnsafeHeader(f"{path}:{start}: #include must name a header literally (<...> or \"...\")")
        arg = re.search(r'[<"]([^>"]*)[>"]', buf).group(1)
        if arg.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", arg) or ".." in arg.replace("\\", "/").split("/"):
            raise UnsafeHeader(f"{path}:{start}: #include of {arg!r} is not allowed (absolute path or '..')")


def clang_available() -> bool:
    return shutil.which("clang") is not None


def clang_version() -> str | None:
    if not clang_available():
        return None
    r = subprocess.run(["clang", "--version"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    return (r.stdout or "").splitlines()[0] if r.stdout else None


def _stub_dir(workdir: Path) -> Path:
    d = Path(workdir) / "stub"
    d.mkdir(parents=True, exist_ok=True)
    for n, t in STUB_FILES.items():
        (d / n).write_text(t, encoding="utf-8")
    return d


def run_clang(header_dir: Path, main_header: str, probe_body: str, workdir: Path, dump: list[str], timeout: float = CLANG_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Biên dịch `#include "<main_header>"` + probe với `-fsyntax-only` và `-Xclang <dump>`; không sinh mã, không chạy gì."""
    header_dir, workdir = Path(header_dir).resolve(), Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    check_header_safe(header_dir / main_header)
    stub = _stub_dir(workdir)
    src = workdir / "probe.c"
    src.write_text(f'#include "{main_header}"\n{probe_body}\n', encoding="utf-8")
    args = ["clang", *CLANG_FLAGS, f"-I{stub}", f"-I{header_dir}", *sum((["-Xclang", d] for d in dump), []), str(src)]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "TMPDIR": str(workdir)}
    return subprocess.run(args, cwd=str(workdir), env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def _check_include_resolution(r: subprocess.CompletedProcess) -> None:
    if "fatal error" in (r.stderr or ""):
        raise RuntimeError("clang could not read the header: " + r.stderr.strip().splitlines()[0][:300])


def _record_for_typedef(node: dict, records: dict) -> dict | None:
    stack = list(node.get("inner", []))
    while stack:
        n = stack.pop()
        for key in ("ownedTagDecl", "decl"):
            ref = n.get(key)
            if isinstance(ref, dict) and ref.get("id") in records:
                return records[ref["id"]]
        stack.extend(n.get("inner", []))
    return None


def struct_members(header_dir: Path, main_header: str, workdir: Path) -> dict[str, list[str]]:
    """{tên typedef struct/union: [tên thành viên]} từ AST của clang (thành viên của struct/union ẩn danh được tính là thành viên trực tiếp)."""
    r = run_clang(header_dir, main_header, "", workdir, ["-ast-dump=json"])
    _check_include_resolution(r)
    ast_ = json.loads(r.stdout)
    records = {n["id"]: n for n in ast_.get("inner", []) if n.get("kind") == "RecordDecl" and n.get("completeDefinition")}
    out: dict[str, list[str]] = {}
    for n in ast_.get("inner", []):
        if n.get("kind") == "TypedefDecl" and re.match(r"^[A-Za-z_]\w*$", n.get("name", "")):
            rec = _record_for_typedef(n, records)
            if rec is not None:
                out[n["name"]] = [m["name"] for m in rec.get("inner", []) if m.get("kind") in ("FieldDecl", "IndirectFieldDecl") and m.get("name")]
    return out


_DUMP = re.compile(r"^Dumping PARITY_V(\d+):\s*$", re.M)
_VALUE = re.compile(r"value: Int (-?\d+)")
_EXPR_OK = re.compile(r"^[\w\s()+\-*/|&^~<>]+$")


def evaluate_exprs(header_dir: Path, main_header: str, exprs: list[str], workdir: Path) -> dict[str, int | None]:
    """Giá trị nguyên mà clang tính được cho từng biểu thức (cast sang unsigned long long); None nếu không phải hằng số nguyên."""
    uniq = []
    for e in exprs:
        if e not in uniq:
            uniq.append(e)
    ok = [e for e in uniq if _EXPR_OK.match(e) and "\n" not in e]
    res: dict[str, int | None] = {e: None for e in uniq}
    if not ok:
        return res
    body = "enum {\n" + "".join(f"  PARITY_V{i} = (unsigned long long)({e}),\n" for i, e in enumerate(ok)) + "};"
    r = run_clang(header_dir, main_header, body, workdir, ["-ast-dump", "-ast-dump-filter=PARITY_V"])
    _check_include_resolution(r)
    parts = _DUMP.split(r.stdout)
    for idx, chunk in zip(parts[1::2], parts[2::2]):
        m = _VALUE.search(chunk)
        if m:
            res[ok[int(idx)]] = int(m.group(1)) & 0xFFFF_FFFF_FFFF_FFFF
    return res


def evaluate_macros(header_dir: Path, main_header: str, names: list[str], workdir: Path) -> dict[str, int | None]:
    return evaluate_exprs(header_dir, main_header, names, workdir)


# ------------------------------------------------------------------------------------------------ (c) offset
def struct_layouts(header_dir: Path, main_header: str, workdir: Path) -> dict[str, dict]:
    """{typedef: {"size": byte, "members": {tên: offset}}} — offset do clang (`__builtin_offsetof`), biên dịch header đúng như nó được viết."""
    members = struct_members(header_dir, main_header, Path(workdir) / "names")
    ok_id = re.compile(r"^[A-Za-z_]\w*$")
    items: list[tuple[str, str | None]] = []
    for t, ms in members.items():
        items.append((t, None))
        items += [(t, m) for m in ms if ok_id.match(m)]
    exprs = [f"sizeof({t})" if m is None else f"__builtin_offsetof({t}, {m})" for t, m in items]
    body = "enum {\n" + "".join(f"  PARITY_V{i} = (unsigned long long)({e}),\n" for i, e in enumerate(exprs)) + "};"
    r = run_clang(header_dir, main_header, body, Path(workdir) / "offsets", ["-ast-dump", "-ast-dump-filter=PARITY_V"])
    _check_include_resolution(r)
    vals: dict[int, int] = {}
    parts = _DUMP.split(r.stdout)
    for idx, chunk in zip(parts[1::2], parts[2::2]):
        m = _VALUE.search(chunk)
        if m:
            vals[int(idx)] = int(m.group(1))
    out: dict[str, dict] = {}
    for i, (t, m) in enumerate(items):
        slot = out.setdefault(t, {"size": None, "members": {}})
        if i in vals:
            if m is None:
                slot["size"] = vals[i]
            else:
                slot["members"][m] = vals[i]
    return out


_RESERVED = re.compile(r"^reserved\w*$", re.I)


def compare_layouts(lay_st: dict, lay_gen: dict, inst_st: dict, inst_gen: dict) -> dict:
    """Theo từng instance chung: thành viên (trừ RESERVED*) của kiểu ST so với kiểu của header sinh — thiếu / thừa / lệch offset."""
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for n in sorted(set(inst_st) & set(inst_gen)):
        ts, tg = inst_st[n][0], inst_gen[n][0]
        if ts in lay_st and tg in lay_gen:
            pairs[(ts, tg)].append(n)
    by_pair, tot = {}, defaultdict(int)
    for (ts, tg), insts in sorted(pairs.items()):
        ms = {k: v for k, v in lay_st[ts]["members"].items() if not _RESERVED.match(k)}
        mg = {k: v for k, v in lay_gen[tg]["members"].items() if not _RESERVED.match(k)}
        mism = {k: {"st": ms[k], "generated": mg[k]} for k in sorted(ms) if k in mg and ms[k] != mg[k]}
        miss, extra = sorted(set(ms) - set(mg)), sorted(set(mg) - set(ms))
        by_pair[f"{ts}->{tg}"] = {"instances": insts, "members_checked": len(ms), "offset_mismatch": mism, "missing_in_generated": miss,
                                  "extra_in_generated": extra, "size_st": lay_st[ts]["size"], "size_generated": lay_gen[tg]["size"]}
        tot["members_checked"] += len(ms)
        tot["offset_mismatch"] += len(mism)
        tot["missing_in_generated"] += len(miss)
        tot["extra_in_generated"] += len(extra)
        tot["size_differs"] += int(lay_st[ts]["size"] != lay_gen[tg]["size"])
    tot["members_matching"] = tot["members_checked"] - tot["offset_mismatch"] - tot["missing_in_generated"]
    tot["instance_pairs"] = len(by_pair)
    tot["instances_compared"] = sum(len(v["instances"]) for v in by_pair.values())
    skipped = sorted(n for n in set(inst_st) & set(inst_gen) if inst_st[n][0] not in lay_st or inst_gen[n][0] not in lay_gen)
    typedefs = {"st_only": sorted(set(lay_st) - set(lay_gen)), "generated_only": sorted(set(lay_gen) - set(lay_st)),
                "common": len(set(lay_st) & set(lay_gen))}
    return {"by_instance_type": by_pair, "totals": dict(tot), "instances_without_layout": skipped, "typedef_names": typedefs}


# ------------------------------------------------------------------------------------------------ (d) giá trị
def compare_values(st_defs: dict, gen_defs: dict, st_dir: Path, gen_dir: Path, main_header: str, workdir: Path) -> dict:
    kst, kgen = macro_kinds(st_defs), macro_kinds(gen_defs)
    ok = INT_KINDS + ("base",)                   # `<X>_BASE` trùng tên cũng phải cùng giá trị (FLASH_BASE: bộ nhớ flash ≠ thanh ghi FLASH)
    names = sorted(n for n in set(kst) & set(kgen) if kst[n] in ok and kgen[n] in ok)
    vs = evaluate_macros(st_dir, main_header, names, Path(workdir) / "values_st")
    vg = evaluate_macros(gen_dir, main_header, names, Path(workdir) / "values_gen")
    mism, unev, match = [], [], 0
    for n in names:
        if vs[n] is None or vg[n] is None:
            unev.append(n)
        elif vs[n] != vg[n]:
            mism.append({"name": n, "st": vs[n], "generated": vg[n]})
        else:
            match += 1
    return {"candidates": len(names), "evaluated": match + len(mism), "match": match, "mismatch": mism, "unevaluated": unev}


def compare_bases(inst_st: dict, inst_gen: dict, st_defs: dict, gen_defs: dict, st_dir: Path, gen_dir: Path, main_header: str, workdir: Path) -> dict:
    common = sorted(set(inst_st) & set(inst_gen))
    vs = evaluate_exprs(st_dir, main_header, [inst_st[n][1] for n in common], Path(workdir) / "bases_st")
    vg = evaluate_exprs(gen_dir, main_header, [inst_gen[n][1] for n in common], Path(workdir) / "bases_gen")
    mism, unev, match = [], [], 0
    for n in common:
        a, b = vs.get(inst_st[n][1]), vg.get(inst_gen[n][1])
        if a is None or b is None:
            unev.append(n)
        elif a != b:
            mism.append({"instance": n, "st": a, "generated": b})
        else:
            match += 1
    return {"checked": match + len(mism), "match": match, "mismatch": mism, "unevaluated": unev}


# ------------------------------------------------------------------------------------------------ báo cáo
def _files_info(d: Path) -> list[dict]:
    return [{"name": p.name, "sha256": sha256_file(p)} for p in sorted(Path(d).glob("*.h"))]


def build_report(st_dir: Path, gen_dir: Path, main_header: str = MAIN_HEADER, workdir: Path | None = None, use_clang: bool = True,
                 meta_extra: dict | None = None) -> dict:
    st_dir, gen_dir = Path(st_dir), Path(gen_dir)
    own = workdir is None
    work = Path(tempfile.mkdtemp(prefix="header_parity_")) if own else Path(workdir)
    try:
        st_text = (st_dir / main_header).read_text(encoding="utf-8", errors="replace")
        gen_text = (gen_dir / main_header).read_text(encoding="utf-8", errors="replace")
        st_defs, gen_defs = parse_defines(st_text), parse_defines(gen_text)
        inst_st, inst_gen = parse_instances(st_defs), parse_instances(gen_defs)
        limitations = ["Tên macro so theo chuỗi đầy đủ, phân loại lý do chỉ là heuristic theo tiền tố <nhóm>_<thanh ghi> (không dùng để quyết định so khớp).",
                       "Chỉ `#define` trong file chính được so (không theo #include); #if/#ifdef bị bỏ qua (lấy mọi nhánh).",
                       "Giá trị chỉ so cho macro số nguyên (số, toán tử số học/bit, macro số nguyên khác); các macro khác (chuỗi, con trỏ, hàm) không so giá trị.",
                       "core_cm4.h của ARM không nằm trong repo ST: stub chỉ gồm __I/__O/__IO/...; macro lõi Cortex-M (NVIC_*, SCB_*, SysTick_*) không được kiểm."]
        rep = {"meta": {"tool": "eval/tools/check_header_parity.py", "main_header": main_header, "st_dir": str(st_dir), "generated_dir": str(gen_dir),
                        "st_files": _files_info(st_dir), "generated_files": _files_info(gen_dir), "clang": clang_version() if use_clang else None,
                        **(meta_extra or {})},
               "macros": compare_macros(st_defs, gen_defs), "instances": compare_instances(inst_st, inst_gen),
               "offsets": None, "values": None, "bases": None, "limitations": limitations}
        if use_clang and clang_available():
            rep["offsets"] = compare_layouts(struct_layouts(st_dir, main_header, work / "st"), struct_layouts(gen_dir, main_header, work / "gen"), inst_st, inst_gen)
            rep["values"] = compare_values(st_defs, gen_defs, st_dir, gen_dir, main_header, work / "v")
            rep["bases"] = compare_bases(inst_st, inst_gen, st_defs, gen_defs, st_dir, gen_dir, main_header, work / "b")
        else:
            limitations.append("clang không dùng được (hoặc --no-clang): bỏ qua (c) offset thành viên và (d) giá trị macro/địa chỉ instance; chỉ so tên.")
        return rep
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


def differs(rep: dict) -> bool:
    c = rep["macros"]["counts"]
    bad = bool(c["missing"] or c["extra"] or rep["instances"]["missing"] or rep["instances"]["extra"] or rep["instances"]["type_differs"])
    if rep["offsets"]:
        t = rep["offsets"]["totals"]
        bad = bad or bool(t["offset_mismatch"] or t["missing_in_generated"] or t["extra_in_generated"])
    if rep["values"]:
        bad = bad or bool(rep["values"]["mismatch"])
    if rep["bases"]:
        bad = bad or bool(rep["bases"]["mismatch"])
    return bad


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _list(names: list[str], max_list: int) -> str:
    shown = ", ".join(f"`{n}`" for n in names[:max_list])
    return shown + (f", … (+{len(names) - max_list})" if len(names) > max_list else "")


def render_markdown(rep: dict, max_list: int = 25, title: str = "Đối chiếu header sinh tự động với header chính thức của ST") -> str:
    m, c = rep["macros"], rep["macros"]["counts"]
    L = [f"# {title}", "",
         f"- ST: `{rep['meta']['st_dir']}` ({', '.join(f['name'] + ' ' + f['sha256'][:12] for f in rep['meta']['st_files'])})",
         f"- Header sinh: `{rep['meta']['generated_dir']}` ({', '.join(f['name'] + ' ' + f['sha256'][:12] for f in rep['meta']['generated_files'] if f['name'] in ('stm32g474xx.h', 'stm32g4xx.h'))})",
         f"- clang: {rep['meta'].get('clang') or 'không dùng'}", "",
         "## Tổng quan", "",
         f"Macro (không tính chốt chặn include): ST {c['st']}, sinh {c['generated']}, chung {c['common']}; **thiếu {c['missing']}**, **thừa {c['extra']}**; "
         f"coverage = chung/ST = {_pct(c['coverage'])}.", "",
         "| loại | ST | sinh | chung | thiếu | thừa | coverage |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k in KINDS:
        v = m["by_kind"][k]
        L.append(f"| {k} | {v['st']} | {v['generated']} | {v['common']} | {v['missing']} | {v['extra']} | {_pct(v['coverage'])} |")
    i = rep["instances"]
    L += ["", f"Instance: ST {i['st']}, sinh {i['generated']}, chung {i['common']} (coverage {_pct(i['coverage'])}); thiếu {len(i['missing'])}, thừa {len(i['extra'])}, "
          f"khác kiểu struct {len(i['type_differs'])}."]
    L += ["", "## (a) Thiếu trong header sinh (có ở ST)", ""]
    for cat, names in sorted(m["missing"].items(), key=lambda kv: -len(kv[1])):
        L.append(f"- **{cat}** ({len(names)}): {_list(names, max_list)}")
    L += ["", "## (b) Thừa trong header sinh (ST không có)", ""]
    for cat, names in sorted(m["extra"].items(), key=lambda kv: -len(kv[1])):
        L.append(f"- **{cat}** ({len(names)}): {_list(names, max_list)}")
    if i["missing"] or i["extra"] or i["type_differs"]:
        L += ["", "### Instance", "", f"- thiếu ({len(i['missing'])}): {_list(i['missing'], max_list)}", f"- thừa ({len(i['extra'])}): {_list(i['extra'], max_list)}",
              f"- khác kiểu struct ({len(i['type_differs'])}): " + ", ".join(f"`{d['instance']}`: ST {d['st']} / sinh {d['generated']}" for d in i["type_differs"][:max_list])]
    L += ["", "## (c) Offset thành viên struct (theo instance, clang `offsetof`)", ""]
    if rep["offsets"] is None:
        L.append("Không chạy (không có clang hoặc `--no-clang`).")
    else:
        t = rep["offsets"]["totals"]
        L += [f"Cặp (kiểu ST -> kiểu sinh) đã so: {t['instance_pairs']} cho {t['instances_compared']} instance; thành viên (trừ RESERVED) {t['members_checked']}: "
              f"khớp {t['members_matching']}, **lệch offset {t['offset_mismatch']}**, **thiếu ở sinh {t['missing_in_generated']}**, thừa ở sinh {t['extra_in_generated']}; "
              f"kích thước struct khác nhau: {t['size_differs']}.", "",
              "| ST -> sinh | instance | kiểm | lệch offset | thiếu ở sinh | thừa ở sinh | size ST / sinh |", "|---|---|---:|---:|---:|---:|---|"]
        for k, v in rep["offsets"]["by_instance_type"].items():
            ex = ", ".join(v["instances"][:3]) + (f" (+{len(v['instances']) - 3})" if len(v["instances"]) > 3 else "")
            L.append(f"| `{k}` | {ex} | {v['members_checked']} | {len(v['offset_mismatch'])} | {len(v['missing_in_generated'])} | {len(v['extra_in_generated'])} | "
                     f"{v['size_st']} / {v['size_generated']} |")
        details = [(k, v) for k, v in rep["offsets"]["by_instance_type"].items() if v["offset_mismatch"] or v["missing_in_generated"] or v["extra_in_generated"]]
        if details:
            L += ["", "Chi tiết các cặp có khác biệt:", ""]
            for k, v in details:
                L.append(f"- `{k}`: lệch {_list(list(v['offset_mismatch']), max_list)}; thiếu ở sinh {_list(v['missing_in_generated'], max_list)}; "
                         f"thừa ở sinh {_list(v['extra_in_generated'], max_list)}")
        if rep["offsets"]["instances_without_layout"]:
            L.append(f"\nInstance chung nhưng không dựng được layout: {_list(rep['offsets']['instances_without_layout'], max_list)}")
    L += ["", "## (d) Giá trị macro trùng tên và địa chỉ instance (clang)", ""]
    if rep["values"] is None:
        L.append("Không chạy (không có clang hoặc `--no-clang`).")
    else:
        v, b = rep["values"], rep["bases"]
        L += [f"Macro số nguyên trùng tên: {v['candidates']}; tính được cả hai bên {v['evaluated']}: khớp {v['match']}, **khác giá trị {len(v['mismatch'])}**; "
              f"không tính được {len(v['unevaluated'])}.",
              f"Địa chỉ cơ sở instance chung: kiểm {b['checked']}, khớp {b['match']}, **khác {len(b['mismatch'])}**, không tính được {len(b['unevaluated'])}."]
        if v["mismatch"]:
            L += ["", "Khác giá trị (tối đa %d):" % max_list, ""] + [f"- `{x['name']}`: ST {x['st']:#x} / sinh {x['generated']:#x}" for x in v["mismatch"][:max_list]]
        if b["mismatch"]:
            L += ["", "Địa chỉ khác:", ""] + [f"- `{x['instance']}`: ST {x['st']:#x} / sinh {x['generated']:#x}" for x in b["mismatch"][:max_list]]
    L += ["", "## Giới hạn", ""] + [f"- {s}" for s in rep["limitations"]]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------------------------------ CLI
def _generated_dir(source: str, tmp: Path) -> Path:
    if source == "agent":
        sys.path.insert(0, str(ROOT / "agent"))
        from hwmodel import header_gen            # noqa: PLC0415 — chỉ nạp khi cần
        header_gen.write(tmp / "gen")
        return tmp / "gen"
    if source == "vendor":
        from eval import sandbox                  # noqa: PLC0415
        return Path(sandbox.load().compile_check.header_dir("stm32g474"))
    raise ValueError(source)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--st-dir", type=Path, help="thư mục chứa header ST (mặc định: corpus/headers/... theo manifest, kiểm sha256)")
    ap.add_argument("--generated-dir", type=Path, help="thư mục header sinh (mặc định: sinh từ --generated-from)")
    ap.add_argument("--generated-from", choices=("agent", "vendor"), default="agent")
    ap.add_argument("--main-header", default=MAIN_HEADER)
    ap.add_argument("--out", type=Path, help="ghi header_parity.json + header_parity.md vào thư mục này")
    ap.add_argument("--max-list", type=int, default=25)
    ap.add_argument("--no-clang", action="store_true")
    ap.add_argument("--strict", action="store_true", help="mã thoát 1 nếu còn bất kỳ khác biệt nào")
    a = ap.parse_args(argv)
    meta_extra: dict = {}
    st_dir = a.st_dir
    if st_dir is None:
        entry = manifest_entry()
        if entry is None:
            ap.error("corpus/manifest.yaml has no ST header entry; pass --st-dir")
        verify_manifest_files(entry)
        st_dir = CORPUS / Path(entry["files"][0]["path"]).parent
        meta_extra["st_source"] = {k: entry.get(k) for k in ("doc_id", "source_url", "tag", "commit", "version")}
    with tempfile.TemporaryDirectory(prefix="header_parity_gen_") as tmp:
        gen_dir = a.generated_dir or _generated_dir(a.generated_from, Path(tmp))
        meta_extra["generated_source"] = str(a.generated_dir) if a.generated_dir else a.generated_from
        rep = build_report(st_dir, gen_dir, a.main_header, workdir=Path(tmp) / "work", use_clang=not a.no_clang, meta_extra=meta_extra)
    c = rep["macros"]["counts"]
    print(f"macros: ST {c['st']}, generated {c['generated']}, common {c['common']}, missing {c['missing']}, extra {c['extra']} (coverage {_pct(c['coverage'])})")
    i = rep["instances"]
    print(f"instances: ST {i['st']}, generated {i['generated']}, missing {len(i['missing'])}, extra {len(i['extra'])}, type differs {len(i['type_differs'])}")
    if rep["offsets"]:
        t = rep["offsets"]["totals"]
        print(f"offsets: members {t['members_checked']}, matching {t['members_matching']}, mismatch {t['offset_mismatch']}, "
              f"missing in generated {t['missing_in_generated']}, extra in generated {t['extra_in_generated']}")
        print(f"values: evaluated {rep['values']['evaluated']}, mismatch {len(rep['values']['mismatch'])}; bases: checked {rep['bases']['checked']}, "
              f"mismatch {len(rep['bases']['mismatch'])}")
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "header_parity.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        (a.out / "header_parity.md").write_text(render_markdown(rep, a.max_list), encoding="utf-8")
        print(f"wrote {a.out}/header_parity.json and header_parity.md")
    return 1 if (a.strict and differs(rep)) else 0


if __name__ == "__main__":
    sys.exit(main())
