"""keyfacts: mọi fact bắt buộc phải xuất hiện; fact cấm (giá trị sai phổ biến) là hallucination."""
from __future__ import annotations

from eval import markers
from eval.graders.common import fact_label, fact_present


def grade(task, run, ctx) -> dict:
    facts = task.expected.get("keyfacts")
    if not facts:
        raise ValueError(f"{task.id}: expected.keyfacts is required")
    forbidden = task.expected.get("forbidden", [])
    answer = run.final_answer or ""

    found = [f for f in facts if fact_present(answer, f)]
    missing = [f for f in facts if f not in found]
    bad = [f for f in forbidden if fact_present(answer, f)]
    tp, fn, fp = len(found), len(missing), len(bad)
    recall = tp / len(facts)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    reasons = [f"missing_fact: {fact_label(f)}" for f in missing]
    reasons += [f"hallucinated_value: {fact_label(f)}" for f in bad]
    if missing and markers.is_abstention(answer):
        reasons.append("abstained: the system declined to answer")
    return {"pass": fn == 0 and fp == 0, "score": f1, "reasons": reasons,
            "details": {"tp": tp, "fn": fn, "fp": fp, "precision": precision, "recall": recall,
                        "hallucination": fp > 0}}
