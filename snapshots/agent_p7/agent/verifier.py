"""Verification / reflection gate (plan 4.1; Kong et al. Algorithm 1, lines 6 and 14).

An answer is accepted only if
  V1  every numeric claim (value+unit, normalized) appears in the collected evidence
      (tool observations) or in the user question,
  V2  every hex address/offset appears in the evidence,
  V3  it cites at least one source that was actually returned by a tool ([doc p.N]),
  V4  no field-type confusion: if the user asked for an *operating* value, the
      supporting facts must not all be Absolute-Maximum ratings (paper Sec. 5.5).
Refusals and "insufficient evidence" answers are accepted as-is (safe abstention).
"""
import json
import re

from ingestion.unit_normalizer import find_quantities

HEX = re.compile(r"\b0x[0-9A-Fa-f]{2,8}\b")
CITE = re.compile(r"\[([^\[\]]+?)\s+p\.?\s*(\d+)\]")
ABSTAIN = ("insufficient evidence", "refuse", "cannot verify", "not found in the documentation", "blocked")


def _evidence_numbers(evidence_text: str) -> set[float]:
    """Normalized quantities found in the evidence + every bare number (JSON columns such as
    "max": "3.6" with "unit": "V" are stored separately, and VDD-evaluated values have no unit)."""
    nums = {round(q[2], 12) for q in find_quantities(evidence_text)}
    for v in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", evidence_text):
        nums.add(round(float(v), 12))
    return nums


def _claim_supported(v: float, norm: float, ev_nums: set[float]) -> bool:
    return any(abs(x - e) <= 1e-9 + 1e-6 * abs(e) for x in (v, norm) for e in ev_nums)


def verify(question: str, answer: str, observations: list[dict]) -> dict:
    low = answer.lower()
    if any(a in low for a in ABSTAIN):
        return {"passed": True, "abstained": True, "issues": [], "checked_claims": 0}
    ev_text = json.dumps(observations, ensure_ascii=False) + " " + question
    ev_nums = _evidence_numbers(ev_text)
    ev_low = ev_text.lower()
    issues, checked = [], 0

    for v, unit, norm, base in find_quantities(answer):
        checked += 1
        if not _claim_supported(v, norm, ev_nums):
            issues.append(f"V1 unsupported value: {v} {unit}")
    for h in HEX.findall(answer):
        checked += 1
        if h.lower() not in ev_low and h.lower().replace("0x", "0x0") not in ev_low:
            issues.append(f"V2 unsupported address: {h}")

    cites = CITE.findall(answer)
    if not cites:
        issues.append("V3 no source citation [doc p.N]")
    else:
        spans = [((s["doc"] or "").lower(), s["p0"], s["p1"]) for s in _iter_sources(observations)]
        for doc, page in cites:
            d0, pg = doc.lower().strip(), int(page)
            if not any((d0 in d or d in d0) and p0 <= pg <= p1 for d, p0, p1 in spans if d):
                issues.append(f"V3 citation not returned by any tool: [{doc} p.{page}]")

    wants_operating = re.search(r"\b(operat\w*|recommended|normal|nominal)\b", question, re.I) and \
        not re.search(r"absolute|maximum rating|abs\.? max|damage", question, re.I)
    if wants_operating:
        cats = {s.get("category") for s in _iter_sources(observations) if s.get("category")}
        if cats and cats <= {"absolute_max"}:
            issues.append("V4 field-type confusion: operating value requested but only absolute-max facts used")
    return {"passed": not issues, "abstained": False, "issues": issues, "checked_claims": checked}


def _iter_sources(obj):
    """Yield every dict in the observations that carries a 'doc' key (a citable source)."""
    if isinstance(obj, dict):
        if "doc" in obj:
            p0 = obj.get("page") or obj.get("page_start") or 0
            yield {"doc": obj.get("doc"), "p0": p0, "p1": obj.get("page_end") or p0, "category": obj.get("category")}
        for v in obj.values():
            yield from _iter_sources(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_sources(v)
