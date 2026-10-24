"""compile (chỉ số báo cáo riêng, KHÔNG gate TSR): `compile_check` của bản vendor trên cùng khối code.

details.status: ok | error | skipped | no_code.  `skipped` (không có clang / chip khác) KHÔNG BAO GIỜ là pass.
"""
from __future__ import annotations

from eval import sandbox
from eval.graders.functional_sim import extract_c_code


def grade(task, run, ctx) -> dict:
    code = extract_c_code(run.final_answer)
    if not code.strip():
        return {"pass": False, "score": 0.0, "reasons": ["no_code: the answer contains no C code block"], "details": {"status": "no_code", "errors": [], "warnings": []}}
    r = sandbox.load().compile_check.compile_check(code, task.expected.get("chip", "stm32g474"))
    ok = r["status"] == "ok"
    reasons = [] if ok else [f"compile_{r['status']}: " + (r.get("reason") or (r["errors"][0]["msg"] if r["errors"] else ""))]
    return {"pass": ok, "score": 1.0 if ok else 0.0, "reasons": reasons,
            "details": {"status": r["status"], "errors": r["errors"][:5], "warnings": r["warnings"][:5], "reason": r.get("reason")}}
