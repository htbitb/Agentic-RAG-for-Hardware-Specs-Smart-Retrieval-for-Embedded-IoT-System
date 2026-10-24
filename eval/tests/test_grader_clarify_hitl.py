"""Grader `clarify` (C5, không gate) và `hitl` (P5, chỉ báo cáo) — tính từ sự kiện `human_reply` / `resume_result` / `hitl_loop` do runner ghi
và sự kiện interrupt/resume của runtime v3 (plan/P5_interfaces.md §3, §5). Kèm: score.py đăng ký `checklist`/`clarify`, thêm `hitl` SAU khi tsr_pass chốt."""
import copy
import json
from pathlib import Path

import yaml

from eval import score
from eval.context import GradeContext
from eval.graders import clarify, hitl
from eval.schema import GATING_GRADERS, RunResult, Task, TurnResult
from eval.tests.trace_builder import Tr

FIX = Path(__file__).parent / "fixtures" / "c5" / "c5_tiny.yaml"
CTX = GradeContext(manifest=[])


def tasks():
    return [Task.from_dict(d) for d in yaml.safe_load(FIX.read_text(encoding="utf-8"))]


def reply(kind="clarify", matched=("hse_hz",), necessary=True, answered=True, decision="answer", source="interrupt", turn=0, **kw):
    return {"type": "human_reply", "turn": turn, "kind": kind, "question": "q", "matched": list(matched), "necessary": necessary, "answered": answered,
            "decision": decision, "source": source, **kw}


def run_of(trace=(), answer="final", system="S0", task_id="C5-901"):
    return RunResult(system=system, variant="", task_id=task_id, seed=0, turns=[TurnResult(answer=answer)], final_answer=answer, trace=list(trace))


# ------------------------------------------------------------------ clarify
def test_clarify_without_any_human_reply_is_all_zero_and_precision_none():
    t = tasks()[0]
    r = clarify.grade(t, run_of(), CTX)
    assert r["pass"] is True and r["reasons"] == []
    d = r["details"]
    assert d == {"precision": None, "recall": 0.0, "asked": 0, "necessary": 0, "required": 1, "covered": [], "missed": ["hse_hz"], "unnecessary": 0,
                 "guessed_correctly": [], "asked_from": {"interrupt": 0, "baseline_text": 0}}


def test_clarify_counts_necessary_and_unnecessary_questions_from_both_sources():
    t = tasks()[0]
    tr = [reply(), reply(matched=(), necessary=False, answered=False, decision="unknown"), reply(kind="text", source="baseline_text", turn=1, matched=(), necessary=False),
          reply(kind="choice", matched=(), necessary=True, decision="choose"), reply(kind="approval", matched=(), decision="approve")]
    d = clarify.grade(t, run_of(tr), CTX)["details"]
    assert (d["asked"], d["necessary"], d["unnecessary"]) == (3, 1, 2) and d["precision"] == 1 / 3
    assert d["covered"] == ["hse_hz"] and d["missed"] == [] and d["recall"] == 1.0
    assert d["asked_from"] == {"interrupt": 2, "baseline_text": 1}


def test_an_unanswered_question_past_max_answers_still_covers_the_item():
    d = clarify.grade(tasks()[0], run_of([reply(answered=False, decision="unknown")]), CTX)["details"]
    assert d["covered"] == ["hse_hz"] and d["recall"] == 1.0


def test_guessing_the_hidden_value_without_asking_is_reported_but_never_gates():
    t = tasks()[0]
    d = clarify.grade(t, run_of(answer="Assuming an 8 MHz crystal, PLLM = 2."), CTX)["details"]
    assert d["guessed_correctly"] == ["hse_hz"] and d["recall"] == 0.0
    d = clarify.grade(t, run_of([reply()], answer="8 MHz crystal"), CTX)["details"]
    assert d["guessed_correctly"] == []                                                     # đã hỏi ⇒ không phải đoán
    assert "clarify" not in GATING_GRADERS


def test_complete_info_tasks_have_no_recall_and_every_question_is_unnecessary():
    t = tasks()[1]
    d = clarify.grade(t, run_of([reply(matched=(), necessary=False, decision="unknown")], task_id="C5-902"), CTX)["details"]
    assert d["required"] == 0 and d["recall"] is None and d["unnecessary"] == 1 and d["precision"] == 0.0 and d["missed"] == []


