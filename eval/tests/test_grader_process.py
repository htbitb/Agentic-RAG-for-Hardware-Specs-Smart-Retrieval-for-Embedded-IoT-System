"""Grader `process` (P4, chỉ báo cáo, KHÔNG gating): chỉ số quá trình tính trên trace v3 phẳng (plan/P4_interfaces.md §4–§5)."""
import random

from eval.graders import process
from eval.schema import RunResult
from eval.tests.trace_builder import Tr


def metrics(tr, tsr=True):
    r, _ = tr.run()
    return process.process_metrics(r, tsr)


# ------------------------------------------------------------------ nhận diện trace v3
def test_a_run_without_run_started_is_not_v3_and_has_no_metrics():
    r = RunResult(system="S2D", variant="", task_id="C3-001", seed=0, trace=[{"type": "agent_trace", "turn": 0, "events": []},
                                                                           {"type": "tool_call", "turn": 0, "tool": "x"}])
    assert process.process_metrics(r, True) == {"v3": False}
    assert process.process_metrics(RunResult(system="S0", variant="", task_id="T", seed=0), None) == {"v3": False}
    assert process.is_v3(r.trace) is False


def test_any_run_started_event_makes_the_trace_v3():
    tr = Tr().start().done()
    assert process.is_v3(tr.events) is True


# ------------------------------------------------------------------ Self-Correction + Mean Repair Iterations
def test_d1_style_run_sim_fails_then_plan_is_updated_then_sim_passes_is_a_self_correction():
    tr = (Tr().start().plan().tool().sim(False, "draft#1").plan().sim(True, "draft#2").gate(True).finish(True).done())
    m = metrics(tr, tsr=True)
    assert m["v3"] is True and m["checks"] == "FPP" and m["has_product"] is True
    assert m["first_failed"] is True and m["self_corrected"] is True and m["repair_iterations"] == 1
    assert m["tsr_pass"] is True
    assert m["plan_updated"] == 2 and m["plan_updated_after_trigger"] == 0     # sim fail của agent không phải tín hiệu replan theo §5
    assert m["finish_total"] == 1 and m["finish_rejected"] == 0 and m["escalated_turns"] == 0 and m["ended_escalated"] is False


def test_self_correction_is_measured_against_the_agents_own_gate_and_the_independent_grader_is_kept_beside_it():
    tr = Tr().start().sim(False).sim(True, "draft#2").gate(True).finish(True).done()
    assert metrics(tr, tsr=False)["self_corrected"] is True and metrics(tr, tsr=False)["tsr_pass"] is False      # Gate nội bộ pass, grader độc lập trượt
    assert metrics(tr, tsr=None)["tsr_pass"] is None


def test_a_run_whose_first_check_passes_is_not_in_the_self_correction_denominator():
    tr = Tr().start().sim(True).gate(False, ["G2-FREQ"]).finish(False).sim(True, "draft#2").gate(True).finish(True).done()
    m = metrics(tr)
    assert m["checks"] == "PFPP" and m["first_failed"] is False and m["self_corrected"] is False and m["repair_iterations"] is None


def test_repair_iterations_count_every_failed_check_before_the_final_pass_across_sim_and_gate():
    tr = Tr().start().sim(False).sim(False, "draft#2").gate(False, ["G2-FREQ"]).finish(False).sim(True, "draft#3").gate(True).finish(True).done()
    m = metrics(tr)
    assert m["checks"] == "FFFPP" and m["self_corrected"] is True and m["repair_iterations"] == 3


def test_a_failed_check_after_an_earlier_pass_still_counts_as_repair_when_the_final_check_passes():
    tr = Tr().start().gate(False, ["G2-FREQ"]).sim(True).sim(False, "draft#2").gate(True).finish(True)
    m = metrics(tr)
    assert m["checks"] == "FPFP" and m["self_corrected"] is True and m["repair_iterations"] == 2


def test_a_run_that_ends_on_a_failed_check_is_not_self_corrected():
    tr = Tr().start().sim(False).gate(False, ["G2-FREQ"]).finish(False).escalated().done("escalated")
    m = metrics(tr, tsr=False)
    assert m["checks"] == "FF" and m["first_failed"] is True and m["self_corrected"] is False and m["repair_iterations"] is None


