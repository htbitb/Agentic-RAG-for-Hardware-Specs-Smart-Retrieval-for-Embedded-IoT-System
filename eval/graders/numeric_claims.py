"""numeric_claims: mọi (giá trị, đơn vị) và hex trong câu trả lời phải truy được về ground truth của task.

Chỉ số báo cáo (Hallucination Rate), KHÔNG phải điều kiện pass của TSR. Giới hạn: tập 'hỗ trợ' là
ground truth + số trong câu hỏi + expected.numeric_support, nên giá trị đúng nhưng ngoài tập này vẫn bị tính
unsupported (cận trên của hallucination).
"""
from __future__ import annotations

from eval.textnorm import _UNITS, close, hex_tokens, quantities


def _support(task) -> tuple[set[int], list[tuple[str, float]]]:
    ints: set[int] = set()
    qtys: list[tuple[str, float]] = []

    def add(item):
        if isinstance(item, dict):
            v, unit = item.get("value"), item.get("unit")
            if unit:
                scale, base = _UNITS[str(unit).lower()]
                qtys.append((base, float(v) * scale))
            elif v is not None:
                add(v)
        elif isinstance(item, str):
            if item.lower().startswith("0x"):
                ints.update(hex_tokens(item))
            else:
                try:
                    add(float(item))
                except ValueError:
                    pass
        elif isinstance(item, (int, float)) and not isinstance(item, bool) and float(item).is_integer():
            ints.add(int(item))

    e = task.expected
    if "exact" in e:
        add(e["exact"].get("value") if e["exact"].get("kind") != "quantity" else
            {"value": e["exact"]["value"], "unit": e["exact"]["unit"]})
        for a in e["exact"].get("allowed", []):
            add(a)
    for f in e.get("keyfacts", []):
        add({"value": f.get("value"), "unit": f.get("unit")} if f.get("unit") else f.get("value"))
    for s in e.get("numeric_support", []):
        add(s)
    question = " ".join(t.get("user", "") for t in task.turns)
    ints.update(hex_tokens(question))
    for _, _, si, base in quantities(question):
        qtys.append((base, si))
    return ints, qtys


def grade(task, run, ctx) -> dict:
    ints, qtys = _support(task)
    answer = run.final_answer or ""
    unsupported, total = [], 0
    for val, unit, si, base in quantities(answer):
        total += 1
        if not any(b == base and close(si, s, rel=1e-3) for b, s in qtys):
            unsupported.append(f"{val:g} {unit}")
    for h in hex_tokens(answer):
        total += 1
        if h not in ints:
            unsupported.append(f"0x{h:x}")
    score = 1.0 - len(unsupported) / total if total else 1.0
    reasons = [f"unsupported_claim: {u}" for u in unsupported]
    return {"pass": not unsupported, "score": score, "reasons": reasons,
            "details": {"claims": total, "unsupported": unsupported}}
