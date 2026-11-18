"""P9: mục báo cáo FI (Recovery Rate) và C9 (Robustness): so task sinh với task gốc trên cùng task."""
from eval import report
from eval.schema import Task


def task(tid, cat):
    return Task.from_dict(dict(id=tid, category=cat, split="dev", turns=[{"user": "q"}], graders=["exact"], expected={"exact": {"value": "x"}}))


def row(system, tid, seed, ok, infra=False):
    return {"system": system, "variant": "", "task_id": tid, "seed": seed, "category": tid.split("-")[0], "infra": infra, "graders": {}, "tsr_pass": ok, "fail_codes": []}


def test_recovery_rate_is_fi_tsr_over_base_tsr_on_the_same_tasks():
    tasks = {t.id: t for t in [task("C1-001", "C1"), task("C1-002", "C1"), task("FI-C1-001", "FI"), task("FI-C1-002", "FI")]}
    scores = [row("S3@P7", "C1-001", s, True) for s in range(2)] + [row("S3@P7", "C1-002", s, True) for s in range(2)] + \
             [row("S3@P7", "FI-C1-001", 0, True), row("S3@P7", "FI-C1-001", 1, False), row("S3@P7", "FI-C1-002", 0, True), row("S3@P7", "FI-C1-002", 1, True)]
    text = report.fi_section(scores, tasks)
    assert "## FI" in text and "| S3@P7 | 100.0% | 75.0% | 75% | 2 |" in text


def test_c9_groups_the_delta_by_transform_and_empty_sets_give_no_section():
    tasks = {t.id: t for t in [task("C1-001", "C1"), task("C9-C1-001-typos", "C9"), task("C9-C1-001-vi", "C9")]}
    scores = [row("S0", "C1-001", 0, True), row("S0", "C9-C1-001-typos", 0, False), row("S0", "C9-C1-001-vi", 0, True)]
    text = report.c9_section(scores, tasks)
    assert "Robustness" in text and "typos: -100 đ (1)" in text and "vi: +0 đ (1)" in text
    assert report.fi_section(scores, tasks) == "" and report.c9_section(scores, {"C1-001": tasks["C1-001"]}) == ""
    assert report.fi_section([row("S0", "C1-001", 0, True, infra=True)], tasks) == ""
