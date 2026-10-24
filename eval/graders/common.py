"""Hàm dùng chung cho graders: so khớp một 'fact' trong văn bản câu trả lời."""
from __future__ import annotations

import re

from eval.textnorm import _UNITS, close, hex_tokens, number_tokens, numeric_tokens_kinds, quantities


def norm_text(s: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    t = re.sub(r"\baf0+(\d)", r"af\1", t)           # AF02 == AF2
    return " " + t + " "


_REF_PREFIX = re.compile(r"(table|figure|fig\.?|section|chapter|page|pages|p\.|pp\.|note|step|rev|revision|version|v)\s*$", re.I)


def fact_kind(fact: dict) -> str:
    if fact.get("kind"):
        return fact["kind"]
    v = fact.get("value")
    if fact.get("unit"):
        return "quantity"
    if isinstance(v, str) and v.lower().startswith("0x"):
        return "hex"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return "number"
    return "text"


def fact_present(answer: str, fact: dict) -> bool:
    kind, v = fact_kind(fact), fact.get("value")
    if kind == "text":
        hay = norm_text(answer)
        return any(norm_text(c) in hay for c in [str(v), *fact.get("aliases", [])])
    if kind == "hex":
        want = int(v, 0) if isinstance(v, str) else int(v)
        return want in hex_tokens(answer) or float(want) in number_tokens(answer)
    tol = max(float(fact.get("tol_pct", 0.0)) / 100.0, 1e-9)
    if kind == "number":
        # bỏ số đứng sau 'Table/Section/Figure/page...' (số hiệu tham chiếu, không phải giá trị)
        vals = [x for pos, x, is_hex in numeric_tokens_kinds(answer)
                if is_hex or not _REF_PREFIX.search(answer[max(0, pos - 14):pos])]
        return any(close(x, float(v), rel=tol) for x in vals)
    if kind == "quantity":
        scale, base = _UNITS[str(fact["unit"]).lower()]
        want = float(v) * scale
        return any(q[3] == base and close(q[2], want, rel=tol) for q in quantities(answer))
    raise ValueError(f"unknown fact kind {kind!r}")


def fact_label(fact: dict) -> str:
    return f"{fact.get('attribute', '?')}={fact.get('value')}{(' ' + fact['unit']) if fact.get('unit') else ''}"
