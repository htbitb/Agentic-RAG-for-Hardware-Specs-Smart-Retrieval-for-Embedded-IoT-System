import json
import re
from pathlib import Path

import pytest

from eval import report
from eval.schema import RunResult, Task, TurnResult
from eval.score import fail_code


def T(i, cat, graders, expected=None):
    return Task(id=f"{cat}-{i:03d}", category=cat, split="dev", turns=[{"user": f"question {cat}-{i}"}], graders=graders,
                expected=expected or {})


TASKS = [T(1, "C1", ["exact"]), T(2, "C1", ["exact"]), T(3, "C1", ["exact"]), T(4, "C1", ["exact"]),
         T(1, "C6", ["safety"], {"safety": {"label": "refuse"}}), T(2, "C6", ["safety"], {"safety": {"label": "answer"}}),
         T(1, "C7", ["attack"]), T(2, "C7", ["attack"]), T(1, "C8", ["abstain"])]
BY_ID = {t.id: t for t in TASKS}


def row(system, tid, seed, ok, codes=(), infra=False, graders=None, usage=None):
    t = BY_ID[tid]
    return {"system": system, "variant": "", "task_id": tid, "seed": seed, "category": t.category, "split": "dev",
            "infra": infra, "errors": ["infra:cache_miss"] if infra else [], "graders": {} if infra else (graders or {}),
            "tsr_pass": None if infra else ok, "fail_codes": list(codes),
            "usage": usage or {"tokens_in": 1000, "tokens_out": 100, "usd": 0.0001, "tool_calls": 0, "llm_calls": 1},
            "latency_s": 1.0 + seed}


def make_scores():
    rows = []
    # S0: C1 -> task1 3/3 pass, task2 0/3, task3 1/3, task4 0/3 ; S1: better
    pat = {"S0": {1: [1, 1, 1], 2: [0, 0, 0], 3: [1, 0, 0], 4: [0, 0, 0]}, "S1": {1: [1, 1, 1], 2: [1, 1, 1], 3: [1, 1, 0], 4: [0, 0, 0]}}
    for s, tasks in pat.items():
        for i, seeds in tasks.items():
            for seed, ok in enumerate(seeds):
                rows.append(row(s, f"C1-{i:03d}", seed, bool(ok), codes=() if ok else ("missing_value",),
                                graders={"exact": {"pass": bool(ok), "score": float(ok), "reasons": [], "details": {}},
                                         "numeric_claims": {"pass": True, "score": 1, "reasons": [], "details": {"claims": 2, "unsupported": ["x"] if s == "S0" else []}},
                                         "citation": {"pass": s == "S1", "score": 1, "reasons": [], "details": {"valid": 1 if s == "S1" else 0, "invalid": 0 if s == "S1" else 1, "unverifiable": 0}}}))
    for s in ("S0", "S1"):
        for seed in range(3):
            rows.append(row(s, "C6-001", seed, s == "S1", codes=() if s == "S1" else ("unsafe_compliance",),
                            graders={"safety": {"pass": s == "S1", "score": 1, "reasons": [], "details": {"label": "refuse" if s == "S1" else "unsafe_compliance", "expected": "refuse", "unsafe": s == "S0", "over_refusal": False}}}))
            rows.append(row(s, "C6-002", seed, s == "S0", codes=() if s == "S0" else ("over_refusal",),
                            graders={"safety": {"pass": s == "S0", "score": 1, "reasons": [], "details": {"label": "answer" if s == "S0" else "refuse", "expected": "answer", "unsafe": False, "over_refusal": s == "S1"}}}))
            for k in (1, 2):
                rows.append(row(s, f"C7-{k:03d}", seed, s == "S1", codes=() if s == "S1" else ("attack_succeeded",),
                                graders={"attack": {"pass": s == "S1", "score": 1, "reasons": [], "details": {"attack_success": s == "S0", "triggered": []}}}))
            rows.append(row(s, "C8-001", seed, True, graders={"abstain": {"pass": True, "score": 1, "reasons": [], "details": {"abstained": True, "fabricated": []}}}))
    rows.append(row("S1", "C8-001", 3, True, infra=True))
    rows.append(row("S1", "C8-001", 4, True, infra=True))
    return rows


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("res")
    runs = [RunResult(system=r["system"], variant="", task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer=f"answer to {r['task_id']} SECRETVALUE123")],
                      final_answer=f"answer to {r['task_id']} SECRETVALUE123", usage=r["usage"], latency_s=r["latency_s"]) for r in make_scores()]
    md = report.build_report(make_scores(), runs, {"model": "m", "seeds": 3, "systems": ["S0", "S1"], "created_at": "t", "commit": None,
                                                   "corpus_manifest_sha256": "abc", "snapshot_agent_v1_sha256": "def", "cache_mode": "record",
                                                   "temperature": 0.0, "known_issues": ["issue-one"], "split": "dev"},
                             TASKS, out, secrets=["SECRETVALUE123"], n_boot=500)
    return md, out


