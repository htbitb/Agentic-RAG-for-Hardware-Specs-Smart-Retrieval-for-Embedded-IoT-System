"""score.py: trace v3 ⇒ `graders.process` (chỉ báo cáo). Không ảnh hưởng tsr_pass, GATING_GRADERS hay validation của Task."""
import json

import yaml

from eval import score
from eval.context import GradeContext
from eval.schema import GATING_GRADERS, GRADERS, RunResult, Task, TurnResult

CTX = GradeContext(manifest=[], system_prompts={"S0": "You are an expert in embedded hardware and you always answer concisely."})


def task_c1():
    return Task(id="C1-001", category="C1", split="dev", turns=[{"user": "Address of X?"}], graders=["exact", "numeric_claims", "citation"],
                expected={"exact": {"attribute": "address", "kind": "hex", "value": "0x48000000"}, "cite_values": ["0x48000000"]})


V3_TRACE = [
    {"type": "run_started", "run_id": "r", "turn": 0, "step": 0, "seq": 0, "ts": 0.0, "goal": "g", "project_id": "p", "ablations": [], "budgets": None},
    {"type": "sim_result", "run_id": "r", "turn": 0, "step": 1, "seq": 1, "ts": 0.0, "tool": "simulate_register_writes", "source": "agent", "pass": False,
     "violations": ["SIM-TIM-MOE"], "effects": [], "unmodeled": [], "artifact": "draft#1"},
    {"type": "sim_result", "run_id": "r", "turn": 0, "step": 2, "seq": 2, "ts": 0.0, "tool": "simulate_register_writes", "source": "agent", "pass": True,
     "violations": [], "effects": [], "unmodeled": [], "artifact": "draft#2"},
    {"type": "finish", "run_id": "r", "turn": 0, "step": 3, "seq": 3, "ts": 0.0, "implicit": False, "accepted": True, "gate": {}, "waived": [], "attempt": 1},
]


def run(answer, trace=(), errors=(), system="S3@P4", variant=""):
    return RunResult(system=system, variant=variant, task_id="C1-001", seed=0, turns=[TurnResult(answer=answer)], final_answer=answer,
                     trace=list(trace), errors=list(errors))


def test_process_is_not_a_gating_grader_and_tasks_do_not_need_to_list_it():
    assert "process" not in GATING_GRADERS and "process" not in GRADERS
    task_c1()                                                                  # Task hợp lệ mà không khai báo "process"


def test_a_v3_run_gets_a_reporting_only_process_entry():
    row = score.score_run(run("It is 0x48000000.", V3_TRACE), task_c1(), CTX)
    p = row["graders"]["process"]
    assert p["pass"] is None and p["score"] is None and p["reasons"] == []
    assert p["details"]["v3"] is True and p["details"]["checks"] == "FP" and p["details"]["self_corrected"] is True
    assert p["details"]["tsr_pass"] is True and row["tsr_pass"] is True


def test_the_process_entry_never_changes_tsr_fail_codes_or_grounded_pass():
    with_trace = score.score_run(run("It is 0x48000400.", V3_TRACE), task_c1(), CTX)
    without = score.score_run(run("It is 0x48000400."), task_c1(), CTX)
    assert "process" in with_trace["graders"] and "process" not in without["graders"]
    stripped = {**with_trace, "graders": {k: v for k, v in with_trace["graders"].items() if k != "process"}}
    assert stripped == without                                                  # mọi trường khác giống hệt
    assert with_trace["tsr_pass"] is False and with_trace["graders"]["process"]["details"]["tsr_pass"] is False


def test_legacy_systems_get_no_process_key_so_old_result_dirs_rescore_identically():
    legacy_trace = [{"type": "agent_trace", "turn": 0, "events": []}, {"type": "tool_call", "turn": 0, "tool": "x", "args": {}, "result": {}}]
    for system in ("S0", "S1", "S2", "S2D"):
        row = score.score_run(run("It is 0x48000000.", legacy_trace, system=system), task_c1(), CTX)
        assert set(row["graders"]) == {"exact", "numeric_claims", "citation"}


def test_infra_runs_are_excluded_before_any_process_entry_is_computed():
    row = score.score_run(run("", V3_TRACE, errors=["infra:cache_miss"]), task_c1(), CTX)
    assert row["tsr_pass"] is None and row["graders"] == {}


def test_a_system_error_run_still_reports_process_details_with_tsr_false():
    row = score.score_run(run("", V3_TRACE, errors=["error:ValueError: boom"]), task_c1(), CTX)
    assert row["tsr_pass"] is False and row["graders"]["process"]["details"]["tsr_pass"] is False


def test_ablation_variant_rows_keep_their_variant_and_get_process_details():
    row = score.score_run(run("It is 0x48000000.", V3_TRACE, variant="-Planner"), task_c1(), CTX)
    assert row["variant"] == "-Planner" and row["graders"]["process"]["details"]["v3"] is True


def test_cli_roundtrip_writes_process_details_into_scores_jsonl(tmp_path):
    tdir = tmp_path / "tasks"
    tdir.mkdir()
    (tdir / "c1.yaml").write_text(yaml.safe_dump(task_c1().to_dict()))
    out = tmp_path / "res"
    out.mkdir()
    (out / "runs.jsonl").write_text(json.dumps(run("0x48000000", V3_TRACE).to_dict()) + "\n" + json.dumps(run("0x48000000", system="S0").to_dict()) + "\n")
    assert score.main(["--run", str(out), "--tasks", str(tdir)], ctx=CTX) == 0
    rows = [json.loads(l) for l in (out / "scores.jsonl").read_text().splitlines()]
    assert rows[0]["graders"]["process"]["details"]["checks"] == "FP" and "process" not in rows[1]["graders"]