def test_gate_internal_simulations_are_part_of_the_gate_result_and_are_not_counted_twice():
    tr = Tr().start().sim(False, "draft#1", source="gate").gate(False, ["G2-FREQ"]).sim(True, "draft#2", source="gate").gate(True).finish(True)
    assert metrics(tr)["checks"] == "FP"


def test_agent_simulations_without_an_artifact_are_exploration_not_a_product_check():
    tr = Tr().start().sim(False, artifact=None).sim(True, artifact=None).done()
    m = metrics(tr)
    assert m["checks"] == "" and m["has_product"] is False and m["first_failed"] is False and m["self_corrected"] is False


def test_a_run_without_any_check_has_no_product_and_no_self_correction():
    m = metrics(Tr().start().tool().finish(True, implicit=True).done())
    assert m["has_product"] is False and m["self_corrected"] is False and m["repair_iterations"] is None and m["finish_total"] == 1


# ------------------------------------------------------------------ Premature-Finish / escalated
def test_rejected_finish_then_accepted_finish_counts_one_premature_of_two():
    tr = Tr().start().sim(True).gate(False, ["G2-FREQ", "DRC-PIN-01"]).finish(False).tool("update_plan").sim(True, "draft#2").gate(True, attempt=2).finish(True, attempt=2).done()
    m = metrics(tr)
    assert m["finish_total"] == 2 and m["finish_rejected"] == 1
    assert m["gate_fail_codes"] == {"G2-FREQ": 1, "DRC-PIN-01": 1}


def test_implicit_finish_is_counted_as_a_finish():
    m = metrics(Tr().start().gate(False, ["G1-V1"]).finish(False, implicit=True).gate(True).finish(True).done())
    assert m["finish_total"] == 2 and m["finish_rejected"] == 1


def test_gate_fail_codes_only_count_failed_gate_results_and_error_findings():
    tr = Tr().start()
    tr.gate(True, ["G5-SKIPPED"], sev="unknown")                      # gate pass: không tính
    tr.gate(False, ["G2-FREQ", "DRC-PWR-01"])
    tr.events[-1]["findings"][1]["severity"] = "unknown"              # unknown không chặn: không phải mã fail
    tr.gate(False, ["G2-FREQ"])
    assert metrics(tr)["gate_fail_codes"] == {"G2-FREQ": 2}


def test_escalated_run_is_counted_and_marks_the_task_as_ended_escalated():
    tr = Tr().start().sim(False).gate(False, ["G2-NO-EFFECT"]).finish(False).escalated().done("escalated")
    m = metrics(tr, tsr=False)
    assert m["escalated_turns"] == 1 and m["ended_escalated"] is True


def test_a_task_that_escalated_early_but_ended_answered_is_not_ended_escalated():
    tr = Tr().start().escalated().done("escalated").at(1).start().sim(True).gate(True).finish(True).done("answered")
    m = metrics(tr)
    assert m["escalated_turns"] == 1 and m["ended_escalated"] is False


def test_done_status_escalated_alone_also_counts():
    m = metrics(Tr().start().done("escalated"))
    assert m["escalated_turns"] == 1 and m["ended_escalated"] is True


# ------------------------------------------------------------------ replan
def test_replan_required_followed_by_plan_updated_and_an_accepted_finish_is_an_effective_replan():
    tr = (Tr().start().plan().gate(False, ["DRC-PIN-01"], trigger="draft").replan("DRC-PIN-01").plan().sim(True, "draft#2").gate(True).finish(True).done())
    m = metrics(tr, tsr=True)
    assert m["replan_required"] == 1 and m["replan_ok_accepted"] == 1 and m["replan_ok_tsr"] == 1
    assert m["plan_updated"] == 2 and m["plan_updated_after_trigger"] == 1          # kế hoạch đầu tiên không phải lập lại có lý do


