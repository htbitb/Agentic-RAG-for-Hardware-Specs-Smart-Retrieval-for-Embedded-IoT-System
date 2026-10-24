import json
from pathlib import Path

import pytest
import yaml

from eval.schema import RunResult, Task, TurnResult, load_tasks


def _write(tmp_path, name, **kw):
    d = {"id": "C1-001", "category": "C1", "split": "dev", "difficulty": "easy", "chips": ["stm32g474"],
         "tags": ["x"], "turns": [{"user": "What is X?"}], "expected": {"exact": {"attribute": "address", "value": "0x10"}},
         "graders": ["exact"]}
    d.update(kw)
    p = tmp_path / "C1" / f"{name}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(d))
    return p


def test_task_from_yaml_roundtrip(tmp_path):
    p = _write(tmp_path, "a")
    t = Task.from_dict(yaml.safe_load(p.read_text()))
    assert t.id == "C1-001" and t.turns[0]["user"] == "What is X?"
    assert t.review_status == "verified" and t.version == 1
    assert Task.from_dict(t.to_dict()) == t


@pytest.mark.parametrize("bad", [{"split": "prod"}, {"category": "C99"}, {"turns": []}, {"graders": ["nope"]}])
def test_task_validation_rejects(tmp_path, bad):
    p = _write(tmp_path, "b", **bad)
    with pytest.raises(ValueError):
        Task.from_dict(yaml.safe_load(p.read_text()))


def test_load_tasks_filters_by_split_category_and_review_status(tmp_path):
    _write(tmp_path, "a", id="C1-001", split="dev")
    _write(tmp_path, "b", id="C1-002", split="test")
    _write(tmp_path, "c", id="C1-003", split="dev", review_status="needs_human")
    ids = lambda ts: sorted(t.id for t in ts)
    assert ids(load_tasks(tmp_path, split="dev")) == ["C1-001"]                       # needs_human bị loại
    assert ids(load_tasks(tmp_path, split="dev", include_needs_human=True)) == ["C1-001", "C1-003"]
    assert ids(load_tasks(tmp_path, categories=["C2"])) == []
    assert ids(load_tasks(tmp_path, split="test")) == ["C1-002"]


def test_load_tasks_rejects_duplicate_ids(tmp_path):
    _write(tmp_path, "a", id="C1-001")
    _write(tmp_path, "b", id="C1-001")
    with pytest.raises(ValueError, match="duplicate"):
        load_tasks(tmp_path)


def test_run_result_json_roundtrip_and_helpers():
    r = RunResult(system="S1", variant="", task_id="C1-001", seed=1,
                  turns=[TurnResult(answer="a", status="answered")], final_answer="a", files={}, board_state=None,
                  trace=[{"type": "sources", "turn": 0, "sources": [{"doc_id": "D", "file": "f.pdf", "page": 3}]}],
                  usage={"tokens_in": 10, "tokens_out": 2, "usd": 0.0, "tool_calls": 0, "llm_calls": 1}, latency_s=1.5,
                  errors=["infra:429 rate limit"])
    again = RunResult.from_dict(json.loads(json.dumps(r.to_dict())))
    assert again == r
    assert again.sources() == [{"doc_id": "D", "file": "f.pdf", "page": 3}]
    assert again.has_infra_error() and again.key() == ("S1", "", "C1-001", 1)


# ---- post-P0 review #6: task phải có ít nhất một grader quyết định TSR -----------------------------------------------------
@pytest.mark.parametrize("graders", [["citation"], ["numeric_claims"], ["citation", "numeric_claims"]])
def test_task_without_a_gating_grader_is_rejected(tmp_path, graders):
    p = _write(tmp_path, "nogate", graders=graders)
    with pytest.raises(ValueError, match="gating"):
        Task.from_dict(yaml.safe_load(p.read_text()))


def test_task_with_a_gating_grader_plus_reporting_graders_is_accepted(tmp_path):
    p = _write(tmp_path, "ok", graders=["exact", "citation", "numeric_claims"])
    assert Task.from_dict(yaml.safe_load(p.read_text())).graders == ["exact", "citation", "numeric_claims"]


def test_every_checked_in_task_still_loads_with_the_gating_rule():
    root = Path(__file__).resolve().parents[1] / "tasks"
    assert len(load_tasks(root, include_needs_human=True)) >= 85
