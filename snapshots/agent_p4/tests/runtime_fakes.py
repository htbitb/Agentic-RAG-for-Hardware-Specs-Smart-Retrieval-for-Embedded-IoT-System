"""Gate giả (thỏa giao diện của plan/P4_interfaces.md §2) và tiện ích dựng runtime cho test vòng lặp — không phụ thuộc cài đặt Gate thật."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeFinding:
    code: str
    gate: str = "G2"
    severity: str = "error"
    kind: str = "local"
    where: str = "requirement R1"
    expected: str = "20000 Hz"
    actual: str = "19000 Hz"
    hint_source: str = "solve_timer_config"
    waivable: bool = False

    def to_dict(self):
        return dict(self.__dict__)


@dataclass
class FakeReport:
    findings: list = field(default_factory=list)
    gates: dict = field(default_factory=lambda: {"G1": "pass", "G2": "pass", "G3": "na", "G4": "pass", "G5": "skipped"})
    sim: dict | None = None
    details: dict = field(default_factory=dict)

    @property
    def passed(self):
        return not any(f.severity == "error" for f in self.findings)

    def errors(self):
        return [f for f in self.findings if f.severity == "error"]

    def failed_codes(self):
        out = []
        for f in self.errors():
            if f.code not in out:
                out.append(f.code)
        return out

    def feedback(self):
        return {"passed": self.passed, "gates": self.gates, "findings": [f.to_dict() for f in self.findings if f.severity != "warning"][:8],
                "hint": "fix the findings"}

    def to_dict(self):
        return {"passed": self.passed, "gates": self.gates, "findings": [f.to_dict() for f in self.findings], "sim": self.sim, "details": self.details}


def fail(*codes, kind="local", gate="G2", **kw):
    gates = {"G1": "pass", "G2": "pass", "G3": "na", "G4": "pass", "G5": "skipped"}
    gates[gate] = "fail"
    return FakeReport([FakeFinding(c, gate=gate, kind=kind, **kw) for c in codes], gates)


def ok():
    return FakeReport()


class FakeGate:
    """Trả lần lượt các báo cáo trong `reports` (báo cáo cuối được lặp lại mãi); ghi lại mọi GateContext nhận được."""

    def __init__(self, reports=None):
        self.reports = list(reports or [ok()])
        self.contexts = []

    def run(self, ctx):
        self.contexts.append(ctx)
        i = min(len(self.contexts) - 1, len(self.reports) - 1)
        r = self.reports[i]
        return r(ctx) if callable(r) else r