def test_replan_effectiveness_distinguishes_accepted_by_the_gate_from_passing_the_independent_grader():
    tr = Tr().start().gate(False, ["DRC-PIN-01"]).replan().plan().gate(True).finish(True).done()
    m = metrics(tr, tsr=False)
    assert m["replan_required"] == 1 and m["replan_ok_accepted"] == 1 and m["replan_ok_tsr"] == 0


def test_a_replan_that_does_not_end_in_an_accepted_finish_is_not_effective():
    tr = Tr().start().gate(False, ["DRC-PIN-01"]).replan().plan().gate(False, ["DRC-PIN-01"]).finish(False).escalated().done("escalated")
    m = metrics(tr, tsr=False)
    assert m["replan_required"] == 1 and m["replan_ok_accepted"] == 0 and m["replan_ok_tsr"] == 0


def test_an_accepted_finish_that_comes_before_the_replan_does_not_make_it_effective():
    tr = Tr().start().gate(True).finish(True).replan().escalated().done("escalated")
    assert metrics(tr)["replan_ok_accepted"] == 0
    assert metrics(Tr().start().gate(True).finish(True).replan().done())["replan_ok_accepted"] == 0        # finish chấp nhận trước replan, không có gì sau đó


def test_plan_updated_after_a_failed_gate_counts_as_reasoned_even_without_replan_required():
    tr = Tr().start().plan().gate(False, ["G2-FREQ"]).plan().plan().sim(True, "draft#2").gate(True).finish(True)
    m = metrics(tr)
    assert m["plan_updated"] == 3 and m["plan_updated_after_trigger"] == 2 and m["replan_required"] == 0


def test_triggers_do_not_leak_across_turns():
    tr = Tr().start().gate(False, ["G2-FREQ"]).replan().finish(False).done().at(1).start().plan().sim(True).gate(True).finish(True).done()
    m = metrics(tr)
    assert m["plan_updated"] == 1 and m["plan_updated_after_trigger"] == 0


# ------------------------------------------------------------------ Step Efficiency
def test_duplicate_tool_calls_are_counted_per_turn_and_internal_calls_are_ignored():
    tr = (Tr().start()
          .tool("get_register_bitfields", {"chip": "stm32g474", "peripheral": "TIM1"})
          .tool("get_register_bitfields", {"peripheral": "TIM1", "chip": "stm32g474"})      # trùng (thứ tự khoá không đổi nghĩa)
          .tool("get_register_bitfields", {"chip": "stm32g474", "peripheral": "TIM2"})
          .tool("run_drc", {}, internal=True).tool("run_drc", {}, internal=True)             # do Gate/runtime gọi
          .tool("update_plan", "plain string args").tool("update_plan", "plain string args")
          .at(1).start().tool("get_register_bitfields", {"chip": "stm32g474", "peripheral": "TIM1"}))   # lượt khác: không trùng
    m = metrics(tr)
    assert m["tool_calls"] == 6 and m["dup_calls"] == 2


# ------------------------------------------------------------------ nhiều lượt
def test_multi_turn_checks_are_chained_in_turn_order_for_the_task_level_self_correction():
    tr = (Tr().start().sim(False).gate(False, ["G2-FREQ"]).finish(False).escalated().done("escalated")
          .at(1).start().tool().done("answered")
          .at(2).start().sim(True, "draft#2").gate(True).finish(True).done())
    m = metrics(tr)
    assert m["turns"] == 3 and m["checks"] == "FFPP" and m["self_corrected"] is True and m["repair_iterations"] == 2
    assert m["ended_escalated"] is False and m["escalated_turns"] == 1


def test_replan_effectiveness_is_decided_by_the_turn_of_the_replan():
    tr = (Tr().start().gate(False, ["DRC-PIN-01"]).replan().escalated().done("escalated")
          .at(1).start().sim(True).gate(True).finish(True).done())
    m = metrics(tr)
    assert m["replan_required"] == 1 and m["replan_ok_accepted"] == 0            # lượt 0 không kết thúc bằng finish được chấp nhận