def test_main_table_has_tsr_per_system_and_category_with_ci(built):
    md, _ = built
    sec = md.split("## Kết quả chính")[1].split("\n## ")[0]
    header = next(l for l in sec.splitlines() if l.startswith("| Hệ |"))
    assert all(c in header for c in ("C1", "C6", "C7", "C8", "Tổng"))
    s0 = next(l for l in sec.splitlines() if l.startswith("| S0 |"))
    cells = [c.strip() for c in s0.strip("|").split("|")]
    assert cells[1].startswith("33.3%") and "[" in cells[1] and "–" in cells[1]     # C1: (1 + 0 + 1/3 + 0)/4
    c1_s0 = report.task_means([r for r in make_scores() if r["system"] == "S0"], "C1")
    assert sorted(c1_s0.values()) == [0.0, 0.0, pytest.approx(1 / 3), 1.0]


def test_infra_runs_are_excluded_from_tsr_but_counted(built):
    md, _ = built
    s1 = [r for r in make_scores() if r["system"] == "S1"]
    assert report.task_means(s1, "C8")["C8-001"] == 1.0
    infra_section = md.split("## Lỗi hạ tầng")[1].split("##")[0]
    assert "| S1 | 2 |" in infra_section


def test_pairwise_section_has_delta_ci_and_mcnemar(built):
    md, _ = built
    sec = md.split("## So sánh cặp")[1].split("\n## ")[0]
    assert "S1 vs S0" in sec and "McNemar" in sec
    row = next(l for l in sec.splitlines() if l.startswith("| S1 vs S0 | C1"))
    assert "pp" in row and "p=" in row


def test_mcnemar_uses_majority_vote_per_task():
    s0 = {"a": 1.0, "b": 0.0, "c": 1 / 3, "d": 0.0}
    s1 = {"a": 1.0, "b": 1.0, "c": 2 / 3, "d": 0.0}
    b, c = report.discordant(s1, s0)
    assert (b, c) == (2, 0)                           # b và c đổi từ sai sang đúng; không có chiều ngược lại


def test_taxonomy_counts_failed_runs_by_code(built):
    md, _ = built
    sec = md.split("## Phân loại lỗi")[1].split("\n## ")[0]
    assert "missing_value" in sec and "unsafe_compliance" in sec and "over_refusal" in sec


def test_metric_table_has_hallucination_citation_safety_asr(built):
    md, _ = built
    sec = md.split("## Chỉ số phụ")[1].split("\n## ")[0]
    for head in ("Hallucination", "Citation Precision", "Safety Acc", "Over-refusal", "ASR", "Abstention Acc", "USD/task", "p50", "p95"):
        assert head in sec, head
    s0 = next(l for l in sec.splitlines() if l.startswith("| S0 |"))
    assert "100.0%" in s0 or "100%" in s0             # ASR của S0 = 100% (cả hai tấn công thành công)


def test_qualitative_examples_are_redacted(built):
    md, _ = built
    assert "SECRETVALUE123" not in md and "[REDACTED]" in md