# ------------------------------------------------------------------ hitl: một run
def v3_trace():
    tr = Tr().start()
    tr.add("tool_call", tool="ask_human", server="control", permission="read", args={}, ok=True, error=None, summary="", security_flags=[], internal=False)
    tr.add("interrupt_raised", interrupt_id="i_1", kind="clarify", tool="ask_human", question="HSE?", why_needed="PLL", options=None, payload={}, asks_used=1)
    tr.add("resumed", interrupt_id="i_1", kind="clarify", decision="answer", payload={"answer": "8 MHz"})
    tr.tool("get_clock_limits").tool("simulate_register_writes")
    tr.add("interrupt_raised", interrupt_id="i_2", kind="approval", tool="write_config_file", question="write clock.h?", why_needed="", options=None,
           payload={"filename": "clock.h"}, asks_used=1)
    tr.add("resumed", interrupt_id="i_2", kind="approval", decision="reject", payload={"feedback": "no"})
    tr.plan().finish(True).done()
    events = tr.events + [reply(interrupt_id="i_1"), {"type": "resume_result", "turn": 0, "interrupt_id": "i_1", "status": "interrupted"},
                          reply(kind="approval", matched=(), decision="reject", interrupt_id="i_2"),
                          {"type": "resume_result", "turn": 0, "interrupt_id": "i_2", "status": "answered"}]
    return events


def test_hitl_applies_only_to_runs_with_interaction_events():
    assert hitl.applies(v3_trace()) and hitl.applies([reply(source="baseline_text", kind="text")])
    assert hitl.applies([{"type": "interrupt_raised", "interrupt_id": "x"}])
    assert not hitl.applies(Tr().start().sim(True).gate(True).finish(True).done().events) and not hitl.applies([])


def test_hitl_metrics_of_a_v3_run():
    m = hitl.hitl_metrics(run_of(v3_trace(), system="S3@P5"))
    assert m["interrupts"] == 2 and m["interrupts_raised"] == 2 and m["by_kind"] == {"clarify": 1, "approval": 1}
    assert m["resumes"] == 2 and m["resume_ok"] == 2 and m["hitl_loop"] is False
    assert m["questions"] == 1 and m["necessary"] == 1 and m["ask_human_unnecessary"] == 0 and m["text_questions"] == 0
    assert m["ask_human_calls"] == 1 and m["rejects"] == 1 and m["replan_after_reject"] == 1


def test_a_reject_without_a_plan_update_before_the_next_interrupt_is_not_a_replan():
    tr = Tr().start()
    tr.add("resumed", interrupt_id="i_1", kind="approval", decision="reject", payload={})
    tr.add("interrupt_raised", interrupt_id="i_2", kind="approval", tool="write_config_file", question="q", why_needed="", options=None, payload={}, asks_used=0)
    tr.plan()
    m = hitl.hitl_metrics(run_of(tr.events))
    assert m["rejects"] == 1 and m["replan_after_reject"] == 0


def test_a_failed_resume_and_a_loop_guard_are_counted():
    evs = [reply(interrupt_id="i_1"), {"type": "resume_result", "turn": 0, "interrupt_id": "i_1", "status": "error", "error": "ResumeError: used"},
           {"type": "hitl_loop", "turn": 0, "interrupt_id": "i_9", "rounds": 6}]
    m = hitl.hitl_metrics(run_of(evs))
    assert m["interrupts"] == 2 and m["resumes"] == 1 and m["resume_ok"] == 0 and m["hitl_loop"] is True


def test_unnecessary_ask_human_and_baseline_text_questions():
    evs = [reply(matched=(), necessary=False, decision="unknown"), reply(kind="text", source="baseline_text", necessary=False, matched=())]
    m = hitl.hitl_metrics(run_of(evs))
    assert m["ask_human_unnecessary"] == 1 and m["text_questions"] == 1 and m["interrupts"] == 1 and m["unnecessary"] == 2


# ------------------------------------------------------------------ score.py
def test_score_registers_checklist_and_clarify_and_adds_hitl_after_tsr():
    assert score.GRADERS["checklist"] and score.GRADERS["clarify"] and "hitl" not in score.GRADERS
    t = tasks()[0]
    ref = t.provenance["reference_solution"]["answer"]
    with_ev = score.score_run(run_of([reply()], answer=ref, task_id="C5-901"), t, CTX)
    without = score.score_run(run_of([], answer=ref, task_id="C5-901"), t, CTX)
    assert with_ev["tsr_pass"] is True and with_ev["graders"]["checklist"]["pass"] is True
    assert with_ev["graders"]["hitl"]["pass"] is None and with_ev["graders"]["hitl"]["details"]["questions"] == 1
    assert "hitl" not in without["graders"]
    strip = lambda row: {**row, "graders": {k: v for k, v in row["graders"].items() if k not in ("hitl", "clarify")}}
    assert strip(with_ev) == strip(without)                                             # hitl/clarify không đổi tsr_pass, fail_codes...


