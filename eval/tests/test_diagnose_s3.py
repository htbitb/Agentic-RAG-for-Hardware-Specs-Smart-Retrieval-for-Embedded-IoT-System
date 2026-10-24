"""eval.tools.diagnose_s3: gán mỗi run S3 thất bại vào một nhóm lỗi dựa trên trace (brief P4 bước 7.6); nhóm "Gate cho qua nhưng grader trượt" là rủi ro tự chấm (D19)."""
from eval.tools.diagnose_s3 import GROUPS, classify, diagnose, render


def ev(type_, turn=0, seq=0, **kw):
    return {"type": type_, "turn": turn, "seq": seq, "run_id": "r", **kw}


def run(trace, tsr=False, codes=("wrong_freq",), reasons=("wrong_freq: x",), errors=()):
    return {"system": "S3@P4", "variant": "", "task_id": "C3-001", "seed": 0, "category": "C3", "infra": False, "tsr_pass": tsr, "fail_codes": list(codes),
            "errors": list(errors), "graders": {"functional_sim": {"pass": tsr, "reasons": list(reasons)}}, "trace": trace}


GATE_OK = ev("gate_result", gates={"G2": "pass"}, passed=True, findings=[], seq=5)
FIN_OK = ev("finish", accepted=True, implicit=False, seq=6)


def test_an_accepted_final_answer_that_the_independent_grader_fails_is_the_self_grading_risk():
    c = classify(run([ev("run_started"), GATE_OK, FIN_OK, ev("done", status="answered", seq=7)]))
    assert c["group"] == "gate_pass_grader_fail" and c["group"] in GROUPS


def test_escalation_after_gate_rejections_is_a_correct_block_that_ran_out_of_budget():
    tr = [ev("run_started"), ev("gate_result", passed=False, gates={"G2": "fail"}, findings=[{"code": "G2-FREQ", "severity": "error", "gate": "G2", "kind": "local", "where": "requirement R1"}], seq=4),
          ev("finish", accepted=False, seq=5), ev("escalated", reason="budget:steps", seq=6), ev("done", status="escalated", seq=7)]
    c = classify(run(tr))
    assert c["group"] == "gate_blocked_budget" and "G2-FREQ" in c["detail"]


def test_escalation_before_any_draft_is_other():
    tr = [ev("run_started"), ev("escalated", reason="budget:tokens", seq=4), ev("done", status="escalated", seq=5)]
    assert classify(run(tr))["group"] == "other"


def test_unmodeled_effects_are_their_own_group():
    tr = [ev("run_started"), ev("gate_result", passed=True, gates={"G2": "skipped"}, findings=[{"code": "G2-UNMODELED", "severity": "warning", "gate": "G2", "kind": "local", "where": "x"}], seq=4),
          FIN_OK]
    assert classify(run(tr, codes=("unmodeled",), reasons=("unmodeled: x",)))["group"] == "simulator_unmodeled"


def test_the_hardware_guardrail_refusal_is_other_not_a_gate_matter():
    tr = [ev("run_started"), ev("guardrail", stage="hardware_safety", blocked=True, seq=2), ev("refused", seq=3), ev("done", status="refused", seq=4)]
    c = classify(run(tr, codes=("over_refusal",), reasons=("over_refusal",)))
    assert c["group"] == "other" and "guardrail" in c["detail"]


def test_many_unrecovered_tool_errors_point_at_wrong_tool_use():
    tr = [ev("run_started")] + [ev("tool_call", tool="get_register_bitfields", ok=False, error="No register", internal=False, seq=i + 2) for i in range(6)] + \
         [ev("finish", accepted=False, seq=20), ev("escalated", reason="budget:steps", seq=21)]
    assert classify(run(tr))["group"] == "wrong_tool"


def test_only_the_last_turn_decides_in_a_multi_turn_run():
    tr = [ev("run_started", turn=0), ev("escalated", turn=0, reason="budget:tokens", seq=3), ev("done", turn=0, status="escalated", seq=4),
          ev("run_started", turn=1), GATE_OK | {"turn": 1}, FIN_OK | {"turn": 1}, ev("done", turn=1, status="answered", seq=9)]
    assert classify(run(tr))["group"] == "gate_pass_grader_fail"


def test_diagnose_skips_passing_and_infra_runs_and_renders_a_table():
    rows = [run([ev("run_started"), GATE_OK, FIN_OK], tsr=True), {**run([]), "infra": True, "tsr_pass": None}, run([ev("run_started"), GATE_OK, FIN_OK])]
    d = diagnose(rows)
    assert len(d["runs"]) == 1 and d["counts"] == {"gate_pass_grader_fail": 1}
    md = render(d)
    assert "Gate cho qua nhưng grader trượt" in md and "C3-001" in md
