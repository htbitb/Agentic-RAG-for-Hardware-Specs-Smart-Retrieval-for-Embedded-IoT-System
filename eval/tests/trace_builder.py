"""Dựng trace v3 phẳng cho test (mỗi lượt có run_id riêng, `seq` tăng dần trong lượt — như runtime thật)."""
from eval.schema import RunResult


class Tr:
    """Dựng trace phẳng: mỗi lượt có run_id riêng và `seq` tăng dần trong lượt (như runtime thật)."""

    def __init__(self):
        self.events, self._seq, self.turn = [], {}, 0

    def at(self, turn):
        self.turn = turn
        return self

    def add(self, type_, **kw):
        seq = self._seq.get(self.turn, 0)
        self._seq[self.turn] = seq + 1
        self.events.append({"type": type_, "run_id": f"run{self.turn}", "turn": self.turn, "step": 0, "seq": seq, "ts": 0.0, **kw})
        return self

    def start(self):
        return self.add("run_started", goal="g", project_id="p", ablations=[], budgets=None)

    def sim(self, ok, artifact="draft#1", source="agent"):
        return self.add("sim_result", tool="simulate_register_writes" if source == "agent" else "gate", source=source, **{"pass": ok},
                        violations=[] if ok else ["SIM-TIM-MOE"], effects=[], unmodeled=[], artifact=artifact)

    def gate(self, ok, codes=(), trigger="finish", attempt=1, sev="error"):
        findings = [{"gate": c.split("-")[0], "code": c, "severity": sev, "kind": "local", "where": "answer"} for c in codes]
        return self.add("gate_result", trigger=trigger, attempt=attempt, gates={"G1": "pass"}, findings=findings, passed=ok, artifact="draft#1")

    def finish(self, accepted, implicit=False, attempt=1):
        return self.add("finish", implicit=implicit, accepted=accepted, gate={"G1": "pass"}, waived=[], attempt=attempt)

    def plan(self):
        return self.add("plan_updated", rationale="r", diff={"added": ["s"], "removed": [], "changed": []}, plan=[])

    def tool(self, tool="get_register_bitfields", args=None, internal=False):
        return self.add("tool_call", tool=tool, server="s", permission="read", args=args if args is not None else {"chip": "stm32g474"},
                        ok=True, error=None, summary="", security_flags=[], internal=internal)

    def replan(self, code="DRC-PIN-01"):
        return self.add("replan_required", reason="structural", code=code)

    def escalated(self):
        return self.add("escalated", reason="budget:steps", code="BUDGET", unmet_requirements=["R1"], tried=[])

    def done(self, status="answered"):
        return self.add("done", status=status, answer_chars=10)

    def run(self, tsr=None):
        return RunResult(system="S3@P4", variant="", task_id="C3-001", seed=0, trace=self.events), tsr