def test_a_failing_checklist_fails_tsr_with_item_reasons():
    t = tasks()[0]
    bad = t.provenance["wrong_variants"][0]["answer"]
    row = score.score_run(run_of(answer=bad, task_id="C5-901"), t, CTX)
    assert row["tsr_pass"] is False and "item pll" in row["fail_codes"]


def test_hitl_loop_error_is_a_system_error():
    t = tasks()[0]
    row = score.score_run(RunResult(system="S3@P5", variant="", task_id="C5-901", seed=0, turns=[TurnResult(answer="", status="interrupted")],
                                    final_answer="", trace=[{"type": "hitl_loop", "turn": 0, "interrupt_id": "i", "rounds": 6}],
                                    errors=["error:hitl_loop: still interrupted after 6 rounds"]), t, CTX)
    assert row["tsr_pass"] is False and "system_error" in row["fail_codes"] and row["graders"]["hitl"]["details"]["hitl_loop"] is True


def test_score_main_loads_the_oracle_variants(tmp_path):
    out = tmp_path / "res"
    out.mkdir()
    ref = tasks()[0].provenance["reference_solution"]["answer"]
    rows = [run_of(answer=ref, task_id="C5-901"), run_of(answer=ref, task_id="C5-901-O")]
    (out / "runs.jsonl").write_text("".join(json.dumps(r.to_dict()) + "\n" for r in rows))
    assert score.main(["--run", str(out), "--tasks", str(FIX.parent)], ctx=CTX) == 0
    got = {r["task_id"]: r for r in map(json.loads, (out / "scores.jsonl").read_text().splitlines())}
    assert set(got) == {"C5-901", "C5-901-O"} and got["C5-901-O"]["tsr_pass"] is True and "clarify" not in got["C5-901-O"]["graders"]


# ------------------------------------------------------------------ aggregate
def srow(system, tsr, trace=(), task=None, proc=None, category="C5"):
    t = task or tasks()[0]
    r = run_of(trace, system=system, task_id=t.id)
    row = {"system": system, "variant": "", "task_id": t.id, "seed": 0, "category": category, "tsr_pass": tsr, "graders": {}}
    if hitl.applies(trace):
        row["graders"]["hitl"] = hitl.grader_result(r)
    if "clarify" in t.graders:
        row["graders"]["clarify"] = clarify.grade(t, r, CTX)
    if proc is not None:
        row["graders"]["process"] = {"details": {"v3": True, "tool_calls": proc}}
    return row


def test_aggregate_resume_success_autonomy_and_interventions():
    rows = [srow("S3@P5", True, v3_trace(), proc=4), srow("S3@P5", True, Tr().start().done().events, proc=6),
            {"system": "S3@P5", "tsr_pass": None, "graders": {}}]                       # lỗi hạ tầng: bỏ
    a = hitl.aggregate(rows)
    assert a["hitl"] is True and a["n_runs"] == 2 and a["runs_with_interaction"] == 1 and a["v3_runs"] == 2
    assert a["interrupts"] == 2 and a["resume_success"] == 1.0
    assert a["tool_calls"] == 4 + 6 - 1 and a["autonomy_ratio"] == 9 / 11                # ask_human không tính là bước tự chủ
    assert a["interventions_per_task"] == 1.0 and a["replan_after_reject_rate"] == 1.0 and a["hitl_loop_runs"] == 0


def test_aggregate_for_a_baseline_has_no_autonomy_and_counts_text_questions():
    rows = [srow("S0", True, [reply(kind="text", source="baseline_text")]), srow("S0", False)]
    a = hitl.aggregate(rows)
    assert a["autonomy_ratio"] is None and a["resume_success"] is None and a["text_questions"] == 1 and a["interventions_per_task"] == 0.5
    assert hitl.aggregate([srow("S0", True)]) == {"hitl": False, "n_runs": 1}


def test_clarify_aggregate_splits_missing_and_complete_halves():
    t901, t902 = tasks()
    rows = [srow("S0", True, [reply(kind="text", source="baseline_text")]), srow("S0", True, [reply(matched=(), necessary=False)]),
            srow("S0", True, [reply(matched=(), necessary=False, kind="text", source="baseline_text")], task=t902),
            srow("S0", True, [], task=t902)]
    c = hitl.clarify_aggregate(rows)
    assert c["missing"]["asked"] == 2 and c["missing"]["necessary"] == 1 and c["missing"]["precision"] == 0.5
    assert c["missing"]["required"] == 2 and c["missing"]["covered"] == 1 and c["missing"]["recall"] == 0.5
    assert c["complete"]["runs"] == 2 and c["complete"]["unnecessary"] == 1 and c["complete"]["unnecessary_per_run"] == 0.5 and c["complete"]["recall"] is None