def test_figures_and_manifest_summary(built):
    md, out = built
    assert (out / "figures" / "tsr_by_category.png").stat().st_size > 1000
    assert (out / "figures" / "cost_vs_tsr.png").exists()
    assert "issue-one" in md and "snapshot" in md.lower() and "abc" in md


def test_cost_and_latency_averages_exclude_infra_runs():
    scores = make_scores()
    runs = [RunResult(system=r["system"], variant="", task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer="a")], final_answer="a",
                      usage=({"tokens_in": 0, "tokens_out": 0, "usd": 0.0} if r["infra"] else {"tokens_in": 1000, "tokens_out": 100, "usd": 0.0001}),
                      latency_s=r["latency_s"], errors=r["errors"]) for r in scores]
    table = report.secondary_table(scores, runs, 200)
    s1 = next(l for l in table.splitlines() if l.startswith("| S1 |"))
    assert "1000 / 100" in s1 and "0.00010" in s1


def test_post_run_changes_are_listed_in_the_report(tmp_path):
    runs = [RunResult(system=r["system"], variant="", task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer="a")], final_answer="a",
                      usage=r["usage"], latency_s=r["latency_s"]) for r in make_scores()]
    md = report.build_report(make_scores(), runs, {"model": "m", "seeds": 3, "systems": ["S0", "S1"], "split": "dev",
                                                   "post_run_changes": ["grader đã sửa sau khi chạy", "C2-008 chạy lại"]},
                             TASKS, tmp_path, n_boot=200)
    sec = md.split("**Thay đổi sau khi lượt chạy bắt đầu**")[1]
    assert "- grader đã sửa sau khi chạy" in sec and "- C2-008 chạy lại" in sec


def test_report_has_no_post_run_section_when_there_were_none(built):
    assert "Thay đổi sau khi lượt chạy bắt đầu" not in built[0]


def test_report_numbers_do_not_depend_on_the_order_of_the_score_rows():
    import random

    scores = make_scores()
    shuffled = scores[:]
    random.Random(7).shuffle(shuffled)
    assert list(report.task_means(shuffled)) == sorted(report.task_means(shuffled))
    assert report.main_table(scores, 500) == report.main_table(shuffled, 500)
    assert report.taxonomy_table(scores) == report.taxonomy_table(shuffled)


def test_taxonomy_ties_are_ordered_by_code():
    rows = [{"system": "S0", "tsr_pass": False, "fail_codes": [c], "task_id": "T", "seed": 0, "category": "C1", "graders": {}}
            for c in ("zeta", "alpha", "mid")]
    body = report.taxonomy_table(rows).splitlines()
    assert [l.split("|")[1].strip() for l in body[2:]] == ["alpha", "mid", "zeta"]


def test_grounded_pass_requires_correct_answer_and_a_valid_citation():
    from eval.schema import grounded_pass

    cit = lambda valid: {"pass": True, "score": 1, "reasons": [], "details": {"valid": valid, "invalid": 0, "unverifiable": 0}}
    assert grounded_pass({"tsr_pass": True, "graders": {"exact": {}, "citation": cit(1)}}) is True
    assert grounded_pass({"tsr_pass": True, "graders": {"exact": {}, "citation": cit(0)}}) is False
    assert grounded_pass({"tsr_pass": False, "graders": {"exact": {}, "citation": cit(2)}}) is False
    assert grounded_pass({"tsr_pass": True, "graders": {"safety": {}}}) is None        # nhóm không có grader citation
    assert grounded_pass({"tsr_pass": None, "graders": {}}) is None                    # run lỗi hạ tầng


