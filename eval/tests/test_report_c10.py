"""P7: mục báo cáo C10 (đường cong học của Lesson memory) và schema fresh_sessions."""
from eval import report
from eval.schema import RunResult, Task


def run(system, task_id, seed, encounters, variant=""):
    """encounters: danh sách (số lần Gate không qua, số lesson dùng, số lesson ghi) cho từng lượt (mỗi lượt một run_id)."""
    trace = []
    for k, (fails, used, written) in enumerate(encounters):
        rid = f"r{seed}{k}"
        trace += [{"type": "gate_result", "run_id": rid, "passed": False} for _ in range(fails)] + [{"type": "gate_result", "run_id": rid, "passed": True}]
        if used:
            trace.append({"type": "lesson_used", "run_id": rid, "ids": ["L-x"] * used})
        trace += [{"type": "lesson_written", "run_id": rid}] * written
    return RunResult(system=system, variant=variant, task_id=task_id, seed=seed, turns=[], final_answer="", files={}, board_state=None, trace=trace, usage={}, latency_s=0.0, errors=[])


def score(system, task_id, seed, infra=False):
    return {"system": system, "variant": "", "task_id": task_id, "seed": seed, "category": "C10", "infra": infra, "graders": {}, "tsr_pass": True, "fail_codes": []}


def tasks():
    t = Task.from_dict(dict(id="C10-001", category="C10", split="dev", turns=[{"user": "a"}, {"user": "b"}], graders=["final_state"], fresh_sessions=True,
                            expected={"spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1000, "duty_pct": 50, "tol_pct": 1}]}))
    return {t.id: t}


def test_the_learning_curve_table_shows_repairs_per_encounter_with_lessons_used_and_written():
    runs = [run("S3@P7", "C10-001", 0, [(1, 0, 1), (0, 1, 0)]), run("S3@P7", "C10-001", 1, [(2, 0, 1), (0, 1, 0)]),
            run("S3@P7 [-Lessons]", "C10-001", 0, [(1, 0, 0), (1, 0, 0)])]
    scores = [score("S3@P7", "C10-001", 0), score("S3@P7", "C10-001", 1), score("S3@P7 [-Lessons]", "C10-001", 0)]
    text = report.c10_section(scores, runs, tasks())
    assert "## C10" in text
    row = next(l for l in text.splitlines() if l.startswith("| S3@P7 |"))
    assert "1.50 (n=2, dùng 0, ghi 2, chấp nhận 2/2)" in row and "0.00 (n=2, dùng 2, ghi 0, chấp nhận 2/2)" in row
    base = next(l for l in text.splitlines() if l.startswith("| S3@P7 [-Lessons] |"))
    assert base.count("1.00 (n=1") == 2


def test_infra_runs_and_runs_of_other_categories_are_left_out_and_no_c10_means_no_section():
    runs = [run("S3@P7", "C10-001", 0, [(3, 0, 0)])]
    assert report.c10_section([score("S3@P7", "C10-001", 0, infra=True)], runs, tasks()) == ""
    assert report.c10_section([score("S3@P7", "C10-001", 0)], runs, {}) == ""


def test_fresh_sessions_is_a_task_flag_that_does_not_change_old_task_serialisation():
    d = Task.from_dict(dict(id="C7-901", category="C7", split="dev", turns=[{"user": "q"}], graders=["attack"], expected={"attack": {"checks": [{"type": "key_leak"}]}})).to_dict()
    assert "fresh_sessions" not in d and "tool_rules" not in d
    t = tasks()["C10-001"]
    assert t.fresh_sessions is True and t.to_dict()["fresh_sessions"] is True
