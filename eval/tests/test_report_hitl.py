"""report.py (P5): mục 'C5 và Human-in-the-loop' (Clarification P/R theo nửa thiếu/đủ thông tin, câu hỏi thừa/task, Resume Success, Autonomy Ratio,
ask_human thừa, Replan sau Reject, TSR C5 thường vs oracle-info), cột C5-O tách khỏi 'Tổng', bảng Self-Correction tách lớp (D35)."""
from pathlib import Path

import yaml

from eval import report
from eval.context import GradeContext
from eval.graders import clarify, hitl, process
from eval.schema import RunResult, Task, TurnResult, load_tasks
from eval.tests.test_report_process import TASKS as P_TASKS, s3_rows, section, srow as p_srow, table_cells
from eval.tests.trace_builder import Tr

FIX = Path(__file__).parent / "fixtures" / "c5"
CTX = GradeContext(manifest=[])
T = {t.id: t for t in load_tasks(FIX, oracle=True)}


def reply(kind="text", matched=(), necessary=False, source="baseline_text", decision="answer"):
    return {"type": "human_reply", "turn": 0, "kind": kind, "question": "q", "matched": list(matched), "necessary": necessary, "answered": necessary,
            "decision": decision, "source": source}


def crow(system, tid, seed, ok, trace=(), proc=None):
    t = T[tid]
    run = RunResult(system=system, variant="", task_id=tid, seed=seed, turns=[TurnResult(answer="a")], final_answer="a", trace=list(trace))
    graders = {"checklist": {"pass": ok, "score": float(ok), "reasons": [] if ok else ["item pll: x"], "details": {"items": {}}}}
    if "clarify" in t.graders:
        graders["clarify"] = clarify.grade(t, run, CTX)
    if hitl.applies(trace):
        graders["hitl"] = hitl.grader_result(run)
    if proc is not None:
        graders["process"] = process.grader_result(RunResult(system=system, variant="", task_id=tid, seed=seed, trace=proc.events), ok)
    return {"system": system, "variant": "", "task_id": tid, "seed": seed, "category": t.category, "split": t.split, "infra": False, "errors": [],
            "graders": graders, "tsr_pass": ok, "grounded_pass": None, "fail_codes": [] if ok else ["item pll"],
            "usage": {"tokens_in": 1, "tokens_out": 1, "usd": 0.0, "tool_calls": 0, "llm_calls": 1}, "latency_s": 1.0}


def v3_with_interrupt():
    tr = Tr().start().tool("get_clock_limits")
    tr.add("interrupt_raised", interrupt_id="i_1", kind="clarify", tool="ask_human", question="HSE?", why_needed="", options=None, payload={}, asks_used=1)
    tr.add("resumed", interrupt_id="i_1", kind="clarify", decision="answer", payload={})
    tr.sim(True).gate(True).finish(True).done()
    return tr


def rows():
    tr = v3_with_interrupt()
    events = tr.events + [reply("clarify", ("hse_hz",), True, "interrupt"), {"type": "resume_result", "turn": 0, "interrupt_id": "i_1", "status": "answered"}]
    return [crow("S0", "C5-901", 0, False, [reply("text", ("hse_hz",), True)]), crow("S0", "C5-901", 1, False),
            crow("S0", "C5-901-O", 0, True), crow("S0", "C5-901-O", 1, True),
            crow("S0", "C5-902", 0, True, [reply()]), crow("S0", "C5-902", 1, True, [reply()]),
            crow("S3@P5", "C5-901", 0, True, events, proc=tr), crow("S3@P5", "C5-901-O", 0, True, proc=Tr().start().done()),
            crow("S3@P5", "C5-902", 0, True, proc=Tr().start().done())]


def build(tmp_path, rs, tasks=None):
    runs = [RunResult(system=r["system"], variant="", task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer="a")], final_answer="a",
                      usage=r["usage"], latency_s=1.0) for r in rs]
    return report.build_report(rs, runs, {"model": "m", "seeds": 2, "split": "dev"}, tasks or list(T.values()), tmp_path, n_boot=100)


def test_oracle_rows_get_their_own_group_and_never_enter_the_total(tmp_path):
    main = section(build(tmp_path, rows()), "## Kết quả chính")
    s0 = table_cells(main, "S0")
    assert s0["C5"].startswith("50.0%") and s0["C5-O"].startswith("100.0%")         # C5: (0/2 + 2/2)/2; C5-O: 2/2
    assert s0["Tổng"].startswith("50.0%")                                             # chỉ C5-901 + C5-902; nếu đếm cả C5-901-O sẽ là 66.7%
    assert list(table_cells(main, "S0")).index("C5-O") == list(table_cells(main, "S0")).index("C5") + 1