def test_grounded_tsr_section_only_covers_tasks_with_citation(built):
    md, _ = built
    sec = md.split("## Grounded TSR")[1].split("\n## ")[0]
    header = next(l for l in sec.splitlines() if l.startswith("| Hệ |"))
    assert "C1" in header and "C6" not in header and "C7" not in header
    s0 = next(l for l in sec.splitlines() if l.startswith("| S0 |"))
    s1 = next(l for l in sec.splitlines() if l.startswith("| S1 |"))
    assert [c.strip() for c in s0.strip("|").split("|")][1].startswith("0.0%")         # S0 đúng nhưng không có trích dẫn hợp lệ
    assert [c.strip() for c in s1.strip("|").split("|")][1].startswith("66.7%")        # S1: (1 + 1 + 2/3 + 0)/4


# ---- post-P0 review #6: bảng lỗi hạ tầng không phụ thuộc thứ tự dòng ----------------------------------------------------
def _infra_row(system, label):
    return {"system": system, "infra": True, "errors": [f"infra:{label} detail"], "task_id": "T", "seed": 0}


def test_infra_table_labels_are_ordered_by_count_then_name_whatever_the_row_order():
    import random

    rows = [_infra_row("S0", l) for l in ("zeta", "alpha", "mid", "beta")] + [_infra_row("S0", "common")] * 2
    want = "infra:common×2, infra:alpha×1, infra:beta×1"
    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        line = next(l for l in report.infra_table(shuffled).splitlines() if l.startswith("| S0 |"))
        assert line.endswith(want + " |"), line


# ---- post-P0 review #5: tổng thời gian chạy + số lần resume trong mục manifest -------------------------------------------
def _manifest_section(manifest, tmp_path):
    runs = [RunResult(system=r["system"], variant="", task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer="a")], final_answer="a",
                      usage=r["usage"], latency_s=r["latency_s"]) for r in make_scores()]
    md = report.build_report(make_scores(), runs, {"model": "m", "seeds": 3, "systems": ["S0", "S1"], "split": "dev", **manifest},
                             TASKS, tmp_path, n_boot=100)
    return md.split("## Manifest tái lập")[1]


def test_manifest_section_shows_total_wall_time_and_number_of_resumes(tmp_path):
    sec = _manifest_section({"wall_seconds": 100.0, "finished_at": "2026-10-21T10:00:00+00:00",
                             "resumes": [{"wall_seconds": 20.5, "finished_at": "2026-10-21T12:00:00+00:00"},
                                         {"wall_seconds": 30.0, "finished_at": "2026-10-21T11:00:00+00:00"}]}, tmp_path)
    assert "wall_seconds_total: `150.5`" in sec and "resumes: `2`" in sec
    assert "finished_at: `2026-10-21T12:00:00+00:00`" in sec                       # lần kết thúc muộn nhất


def test_manifest_section_for_a_legacy_manifest_without_resume_entries(tmp_path):
    sec = _manifest_section({"wall_seconds": 56.5, "resumed_at": ["a", "b", "c"]}, tmp_path)
    assert "wall_seconds_total: `56.5`" in sec and "resumes: `3`" in sec


def test_s2d_sits_between_s2_and_s3_and_has_pairs_against_s2_s1_s0():
    assert report.SYSTEM_ORDER == ["S0", "S1", "S2", "S2D", "S3@P4", "S3@P5", "S3"]
    assert [p for p in report.PAIRS if p[0] == "S2D"] == [("S2D", "S2"), ("S2D", "S1"), ("S2D", "S0")]
    assert ("S2", "S1") in report.PAIRS and ("S1", "S0") in report.PAIRS and ("S2", "S0") in report.PAIRS


def test_pairwise_table_reports_s2d_vs_s2():
    rows = make_scores()
    for i, seeds in {1: [1, 1, 1], 2: [1, 1, 1], 3: [1, 1, 1], 4: [1, 1, 0]}.items():
        for seed, ok in enumerate(seeds):
            rows.append(row("S2D", f"C1-{i:03d}", seed, bool(ok), graders={"exact": {"pass": bool(ok), "score": float(ok), "reasons": [], "details": {}}}))
    for i, seeds in {1: [0, 0, 0], 2: [0, 0, 0], 3: [0, 0, 0], 4: [0, 0, 0]}.items():
        for seed, ok in enumerate(seeds):
            rows.append(row("S2", f"C1-{i:03d}", seed, bool(ok), graders={"exact": {"pass": bool(ok), "score": float(ok), "reasons": [], "details": {}}}))
    out = report.pairwise_table(rows, n_boot=200)
    assert "S2D vs S2" in out and "S2D vs S1" in out and "S2D vs S0" in out
    assert report._systems(rows) == ["S0", "S1", "S2", "S2D"]


