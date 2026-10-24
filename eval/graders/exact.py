"""exact: so khớp chính xác một giá trị (địa chỉ, offset, reset, vị trí bit, quyền truy cập, đại lượng)."""
from __future__ import annotations

from eval import markers
import re

from eval.textnorm import (bit_ranges, canonical_access, close, hex_tokens, number_tokens, numeric_after, numeric_tokens_kinds,
                           quantities, _UNITS)

KEYWORDS = {
    "offset": ["offset"],
    "reset": ["reset value", "reset", "default value", "after reset"],
    "width": ["width", "size", "wide"],
}


_OTHER_ATTR = re.compile(r"(reset|offset|mask|default|size|width|length|count)\b[^.;\n]{0,30}$", re.I)
_CLAUSE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n|,\s*(?:but|while|whereas)\s+|\s+(?:but|while|whereas)\s+", re.I)


_LIST_ITEM = re.compile(r"\s*(?:[-*•+]|\d+[.)])\s+")


def _scoped(answer: str, scope) -> str:
    """Chỉ giữ các mệnh đề nhắc tới thuộc đối tượng (field/thanh ghi) đang được hỏi; không có thì dùng cả câu trả lời."""
    if not scope:
        return answer
    rxs = [re.compile(rf"(?<![A-Za-z0-9_]){re.escape(s)}(?![A-Za-z0-9_])", re.I) for s in scope]
    picked, cont = [], False
    for c in _CLAUSE_SPLIT.split(answer):
        if not c or not c.strip():
            continue                                  # dòng trống không cắt mạch liệt kê
        if any(rx.search(c) for rx in rxs):
            picked.append(c)
            cont = c.rstrip(" *`").endswith(":")     # "... field X consists of:" -> các dòng liệt kê ngay sau thuộc cùng claim
        elif cont and _LIST_ITEM.match(c):
            picked.append(c)
        else:
            cont = False
    return " ".join(picked) if picked else answer


def _default_scope(task, kind: str) -> list[str]:
    prov = task.provenance or {}
    names = [prov.get("field")] if kind == "bits" else [prov.get("doc_name"), prov.get("register")]
    return [n for n in names if n]


# review G-4: thanh ghi KHÁC được nêu trong cùng câu ("ADC_CFGR is at offset 0x0C, CFGR2 is at offset 0x10") không được tạo claim
_FINE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n|,\s+|\s+(?:but|while|whereas)\s+", re.I)
_REG_IDENT = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+(?![A-Za-z0-9_])")


def _claim_text(answer: str, scope) -> str:
    """Văn bản để tìm claim offset/reset/width: bỏ mệnh đề chỉ nói về thanh ghi khác (có định danh dạng A_B nhưng không chứa
    tên đối tượng được hỏi). Không bỏ gì thì trả nguyên văn."""
    low = [x.lower() for x in (scope or [])]
    if not low:
        return answer
    parts = [c for c in _FINE_SPLIT.split(answer) if c]
    keep = [c for c in parts if any(x in c.lower() for x in low) or not _REG_IDENT.search(c)]
    return answer if len(keep) == len(parts) or not keep else ". ".join(keep)


# review G-5: dải bit đi kèm 'reserved' ("bits 31:18 are reserved", "Reserved: bits 31:18") không phải claim về field được hỏi
_RANGE = r"(?:\bbits?(?:\s+positions?)?\s*)?(?:\[\s*\d+(?:\s*:\s*\d+)?\s*\]|\d+(?:\s*(?:-|–|\.\.|:|to|through)\s*\d+)?)"
_RES = r"(?:reserved|res\.)"
_RES_AFTER = re.compile(rf"{_RANGE}\s*[:,(\-–]?\s*(?:(?:are|is|as)\s+)?{_RES}", re.I)
_RES_BEFORE = re.compile(rf"\b{_RES}\s*[:,(\-–]?\s*{_RANGE}", re.I)


def _strip_reserved(text: str) -> str:
    return _RES_BEFORE.sub(" ", _RES_AFTER.sub(" ", text))


# D18 (P4): mệnh đề nói về BIT / TRƯỜNG của thanh ghi ("bit 6 is set at reset", "All other bits reset to 0", "reset value of DS[2:0] is 010") không phải claim về
# giá trị reset của CẢ thanh ghi: bỏ khi tìm claim. Giá trị đúng của cả thanh ghi vẫn phải xuất hiện ở đâu đó (ok_vals & toks) nên không nới cho câu trả lời thiếu.
_SUBFIELD = re.compile(r"(?<![A-Za-z0-9_])bits?(?![A-Za-z0-9_])|\[\s*\d+\s*(?::\s*\d+)?\s*\]|(?<![A-Za-z0-9_])fields?(?![A-Za-z0-9_])", re.I)


