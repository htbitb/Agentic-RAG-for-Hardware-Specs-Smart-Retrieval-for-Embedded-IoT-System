"""G5 Compile (P4_interfaces §2.3): `compile_check(code)` (clang -fsyntax-only, header CMSIS sinh từ SVD). ok -> pass; error -> G5-COMPILE (local) với
dòng/cột/thông điệp đầu tiên định vị theo khối code; skipped (chip khác / không có toolchain) -> gate skipped + G5-SKIPPED unknown, có thể miễn —
không bao giờ là pass nhưng không chặn."""
from __future__ import annotations

from dataclasses import dataclass, field

from .codeblocks import Program
from .types import Finding, tool_error


@dataclass
class CompileResult:
    status: str                        # pass | skipped | na  ("fail" do Gate suy ra)
    findings: list[Finding]
    details: dict = field(default_factory=dict)


def _F(code, where, expected, actual, hint, severity="error", waivable=False) -> Finding:
    return Finding(gate="G5", code=code, where=where, expected=expected, actual=actual, hint_source=hint, severity=severity, kind="local", waivable=waivable)


def run(call, prog: Program | None, chip: str) -> CompileResult:
    if prog is None:
        return CompileResult("na", [])
    res = call("compile_check", {"code": prog.code, "chip": chip})
    err = tool_error(res)
    status = res.get("status") if err is None else None
    if status not in ("ok", "error", "skipped"):
        return CompileResult("skipped", [_F("G5-TOOL-ERROR", "tool compile_check", "a compile_check result (ok | error | skipped)",
                                            f"compile_check failed: {err or f'unexpected status {status!r}'}",
                                            "compile_check (infrastructure problem; G5 is skipped and never counted as a pass)", severity="unknown")])
    details = {"status": status, "errors": len(res.get("errors") or []), "warnings": len(res.get("warnings") or []), "wrapped": prog.wrapped}
    if status == "ok":
        return CompileResult("pass", [], details)
    if status == "skipped":
        return CompileResult("skipped", [_F("G5-SKIPPED", "code", "the code compiled with clang for Cortex-M4 against the CMSIS device header",
                                            f"compilation skipped: {res.get('reason') or 'no reason given'}",
                                            "compile_check (needs clang and a supported chip); may be waived: finish(waived_requirements=[{\"id\": \"G5-SKIPPED\", ...}])",
                                            severity="unknown", waivable=True)], details)
    first = (res.get("errors") or [{}])[0]
    line, col = first.get("line"), first.get("col")
    if first.get("file"):
        where = f"{first['file']} line {line}, col {col} (included by the code)"
    else:
        where = f"{prog.locate(line)}, col {col}"
    n = details["errors"]
    return CompileResult("pass", [_F("G5-COMPILE", where, "C code that compiles for Cortex-M4 against the CMSIS device header (clang -fsyntax-only)",
                                     f"{first.get('msg', 'compile error')}" + (f" (+{n - 1} more error(s))" if n > 1 else ""),
                                     "compile_check (stm32g4xx.h generated from the SVD: TIM1->PSC, RCC_APB2ENR_TIM1EN, ...)")], details)