def test_report_title_names_the_systems_present_and_manifest_shows_the_p1_snapshot_hashes(tmp_path):
    rows = make_scores()
    for seed in range(3):
        rows.append(row("S2D", "C1-001", seed, True, graders={"exact": {"pass": True, "score": 1.0, "reasons": [], "details": {}}}))
    runs = [RunResult(system=r["system"], variant="", task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer="a")], final_answer="a",
                      usage=r["usage"], latency_s=r["latency_s"]) for r in rows]
    md = report.build_report(rows, runs, {"model": "m", "seeds": 3, "systems": ["S0", "S1", "S2D"], "split": "dev",
                                          "snapshot_agent_p1_sha256": "p1code", "snapshot_agent_p1_data_sha256": "p1data"},
                             TASKS, tmp_path, n_boot=100)
    first = md.splitlines()[0]
    assert "S2D (Agent v1 + dữ liệu P1)" in first and "S0 (Direct LLM)" in first and "S1 (Native RAG)" in first
    assert "S2 (Agent v1" not in first                          # S2 không có trong lượt này
    assert "snapshot_agent_p1_sha256: `p1code`" in md and "snapshot_agent_p1_data_sha256: `p1data`" in md


# ------------------------------------------------------------------ C3: functional_sim + compile
def c3_row(system, i, seed, ok, code=None, status="ok", analysis=True, blocks=1):
    fs_details = {"blocks": blocks} if blocks == 0 else {"blocks": blocks, "analysis_ok": analysis, "ops": 5}
    code = "no_code" if blocks == 0 else code
    return {"system": system, "variant": "", "task_id": f"C3-{i:03d}", "seed": seed, "category": "C3", "split": "dev", "infra": False, "errors": [],
            "graders": {"functional_sim": {"pass": ok, "score": float(ok), "reasons": [] if ok else [f"{code}: x"], "details": fs_details},
                        "compile": {"pass": status == "ok", "score": 1.0 if status == "ok" else 0.0, "reasons": [],
                                    "details": {"status": "no_code" if blocks == 0 else status}}},
            "tsr_pass": ok, "grounded_pass": None, "fail_codes": [] if ok else [code],
            "usage": {"tokens_in": 100, "tokens_out": 100, "usd": 0.0}, "latency_s": 1.0}


C3_TASKS = [Task(id=f"C3-{i:03d}", category="C3", split="dev", turns=[{"user": "q"}], graders=["functional_sim", "compile"], tags=[kind],
                 expected={"spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1, "tol_pct": 1}]})
            for i, kind in ((1, "pwm"), (2, "pwm"), (3, "uart"))]


def c3_rows():
    rows = []
    for seed in (1, 2, 3):
        rows.append(c3_row("S0", 1, seed, True))                                                      # pwm-1: đạt cả 3 seed
        rows.append(c3_row("S0", 2, seed, seed == 1, code="sim_violation:SIM-TIM-MOE"))              # pwm-2: chỉ seed 1
        rows.append(c3_row("S0", 3, seed, False, blocks=0) if seed == 3
                    else c3_row("S0", 3, seed, False, code="unsupported_construct:unknown_symbol", analysis=False, status="error"))
        rows.append(c3_row("S1", 1, seed, False, code="sim_violation:SIM-CLK-GATE", status="skipped"))
        rows.append(c3_row("S1", 2, seed, False, code="wrong_freq"))
        rows.append(c3_row("S1", 3, seed, True))
    return rows


def _c3_report(tmp_path, manifest=None):
    rows = c3_rows()
    runs = [RunResult(system=r["system"], variant="", task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer="a")], final_answer="a",
                      usage=r["usage"], latency_s=1.0) for r in rows]
    return report.build_report(rows, runs, manifest or {"model": "m", "seeds": 3, "systems": ["S0", "S1"], "split": "dev"}, C3_TASKS, tmp_path, n_boot=100)


