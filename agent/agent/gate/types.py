"""Kiểu dữ liệu của Gate v2 (P4_interfaces §2.1): Finding (phản hồi có kiểu) và GateReport.

severity: error (chặn) | warning (không chặn) | unknown (không kiểm được — KHÔNG chặn nhưng KHÔNG BAO GIỜ được tính là pass).
kind: local (agent tự sửa) | structural (runtime chèn REPLAN_REQUIRED).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

FEEDBACK_MAX = 8
_REQ_REF = re.compile(r'^requirement (?:"((?:[^"\\]|\\.)*)"|(\S+))')


def requirement_ref(rid) -> str:
    """`where` của finding gắn với requirement: 'requirement R1', hoặc 'requirement "PWM PA8"' (JSON) khi id có khoảng trắng / dấu nháy."""
    s = str(rid)
    return f"requirement {s}" if s and not re.search(r'[\s"]', s) else f"requirement {json.dumps(s, ensure_ascii=False)}"


def requirement_id(where: str) -> str | None:
    m = _REQ_REF.match(where or "")
    if not m:
        return None
    return json.loads(f'"{m.group(1)}"') if m.group(1) is not None else m.group(2)


def tool_error(result) -> str | None:
    """Thông điệp lỗi nếu lời gọi tool thất bại (`{"error": ...}` của ToolHub/hw-sandbox, `{"ok": false, "error": {...}}` của board-state), ngược lại None."""
    if not isinstance(result, dict):
        return f"unexpected result type {type(result).__name__}"
    err = result.get("error")
    if err is None or result.get("ok") is True:
        return None
    if isinstance(err, dict):
        return f"{err.get('code', 'ERROR')}: {err.get('message', '')}".strip()
    return str(err)


@dataclass(frozen=True)
class Finding:
    gate: str
    code: str
    where: str
    expected: str
    actual: str
    hint_source: str
    severity: str = "error"
    kind: str = "local"
    waivable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateReport:
    gates: dict[str, str]
    findings: list[Finding]
    sim: dict | None = None
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.errors() and "fail" not in self.gates.values()

    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    def failed_codes(self) -> list[str]:
        return list(dict.fromkeys(f.code for f in self.errors()))

    def to_dict(self) -> dict:
        return {"passed": self.passed, "gates": dict(self.gates), "findings": [f.to_dict() for f in self.findings], "sim": self.sim,
                "details": self.details, "failed_codes": self.failed_codes()}

    def feedback(self) -> dict:
        shown = (self.errors() + [f for f in self.findings if f.severity == "unknown"])[:FEEDBACK_MAX]
        return {"passed": self.passed, "gates": dict(self.gates), "findings": [f.to_dict() for f in shown], "hint": self._hint()}

    def _hint(self) -> str:
        errors = self.errors()
        if not errors and "fail" not in self.gates.values():
            unverified = [g for g, s in self.gates.items() if s == "skipped"]
            return "All enabled gates passed." + (f" Not verified (skipped, never counted as a pass): {', '.join(unverified)}." if unverified else "")
        parts = [f"The answer was rejected by the finish gate ({len(errors)} error(s): {', '.join(self.failed_codes())}). "
                 "Fix each finding using its hint_source, then finish again."]
        if any(f.kind == "structural" for f in errors):
            parts.append("Some errors are structural: revise the plan with update_plan before acting again.")
        if any(f.waivable for f in errors):
            parts.append("Errors marked waivable may be waived only when the requirement truly cannot be verified: "
                         "finish(waived_requirements=[{\"id\": <requirement id>, \"reason\": <why>}]).")
        return " ".join(parts)
