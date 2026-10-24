"""compile_check: `clang --target=thumbv7em-none-eabi -fsyntax-only` với header sinh từ SVD (hwmodel.header_gen).

Kết quả: {"status": "ok" | "error" | "skipped", "errors": [...], "warnings": [...], "reason"?}.  `skipped` KHÔNG BAO GIỜ là pass (`is_pass`).
An toàn (mã của hệ là dữ liệu KHÔNG tin cậy): chỉ tiền xử lý + kiểm cú pháp, KHÔNG biên dịch ra mã/KHÔNG chạy; include chỉ tìm trong thư mục header
tự sinh (`-nostdinc`); trước khi gọi clang quét và chặn #include đường dẫn tuyệt đối / `..` / dạng macro, #include_next, #import, #embed.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import data, header_gen

SUPPORTED_CHIPS = {"stm32g474"}
MAX_CODE_BYTES = 64 * 1024
CLANG_TIMEOUT_S = 30
TARGET_FLAGS = ["--target=thumbv7em-none-eabi", "-mcpu=cortex-m4", "-ffreestanding", "-nostdinc", "-std=gnu11"]
_DIAG = re.compile(r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+): (?P<sev>fatal error|error|warning): (?P<msg>.*)$", re.M)
_DIRECTIVE = re.compile(r"^\s*#\s*(?P<name>[A-Za-z_]+)(?P<rest>.*)$")
_INCLUDE_ARG = re.compile(r'^\s*(?:<(?P<ang>[^>]*)>|"(?P<quo>[^"]*)")\s*(?://.*|/\*.*)?$')

_HDR_CACHE: dict[tuple, Path] = {}
_TMP_DIRS: list[str] = []


def _cleanup() -> None:
    for d in _TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup)


def is_pass(result: dict) -> bool:
    return result.get("status") == "ok"


def _problem(line: int, msg: str, kind: str) -> dict:
    return {"line": line, "col": 1, "msg": msg, "kind": kind}


def scan_directives(code: str) -> list[dict]:
    """Các chỉ thị tiền xử lý bị cấm. Nối dòng `\\` trước khi quét để không giấu được chỉ thị."""
    problems: list[dict] = []
    logical, buf, start = [], "", 1
    for i, raw in enumerate(code.split("\n"), 1):
        if not buf:
            start = i
        if raw.endswith("\\"):
            buf += raw[:-1]
            continue
        logical.append((start, buf + raw))
        buf = ""
    if buf:
        logical.append((start, buf))
    for lineno, text in logical:
        m = _DIRECTIVE.match(text)
        if not m:
            continue
        name, rest = m.group("name"), m.group("rest")
        if name in ("include_next", "import", "embed"):
            problems.append(_problem(lineno, f"#{name} is not allowed", "forbidden_directive"))
        elif name == "include":
            a = _INCLUDE_ARG.match(rest)
            if not a:
                problems.append(_problem(lineno, "#include must name a header literally (<...> or \"...\"): macro/computed includes are not allowed", "forbidden_directive"))
                continue
            path = a.group("ang") if a.group("ang") is not None else a.group("quo")
            if path.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", path) or ".." in path.replace("\\", "/").split("/"):
                problems.append(_problem(lineno, f"#include of {path!r} is not allowed (absolute path or '..')", "forbidden_directive"))
    return problems


def parse_diagnostics(stderr: str, main_name: str = "main.c") -> tuple[list[dict], list[dict]]:
    errors, warnings = [], []
    for m in _DIAG.finditer(stderr or ""):
        rec = {"line": int(m.group("line")), "col": int(m.group("col")), "msg": m.group("msg").strip(), "kind": "compile"}
        if os.path.basename(m.group("file")) != main_name:
            rec["file"] = os.path.basename(m.group("file"))
        (warnings if m.group("sev") == "warning" else errors).append(rec)
    return errors, warnings


def header_dir(chip: str = "stm32g474") -> Path:
    """Thư mục header tự sinh (tạo một lần mỗi tiến trình, ở thư mục tạm riêng)."""
    db = data.default_db()
    key = (chip, str(db), db.stat().st_mtime_ns, data.default_attrs().stat().st_mtime_ns)
    if key not in _HDR_CACHE:
        d = tempfile.mkdtemp(prefix="hwmodel_hdr_")
        _TMP_DIRS.append(d)
        header_gen.write(d, chip)
        _HDR_CACHE[key] = Path(d)
    return _HDR_CACHE[key]


def header_checksum(chip: str = "stm32g474") -> str:
    return header_gen.checksum(header_gen.render(header_gen.build_model(chip)))


def clang_command(src: Path, hdr: Path, extra: list[str] | None = None) -> list[str]:
    return ["clang", *TARGET_FLAGS, f"-I{hdr}", f"-I{hdr / 'include'}", *(extra or []), str(src)]


def run_clang(args: list[str], cwd: str, timeout: float = CLANG_TIMEOUT_S) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "TMPDIR": cwd}
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def compile_check(code: str, chip: str = "stm32g474", timeout: float = CLANG_TIMEOUT_S) -> dict:
    base = {"errors": [], "warnings": []}
    if chip not in SUPPORTED_CHIPS:
        return {"status": "skipped", "reason": f"compile_check has no header for {chip!r} (supported: {', '.join(sorted(SUPPORTED_CHIPS))})", **base}
    if shutil.which("clang") is None:
        return {"status": "skipped", "reason": "clang is not installed on this machine", **base}
    if len(code.encode("utf-8", "replace")) > MAX_CODE_BYTES:
        return {"status": "error", "errors": [_problem(1, f"code exceeds {MAX_CODE_BYTES} bytes", "too_large")], "warnings": []}
    bad = scan_directives(code)
    if bad:
        return {"status": "error", "errors": bad, "warnings": []}
    hdr = header_dir(chip)
    with tempfile.TemporaryDirectory(prefix="hwmodel_cc_") as tmp:
        src = Path(tmp) / "main.c"
        src.write_text(code, encoding="utf-8")
        try:
            r = run_clang(clang_command(src, hdr, ["-fsyntax-only", "-Wall", "-Werror=implicit-function-declaration", "-Werror=implicit-int",
                                                   "-fno-color-diagnostics"]), tmp, timeout)
        except subprocess.TimeoutExpired:
            return {"status": "error", "errors": [_problem(1, f"clang timed out after {timeout:g} s", "timeout")], "warnings": []}
    errors, warnings = parse_diagnostics(r.stderr)
    if r.returncode != 0 and not errors:
        errors = [_problem(1, (r.stderr or "clang failed").strip()[:500], "compile")]
    return {"status": "ok" if r.returncode == 0 else "error", "errors": errors, "warnings": warnings}
