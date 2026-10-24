"""Grader `hitl` (P5, CHỈ BÁO CÁO — plan/P5_interfaces.md §5): số đếm tương tác người–hệ của một run, như `process` (không pass/score, không nằm trong
GATING_GRADERS, được score.py thêm SAU khi tsr_pass đã chốt nên không thể ảnh hưởng nó). Chỉ tính cho run có sự kiện `human_reply` / `resume_result` /
`hitl_loop` (runner ghi) hoặc `interrupt_raised` (runtime v3 ghi); run khác không có khoá `hitl` (scores cũ chấm lại giống hệt).

Sự kiện runner (eval/run.py, mỗi sự kiện có `turn` = chỉ số lượt người dùng đã gửi, kể cả lượt bổ sung của baseline):
  human_reply   {kind, question, matched, necessary, answered, decision, source: interrupt|baseline_text, index, answer, [interrupt_id]}
  resume_result {interrupt_id, status}  — trạng thái TurnResult sau `adapter.resume` ("error" kèm `error` nếu resume ném lỗi)
  hitl_loop     {interrupt_id, rounds}  — hệ vẫn interrupted sau `max_answers + 3` vòng ⇒ runner dừng hội thoại, gắn `error:hitl_loop`
Định nghĩa một run:
  interrupts            = human_reply(source=interrupt) + hitl_loop (interrupt runner đã thấy; cái cuối của hitl_loop không được trả lời)
  interrupts_raised     = số `interrupt_raised` của runtime (đối chiếu);  by_kind = interrupt đã trả lời theo kind
  resumes / resume_ok   = số resume_result / số có status khác "error" (answered | interrupted | refused | blocked | escalated...)
  questions/necessary   = human_reply kind ∈ {clarify, text} / trong đó necessary;  ask_human_unnecessary = interrupt clarify necessary=False
  text_questions        = human_reply source=baseline_text (lượt người dùng bổ sung của baseline)
  ask_human_calls       = sự kiện tool_call (không internal) của tool `ask_human` — bị trừ khỏi số tool call khi tính Autonomy (lời gọi đó chính là can thiệp)
  rejects               = `resumed` (runtime) có decision=reject;  replan_after_reject = số reject mà sau nó, cùng run_id, có >= 1 `plan_updated`
                          trước interrupt kế tiếp (Replan sau Reject = replan_after_reject / rejects)
`aggregate(rows)` gộp các hàng scores.jsonl của MỘT hệ:
  Resume Success = Σ resume_ok / Σ interrupts;  Autonomy Ratio = T / (T + Σ interrupts) với T = Σ process.tool_calls (mọi run có trace v3) − Σ ask_human_calls;
  can thiệp TB/task = Σ (interrupts + text_questions) / số run;  mẫu số 0 ⇒ None (report in N/A).
`clarify_aggregate(rows)` gộp grader `clarify` theo nửa: thiếu thông tin (required > 0) và đủ thông tin (required = 0).
"""
from __future__ import annotations

from collections import Counter

RUNNER_EVENTS = ("human_reply", "resume_result", "hitl_loop")
TRIGGERS = (*RUNNER_EVENTS, "interrupt_raised")


def _dicts(trace) -> list[dict]:
    return [e for e in (trace or []) if isinstance(e, dict)]


def applies(trace) -> bool:
    return any(e.get("type") in TRIGGERS for e in _dicts(trace))


def _num(v) -> float:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _replan_after_reject(evs: list[dict]) -> tuple[int, int]:
    groups: dict = {}
    for idx, e in enumerate(evs):
        if e.get("type") in RUNNER_EVENTS:
            continue
        groups.setdefault(e.get("run_id"), []).append((_num(e.get("seq")) if "seq" in e else idx, idx, e))
    rejects = replanned = 0
    for items in groups.values():
        seq = [e for _, _, e in sorted(items, key=lambda x: (x[0], x[1]))]
        for i, e in enumerate(seq):
            if e.get("type") != "resumed" or e.get("decision") != "reject":
                continue
            rejects += 1
            for f in seq[i + 1:]:
                if f.get("type") == "interrupt_raised":
                    break
                if f.get("type") == "plan_updated":
                    replanned += 1
                    break
    return rejects, replanned