def test_two_runs_with_the_same_turn_number_but_different_run_ids_are_not_merged():
    tr = Tr().start().sim(False).gate(False, ["G2-FREQ"]).escalated().done("escalated")
    other = Tr().start().sim(True).gate(True).finish(True).done()
    for e in other.events:
        e["run_id"] = "another-run"                                        # cùng turn=0, seq lại bắt đầu từ 0
    r = RunResult(system="S3@P4", variant="", task_id="C3-001", seed=0, trace=[*tr.events, *other.events])
    m = process.process_metrics(r, True)
    assert m["turns"] == 2 and m["checks"] == "FFPP" and m["ended_escalated"] is False and m["escalated_turns"] == 1


def test_the_order_of_trace_events_in_the_list_does_not_matter_only_turn_and_seq():
    tr = Tr().start().sim(False).plan().sim(True, "draft#2").gate(True).finish(True).done().at(1).start().plan().sim(True, "draft#3").gate(True).finish(True).done()
    base = metrics(tr)
    for seed in range(5):
        shuffled = tr.events[:]
        random.Random(seed).shuffle(shuffled)
        r = RunResult(system="S3@P4", variant="", task_id="C3-001", seed=0, trace=shuffled)
        assert process.process_metrics(r, True) == base


def test_malformed_and_foreign_events_are_ignored_without_crashing():
    tr = Tr().start().sim(True)
    tr.events += [{"type": "worker", "llm": "m"}, {"type": "gate_result"}, {"type": "sim_result", "source": "agent", "artifact": "d", "pass": "yes"},
                  {"type": "tool_call", "tool": "x"}, {"turn": 0}, "not-a-dict"]
    m = metrics(tr)
    assert m["v3"] is True and m["checks"] == "P"


def test_details_are_json_serialisable():
    import json
    json.dumps(metrics(Tr().start().sim(False).gate(False, ["G2-FREQ"]).replan().plan().gate(True).finish(True).done()))


# ------------------------------------------------------------------ như một grader (hình dạng trong scores.jsonl)
def test_grader_result_is_reporting_only_with_no_pass_or_score():
    tr = Tr().start().sim(False).sim(True, "draft#2").gate(True).finish(True)
    r, _ = tr.run()
    g = process.grader_result(r, True)
    assert g["pass"] is None and g["score"] is None and g["reasons"] == [] and g["details"] == process.process_metrics(r, True)


# ------------------------------------------------------------------ tổng hợp cho report
def row(metrics_, category="C3", tsr=True):
    return {"category": category, "tsr_pass": tsr, "graders": {"process": {"pass": None, "score": None, "reasons": [], "details": metrics_}}}


def rows_from(*specs):
    out = []
    for build, category, tsr in specs:
        r, _ = build.run()
        out.append(row(process.process_metrics(r, tsr), category, tsr))
    return out


def test_aggregate_of_rows_without_process_details_is_not_v3():
    legacy = {"category": "C1", "tsr_pass": True, "graders": {"exact": {"pass": True, "details": {}}}}
    assert process.aggregate([legacy, {"category": "C1", "tsr_pass": None, "graders": {}}]) == {"v3": False}
    assert process.aggregate([]) == {"v3": False}


def test_aggregate_self_correction_rate_with_the_independent_grader_share():
    sc_ok = Tr().start().sim(False).sim(True, "d#2").gate(True).finish(True)
    sc_gate_only = Tr().start().sim(False).sim(True, "d#2").gate(True).finish(True)
    never_fixed = Tr().start().sim(False).gate(False, ["G2-FREQ"]).finish(False).escalated().done("escalated")
    first_pass = Tr().start().sim(True).gate(True).finish(True)
    agg = process.aggregate(rows_from((sc_ok, "C3", True), (sc_gate_only, "C3", False), (never_fixed, "C3", False), (first_pass, "C1", True)))
    assert agg["v3"] is True and agg["n_runs"] == 4 and agg["with_product"] == 4
    assert agg["first_failed"] == 3 and agg["self_corrected"] == 2 and agg["self_corrected_tsr"] == 1
    assert agg["self_correction_rate"] == 2 / 3 and agg["self_corrected_tsr_rate"] == 1 / 2


