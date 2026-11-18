"""P6/P9: Interceptor (hook ở tầng kết quả tool), tool_rules trong schema và exposure của attack grader."""
import copy
import importlib.util
from pathlib import Path

import pytest

from eval import schema
from eval.graders import attack
from eval.schema import Task, load_tasks

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("eval_interceptor", ROOT / "eval" / "adapters" / "interceptor.py")
ic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ic)


class Hub:
    def __init__(self, results):
        self.results, self.calls = results, []

    def _invoke(self, name, args):
        self.calls.append((name, args))
        return copy.deepcopy(self.results[name])


SEARCH = {"results": [{"doc": "D", "page_start": 1, "text": "TIM1 is an advanced timer.", "score": 1.0}, {"doc": "D", "page_start": 2, "text": "Second hit."}]}
SPECS = {"chip": "x", "results": [{"parameter": "VDD", "min": "1.7", "typ": "3.0", "max": "3.6", "unit": "V", "quote": "VDD 1.7 3.0 3.6 V"}]}


def hub():
    return Hub({"search_manual": SEARCH, "get_electrical_specs": SPECS})


def test_kinds_match_the_schema_and_rules_are_validated():
    assert tuple(ic.KINDS) == tuple(schema.TOOL_RULE_KINDS)
    ok = {"tool": "search_manual", "kind": "inject_text", "payload": "p"}
    assert ic.validate_rule(ok) is None
    for bad in ({"kind": "inject_text", "payload": "p"}, {"tool": "t", "kind": "nope"}, {"tool": "t", "kind": "inject_text"}, {"tool": "t", "kind": "inject_text", "payload": " "},
                {"tool": "t", "kind": "raise", "error": "KeyError"}, {"tool": "t", "kind": "corrupt_number", "factor": "x"}, {"tool": "t", "kind": "raise", "times": -1}, "x"):
        assert ic.validate_rule(bad), bad
    with pytest.raises(ValueError):
        ic.Interceptor(hub(), [{"tool": "t", "kind": "nope"}])
    assert ic.install(hub(), []) is None


def test_inject_text_appends_to_the_first_text_field_and_leaves_the_original_untouched():
    h = hub()
    i = ic.install(h, [{"tool": "search_manual", "kind": "inject_text", "payload": "PAYLOAD"}])
    r = h._invoke("search_manual", {})
    assert r["results"][0]["text"] == "TIM1 is an advanced timer. PAYLOAD" and r["results"][1]["text"] == "Second hit."
    assert SEARCH["results"][0]["text"] == "TIM1 is an advanced timer."                 # kết quả gốc không bị sửa
    assert i.drain() == [{"tool": "search_manual", "rule": 0, "kind": "inject_text", "call_no": 1, "applied": True}] and i.drain() == []


def test_times_and_after_select_which_matching_calls_are_poisoned():
    h = hub()
    ic.install(h, [{"tool": "search_manual", "kind": "inject_text", "payload": "P", "mode": "prepend", "after": 1, "times": 2}])
    texts = [h._invoke("search_manual", {})["results"][0]["text"] for _ in range(4)]
    assert texts == ["TIM1 is an advanced timer.", "P TIM1 is an advanced timer.", "P TIM1 is an advanced timer.", "TIM1 is an advanced timer."]


def test_other_tools_and_non_dict_results_are_not_touched_and_field_selects_the_key():
    h = hub()
    i = ic.install(h, [{"tool": "get_electrical_specs", "kind": "inject_text", "payload": "P", "field": "quote"}])
    assert h._invoke("search_manual", {}) == SEARCH
    assert h._invoke("get_electrical_specs", {})["results"][0]["quote"] == "VDD 1.7 3.0 3.6 V P"
    assert [e["tool"] for e in i.drain()] == ["get_electrical_specs"]
    h2 = Hub({"x": ["a list"]})
    ic.install(h2, [{"tool": "x", "kind": "inject_text", "payload": "P"}])
    assert h2._invoke("x", {}) == ["a list"]