def c3_section(md):
    return md.split("## C3 — chức năng (functional_sim) và compile")[1].split("\n## ")[0]


def cells(sec, system, table=0):
    blocks = [b for b in sec.split("\n\n") if b.lstrip().startswith("|")]
    lines = blocks[table].splitlines()
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    row = next(l for l in lines if l.startswith(f"| {system} "))
    return dict(zip(header, [c.strip() for c in row.strip("|").split("|")]))


def test_c3_table_reports_pass_at_k_analysability_and_compile_counts(tmp_path):
    sec = c3_section(_c3_report(tmp_path))
    s0, s1 = cells(sec, "S0"), cells(sec, "S1")
    # S0: pass@1 = (pwm-1 ✓, pwm-2 ✓ ở seed 1, uart ✗) / 3; pass@3 = 2/3; 9 run, 1 không có code, 6/8 phân tích được; compile ok 6 / lỗi 2
    assert s0["Pass@1"] == "66.7%" and s0["Pass@3"] == "66.7%"
    assert s0["Phân tích được"] == "6/8" and s0["Không có code"] == "1"
    assert (s0["compile ok"], s0["compile error"], s0["compile skipped"]) == ("6", "2", "0")
    # S1: chỉ uart đạt; mọi run phân tích được; compile skipped 3 (pwm-1)
    assert s1["Pass@1"] == "33.3%" and s1["Phân tích được"] == "9/9" and s1["Không có code"] == "0"
    assert (s1["compile ok"], s1["compile error"], s1["compile skipped"]) == ("6", "0", "3")


def test_c3_section_has_failure_codes_by_simulator_code(tmp_path):
    sec = c3_section(_c3_report(tmp_path))
    codes = {l.split("|")[1].strip(): [c.strip() for c in l.strip("|").split("|")[1:]] for l in sec.splitlines()
             if l.startswith("| ") and ("sim_violation" in l or "unsupported" in l or "wrong_freq" in l or "no_code" in l)}
    assert codes["sim_violation:SIM-TIM-MOE"] == ["2", "0"] and codes["sim_violation:SIM-CLK-GATE"] == ["0", "3"]
    assert codes["unsupported_construct:unknown_symbol"] == ["2", "0"] and codes["wrong_freq"] == ["0", "3"] and codes["no_code"] == ["1", "0"]


def test_c3_section_breaks_tsr_down_by_task_type(tmp_path):
    sec = c3_section(_c3_report(tmp_path))
    pwm, uart = cells(sec, "pwm", table=2), cells(sec, "uart", table=2)
    assert pwm["S0"] == "66.7%" and pwm["S1"] == "0.0%" and uart["S0"] == "0.0%" and uart["S1"] == "100.0%"
    assert pwm["Số task"] == "2" and uart["Số task"] == "1"


def test_no_c3_section_without_c3_rows(built):
    assert "## C3 — chức năng" not in built[0]


def test_manifest_section_shows_the_hwmodel_hashes_used_for_running_and_for_scoring(tmp_path):
    md = _c3_report(tmp_path, {"model": "m", "seeds": 3, "systems": ["S0", "S1"], "split": "dev", "hwmodel_vendor_sha256": "v" * 64,
                               "hwmodel_data_sha256": "d" * 64, "scoring": {"hwmodel_vendor_sha256": "w" * 64, "scored_at": "T"}})
    assert "hwmodel_vendor_sha256: `" + "v" * 64 in md and "hwmodel_data_sha256: `" + "d" * 64 in md
    assert "chấm điểm với hwmodel_vendor_sha256 `" + "w" * 64 in md


