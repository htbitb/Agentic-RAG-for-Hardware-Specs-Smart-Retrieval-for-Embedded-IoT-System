"""clarify (C5, KHÔNG gate — plan/P5_interfaces.md §3, §5): hệ có hỏi lại đúng thông tin ẩn bắt buộc không, và hỏi thừa bao nhiêu.

Tính từ sự kiện `human_reply` trong `run.trace` (runner ghi cho MỌI hệ: interrupt `clarify` của S3, câu hỏi văn bản của baseline). Chỉ các sự kiện
`kind` ∈ {clarify, text} là câu hỏi làm rõ; `choice`/`approval` không tính. Run không có sự kiện nào ⇒ mọi số đếm 0, precision None.
  asked          = số câu hỏi làm rõ;  necessary = số câu có `necessary=True` (khớp mục ẩn còn chưa được trả lời — SimulatedHuman quyết định)
  precision      = necessary / asked (None khi asked = 0);  unnecessary = asked − necessary
  required       = số mục hidden_info bắt buộc;  covered = mục bắt buộc nằm trong `matched` của ít nhất một câu hỏi;  missed = phần còn lại
  recall         = |covered| / required (None khi task không có mục bắt buộc — task đủ thông tin chỉ báo số câu hỏi thừa)
  guessed_correctly = mục ẩn KHÔNG được hỏi mà câu trả lời cuối vẫn khớp `value_patterns` (đoán trùng; báo riêng, không gate)
  asked_from     = {"interrupt": n, "baseline_text": n}
"""
from __future__ import annotations

import re

QUESTION_KINDS = ("clarify", "text")


def human_replies(trace) -> list[dict]:
    return [e for e in (trace or []) if isinstance(e, dict) and e.get("type") == "human_reply"]


def grade(task, run, ctx) -> dict:
    questions = [e for e in human_replies(run.trace) if e.get("kind") in QUESTION_KINDS]
    asked = len(questions)
    necessary = sum(1 for e in questions if e.get("necessary") is True)
    hidden = [h for h in task.hidden_info or [] if isinstance(h, dict)]
    required = [h["id"] for h in hidden if h.get("required", True)]
    asked_ids = {i for e in questions for i in (e.get("matched") or [])}
    covered = [i for i in required if i in asked_ids]
    final = run.final_answer or ""
    guessed = [h["id"] for h in hidden if h["id"] not in asked_ids and any(re.search(p, final, re.I) for p in h.get("value_patterns") or [])]
    details = {"precision": necessary / asked if asked else None, "recall": len(covered) / len(required) if required else None,
               "asked": asked, "necessary": necessary, "required": len(required), "covered": covered,
               "missed": [i for i in required if i not in covered], "unnecessary": asked - necessary, "guessed_correctly": guessed,
               "asked_from": {"interrupt": sum(1 for e in questions if e.get("source") == "interrupt"),
                              "baseline_text": sum(1 for e in questions if e.get("source") == "baseline_text")}}
    return {"pass": True, "score": None, "reasons": [], "details": details}