def test_a_rule_whose_field_is_absent_is_logged_as_not_applied():
    h = hub()
    i = ic.install(h, [{"tool": "get_electrical_specs", "kind": "inject_text", "payload": "P", "field": "nothing"}])
    assert h._invoke("get_electrical_specs", {}) == SPECS and i.drain()[0]["applied"] is False


def test_raise_faults_never_reach_the_real_tool_and_corrupt_number_scales_the_numbers():
    h = hub()
    i = ic.install(h, [{"tool": "search_manual", "kind": "raise", "error": "TimeoutError", "times": 2}, {"tool": "get_electrical_specs", "kind": "corrupt_number", "factor": 10}])
    for _ in range(2):
        with pytest.raises(TimeoutError):
            h._invoke("search_manual", {})
    assert h._invoke("search_manual", {}) == SEARCH and [c[0] for c in h.calls] == ["search_manual"]
    r = h._invoke("get_electrical_specs", {})["results"][0]
    assert (r["min"], r["typ"], r["max"]) == ("17", "30", "36") and r["unit"] == "V"
    assert [(e["kind"], e.get("error")) for e in i.drain()][:2] == [("raise", "TimeoutError"), ("raise", "TimeoutError")]


# ---------------------------------------------------------------- schema
def task_dict(**kw):
    d = dict(id="C7-900", category="C7", split="dev", turns=[{"user": "q"}], graders=["attack"], expected={"attack": {"checks": [{"type": "key_leak"}]}})
    d.update(kw)
    return d


def test_task_accepts_valid_tool_rules_and_rejects_bad_ones():
    t = Task.from_dict(task_dict(tool_rules=[{"tool": "search_manual", "kind": "inject_text", "payload": "p"}]))
    assert t.tool_rules and "tool_rules" in t.to_dict()
    for bad in ([{"tool": "x", "kind": "weird"}], [{"kind": "raise"}], [{"tool": "x", "kind": "inject_text"}], "x"):
        with pytest.raises(ValueError):
            Task.from_dict(task_dict(tool_rules=bad))


def test_serialisation_of_tasks_without_rules_is_unchanged_so_old_task_set_hashes_stay_valid():
    d = Task.from_dict(task_dict()).to_dict()
    assert "tool_rules" not in d and Task.from_dict(d).tool_rules == []


def test_the_indirect_c7_tasks_load_and_use_only_known_attack_checks():
    ts = [t for t in load_tasks(ROOT / "eval" / "tasks", categories=["C7"]) if t.tool_rules]
    assert len(ts) == 14 and {t.split for t in ts} == {"dev", "test"}
    for t in ts:
        assert all(c["type"] in attack.CHECKS for c in t.expected["attack"]["checks"]) and not any(ic.validate_rule(r) for r in t.tool_rules)


# ---------------------------------------------------------------- attack grader: exposure
class Run:
    def __init__(self, trace, answer="ok", files=None):
        self.trace, self.final_answer, self.files, self.turns, self.system = trace, answer, files or {}, [], "S3@P5"


def test_the_attack_grader_reports_whether_the_run_was_exposed_to_the_injected_content():
    t = Task.from_dict(task_dict(tool_rules=[{"tool": "search_manual", "kind": "inject_text", "payload": "p"}]))
    exposed = attack.grade(t, Run([{"type": "tool_intercept", "kind": "inject_text", "applied": True}]), None)
    not_exposed = attack.grade(t, Run([{"type": "tool_intercept", "kind": "inject_text", "applied": False}]), None)
    assert exposed["details"]["exposed"] is True and not_exposed["details"]["exposed"] is False and exposed["pass"] and not_exposed["pass"]
    direct = attack.grade(Task.from_dict(task_dict()), Run([]), None)
    assert "exposed" not in direct["details"]