# ------------------------------------------------------------------ C4: final_state + conflict_detected, Proactive detection rate
def c4_row(system, i, seed, fs_ok, items, fs_code="wrong_pin", must_not=(), source_turn=2, fallback=None):
    """items: [(code, cause_turn, detected_turn | None)]"""
    its = [{"code": c, "cause_turn": t, "detected": d is not None, "turn": d, "proactive": d is not None and d <= t, "proactive_from0": d is not None and d <= t,
            "proactive_w2": d is not None and d <= t, "evidence": None} for c, t, d in items]
    cd_ok = all(x["proactive"] for x in its) and not must_not
    cd_reasons = [f"conflict_missed:{x['code'].split(':')[0]}: x" for x in its if not x["detected"]] + [f"conflict_late:{x['code'].split(':')[0]}: x" for x in its if x["detected"] and not x["proactive"]]
    cd_reasons += [f"must_not:unsafe_connection: turn 2 ..." for _ in must_not]
    return {"system": system, "variant": "", "task_id": f"C4-{i:03d}", "seed": seed, "category": "C4", "split": "dev", "infra": False, "errors": [],
            "graders": {"final_state": {"pass": fs_ok, "score": float(fs_ok), "reasons": [] if fs_ok else [f"{fs_code}: x"],
                                        "details": {"blocks": 1, "analysis_ok": True, "source_turn": source_turn, "fallback": fallback, "turns": 3}},
                        "conflict_detected": {"pass": cd_ok, "score": float(cd_ok), "reasons": cd_reasons,
                                              "details": {"items": its, "must_not": [{"code": "unsafe_connection"}] * len(must_not), "n_items": len(its),
                                                          "n_detected": sum(x["detected"] for x in its), "n_proactive": sum(x["proactive"] for x in its)}},
                        "compile": {"pass": True, "score": 1.0, "reasons": [], "details": {"status": "ok"}}},
            "tsr_pass": fs_ok and cd_ok, "grounded_pass": None, "fail_codes": [fail_code(r) for r in ([] if fs_ok else [f"{fs_code}: x"]) + cd_reasons],
            "usage": {"tokens_in": 100, "tokens_out": 100, "usd": 0.0}, "latency_s": 1.0}


PIN, LVL, CLK = ("PIN_CONFLICT:PA8", 1), ("LEVEL_MISMATCH:1.8V-3.3V", 1), ("CLOCK_LIMIT:SYSCLK", 1)
C4_TASKS = [Task(id=f"C4-{i:03d}", category="C4", split="dev", turns=[{"user": "q"}] * 3, graders=["final_state", "conflict_detected"], tags=[kind],
                 expected={"spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1, "tol_pct": 1}],
                           "must_detect": [{"code": c, "turn": t} for c, t in codes_]})
            for i, kind, codes_ in ((1, "pin_conflict", [PIN, LVL]), (2, "clock_limit", [CLK]))]


def c4_rows():
    rows = []
    for seed in (1, 2, 3):
        rows.append(c4_row("S0", 1, seed, True, [(PIN[0], 1, None), (LVL[0], 1, None)]))                                   # S0: đúng nhưng không nêu gì
        rows.append(c4_row("S0", 2, seed, False, [(CLK[0], 1, 2 if seed == 1 else None)], fs_code="sim_violation:SIM-CLK-LIMIT"))   # seed 1: nêu muộn
        rows.append(c4_row("S2D", 1, seed, True, [(PIN[0], 1, 1), (LVL[0], 1, 1 if seed < 3 else 0)], must_not=[1] if seed == 3 else ()))
        rows.append(c4_row("S2D", 2, seed, True, [(CLK[0], 1, 1)], fallback={"from_turn": 1, "reason": "x"} if seed == 2 else None))
    return rows


def _c4_report(tmp_path):
    rows = c4_rows()
    runs = [RunResult(system=r["system"], variant="", task_id=r["task_id"], seed=r["seed"], turns=[TurnResult(answer="a")], final_answer="a",
                      usage=r["usage"], latency_s=1.0) for r in rows]
    return report.build_report(rows, runs, {"model": "m", "seeds": 3, "systems": ["S0", "S2D"], "split": "dev"}, C4_TASKS, tmp_path, n_boot=100)


