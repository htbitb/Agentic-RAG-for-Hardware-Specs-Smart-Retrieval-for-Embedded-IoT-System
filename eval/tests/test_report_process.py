"""report.py (P4): hệ S3@P4, biến thể ablation không bị gộp vào hệ chính, mục 'Chỉ số quá trình (S3)', hash snapshot P4 trong manifest."""
from eval import report
from eval.graders import process
from eval.schema import RunResult, Task, TurnResult
from eval.tests.trace_builder import Tr

TASKS = [Task(id=f"C3-{i:03d}", category="C3", split="dev", turns=[{"user": "q"}], graders=["functional_sim", "compile"], tags=["pwm"],
              expected={"spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1, "tol_pct": 1}]}) for i in (1, 2, 3)]
TASKS.append(Task(id="C1-001", category="C1", split="dev", turns=[{"user": "q"}], graders=["exact"]))

D1 = lambda: Tr().start().plan().sim(False).plan().sim(True, "d#2").gate(True).finish(True).done()          # tự sửa, 2 plan_updated
CLEAN = lambda: Tr().start().sim(True).gate(True).finish(True).done()                                        # đúng ngay, không plan
REJECTED = lambda: Tr().start().sim(True).gate(False, ["G2-FREQ", "DRC-PIN-01"]).finish(False).replan().plan().sim(True, "d#2").gate(True).finish(True).done()
ESCALATED = lambda: Tr().start().sim(False).gate(False, ["G2-NO-EFFECT"]).finish(False).escalated().done("escalated")


def srow(system, tid, seed, ok, tr=None, category="C3", variant="", infra=False):
    run = RunResult(system=system, variant=variant, task_id=tid, seed=seed, trace=tr.events if tr else [])
    graders = {} if infra else {"functional_sim": {"pass": ok, "score": float(ok), "reasons": [], "details": {"blocks": 1, "analysis_ok": True}}}
    if tr is not None and not infra:
        graders["process"] = process.grader_result(run, ok)
    return {"system": system, "variant": variant, "task_id": tid, "seed": seed, "category": category, "split": "dev", "infra": infra,
            "errors": ["infra:cache_miss"] if infra else [], "graders": graders, "tsr_pass": None if infra else ok, "grounded_pass": None,
            "fail_codes": [] if ok or infra else ["wrong_freq"], "usage": {"tokens_in": 100, "tokens_out": 10, "usd": 0.001, "tool_calls": 3, "llm_calls": 2},
            "latency_s": 1.0}


def runs_of(rows):
    return [RunResult(system=r["system"], variant=r["variant"], task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer="a")], final_answer="a",
                      usage=r["usage"], latency_s=1.0) for r in rows]


def build(tmp_path, rows, manifest=None):
    return report.build_report(rows, runs_of(rows), manifest or {"model": "m", "seeds": 1, "systems": ["S3@P4"], "split": "dev"}, TASKS, tmp_path, n_boot=100)


def section(md, heading):
    return md.split(heading)[1].split("\n## ")[0]


def table_cells(sec, first_cell, table=0):
    blocks = [b.strip() for b in sec.split("\n\n") if b.lstrip().startswith("|")]
    lines = blocks[table].splitlines()
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    row = next(l for l in lines if l.startswith(f"| {first_cell} "))
    return dict(zip(header, [c.strip() for c in row.strip("|").split("|")]))


def s3_rows():
    return [srow("S3@P4", "C3-001", 0, True, D1()), srow("S3@P4", "C3-002", 0, True, REJECTED()), srow("S3@P4", "C3-003", 0, False, ESCALATED()),
            srow("S3@P4", "C1-001", 0, True, CLEAN(), category="C1")]


def s2d_rows():
    return [srow("S2D", "C3-001", 0, True), srow("S2D", "C3-002", 0, False), srow("S2D", "C3-003", 0, False), srow("S2D", "C1-001", 0, True, category="C1")]


# ------------------------------------------------------------------ đăng ký hệ
def test_s3_p4_is_registered_before_the_generic_s3_with_its_title_and_pairs():
    assert report.SYSTEM_ORDER == ["S0", "S1", "S2", "S2D", "S3@P4", "S3@P5", "S3"]
    assert report.SYSTEM_TITLES["S3@P4"] == "S3@P4 (Agent v3, runtime+Gate P4)"
    assert ("S3@P4", "S2D") in report.PAIRS and ("S3@P4", "S0") in report.PAIRS


def test_pairs_with_a_missing_system_are_skipped_and_present_ones_are_reported():
    rows = [*s3_rows(), *[{**r, "task_id": r["task_id"]} for r in s2d_rows()]]
    out = report.pairwise_table(rows, n_boot=100)
    assert "S3@P4 vs S2D" in out and "S3@P4 vs S0" not in out
    assert report._systems(rows) == ["S2D", "S3@P4"]


def test_report_title_and_manifest_show_the_p4_system_and_snapshot_hashes(tmp_path):
    md = build(tmp_path, s3_rows(), {"model": "m", "seeds": 1, "systems": ["S3@P4"], "split": "dev",
                                     "snapshot_agent_p4_sha256": "p4code", "snapshot_agent_p4_data_sha256": "p4data"})
    assert "S3@P4 (Agent v3, runtime+Gate P4)" in md.splitlines()[0]
    assert "snapshot_agent_p4_sha256: `p4code`" in md and "snapshot_agent_p4_data_sha256: `p4data`" in md


def test_a_manifest_without_the_p4_keys_does_not_show_them(tmp_path):
    md = build(tmp_path, s3_rows())
    assert "snapshot_agent_p4" not in md


# ------------------------------------------------------------------ biến thể ablation
def ablation_rows():
    return [srow("S3@P4", "C3-001", 0, False, D1(), variant="-Planner"), srow("S3@P4", "C3-002", 0, False, ESCALATED(), variant="-Planner"),
            srow("S3@P4", "C3-001", 0, True, D1(), variant="-Sandbox")]


def test_ablation_variants_are_separate_rows_and_never_merge_into_the_main_system(tmp_path):
    rows = [srow("S3@P4", "C3-001", 0, True, D1()), srow("S3@P4", "C3-002", 0, True, CLEAN()), *ablation_rows()]
    md = build(tmp_path, rows)
    main = section(md, "## Kết quả chính")
    main_row = table_cells(main, "S3@P4")
    assert main_row["C3"].startswith("100.0%")                                  # hai run ablation (fail) không kéo điểm hệ chính xuống
    assert table_cells(main, "S3@P4 [-Planner]")["C3"].startswith("0.0%")
    assert table_cells(main, "S3@P4 [-Sandbox]")["C3"].startswith("100.0%")
    systems = [l.split("|")[1].strip() for l in main.splitlines() if l.startswith("| S3")]
    assert systems == ["S3@P4", "S3@P4 [-Planner]", "S3@P4 [-Sandbox]"]           # biến thể đứng ngay sau hệ gốc


def test_ablation_labels_get_their_own_process_rows_and_a_note_explains_the_grouping(tmp_path):
    md = build(tmp_path, [*s3_rows(), *ablation_rows()])
    proc = section(md, "## Chỉ số quá trình (S3)")
    assert table_cells(proc, "S3@P4 [-Planner]", 0)["Run có trace v3"] == "2"
    assert table_cells(proc, "S3@P4", 0)["Run có trace v3"] == "4"
    assert "biến thể ablation" in md.lower() and "S3@P4 [-Planner]" in md


def test_report_title_lists_each_base_system_once_even_with_ablation_variants(tmp_path):
    first = build(tmp_path, [*s3_rows(), *ablation_rows()]).splitlines()[0]
    assert first.count("S3@P4 (Agent v3, runtime+Gate P4)") == 1 and "[-Planner]" not in first


def test_no_ablation_note_when_there_are_no_variant_rows(tmp_path):
    assert "biến thể ablation" not in build(tmp_path, s3_rows()).lower()


def test_variant_rows_with_the_same_task_and_seed_do_not_collide_in_cost_tables(tmp_path):
    md = build(tmp_path, [srow("S3@P4", "C3-001", 0, True, D1()), *ablation_rows()])
    sec = section(md, "## Chỉ số phụ")
    assert "| S3@P4 [-Planner] |" in sec and "| S3@P4 [-Sandbox] |" in sec and "| S3@P4 |" in sec


# ------------------------------------------------------------------ mục chỉ số quá trình
def test_process_section_is_after_c4_position_and_before_pairs_and_absent_without_v3(tmp_path):
    md = build(tmp_path, [*s3_rows(), *s2d_rows()])
    assert md.index("## Chỉ số quá trình (S3)") > md.index("## C3 — chức năng") and md.index("## Chỉ số quá trình (S3)") < md.index("## So sánh cặp")
    assert "## Chỉ số quá trình (S3)" not in build(tmp_path, s2d_rows())


def test_process_section_comes_after_the_c4_section_when_c4_exists(tmp_path):
    c4_task = Task(id="C4-001", category="C4", split="dev", turns=[{"user": "a"}, {"user": "b"}], graders=["final_state", "conflict_detected"],
                   expected={"spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1, "tol_pct": 1}], "must_detect": [{"code": "PIN_CONFLICT:PA8", "turn": 1}]})
    r = srow("S3@P4", "C4-001", 0, True, D1(), category="C4")
    r["graders"]["final_state"] = {"pass": True, "score": 1.0, "reasons": [], "details": {"blocks": 1, "analysis_ok": True, "source_turn": 1, "fallback": None, "turns": 2}}
    r["graders"]["conflict_detected"] = {"pass": True, "score": 1.0, "reasons": [], "details": {"items": [], "must_not": [], "n_items": 0, "n_detected": 0, "n_proactive": 0}}
    rows = [*s3_rows(), r]
    md = report.build_report(rows, runs_of(rows), {"model": "m", "seeds": 1, "split": "dev"}, [*TASKS, c4_task], tmp_path, n_boot=100)
    assert md.index("## C4 — thiết kế nhiều lượt") < md.index("## Chỉ số quá trình (S3)") < md.index("## So sánh cặp")


def test_systems_without_a_v3_trace_show_na_everywhere(tmp_path):
    sec = section(build(tmp_path, [*s3_rows(), *s2d_rows()]), "## Chỉ số quá trình (S3)")
    for t in (0, 1, 2):
        cells = table_cells(sec, "S2D", t)
        assert all(v == "N/A" for k, v in cells.items() if k != "Hệ"), cells


def test_self_correction_rate_is_shown_next_to_the_independent_grader_share(tmp_path):
    rows = s3_rows()
    rows.append(srow("S3@P4", "C3-001", 1, False, D1()))                          # tự sửa theo Gate của agent nhưng grader độc lập trượt
    t0 = table_cells(section(build(tmp_path, rows), "## Chỉ số quá trình (S3)"), "S3@P4", 0)
    assert t0["Run có trace v3"] == "5" and t0["Kiểm tra đầu fail"] == "3"
    assert t0["Self-Correction Rate"] == "2/3 (66.7%)"
    assert t0["…trong đó sản phẩm cuối cũng pass grader độc lập"] == "1/2 (50.0%)"
    assert t0["Mean Repair Iterations"] == "1.00"


def test_replan_and_plan_coverage_columns(tmp_path):
    t1 = table_cells(section(build(tmp_path, s3_rows()), "## Chỉ số quá trình (S3)"), "S3@P4", 1)
    assert t1["plan_updated (tổng)"] == "3" and t1["plan_updated sau replan_required / gate fail"] == "1" and t1["replan_required"] == "1"
    assert t1["Replan Effectiveness (kết thúc được chấp nhận)"] == "1/1 (100.0%)"
    assert t1["Replan Effectiveness (pass grader độc lập)"] == "1/1 (100.0%)"
    assert t1["plan_updated ≥ 1 trên C3/C4"] == "2/3 (66.7%)"                       # D1 và REJECTED có plan; ESCALATED không


def test_finish_escalation_and_step_efficiency_columns(tmp_path):
    t2 = table_cells(section(build(tmp_path, s3_rows()), "## Chỉ số quá trình (S3)"), "S3@P4", 2)
    assert t2["finish (tổng)"] == "5" and t2["Premature-Finish Rate"] == "2/5 (40.0%)"
    assert t2["Lượt escalated"] == "1" and t2["Task kết thúc escalated"] == "1/4 (25.0%)"
    assert t2["Step Efficiency (tool call / task thành công)"] == "0.00"            # trace dựng tay không có tool_call ⇒ 0 call / 3 thành công
    assert t2["Tỷ lệ gọi trùng"] == "N/A"


def test_step_efficiency_and_duplicate_rate_with_tool_calls(tmp_path):
    ok = Tr().start().tool("a", {"x": 1}).tool("a", {"x": 1}).tool("b", {}).sim(True).gate(True).finish(True).done()
    bad = Tr().start().tool("c", {}).sim(False).gate(False, ["G2-FREQ"]).done()
    t2 = table_cells(section(build(tmp_path, [srow("S3@P4", "C3-001", 0, True, ok), srow("S3@P4", "C3-002", 0, False, bad)]), "## Chỉ số quá trình (S3)"), "S3@P4", 2)
    assert t2["Step Efficiency (tool call / task thành công)"] == "4.00" and t2["Tỷ lệ gọi trùng"] == "1/4 (25.0%)"


def test_gate_failure_codes_table_counts_codes_per_system(tmp_path):
    sec = section(build(tmp_path, [*s3_rows(), *ablation_rows()]), "## Chỉ số quá trình (S3)")
    t3 = [b for b in sec.split("\n\n") if b.lstrip().startswith("|")][3]
    header = [c.strip() for c in t3.splitlines()[0].strip("|").split("|")]
    body = {l.split("|")[1].strip(): [c.strip() for c in l.strip("|").split("|")[1:]] for l in t3.splitlines()[2:]}
    assert header[1:] == ["S3@P4", "S3@P4 [-Planner]", "S3@P4 [-Sandbox]"]
    assert body["G2-FREQ"][0] == "1" and body["DRC-PIN-01"][0] == "1" and body["G2-NO-EFFECT"] == ["1", "1", "0"]


def test_section_states_that_self_correction_is_measured_against_the_agents_own_gate(tmp_path):
    sec = section(build(tmp_path, s3_rows()), "## Chỉ số quá trình (S3)")
    assert "Gate của chính agent" in sec and "requirement do agent ghi" in sec and "grader độc lập" in sec
    assert "không gating" in sec or "KHÔNG gating" in sec


def test_infra_rows_with_a_v3_trace_are_excluded_from_process_counts(tmp_path):
    rows = [*s3_rows(), srow("S3@P4", "C3-001", 1, None, D1(), infra=True)]
    t0 = table_cells(section(build(tmp_path, rows), "## Chỉ số quá trình (S3)"), "S3@P4", 0)
    assert t0["Run có trace v3"] == "4"
