"""Bản tóm tắt dễ đọc của một run (dùng cho demo D1 trong báo cáo) dựng từ sự kiện trace chuẩn hoá."""
from agent.runtime.summary import render_summary


def ev(seq, type_, **kw):
    return {"type": type_, "run_id": "r1", "turn": 0, "step": kw.pop("step", 0), "seq": seq, "ts": 1.0, **kw}


EVENTS = [
    ev(1, "run_started", goal="PWM 20 kHz on PA8", project_id="p", ablations=[], budgets={}),
    ev(2, "plan_updated", step=1, rationale="initial", diff={"added": ["s1: record requirement", "s2: simulate"], "removed": [], "changed": []}, plan=[], after_replan=False),
    ev(3, "tool_call", step=2, tool="set_requirements", server="board-state", permission="state-mutating", args="{}", ok=True, error=None, summary="{}", internal=False),
    ev(4, "sim_result", step=3, tool="simulate_register_writes", source="agent", **{"pass": False}, violations=["SIM-TIM-MOE"], effects=[], unmodeled=[], artifact="sim#1"),
    ev(5, "plan_updated", step=4, rationale="MOE missing", diff={"added": ["s2b: set BDTR.MOE"], "removed": [], "changed": []}, plan=[], after_replan=False),
    ev(6, "sim_result", step=5, tool="simulate_register_writes", source="agent", **{"pass": True}, violations=[], effects=[{"pin": "PA8", "pwm_hz": 20000.0, "duty_pct": 25.0}], unmodeled=[], artifact="sim#2"),
    ev(7, "gate_result", step=6, trigger="finish", attempt=1, gates={"G1": "pass", "G2": "pass", "G3": "pass", "G4": "pass", "G5": "pass"}, passed=True, artifact="draft#1", findings=[]),
    ev(8, "finish", step=6, implicit=False, accepted=True, gate={"G1": "pass", "G2": "pass"}, waived=[], attempt=1),
    ev(9, "done", step=6, status="answered", answer_chars=120),
]


def test_summary_tells_the_story_of_a_self_correction():
    md = render_summary([{"question": "PWM 20 kHz on PA8", "answer": "Here is the code.", "status": "answered", "events": EVENTS,
                          "usage": {"llm_calls": 6, "tool_calls": 4, "tokens_in": 1000, "tokens_out": 100, "usd": 0.001, "steps": 6}, "turn": 0}], title="D1")
    assert md.startswith("# D1")
    assert "SIM-TIM-MOE" in md and "s2b: set BDTR.MOE" in md and "20000" in md
    assert md.index("SIM-TIM-MOE") < md.index("s2b: set BDTR.MOE") < md.index("pwm_hz")
    assert "Self-correction" in md and "simulation failed" in md.lower()
    assert "Here is the code." in md and "G1" in md


def test_summary_reports_an_honest_first_try_success():
    ok_events = [e for e in EVENTS if e["type"] not in ("plan_updated",) and not (e["type"] == "sim_result" and not e["pass"])]
    md = render_summary([{"question": "q", "answer": "a", "status": "answered", "events": ok_events, "usage": {}, "turn": 0}], title="D1")
    assert "No check failed before the final answer" in md


def test_a_failure_after_an_early_pass_that_is_later_fixed_is_still_a_self_correction():
    """Chuỗi kiểm tra: mô phỏng của agent PASS, Gate trượt, Gate lần sau PASS (đúng diễn biến của demo D1 run 1)."""
    evs = [ev(1, "run_started", goal="g", project_id="p", ablations=[], budgets={}),
           ev(2, "sim_result", tool="simulate_register_writes", source="agent", **{"pass": True}, violations=[], effects=[], unmodeled=[], artifact="sim#1"),
           ev(3, "gate_result", trigger="finish", attempt=1, gates={"G2": "fail"}, passed=False, artifact="draft#1", findings=[{"gate": "G2", "code": "G2-SIM-FLASH-WS", "severity": "error", "kind": "local", "where": "x"}]),
           ev(4, "gate_result", trigger="finish", attempt=2, gates={"G2": "pass"}, passed=True, artifact="draft#2", findings=[])]
    md = render_summary([{"question": "q", "answer": "a", "status": "answered", "events": evs, "usage": {}, "turn": 0}])
    assert "Self-correction" in md and "did not pass" not in md and "1 failing check" in md


def test_a_run_that_ends_on_a_failing_check_says_so():
    evs = [ev(1, "gate_result", trigger="finish", attempt=1, gates={"G2": "fail"}, passed=False, artifact="draft#1", findings=[])]
    md = render_summary([{"question": "q", "answer": "a", "status": "escalated", "events": evs, "usage": {}, "turn": 0}])
    assert "last check did not pass" in md