def c4_section(md):
    return md.split("## C4 — thiết kế nhiều lượt có xung đột cài sẵn")[1].split("\n## ")[0]


def test_c4_table_reports_final_state_conflict_detection_and_proactive_rate(tmp_path):
    sec = c4_section(_c4_report(tmp_path))
    s0, s2d = cells(sec, "S0"), cells(sec, "S2D")
    # S0: C4-001 (final_state ✓, 0/2 mục chủ động) x3 ; C4-002 (final_state ✗, 1/3 lần nêu muộn) x3 -> 9 mục: 0 chủ động, 1 muộn, 8 bỏ sót
    assert s0["final_state"] == "50.0%" and s0["conflict_detected"] == "0.0%"
    assert s0["Proactive detection rate"].startswith("0.0%") and s0["Phát hiện muộn"] == "1" and s0["Bỏ sót"] == "8"
    # S2D: C4-001: seed 3 vi phạm must_not nhưng nêu đủ; C4-002 nêu chủ động -> 9 mục, 9 chủ động
    assert s2d["Proactive detection rate"].startswith("100.0%") and s2d["Phát hiện muộn"] == "0" and s2d["Bỏ sót"] == "0"
    assert s2d["conflict_detected"] == "83.3%" and s2d["Vi phạm must_not"] == "1"
    assert s2d["Code lấy từ lượt trước"] == "1"


def test_c4_section_breaks_the_proactive_rate_down_by_conflict_family(tmp_path):
    sec = c4_section(_c4_report(tmp_path))
    pin, lvl, clk = (cells(sec, f, table=1) for f in ("PIN_CONFLICT", "LEVEL_MISMATCH", "CLOCK_LIMIT"))
    assert pin["S0"] == "0.0% (0/3)" and pin["S2D"] == "100.0% (3/3)"
    assert lvl["S0"] == "0.0% (0/3)" and lvl["S2D"] == "100.0% (3/3)"
    assert clk["S0"] == "0.0% (0/3)" and clk["S2D"] == "100.0% (3/3)"


def test_c4_section_lists_failure_codes_of_both_graders(tmp_path):
    sec = c4_section(_c4_report(tmp_path))
    rows = {l.split("|")[1].strip(): [c.strip() for c in l.strip("|").split("|")[1:]] for l in sec.splitlines() if l.startswith("| ") and ("conflict_" in l or "sim_violation" in l or "must_not" in l)}
    assert rows["sim_violation:SIM-CLK-LIMIT"] == ["3", "0"] and rows["conflict_missed:PIN_CONFLICT"] == ["3", "0"] and rows["conflict_late:CLOCK_LIMIT"] == ["1", "0"]
    assert rows["must_not:unsafe_connection"] == ["0", "1"]


def test_no_c4_section_without_c4_rows(built):
    assert "## C4 — thiết kế nhiều lượt" not in built[0]


def test_c4_section_reports_the_sensitivity_of_the_proactive_rate(tmp_path):
    """Ba cách đếm cạnh nhau: D25 nguyên văn (cả nêu ở lượt trước), cách chấm thực tế (từ lượt gây xung đột), nới 2 câu — để đọc độ bất định của bộ nhận diện."""
    sec = c4_section(_c4_report(tmp_path))
    assert "Độ nhạy của Proactive detection rate" in sec
    row = cells(sec, "S2D", table=2)
    assert row["D25 gốc: tính cả nêu ở lượt TRƯỚC (nới hơn)"].startswith("100.0%")
    assert row["Dùng để chấm: chỉ từ lượt gây xung đột (`from_turn`)"].startswith("100.0%")
    assert row["Như cột 2, cho phép cảnh báo ở câu liền sau (nới 2 câu)"].startswith("100.0%")
    assert cells(sec, "S0", table=2)["Dùng để chấm: chỉ từ lượt gây xung đột (`from_turn`)"].startswith("0.0%")
