"""AgentState (serialize JSON), kế hoạch (chuẩn hoá + diff), ngân sách, bộ đếm lỗi, và CheckpointStore (SQLite, resume)."""
import json
import sqlite3

import pytest

from agent.runtime.checkpoint import CheckpointStore
from agent.runtime.state import (AgentState, Budgets, PlanError, diff_plans, normalize_plan)


def make_state(**kw):
    return AgentState.new(run_id="r1", project_id="p1", goal="PWM 20 kHz on PA8", turn=0, **kw)


# ---------------------------------------------------------------- AgentState
def test_new_state_has_the_fields_of_the_brief():
    s = make_state()
    assert (s.run_id, s.project_id, s.goal, s.turn, s.status) == ("r1", "p1", "PWM 20 kHz on PA8", 0, "INTAKE")
    assert s.messages == [] and s.plan == [] and s.artifacts == [] and s.iteration_counters == {}
    assert set(s.budgets) == {"steps", "tokens", "usd", "wall_s"}
    assert set(s.used) >= {"steps", "tokens_in", "tokens_out", "usd", "wall_s", "llm_calls", "tool_calls"}


def test_state_round_trips_through_json_exactly():
    s = make_state()
    s.messages = [{"role": "user", "content": "hi"},
                  {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "extra_content": {"google": {"thought_signature": "abc"}},
                                                                        "function": {"name": "t", "arguments": "{}"}}]}]
    s.plan = [{"id": "s1", "title": "x", "status": "todo", "depends_on": [], "acceptance": "ok"}]
    s.iteration_counters = {"G2-SIM-TIM-MOE": 2}
    s.pending_calls = [{"id": "c1", "name": "t", "arguments": {"a": [1, 2]}}]
    s.in_flight = {"call_id": "c1", "tool": "set_target"}
    s.used["tokens_in"] = 123
    s2 = AgentState.from_json(s.to_json())
    assert s2 == s and json.loads(s.to_json())["run_id"] == "r1"


def test_from_json_ignores_unknown_future_fields_but_keeps_known_ones():
    d = json.loads(make_state().to_json())
    d["field_from_the_future"] = 1
    assert AgentState.from_json(json.dumps(d)).run_id == "r1"


def test_budget_exceeded_reports_the_first_exhausted_dimension():
    s = make_state(budgets=Budgets(steps=3, tokens=100, usd=1.0, wall_s=10))
    assert s.budget_exceeded() is None
    s.used["steps"] = 3
    assert s.budget_exceeded() == "steps"
    s.used["steps"] = 0
    s.used["tokens_in"], s.used["tokens_out"] = 60, 41
    assert s.budget_exceeded() == "tokens"
    s.used["tokens_in"] = s.used["tokens_out"] = 0
    s.used["usd"] = 1.0
    assert s.budget_exceeded() == "usd"
    s.used["usd"] = 0.0
    s.used["wall_s"] = 10.0
    assert s.budget_exceeded() == "wall_s"


def test_budgets_accept_overrides_and_ignore_none():
    b = Budgets.from_overrides({"steps": 5, "usd": None, "wall_s": 9})
    assert (b.steps, b.wall_s) == (5, 9) and b.usd == Budgets().usd


def test_count_error_returns_the_new_count_per_code():
    s = make_state()
    assert [s.count_error("A"), s.count_error("A"), s.count_error("B"), s.count_error("A")] == [1, 2, 1, 3]
    assert s.iteration_counters == {"A": 3, "B": 1}


# ---------------------------------------------------------------- plan
STEPS = [{"id": "s1", "title": "record requirement", "status": "done", "acceptance": "R1 stored"},
         {"id": "s2", "title": "write code", "status": "doing", "depends_on": ["s1"]}]


def test_normalize_plan_fills_defaults():
    plan = normalize_plan(STEPS)
    assert plan[0] == {"id": "s1", "title": "record requirement", "status": "done", "depends_on": [], "acceptance": "R1 stored"}
    assert plan[1]["depends_on"] == ["s1"] and plan[1]["acceptance"] == ""


def test_normalize_plan_accepts_a_json_string():
    assert [p["id"] for p in normalize_plan(json.dumps(STEPS))] == ["s1", "s2"]


