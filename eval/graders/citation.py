"""citation: trích dẫn hợp lệ khi doc_id ánh xạ được qua manifest VÀ text trang chứa giá trị được trích.

* S1: dùng `sources` (metadata truy hồi, số trang đã là chỉ số PDF 1-based).
* S0/S2: phân tích `[doc p.N]` trong câu trả lời; số trang in + page_offset = chỉ số PDF.
* doc không có PDF thật (file: null) -> `unverifiable`, đếm riêng, không vào Citation Precision.
Là chỉ số báo cáo, không phải điều kiện pass của TSR.
"""
from __future__ import annotations

import re

from eval.graders.common import fact_present

_GROUP = re.compile(r"[\[(]([^\[\]()]{2,200})[\])]")
_PART = re.compile(r"^\s*(.+?)[,\s]+(?:pp?|pages?)\.?\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*$", re.I)
_SINGLE_TOKEN = re.compile(r"^(?=[A-Za-z0-9_.\-]*[0-9_])[A-Za-z0-9_.\-]+$")   # giống doc_id: có chữ số hoặc dấu _


def extract_citations(text: str, ctx) -> list[dict]:
    out = []
    for g in _GROUP.finditer(text or ""):
        for part in g.group(1).split(";"):
            m = _PART.match(part)
            if not m:
                continue
            phrase, lo = m.group(1).strip(), int(m.group(2))
            hi = int(m.group(3)) if m.group(3) else lo
            entry = ctx.resolve_doc(phrase)
            if entry is None and not _SINGLE_TOKEN.match(phrase):
                continue                     # '(see Table 5, p.12)' không phải trích dẫn tài liệu
            out.append({"phrase": phrase, "doc_id": entry["doc_id"] if entry else None, "lo": lo, "hi": max(lo, hi)})
    return out


def task_facts(task) -> list[dict]:
    e = task.expected
    if e.get("cite_values"):
        return [{"value": v, "kind": "text"} if isinstance(v, str) and not v.lower().startswith("0x") else {"value": v}
                for v in e["cite_values"]]
    facts = []
    ex = e.get("exact")
    if ex and ex.get("kind", "hex") in ("hex", "int"):
        facts.append({"value": ex["value"], "kind": "hex"})
    elif ex and ex.get("kind") == "quantity":
        facts.append({"value": ex["value"], "unit": ex["unit"], "tol_pct": ex.get("tol_pct", 0)})
    facts += list(e.get("keyfacts", []))
    return facts


def _check(entry, lo, hi, ctx, facts, offset_applies: bool) -> tuple[str, str]:
    if not entry.get("file"):
        return "unverifiable", "doc has no real PDF"
    offset = (entry.get("page_offset") or 0) if offset_applies else 0
    n_pages = entry.get("pages") or 0
    pdf_pages = [p + offset for p in range(lo, hi + 1)]
    if any(not (1 <= p <= n_pages) for p in pdf_pages):
        return "invalid", f"page_out_of_range: p.{lo}-{hi} of {n_pages}"
    if not facts:
        return "unverifiable", "no checkable value in task"
    for p in pdf_pages:
        text = ctx.page_text(entry["doc_id"], p)
        if text is not None and any(fact_present(text, f) for f in facts):
            return "valid", ""
    return "invalid", "citation_unsupported: cited page does not contain the expected value"


def grade(task, run, ctx) -> dict:
    facts = task_facts(task)
    sources = run.sources()
    from_sources = bool(sources)
    if from_sources:
        cites = []
        for s in sources:
            entry = ctx.entry(s.get("doc_id", "")) or ctx.resolve_doc(s.get("file", ""))
            cites.append({"phrase": s.get("doc_id") or s.get("file", "?"), "doc_id": entry["doc_id"] if entry else None,
                          "lo": int(s["page"]), "hi": int(s["page"])})
    else:
        cites = extract_citations(run.final_answer or "", ctx)

    counts = {"valid": 0, "invalid": 0, "unverifiable": 0}
    reasons, per = [], []
    for c in cites:
        entry = ctx.entry(c["doc_id"]) if c["doc_id"] else None
        if entry is None:
            status, why = "invalid", f"unknown_doc: {c['phrase']}"
        else:
            status, why = _check(entry, c["lo"], c["hi"], ctx, facts, offset_applies=not from_sources)
        counts[status] += 1
        per.append({"doc": c["phrase"], "pages": [c["lo"], c["hi"]], "status": status})
        if status == "invalid":
            reasons.append(why if why.startswith(("unknown_doc", "citation_unsupported")) else f"citation_invalid: {why}")
    verifiable = counts["valid"] + counts["invalid"]
    precision = counts["valid"] / verifiable if verifiable else None
    retrieval_hit = counts["valid"] > 0
    if from_sources and not retrieval_hit and facts:
        reasons.append("retrieval_miss: no retrieved page contains the expected value")
    details = {**counts, "n_citations": len(cites), "precision": precision, "per_citation": per,
               "source": "sources" if from_sources else "answer", "retrieval_hit": retrieval_hit}
    return {"pass": counts["valid"] >= 1 and counts["invalid"] == 0, "score": precision if precision is not None else 0.0,
            "reasons": reasons, "details": details}