def hitl_metrics(run) -> dict:
    evs = _dicts(getattr(run, "trace", None))
    replies = [e for e in evs if e.get("type") == "human_reply"]
    from_interrupt = [e for e in replies if e.get("source") == "interrupt"]
    loops = [e for e in evs if e.get("type") == "hitl_loop"]
    resumes = [e for e in evs if e.get("type") == "resume_result"]
    questions = [e for e in replies if e.get("kind") in ("clarify", "text")]
    rejects, replanned = _replan_after_reject(evs)
    return {"interrupts": len(from_interrupt) + len(loops), "interrupts_raised": sum(1 for e in evs if e.get("type") == "interrupt_raised"),
            "by_kind": dict(Counter(str(e.get("kind")) for e in from_interrupt)),
            "decisions": dict(Counter(str(e.get("decision")) for e in replies)),
            "resumes": len(resumes), "resume_ok": sum(1 for e in resumes if e.get("status") != "error"), "hitl_loop": bool(loops),
            "questions": len(questions), "necessary": sum(1 for e in questions if e.get("necessary") is True),
            "unnecessary": sum(1 for e in questions if e.get("necessary") is not True),
            "ask_human_unnecessary": sum(1 for e in from_interrupt if e.get("kind") == "clarify" and e.get("necessary") is not True),
            "text_questions": sum(1 for e in replies if e.get("source") == "baseline_text"),
            "ask_human_calls": sum(1 for e in evs if e.get("type") == "tool_call" and e.get("tool") == "ask_human" and e.get("internal") is not True),
            "rejects": rejects, "replan_after_reject": replanned}


def grader_result(run) -> dict:
    """Hình dạng trong scores.jsonl (`graders.hitl`): không `pass`/`score` vì không gating."""
    return {"pass": None, "score": None, "reasons": [], "details": hitl_metrics(run)}


def _ratio(num, den):
    return num / den if den else None


def _details(row: dict, name: str) -> dict:
    return (((row.get("graders") or {}).get(name) or {}).get("details")) or {}


def aggregate(rows) -> dict:
    """Gộp các hàng scores.jsonl (không lỗi hạ tầng) của MỘT hệ/biến thể. Không có hàng nào có `hitl` ⇒ {"hitl": False}."""
    rows = [r for r in rows if r.get("tsr_pass") is not None]
    hs = [_details(r, "hitl") for r in rows if _details(r, "hitl")]
    if not hs:
        return {"hitl": False, "n_runs": len(rows)}
    tot = lambda k: sum(h.get(k) or 0 for h in hs)
    v3 = [_details(r, "process") for r in rows if _details(r, "process").get("v3")]
    interrupts = tot("interrupts")
    kinds: Counter = Counter()
    for h in hs:
        kinds.update(h.get("by_kind") or {})
    tool_calls = sum(d.get("tool_calls") or 0 for d in v3) - tot("ask_human_calls")
    return {"hitl": True, "n_runs": len(rows), "runs_with_interaction": len(hs), "v3_runs": len(v3),
            "interrupts": interrupts, "by_kind": dict(kinds), "resumes": tot("resumes"), "resume_ok": tot("resume_ok"),
            "resume_success": _ratio(tot("resume_ok"), interrupts),
            "tool_calls": tool_calls if v3 else None, "autonomy_ratio": _ratio(tool_calls, tool_calls + interrupts) if v3 else None,
            "text_questions": tot("text_questions"), "interventions_per_task": _ratio(interrupts + tot("text_questions"), len(rows)),
            "questions": tot("questions"), "necessary": tot("necessary"), "ask_human_unnecessary": tot("ask_human_unnecessary"),
            "rejects": tot("rejects"), "replan_after_reject": tot("replan_after_reject"),
            "replan_after_reject_rate": _ratio(tot("replan_after_reject"), tot("rejects")),
            "hitl_loop_runs": sum(1 for h in hs if h.get("hitl_loop"))}


def clarify_aggregate(rows) -> dict:
    """Clarification Precision/Recall gộp (pooled) theo nửa: `missing` (task có mục ẩn bắt buộc) và `complete` (đủ thông tin)."""
    out = {}
    for half, keep in (("missing", lambda d: d.get("required", 0) > 0), ("complete", lambda d: d.get("required", 0) == 0)):
        ds = [d for r in rows if r.get("tsr_pass") is not None for d in [_details(r, "clarify")] if d and keep(d)]
        asked, nec = sum(d["asked"] for d in ds), sum(d["necessary"] for d in ds)
        req, cov = sum(d["required"] for d in ds), sum(len(d["covered"]) for d in ds)
        out[half] = {"runs": len(ds), "asked": asked, "necessary": nec, "unnecessary": asked - nec, "precision": _ratio(nec, asked),
                     "required": req, "covered": cov, "recall": _ratio(cov, req), "guessed": sum(len(d.get("guessed_correctly") or []) for d in ds),
                     "from_interrupt": sum((d.get("asked_from") or {}).get("interrupt", 0) for d in ds),
                     "from_text": sum((d.get("asked_from") or {}).get("baseline_text", 0) for d in ds),
                     "unnecessary_per_run": _ratio(asked - nec, len(ds))}
    return out
