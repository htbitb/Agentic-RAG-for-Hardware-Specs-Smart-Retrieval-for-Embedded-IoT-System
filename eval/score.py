"""Chấm lại từ runs.jsonl -> scores.jsonl. KHÔNG gọi LLM / mạng (chỉ đọc kết quả đã ghi + tài liệu corpus đã cache).

    python -m eval.score --run eval/results/<timestamp>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from eval.context import GradeContext
from eval.envload import LLMConfig, redact
from eval.graders import abstain, attack, checklist, citation, clarify, compile as compile_grader, conflict_detected, exact, final_state, functional_sim, hitl, keyfacts, numeric_claims, process, safety
from eval.schema import GATING_GRADERS, RunResult, Task, grounded_pass, load_tasks

ROOT = Path(__file__).resolve().parents[1]
GRADERS = {"exact": exact.grade, "keyfacts": keyfacts.grade, "numeric_claims": numeric_claims.grade,
           "citation": citation.grade, "safety": safety.grade, "attack": attack.grade, "abstain": abstain.grade,
           "functional_sim": functional_sim.grade, "compile": compile_grader.grade, "final_state": final_state.grade,
           "conflict_detected": conflict_detected.grade, "checklist": checklist.grade, "clarify": clarify.grade}


_COMPOUND = re.compile(r"^(sim_violation|inactive|unsupported_construct|conflict_missed|conflict_late|must_not):([A-Za-z0-9_-]+)")


def fail_code(reason: str) -> str:
    """Mã lỗi của một lý do: `sim_violation:SIM-TIM-MOE: ...` -> `sim_violation:SIM-TIM-MOE` (giữ mã mô phỏng để phân loại lỗi C3);
    các grader khác giữ nguyên hành vi cũ (phần trước dấu ':' đầu tiên)."""
    m = _COMPOUND.match(reason)
    return f"{m.group(1)}:{m.group(2)}" if m else reason.split(":", 1)[0].strip()


def score_run(run: RunResult, task: Task, ctx: GradeContext) -> dict:
    row = {"system": run.system, "variant": run.variant, "task_id": run.task_id, "seed": run.seed, "category": task.category,
           "split": task.split, "infra": run.has_infra_error(), "errors": list(run.errors), "graders": {}, "tsr_pass": None,
           "grounded_pass": None, "fail_codes": [], "usage": run.usage, "latency_s": run.latency_s}
    if row["infra"]:
        return row                                   # lỗi hạ tầng: loại khỏi TSR, vẫn được đếm trong report
    for name in task.graders:
        row["graders"][name] = GRADERS[name](task, run, ctx)
    system_error = any(e.startswith("error:") for e in run.errors)
    gating = [n for n in task.graders if n in GATING_GRADERS]
    failed = [n for n in gating if not row["graders"][n]["pass"]]
    row["tsr_pass"] = not failed and not system_error
    row["grounded_pass"] = grounded_pass(row)
    if process.is_v3(run.trace):                     # P4: chỉ số quá trình, chỉ báo cáo — thêm SAU khi tsr_pass đã chốt nên không thể ảnh hưởng nó
        row["graders"]["process"] = process.grader_result(run, row["tsr_pass"])
    if hitl.applies(run.trace):                      # P5: tương tác người–hệ (interrupt / câu hỏi văn bản), chỉ báo cáo — cũng thêm SAU khi tsr_pass đã chốt
        row["graders"]["hitl"] = hitl.grader_result(run)
    if system_error:
        row["fail_codes"].append("system_error")
    for n in failed:
        codes = [fail_code(r) for r in row["graders"][n]["reasons"]] or [f"{n}_failed"]
        row["fail_codes"] += [c for c in codes if c not in row["fail_codes"]]
    return json.loads(redact(json.dumps(row, ensure_ascii=False), ctx.secrets))


def load_runs(path: Path) -> list[RunResult]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(RunResult.from_dict(json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def build_context() -> GradeContext:
    from eval.system_prompts import load_system_prompts

    cfg = LLMConfig.load()
    return GradeContext.load(system_prompts=load_system_prompts(), secrets=[cfg.api_key] if cfg.api_key else [])


def record_scoring(run_dir: Path) -> None:
    """Ghi vào manifest bản hwmodel đóng băng đã dùng để CHẤM (có thể khác bản lúc chạy nếu đã sửa simulator và chấm lại, D19)."""
    from datetime import datetime, timezone

    from eval import sandbox

    path = Path(run_dir) / "manifest.json"
    if not path.is_file():
        return
    m = json.loads(path.read_text(encoding="utf-8"))
    m["scoring"] = {**sandbox.vendor_hashes(), "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None, ctx: GradeContext | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, default=ROOT / "eval" / "tasks")
    a = ap.parse_args(argv)
    ctx = ctx or build_context()
    tasks = {t.id: t for t in load_tasks(a.tasks, include_needs_human=True, oracle=True)}       # luôn nạp cả biến thể oracle-info (C5-xxx-O)
    rows, skipped = [], 0
    for run in load_runs(a.run / "runs.jsonl"):
        if run.task_id not in tasks:
            skipped += 1
            continue
        rows.append(score_run(run, tasks[run.task_id], ctx))
    (a.run / "scores.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    record_scoring(a.run)
    print(f"Đã chấm {len(rows)} run -> {a.run / 'scores.jsonl'}" + (f" (bỏ qua {skipped}: task không còn)" if skipped else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