def _drop_subfield_clauses(text: str) -> str:
    parts = [c for c in _FINE_SPLIT.split(text) if c]
    keep = [c for c in parts if not _SUBFIELD.search(c)]
    return ". ".join(keep)


def _to_int(v) -> int:
    return int(v, 0) if isinstance(v, str) else int(v)


def _result(ok, reasons, **details):
    return {"pass": bool(ok), "score": 1.0 if ok else 0.0, "reasons": reasons, "details": details}


def _grade_numeric(answer, attr, expected, allowed, equivalent=frozenset(), scope=None):
    """`equivalent`: giá trị tương đương `expected` (vd alias địa chỉ ESP32 DPORT/AHB) — được chấp nhận như đáp án."""
    ok_vals = {expected} | set(equivalent)
    toks = set(hex_tokens(answer)) | {int(x) for x in number_tokens(answer) if float(x).is_integer()}
    if attr == "address":
        # hex lớn đứng sau 'reset/offset/mask/...' là giá trị của thuộc tính khác, không phải địa chỉ mâu thuẫn
        addr_like = [int(v) for pos, v, is_hex in numeric_tokens_kinds(answer)
                     if is_hex and v >= 0x1000 and not _OTHER_ATTR.search(answer[max(0, pos - 45):pos])]
        others = {t for t in addr_like if t not in ok_vals and t not in allowed}
        if ok_vals & toks and not others:
            return True, []
        if others:
            return False, [f"wrong_value: conflicting {attr} {', '.join(hex(t) for t in sorted(others))}"]
        return False, [f"missing_value: {attr} {hex(expected)} not found"]
    others = [w for a, ws in KEYWORDS.items() if a != attr for w in ws] + ["base", "address"]
    text = _claim_text(answer, scope)
    if attr == "reset":
        text = _drop_subfield_clauses(text)
    claims = {int(x) for x in numeric_after(text, KEYWORDS.get(attr, [attr]), stop=others) if float(x).is_integer()}
    if claims:
        extra = claims - ok_vals - allowed
        if extra:
            return False, [f"wrong_value: {attr} stated as {', '.join(hex(c) for c in sorted(claims))}, expected {hex(expected)}"]
    if ok_vals & toks:
        return True, []
    return False, [f"missing_value: {attr} {hex(expected)} not found"]


def grade(task, run, ctx) -> dict:
    spec = task.expected.get("exact")
    if not spec or "value" not in spec:
        raise ValueError(f"{task.id}: expected.exact.value is required")
    kind, attr, answer = spec.get("kind", "hex"), spec.get("attribute", "value"), run.final_answer or ""
    allowed = spec.get("allowed", [])

    if kind in ("hex", "int"):
        expected, allow = _to_int(spec["value"]), {_to_int(a) for a in allowed}
        equiv = {_to_int(a) for a in spec.get("equivalent", [])}
        ok, reasons = _grade_numeric(answer, attr, expected, allow, equiv, spec.get("scope") or _default_scope(task, kind))
    elif kind == "bits":
        lo, hi = sorted(int(x) for x in spec["value"])
        scope = spec.get("scope") or _default_scope(task, "bits")
        found, allow = bit_ranges(_strip_reserved(_scoped(answer, scope))), {tuple(sorted(a)) for a in allowed}
        extra = found - {(lo, hi)} - allow
        ok = (lo, hi) in found and not extra
        reasons = [] if ok else ([f"wrong_value: bit range(s) {sorted(extra)} instead of [{hi}:{lo}]"] if extra
                                 else [f"missing_value: bit range [{hi}:{lo}] not found"])
    elif kind == "access":
        scope = spec.get("scope") or _default_scope(task, "access")
        found = canonical_access(_scoped(answer, scope))
        ok = found == {str(spec["value"]).lower()}
        reasons = [] if ok else ([f"wrong_value: access {sorted(found)} instead of {spec['value']}"] if found
                                 else [f"missing_value: access {spec['value']} not found"])
    elif kind == "quantity":
        scale, base = _UNITS[str(spec["unit"]).lower()]
        want = float(spec["value"]) * scale
        tol = float(spec.get("tol_pct", 0.0)) / 100.0
        same = [q for q in quantities(answer) if q[3] == base]
        ok = any(close(q[2], want, rel=max(tol, 1e-6)) for q in same)
        reasons = [] if ok else ([f"wrong_value: {attr} given as {sorted({q[0] for q in same})} {spec['unit']}-class values"] if same
                                 else [f"missing_value: {attr} {spec['value']} {spec['unit']} not found"])
    else:
        raise ValueError(f"{task.id}: unknown exact kind {kind!r}")

    if not ok and markers.is_abstention(answer):
        reasons.append("abstained: the system declined to give a value")
    return _result(ok, reasons, attribute=attr, kind=kind)