@pytest.mark.parametrize("bad,msg", [
    ([], "at least one step"),
    ("not json", "valid JSON"),
    ([{"id": "s1", "title": "a"}, {"id": "s1", "title": "b"}], "duplicate id"),
    ([{"id": "s1", "title": "a", "status": "finished"}], "status"),
    ([{"id": "s1", "title": "a", "depends_on": ["s9"]}], "unknown step"),
    ([{"id": "s1", "title": ""}], "title"),
    ([{"title": "no id"}], "id"),
    ([{"id": "s1", "title": "a", "depends_on": ["s1"]}], "itself"),
])
def test_normalize_plan_rejects_bad_input_with_a_message(bad, msg):
    with pytest.raises(PlanError, match=msg):
        normalize_plan(bad)


def test_diff_plans_lists_added_removed_and_changed():
    old = normalize_plan(STEPS)
    new = normalize_plan([{"id": "s1", "title": "record requirement", "status": "done", "acceptance": "R1 stored"},
                          {"id": "s2", "title": "write code", "status": "done"},
                          {"id": "s2b", "title": "enable TIM1EN before writing TIM1", "status": "todo"}])
    d = diff_plans(old, new)
    assert d["added"] == ["s2b: enable TIM1EN before writing TIM1"]
    assert d["removed"] == []
    assert d["changed"] == ["s2: status doing -> done, depends_on ['s1'] -> []"]
    assert diff_plans(new, [new[0]])["removed"] == ["s2: write code", "s2b: enable TIM1EN before writing TIM1"]
    assert diff_plans([], new)["added"][0].startswith("s1:")
    assert diff_plans(new, new) == {"added": [], "removed": [], "changed": []}


# ---------------------------------------------------------------- checkpoint store
@pytest.fixture()
def store(tmp_path):
    s = CheckpointStore(tmp_path / "ck.sqlite")
    yield s
    s.close()


def test_save_and_load_returns_an_equal_state(store):
    s = make_state()
    s.messages.append({"role": "user", "content": "x"})
    store.save(s)
    assert store.load("r1") == s
    assert store.load("nope") is None


def test_save_overwrites_the_latest_state(store):
    s = make_state()
    store.save(s)
    s.status = "ACT"
    s.used["steps"] = 4
    store.save(s)
    got = store.load("r1")
    assert got.status == "ACT" and got.used["steps"] == 4


def test_the_checkpoint_survives_reopening_the_database(tmp_path):
    a = CheckpointStore(tmp_path / "ck.sqlite")
    s = make_state()
    s.status = "ACT"
    a.save(s)
    a.close()
    assert CheckpointStore(tmp_path / "ck.sqlite").load("r1").status == "ACT"


def test_unfinished_runs_are_those_not_in_a_terminal_status(store):
    for rid, st in (("a", "ACT"), ("b", "DONE"), ("c", "ESCALATED"), ("d", "REFUSED"), ("e", "FINISH_GATE")):
        s = AgentState.new(run_id=rid, project_id="p", goal="g", turn=0)
        s.status = st
        store.save(s)
    assert sorted(store.unfinished_runs()) == ["a", "e"]


def test_sessions_keep_history_and_plan_between_turns(store):
    assert store.session("p1") == {"history": [], "plan": []}
    store.save_session("p1", [{"turn": 0, "user": "u", "answer": "a", "status": "answered"}], [{"id": "s1", "title": "t", "status": "done", "depends_on": [], "acceptance": ""}])
    got = store.session("p1")
    assert got["history"][0]["answer"] == "a" and got["plan"][0]["id"] == "s1"
    assert store.session("other") == {"history": [], "plan": []}


def test_next_turn_index_counts_finished_turns_of_the_project(store):
    assert store.next_turn("p1") == 0
    store.save_session("p1", [{"turn": 0, "user": "u", "answer": "a", "status": "answered"}], [])
    assert store.next_turn("p1") == 1


def test_the_database_is_a_plain_sqlite_file_with_one_row_per_run(store, tmp_path):
    store.save(make_state())
    store.save(make_state())
    rows = sqlite3.connect(tmp_path / "ck.sqlite").execute("select run_id, status from runs").fetchall()
    assert rows == [("r1", "INTAKE")]
