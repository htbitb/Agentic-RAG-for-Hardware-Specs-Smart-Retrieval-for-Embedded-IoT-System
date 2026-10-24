"""process (P5, D35): Self-Correction tách lớp vật lý (G2/G3/G5/simulator/DRC) / provenance (G1) — chỉ THÊM khoá, mọi chỉ số cũ giữ nguyên;
sự kiện do runner ghi (human_reply, resume_result, hitl_loop) không làm đổi chỉ số quá trình."""
import pytest

from eval.graders import process
from eval.schema import RunResult
from eval.tests.trace_builder import Tr


def metrics(tr, tsr=True):
    r, _ = tr.run()
    return process.process_metrics(r, tsr)


def gate_with(findings, ok=False):
    tr = Tr().start()
    tr.add("gate_result", trigger="finish", attempt=1, gates={}, findings=findings, passed=ok, artifact="draft#1")
    return tr


def f(gate, code, sev="error"):
    return {"gate": gate, "code": code, "severity": sev, "kind": "local", "where": "answer"}


@pytest.mark.parametrize("findings,cls", [
    ([f("G1", "G1-V2"), f("G1", "G1-V3")], "provenance"),
    ([f("G2", "G2-FREQ")], "physical"),
    ([f("G3", "DRC-PIN-01")], "physical"),                       # dạng thật trong trace S3@P4: DRC nằm dưới gate G3
    ([f("DRC", "DRC-PIN-01")], "physical"),                      # dạng của trace_builder (gate = tiền tố mã)
    ([f("G5", "G5-COMPILE")], "physical"),
    ([f("G1", "G1-V1"), f("G3", "DRC-CLK-02")], "mixed"),
    ([f("G4", "G4-ABS-MAX")], "other"),
    ([f("G1", "G1-V1"), f("G4", "G4-ABS-MAX")], "other"),
    ([f("G2", "G2-UNMODELED", "warning")], "other"),            # fail không có finding error ⇒ unspecified
    ([{"code": "G1-V3", "severity": "error"}], "provenance"),     # thiếu trường gate ⇒ theo tiền tố mã
])
def test_the_class_of_a_first_failed_run(findings, cls):
    tr = gate_with(findings)
    tr.finish(False).sim(True, "draft#2").gate(True).finish(True).done()
    m = metrics(tr)
    assert m["first_failed"] is True and m["self_corrected"] is True and m["fail_class"] == cls


def test_an_agent_simulation_failure_is_physical_and_classes_accumulate_over_the_run():
    tr = Tr().start().sim(False).gate(False, ["G1-V3"]).finish(False).sim(True, "d#2").gate(True).finish(True).done()
    m = metrics(tr)
    assert m["fail_classes"] == ["physical", "provenance"] and m["fail_class"] == "mixed"


def test_runs_that_did_not_fail_first_have_no_class_but_keep_their_fail_classes():
    m = metrics(Tr().start().sim(True).gate(False, ["G1-V1"]).finish(False).gate(True).finish(True).done())
    assert m["first_failed"] is False and m["fail_class"] is None and m["fail_classes"] == ["provenance"]
    m = metrics(Tr().start().sim(True).gate(True).finish(True).done())
    assert m["fail_classes"] == [] and m["fail_class"] is None


def row(tr, tsr, category="C3"):
    r, _ = tr.run()
    return {"category": category, "tsr_pass": tsr, "graders": {"process": process.grader_result(r, tsr)}}


def test_aggregate_splits_self_correction_by_class_and_keeps_every_old_key():
    prov = lambda: Tr().start().gate(False, ["G1-V3"]).finish(False).gate(True).finish(True).done()
    phys = lambda: Tr().start().sim(False).sim(True, "d#2").gate(True).finish(True).done()
    mixed = lambda: Tr().start().gate(False, ["G1-V1", "DRC-PIN-01"]).finish(False).gate(True).finish(True).done()
    stuck = lambda: Tr().start().gate(False, ["G2-FREQ"]).finish(False).escalated().done("escalated")
    other = lambda: Tr().start().gate(False, ["G4-ABS-MAX"]).finish(False).gate(True).finish(True).done()
    rows = [row(prov(), True), row(prov(), False), row(phys(), True), row(mixed(), True), row(stuck(), False), row(other(), True),
            row(Tr().start().sim(True).gate(True).finish(True).done(), True)]
    a = process.aggregate(rows)
    assert a["first_failed"] == 6 and a["self_corrected"] == 5                                  # gộp như cũ
    assert a["sc_split_runs"] == 6
    assert (a["sc_provenance_first_failed"], a["sc_provenance_corrected"], a["sc_provenance_corrected_tsr"]) == (2, 2, 1)
    assert (a["sc_physical_first_failed"], a["sc_physical_corrected"], a["sc_physical_rate"]) == (3, 2, 2 / 3)
    assert a["sc_mixed_first_failed"] == 1 and (a["sc_other_first_failed"], a["sc_other_corrected"]) == (1, 1)
    assert a["sc_physical_corrected_tsr_rate"] == 1.0