def test_aggregate_mean_repair_iterations_averages_only_self_corrected_runs():
    a = Tr().start().sim(False).sim(True, "d#2").gate(True)                          # 1 lần sửa
    b = Tr().start().sim(False).sim(False, "d#2").gate(False, ["G2-FREQ"]).sim(True, "d#3").gate(True)   # 3 lần sửa
    c = Tr().start().sim(False).gate(False, ["G2-FREQ"])                              # không tự sửa: bị loại
    agg = process.aggregate(rows_from((a, "C3", True), (b, "C3", True), (c, "C3", False)))
    assert agg["mean_repair_iterations"] == 2.0


def test_aggregate_rates_are_none_not_zero_when_the_denominator_is_empty():
    agg = process.aggregate(rows_from((Tr().start().tool().finish(True, implicit=True), "C1", True)))
    assert agg["self_correction_rate"] is None and agg["mean_repair_iterations"] is None and agg["replan_effectiveness_accepted"] is None
    assert agg["premature_finish_rate"] == 0.0 and agg["self_corrected_tsr_rate"] is None


def test_aggregate_premature_finish_replan_and_escalation_totals():
    a = Tr().start().sim(True).gate(False, ["G2-FREQ"]).finish(False).gate(True, attempt=2).finish(True, attempt=2).done()
    b = Tr().start().gate(False, ["DRC-PIN-01"]).replan().plan().gate(True).finish(True).done()
    c = Tr().start().gate(False, ["DRC-PIN-01"]).replan().escalated().done("escalated")
    agg = process.aggregate(rows_from((a, "C3", True), (b, "C3", False), (c, "C4", False)))
    assert agg["finish_total"] == 3 and agg["finish_rejected"] == 1 and agg["premature_finish_rate"] == 1 / 3
    assert agg["replan_required"] == 2 and agg["replan_ok_accepted"] == 1 and agg["replan_ok_tsr"] == 0
    assert agg["replan_effectiveness_accepted"] == 0.5 and agg["replan_effectiveness_tsr"] == 0.0
    assert agg["plan_updated"] == 1 and agg["plan_updated_after_trigger"] == 1
    assert agg["escalated_turns"] == 1 and agg["ended_escalated"] == 1 and agg["ended_escalated_rate"] == 1 / 3
    assert agg["gate_fail_codes"] == {"G2-FREQ": 1, "DRC-PIN-01": 2}


def test_aggregate_step_efficiency_is_tool_calls_of_all_runs_per_successful_run_and_dup_rate():
    ok = Tr().start().tool("a", {"x": 1}).tool("a", {"x": 1}).tool("b", {}).sim(True).gate(True).finish(True)           # 3 call, 1 trùng
    bad = Tr().start().tool("a", {"x": 1}).tool("c", {}).sim(False).gate(False, ["G2-FREQ"])                              # 2 call
    agg = process.aggregate(rows_from((ok, "C3", True), (bad, "C3", False)))
    assert agg["tool_calls"] == 5 and agg["successes"] == 1 and agg["step_efficiency"] == 5.0
    assert agg["dup_calls"] == 1 and agg["dup_rate"] == 1 / 5
    none_ok = process.aggregate(rows_from((bad, "C3", False)))
    assert none_ok["step_efficiency"] is None and none_ok["tool_calls"] == 2


def test_aggregate_plan_coverage_on_design_categories_only():
    with_plan = Tr().start().plan().sim(True).gate(True).finish(True)
    without = Tr().start().sim(True).gate(True).finish(True)
    agg = process.aggregate(rows_from((with_plan, "C3", True), (without, "C3", True), (without, "C4", False), (with_plan, "C1", True)))
    assert agg["design_runs"] == 3 and agg["design_with_plan"] == 1 and agg["design_plan_coverage"] == 1 / 3
    no_design = process.aggregate(rows_from((with_plan, "C1", True)))
    assert no_design["design_runs"] == 0 and no_design["design_plan_coverage"] is None


def test_aggregate_ignores_rows_without_process_details_even_when_mixed_in():
    legacy = {"category": "C1", "tsr_pass": True, "graders": {}}
    agg = process.aggregate([legacy, *rows_from((Tr().start().sim(True).gate(True).finish(True), "C3", True))])
    assert agg["n_runs"] == 1
