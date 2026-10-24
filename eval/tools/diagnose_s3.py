"""Chẩn đoán lỗi S3 từ trace (brief P4 bước 7.6): mỗi run THẤT BẠI (tsr_pass False, không phải lỗi hạ tầng) được gán một nhóm.

    eval/.venv/bin/python -m eval.tools.diagnose_s3 --run eval/results/<dir> [--system S3@P4] [--out diagnosis.md]

Nhóm (đề xuất tự động từ trace; người đọc xác nhận/tinh chỉnh, đặc biệt "hiểu sai đề" cần so requirement agent ghi với spec của task):
  gate_pass_grader_fail  lượt CUỐI được Gate chấp nhận (không ESCALATED) nhưng grader độc lập trượt  => RỦI RO TỰ CHẤM (D19): báo riêng, kèm ví dụ
  gate_blocked_budget    Gate từ chối đúng (có finding lỗi) rồi hết ngân sách / lặp lỗi => ESCALATED
  simulator_unmodeled    tính chất cần kiểm không được mô hình hoá (G2-UNMODELED / mã grader `unmodeled`)
  wrong_tool             ≥ 5 tool call lỗi (tham số/tool sai) và không kết thúc được chấp nhận
  misread_task           (gán tay) agent ghi requirement khác đề; công cụ chỉ gợi ý khi grader báo wrong_pin/freq... và Gate đã chấp nhận
  other                  guardrail xác định của v1, hết ngân sách trước khi có bản nháp, lỗi hệ...
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

GROUPS = {
    "gate_pass_grader_fail": "Gate cho qua nhưng grader trượt",
    "gate_blocked_budget": "Gate chặn đúng nhưng hết ngân sách",
    "simulator_unmodeled": "simulator không mô hình hoá",
    "wrong_tool": "tool sai / dùng tool lỗi",
    "misread_task": "hiểu sai đề",
    "other": "khác",
}


def _last_turn(trace: list[dict]) -> list[dict]:
    evs = [e for e in trace if isinstance(e, dict) and e.get("type") not in (None, "worker")]
    turns = [e.get("turn", 0) for e in evs if isinstance(e.get("turn"), int)]
    last = max(turns, default=0)
    return sorted([e for e in evs if e.get("turn", 0) == last], key=lambda e: e.get("seq", 0))


def _error_codes(ev: dict) -> list[str]:
    return [f["code"] for f in ev.get("findings", []) if f.get("severity") == "error"]


def classify(row: dict) -> dict:
    last = _last_turn(row.get("trace") or [])
    escalated = [e for e in last if e["type"] == "escalated"]
    gates = [e for e in last if e["type"] == "gate_result"]
    finishes = [e for e in last if e["type"] == "finish"]
    guard = [e for e in last if e["type"] == "guardrail" and e.get("blocked")]
    tool_errors = [e for e in (row.get("trace") or []) if isinstance(e, dict) and e.get("type") == "tool_call" and not e.get("internal") and e.get("ok") is False]
    unmodeled = any("unmodeled" in str(c) for c in row.get("fail_codes", [])) or any("G2-UNMODELED" in [f["code"] for f in g.get("findings", [])] for g in gates)
    last_gate_codes = _error_codes(gates[-1]) if gates else []
    accepted_last = bool(finishes) and finishes[-1].get("accepted") and not escalated
    if guard and not gates:
        return {"group": "other", "detail": "refused/blocked by the deterministic v1 guardrail before the runtime ran"}
    if unmodeled:
        return {"group": "simulator_unmodeled", "detail": "an effect the simulator does not model decided the outcome"}
    if escalated:
        if gates and last_gate_codes:
            return {"group": "wrong_tool" if len(tool_errors) >= 5 else "gate_blocked_budget",
                    "detail": f"escalated ({escalated[-1].get('reason')}) after gate errors: {', '.join(last_gate_codes)}; {len(tool_errors)} tool error(s)"}
        return {"group": "wrong_tool" if len(tool_errors) >= 5 else "other", "detail": f"escalated ({escalated[-1].get('reason')}) before any draft reached the gate; {len(tool_errors)} tool error(s)"}
    if accepted_last:
        start = (gates[-1].get("start") or {}).get("source") if gates else None
        return {"group": "gate_pass_grader_fail", "detail": f"final answer accepted by the gate (start state from {start}); grader: " + "; ".join(
            r for g in (row.get("graders") or {}).values() for r in (g.get("reasons") or [])[:2])[:300]}
    if len(tool_errors) >= 5:
        return {"group": "wrong_tool", "detail": f"{len(tool_errors)} tool error(s) and no accepted answer"}
    return {"group": "other", "detail": "no accepted finish and no escalation in the last turn" + (f"; errors {row.get('errors')}" if row.get("errors") else "")}


def diagnose(rows: list[dict]) -> dict:
    out = []
    for r in rows:
        if r.get("infra") or r.get("tsr_pass") is not False:
            continue
        c = classify(r)
        out.append({"task_id": r["task_id"], "seed": r["seed"], "category": r.get("category"), "variant": r.get("variant", ""), "fail_codes": r.get("fail_codes", []), **c})
    return {"runs": out, "counts": dict(Counter(x["group"] for x in out))}


def render(d: dict) -> str:
    lines = ["# Chẩn đoán lỗi S3@P4", "", "| Nhóm | Số run |", "|---|---|"]
    lines += [f"| {GROUPS[g]} | {n} |" for g, n in sorted(d["counts"].items(), key=lambda kv: -kv[1])]
    lines += ["", "## Từng run thất bại", "", "| Task | Seed | Mã lỗi grader | Nhóm đề xuất | Chi tiết |", "|---|---|---|---|---|"]
    lines += [f"| {x['task_id']} | {x['seed']} | {', '.join(x['fail_codes'])} | {GROUPS[x['group']]} | {x['detail'].replace('|', '/')} |" for x in d["runs"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--system", default="S3@P4")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    scores = [json.loads(l) for l in (a.run / "scores.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    runs = {(r["system"], r.get("variant", ""), r["task_id"], r["seed"]): r for r in map(json.loads, (a.run / "runs.jsonl").read_text(encoding="utf-8").splitlines() if (a.run / "runs.jsonl").exists() else [])}
    rows = []
    for s in scores:
        if s["system"] != a.system:
            continue
        rows.append({**s, "trace": (runs.get((s["system"], s.get("variant", ""), s["task_id"], s["seed"])) or {}).get("trace", [])})
    text = render(diagnose(rows))
    (a.out or a.run / "diagnosis.md").write_text(text, encoding="utf-8")
    print(text, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