def test_old_score_rows_without_the_new_keys_give_an_empty_split_and_unchanged_old_metrics():
    tr = Tr().start().gate(False, ["G1-V3"]).finish(False).gate(True).finish(True).done()
    new = row(tr, True)
    old = {**new, "graders": {"process": {**new["graders"]["process"], "details": {k: v for k, v in new["graders"]["process"]["details"].items()
                                                                                   if k not in ("fail_class", "fail_classes")}}}}
    a_old, a_new = process.aggregate([old]), process.aggregate([new])
    assert a_old["sc_split_runs"] == 0 and a_old["sc_provenance_rate"] is None and a_new["sc_provenance_rate"] == 1.0
    assert {k: v for k, v in a_old.items() if not k.startswith("sc_")} == {k: v for k, v in a_new.items() if not k.startswith("sc_")}


def test_runner_events_do_not_change_any_process_metric():
    tr = Tr().start().tool("a").sim(False).sim(True, "d#2").gate(True).finish(True).done()
    tr.at(1).start().tool("b").gate(True).finish(True).done()
    base, _ = tr.run()
    extra = RunResult(system="S3@P5", variant="", task_id="C3-001", seed=0, trace=[
        *tr.events, {"type": "human_reply", "turn": 1, "kind": "clarify", "question": "q", "matched": [], "necessary": False, "answered": False,
                     "decision": "unknown", "source": "interrupt"},
        {"type": "resume_result", "turn": 2, "interrupt_id": "i", "status": "answered"}, {"type": "hitl_loop", "turn": 3, "interrupt_id": "j", "rounds": 6}])
    assert process.process_metrics(extra, True) == process.process_metrics(base, True)
    assert process.process_metrics(extra, True)["turns"] == 2


# ------------------------------------------------------------------ review P4 m2 / m3 (controller P5)
def test_m3_events_without_run_id_such_as_the_adapter_worker_event_are_not_a_turn():
    tr = Tr().start().tool("a").sim(True).gate(True).finish(True).done().at(1).start().gate(False, ["G2-FREQ"]).escalated().done("escalated")
    worker = {"type": "worker", "llm": "m"}                                     # adapter S3 ghi sự kiện này, không có run_id/turn
    stray = {"type": "tool_call", "turn": 1, "tool": "b", "args": {}}           # sự kiện thiếu run_id: không thuộc lượt nào
    r = RunResult(system="S3@P4", variant="", task_id="C3-001", seed=0, trace=[worker, *tr.events, stray])
    m = process.process_metrics(r, True)
    assert m["turns"] == 2 and m["tool_calls"] == 1 and m["ended_escalated"] is True and m["escalated_turns"] == 1


def test_m2_duplicate_calls_are_keyed_on_args_sha_when_present():
    tr = Tr().start()
    tr.tool("read_doc", {"q": "x" * 400 + "<clipped>"})
    tr.events[-1]["args_sha"] = "a" * 32
    tr.tool("read_doc", {"q": "x" * 400 + "<clipped>"})
    tr.events[-1]["args_sha"] = "b" * 32                                        # args bị cắt giống nhau nhưng tham số đầy đủ khác: không trùng
    tr.tool("read_doc", {"q": "x" * 400 + "<clipped>"})
    tr.events[-1]["args_sha"] = "a" * 32                                        # cùng sha với lời gọi đầu: trùng (so args thì cả 3 đều "trùng")
    tr.tool("other").tool("other")                                              # không có args_sha: so args như trước
    m = metrics(tr.done())
    assert m["tool_calls"] == 5 and m["dup_calls"] == 2