def test_relabel_keeps_scores_categories_untouched():
    rs = rows()
    out = report.relabel_oracle(rs)
    assert {r["category"] for r in rs} == {"C5"} and {r["category"] for r in out} == {"C5", "C5-O"}


def test_hitl_section_reports_clarification_by_half(tmp_path):
    sec = section(build(tmp_path, rows()), "## C5 và Human-in-the-loop (P5)")
    s0 = table_cells(sec, "S0", 0)
    assert s0["Clarification Precision (thiếu thông tin)"] == "1/1 (100.0%)" and s0["Clarification Recall (thiếu thông tin)"] == "1/2 (50.0%)"
    assert s0["Câu hỏi thừa / run (đủ thông tin)"] == "1.00" and s0["Run thiếu tt"] == "2" and s0["Run đủ tt"] == "2"
    s3 = table_cells(sec, "S3@P5", 0)
    assert s3["Clarification Recall (thiếu thông tin)"] == "1/1 (100.0%)" and s3["Câu hỏi thiếu tt: interrupt / văn bản"] == "1 / 0"


def test_hitl_section_lists_unnecessary_questions_per_complete_task(tmp_path):
    sec = section(build(tmp_path, rows()), "## C5 và Human-in-the-loop (P5)")
    cells = table_cells(sec, "C5-902", 1)
    assert cells["S0"] == "1.00 (2 run)" and cells["S3@P5"] == "0.00 (1 run)"


def test_hitl_section_reports_resume_success_and_autonomy_for_the_hitl_system(tmp_path):
    sec = section(build(tmp_path, rows()), "## C5 và Human-in-the-loop (P5)")
    s3 = table_cells(sec, "S3@P5", 2)
    assert s3["Interrupt"] == "1" and s3["Resume Success"] == "1/1 (100.0%)" and s3["Theo loại"] == "clarify×1"
    assert s3["Autonomy Ratio"] == "0.50" and s3["Can thiệp TB / task"] == "0.33" and s3["Run kẹt (hitl_loop)"] == "0"
    s0 = table_cells(sec, "S0", 2)
    assert s0["Autonomy Ratio"] == "N/A" and s0["Lượt bổ sung (câu hỏi văn bản)"] == "3" and s0["Resume Success"] == "N/A"


def test_hitl_section_compares_c5_with_its_oracle_variant(tmp_path):
    sec = section(build(tmp_path, rows()), "## C5 và Human-in-the-loop (P5)")
    s0 = table_cells(sec, "S0", 3)
    assert s0["TSR C5 (thường)"].startswith("50.0%") and s0["TSR C5-O (oracle-info)"].startswith("100.0%")
    assert s0["Δ oracle − thường trên task có cả hai (CI 95% bootstrap cặp)"].startswith("+100.0 pp") and s0["Cặp"] == "1"


def test_no_hitl_section_for_old_result_dirs(tmp_path):
    md = report.build_report(s3_rows(), [], {"model": "m", "seeds": 1, "split": "dev"}, P_TASKS, tmp_path, n_boot=100)
    assert "## C5 và Human-in-the-loop" not in md


def test_process_section_has_the_physical_provenance_split_as_its_last_table(tmp_path):
    prov = Tr().start().gate(False, ["G1-V3"]).finish(False).gate(True).finish(True).done()
    phys = Tr().start().sim(False).sim(True, "d#2").gate(True).finish(True).done()
    rs = [p_srow("S3@P4", "C3-001", 0, True, prov), p_srow("S3@P4", "C3-002", 0, False, phys), p_srow("S2D", "C3-001", 0, True)]
    md = report.build_report(rs, [], {"model": "m", "seeds": 1, "split": "dev"}, P_TASKS, tmp_path, n_boot=100)
    sec = section(md, "## Chỉ số quá trình (S3)")
    t4 = table_cells(sec, "S3@P4", 4)
    assert t4["Self-Correction (vật lý: G2/G3/G5/simulator/DRC)"] == "1/1 (100.0%)" and t4["…trong đó hỗn hợp G1 + vật lý"] == "0"
    assert t4["Self-Correction (provenance: G1)"] == "1/1 (100.0%)" and t4["Run first_failed có phân lớp"] == "2/2"
    assert table_cells(sec, "S2D", 4)["Self-Correction (provenance: G1)"] == "N/A"
    assert "D35" in sec
