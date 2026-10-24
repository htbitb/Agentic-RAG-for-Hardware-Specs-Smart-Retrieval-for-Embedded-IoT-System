"""conflict_detected (gate với task có `must_detect`, C4; D25): hệ có NÊU CHỦ ĐỘNG các xung đột thiết kế cài sẵn (người dùng không nhắc) hay không.

expected:
  must_detect:                                   # mỗi xung đột kỳ vọng có mã + lượt gây ra (chỉ số 0-based của lượt NGƯỜI DÙNG đưa ra yêu cầu xung đột)
    - {code: "PIN_CONFLICT:PA8", turn: 1}
    - {code: "LEVEL_MISMATCH:1.8V-3.3V", turn: 1}
    - {code: "CLOCK_LIMIT:SYSCLK", turn: 1, from_turn: 1}     # (tuỳ chọn) chỉ tính phát hiện từ lượt from_turn: câu trả lời lượt trước nhắc giới hạn một cách tự nhiên
  must_not:                                      # hành vi không được xảy ra
    - unsafe_connection                          # khuyến nghị nối trực tiếp / không cần level shifter (tuỳ chọn {code: unsafe_connection, pin: PA3} | {rails: [1.8, 3.3]})

Mỗi mục kết quả: `detected` (có câu nêu xung đột ở lượt nào đó), `turn` (lượt đầu tiên nêu), `proactive` (nêu ở lượt gây xung đột HOẶC SỚM HƠN — không tính nếu
chỉ nêu sau khi người dùng đã hỏi trực tiếp ở lượt sau). Chỉ để báo cáo độ nhạy (không dùng để chấm): `proactive_from0` (D25 gốc: tính cả câu nêu ở lượt TRƯỚC lượt gây xung đột, bỏ qua `from_turn`), `proactive_w2` (như `proactive`, cảnh báo được phép nằm ở câu liền sau câu có định danh). Đạt khi mọi mục `proactive` và không vi phạm `must_not`. Nhận diện: eval/graders/conflicts.py (tất định).
Mã lý do: conflict_missed:<họ mã> · conflict_late:<họ mã> · must_not:unsafe_connection.
"""
from __future__ import annotations

from eval.graders import conflicts


def _res(ok: bool, reasons: list[str], details: dict) -> dict:
    return {"pass": ok, "score": 1.0 if ok else 0.0, "reasons": reasons, "details": details}


def must_not_entries(expected: dict) -> list[dict]:
    out = []
    for m in expected.get("must_not", []) or []:
        out.append(m if isinstance(m, dict) else {"code": m})
    return out


def grade(task, run, ctx) -> dict:
    must = task.expected.get("must_detect") or []
    if not must:
        raise ValueError(f"{task.id}: expected.must_detect is required for conflict_detected")
    answers = [t.answer for t in run.turns] or [run.final_answer]
    items, reasons = [], []
    for m in must:
        code, cause, start = m["code"], m["turn"], m.get("from_turn", 0)
        found = next(((i, h) for i, a in enumerate(answers) if i >= start and (h := conflicts.detect(a, code))), None)
        turn, hit = found if found else (None, None)
        # độ nhạy (KHÔNG dùng để chấm): "at_cause" = nêu đúng ở lượt gây xung đột; "proactive_w2" = như `proactive` nhưng cho phép cảnh báo nằm ở câu liền sau câu có định danh
        wide = next((i for i, a in enumerate(answers) if i >= start and conflicts.detect(a, code, window=2)), None)
        item = {"code": code, "cause_turn": cause, "from_turn": start, "detected": found is not None, "turn": turn, "proactive": found is not None and turn <= cause,
                "proactive_from0": any(i <= cause and conflicts.detect(a, code) for i, a in enumerate(answers)),
                "proactive_w2": wide is not None and wide <= cause, "evidence": hit["sentence"][:240] if hit else None}
        items.append(item)
        family = conflicts.parse_code(code)[0]
        if not item["detected"]:
            reasons.append(f"conflict_missed:{family}: {code} was never raised in {len(answers)} turn(s)")
        elif not item["proactive"]:
            reasons.append(f"conflict_late:{family}: {code} was first raised at turn {turn}, after the turn ({cause}) that introduced it")
    violations = []
    for entry in must_not_entries(task.expected):
        if entry["code"] != "unsafe_connection":
            raise ValueError(f"{task.id}: unknown must_not entry {entry['code']!r}")
        for i, a in enumerate(answers):
            hit = conflicts.detect_unsafe_connection(a, pin=entry.get("pin"), rails=entry.get("rails"))
            if hit:
                violations.append({"code": "unsafe_connection", "turn": i, "evidence": hit["sentence"][:240]})
                reasons.append(f"must_not:unsafe_connection: turn {i} advises connecting without level shifting ({hit['cue']!r})")
                break
    details = {"items": items, "must_not": violations, "n_items": len(items), "n_detected": sum(i["detected"] for i in items),
               "n_proactive": sum(i["proactive"] for i in items), "n_proactive_from0": sum(i["proactive_from0"] for i in items), "n_proactive_w2": sum(i["proactive_w2"] for i in items)}
    return _res(not reasons, reasons, details)
