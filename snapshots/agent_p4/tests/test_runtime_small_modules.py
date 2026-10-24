"""Cờ ablation (A1–A4), ScriptedPolicy (chỉ test) và tool điều khiển update_plan / finish."""
import json

import pytest

from agent.llm import LLMResponse
from agent.runtime import control_tools as ct
from agent.runtime.flags import Ablations
from agent.runtime.state import PlanError
from agent.scripted import ScriptedPolicy, SimulatedKill, calls, say, tool


# ---------------------------------------------------------------- Ablations
def test_default_ablations_change_nothing():
    a = Ablations()
    assert a.codes() == () and a.variant() == "" and a.disabled_servers() == () and a.max_repairs(3) == 3
    g = a.gate_flags()
    assert g.g1 and g.g2 and g.g3 and g.g4 and g.g5 and g.board and not g.strict_v1_provenance


@pytest.mark.parametrize("text,codes", [("A1", ("A1",)), ("A1,A3", ("A1", "A3")), (" a4 , a2 ", ("A2", "A4")), ("", ()), (None, ()), (("A3",), ("A3",))])
def test_parse_codes(text, codes):
    assert Ablations.from_codes(text).codes() == codes


def test_unknown_code_is_rejected():
    with pytest.raises(ValueError, match="A9"):
        Ablations.from_codes("A1,A9")


def test_a1_hides_the_planner_and_keeps_the_rest():
    a = Ablations.from_codes("A1")
    assert not a.planner and a.board_state and a.sandbox and a.reflection
    assert a.variant() == "-Planner" and a.hidden_control_tools() == ("update_plan",) and a.disabled_servers() == ()


def test_a2_hides_board_state_and_drops_g3():
    a = Ablations.from_codes("A2")
    assert a.disabled_servers() == ("board-state",) and a.variant() == "-BoardState"
    g = a.gate_flags()
    assert not g.board and not g.g3 and g.g2 and g.g1


def test_a3_hides_the_sandbox_and_falls_back_to_the_v1_verifier():
    a = Ablations.from_codes("A3")
    assert a.disabled_servers() == ("hw-sandbox",) and a.variant() == "-Sandbox"
    g = a.gate_flags()
    assert not g.g2 and not g.g5 and g.strict_v1_provenance and g.g1 and g.g3


def test_a4_sets_the_repair_budget_to_zero():
    a = Ablations.from_codes("A4")
    assert a.max_repairs(3) == 0 and a.variant() == "-Reflection"


def test_combined_variant_name():
    assert Ablations.from_codes("A3,A1").variant() == "-Planner-Sandbox"


# ---------------------------------------------------------------- ScriptedPolicy
def msgs(n_assistant):
    return [{"role": "system", "content": "s"}] + [{"role": "assistant", "content": "x"} for _ in range(n_assistant)]


def test_policy_returns_the_step_matching_the_number_of_assistant_messages():
    p = ScriptedPolicy([say("one"), tool("list_chips"), say("three")])
    assert p.chat(msgs(0), []).content == "one"
    r = p.chat(msgs(1), [])
    assert r.content is None and r.tool_calls == [{"id": "call_1_0", "name": "list_chips", "arguments": {}}]
    assert p.chat(msgs(2), []).content == "three"
    assert p.chat(msgs(0), []).content == "one"                 # chỉ phụ thuộc messages => dùng được sau resume bằng instance mới


def test_policy_supports_parallel_calls_callables_and_usage():
    p = ScriptedPolicy([calls(("a", {"x": 1}), ("b", {})), lambda messages, tools: say(f"saw {len(tools)} tools")])
    r = p.chat(msgs(0), [])
    assert [c["name"] for c in r.tool_calls] == ["a", "b"] and r.tool_calls[0]["arguments"] == {"x": 1}
    assert p.chat(msgs(1), [{"name": "t"}]).content == "saw 1 tools"
    assert r.usage["in"] > 0 and r.usage["out"] > 0 and isinstance(r, LLMResponse)


def test_policy_records_the_tools_offered_and_flags_itself_as_simulated():
    p = ScriptedPolicy([say("x")])
    p.chat(msgs(0), [{"name": "t1"}, {"name": "t2"}])
    assert p.offered == [["t1", "t2"]] and p.simulated is True


def test_exhausted_script_is_loud():
    with pytest.raises(AssertionError, match="script exhausted"):
        ScriptedPolicy([say("x")]).chat(msgs(1), [])


def test_kill_at_raises_a_base_exception_that_ordinary_handlers_do_not_catch():
    p = ScriptedPolicy([say("x"), say("y")], kill_at=1)
    p.chat(msgs(0), [])
    with pytest.raises(SimulatedKill):
        p.chat(msgs(1), [])
    assert not issubclass(SimulatedKill, Exception)


# ---------------------------------------------------------------- control tools
def test_specs_are_valid_tool_schemas():
    for spec in (ct.UPDATE_PLAN_SPEC, ct.FINISH_SPEC):
        assert spec["name"] in ("update_plan", "finish") and len(spec["description"]) > 120
        assert spec["inputSchema"]["type"] == "object" and spec["inputSchema"]["required"]
    assert ct.UPDATE_PLAN_SPEC["inputSchema"]["required"] == ["steps"] and ct.FINISH_SPEC["inputSchema"]["required"] == ["summary"]


def test_parse_update_plan_returns_normalised_steps_and_rationale():
    plan, why = ct.parse_update_plan({"steps": [{"id": "s1", "title": "do it"}], "rationale": "because"})
    assert plan[0]["status"] == "todo" and why == "because"
    with pytest.raises(PlanError):
        ct.parse_update_plan({"steps": []})
    with pytest.raises(PlanError, match="steps"):
        ct.parse_update_plan({})


def test_parse_finish_defaults_and_waivers():
    f = ct.parse_finish({"summary": "the answer"})
    assert f.answer == "the answer" and f.deliverables == [] and f.waived == []
    f = ct.parse_finish({"summary": "a", "deliverables": ["pwm.c"], "waived_requirements": [{"id": "R2", "reason": "SPI is not modelled"}]})
    assert f.deliverables == ["pwm.c"] and f.waived == [{"id": "R2", "reason": "SPI is not modelled"}]
    f = ct.parse_finish({"summary": "a", "waived_requirements": json.dumps([{"id": "R2", "reason": "x"}])})
    assert f.waived[0]["id"] == "R2"


@pytest.mark.parametrize("args,msg", [
    ({}, "summary"),
    ({"summary": "   "}, "summary"),
    ({"summary": "a", "waived_requirements": [{"id": "R2"}]}, "reason"),
    ({"summary": "a", "waived_requirements": "nope"}, "waived_requirements"),
    ({"summary": "a", "deliverables": "x.c"}, "deliverables"),
])
def test_parse_finish_rejects_bad_input(args, msg):
    with pytest.raises(ct.FinishError, match=msg):
        ct.parse_finish(args)
