"""schema (P5): trường C5 `human_policy` / `hidden_info`, grader `checklist` (gate) + `clarify` (không gate), mục checklist được kiểm từng
khoá khi nạp, khoá `hse_hz` của spec clock, và biến thể `oracle-info` (`C5-xxx-O`) suy ra tất định (plan/P5_interfaces.md §3)."""
import copy
from pathlib import Path

import pytest
import yaml

from eval.schema import GATING_GRADERS, GRADERS, ORACLE_PREFIX, Task, derive_oracle, is_hitl_task, load_tasks

FIX = Path(__file__).parent / "fixtures" / "c5"


def base(**kw):
    d = copy.deepcopy(yaml.safe_load((FIX / "c5_tiny.yaml").read_text(encoding="utf-8"))[0])
    d.update(kw)
    return d


def item(**kw):
    return {"id": "x", "type": "mentions", "desc": "d", "any_of": ["a"], **kw}


def with_checklist(*items):
    d = base()
    d["expected"]["checklist"] = list(items)
    return d


# ------------------------------------------------------------------ đăng ký grader
def test_checklist_gates_and_clarify_does_not():
    assert {"checklist", "clarify"} <= GRADERS
    assert "checklist" in GATING_GRADERS and "clarify" not in GATING_GRADERS
    assert "hitl" not in GRADERS and "hitl" not in GATING_GRADERS            # như `process`: chỉ báo cáo, không khai báo trong task


def test_a_c5_task_with_only_clarify_has_no_gating_grader():
    with pytest.raises(ValueError, match="gating"):
        Task.from_dict(base(graders=["clarify"]))


# ------------------------------------------------------------------ fixture + roundtrip
def test_the_fixture_loads_and_roundtrips_with_the_new_fields():
    t = Task.from_dict(base())
    assert t.human_policy["clarify"] == {"hse_hz": "The board has an 8 MHz crystal on HSE."}
    assert t.hidden_info[0]["id"] == "hse_hz" and t.hidden_info[0]["required"] is True
    assert Task.from_dict(t.to_dict()) == t


def test_old_tasks_get_empty_defaults():
    t = Task(id="C1-001", category="C1", split="dev", turns=[{"user": "q"}], graders=["exact"])
    assert t.human_policy == {} and t.hidden_info == [] and not is_hitl_task(t)


def test_hitl_tasks_are_c5_or_tasks_with_a_policy_or_hidden_info():
    assert is_hitl_task(Task.from_dict(base()))
    assert is_hitl_task(Task.from_dict(base(human_policy={}, hidden_info=[])))           # C5 đủ thông tin, không khai policy
    t = Task(id="C2-001", category="C2", split="dev", turns=[{"user": "q"}], graders=["keyfacts"], human_policy={"approval": "approve"})
    assert is_hitl_task(t)


# ------------------------------------------------------------------ human_policy / hidden_info
@pytest.mark.parametrize("policy", [
    {"approval": "maybe"}, {"approval": {"reject": ""}}, {"approval": {"approve": "x"}}, {"choice": {"prefer": ""}}, {"choice": "level shifter"},
    {"choice": {"prefer": "x", "other": 1}}, {"clarify": ["hse_hz"]}, {"clarify": {"hse_hz": ""}}, {"max_answers": -1}, {"max_answers": "3"},
    {"max_answers": True}, {"unknown_key": 1}])
def test_bad_human_policy_is_rejected(policy):
    d = base()
    d["human_policy"] = {"clarify": d["human_policy"]["clarify"], **policy}
    with pytest.raises(ValueError, match="human_policy"):
        Task.from_dict(d)


@pytest.mark.parametrize("approval", ["approve", "reject", {"reject": "Use a smaller file name."}])
def test_valid_approval_forms(approval):
    d = base()
    d["human_policy"]["approval"] = approval
    assert Task.from_dict(d).human_policy["approval"] == approval


def test_clarify_keys_must_be_hidden_info_ids():
    d = base()
    d["human_policy"]["clarify"]["baud"] = "115200"
    with pytest.raises(ValueError, match="clarify.*hidden_info"):
        Task.from_dict(d)


def test_every_required_hidden_info_needs_a_clarify_answer_but_an_optional_one_does_not():
    d = base()
    d["hidden_info"].append({"id": "vdd", "keywords": ["supply"], "required": True, "value_patterns": ["3\\.3\\s*V"]})
    with pytest.raises(ValueError, match="vdd"):
        Task.from_dict(d)
    d["hidden_info"][-1]["required"] = False
    assert [h["id"] for h in Task.from_dict(d).hidden_info] == ["hse_hz", "vdd"]


@pytest.mark.parametrize("bad", [
    {"id": "hse_hz", "keywords": []}, {"id": "hse_hz", "keywords": "HSE"}, {"id": "hse_hz", "keywords": ["HSE", ""]}, {"id": "hse_hz", "keywords": [3]},
    {"id": "", "keywords": ["x"]}, {"id": "hse_hz", "keywords": ["x"], "value_patterns": ["("]}, {"id": "hse_hz", "keywords": ["x"], "required": "yes"},
    {"id": "hse_hz", "keywords": ["x"], "values": ["8"]}, {"keywords": ["x"]}])
def test_bad_hidden_info_is_rejected(bad):
    d = base()
    d["hidden_info"] = [bad]
    with pytest.raises(ValueError, match="hidden_info"):
        Task.from_dict(d)


def test_hidden_info_ids_are_unique():
    d = base()
    d["hidden_info"].append(copy.deepcopy(d["hidden_info"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        Task.from_dict(d)


def test_required_defaults_to_true():
    d = base()
    del d["hidden_info"][0]["required"]
    assert Task.from_dict(d).hidden_info[0]["required"] is True
    d["human_policy"]["clarify"] = {}
    with pytest.raises(ValueError, match="hse_hz"):
        Task.from_dict(d)


# ------------------------------------------------------------------ expected.checklist
def test_checklist_grader_needs_a_non_empty_checklist():
    d = base()
    del d["expected"]["checklist"]
    with pytest.raises(ValueError, match="checklist"):
        Task.from_dict(d)
    with pytest.raises(ValueError, match="checklist"):
        Task.from_dict(with_checklist())


@pytest.mark.parametrize("bad", [
    item(type="vibes"), item(desc=""), {"id": "x", "type": "mentions", "any_of": ["a"]}, item(any_of=[]), item(any_of="a"), item(any_of=["("]),
    item(extra=1), {"id": "x", "type": "forbids", "desc": "d", "patterns": ["[unclosed"]}, {"id": "x", "type": "forbids", "desc": "d", "any_of": ["a"]},
    {"id": "", "type": "mentions", "desc": "d", "any_of": ["a"]},
    {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(\\d+) mA"], "unit": "mA", "max": 1},            # thiếu nhóm (?P<v>)
    {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)"], "unit": "furlong", "max": 1},
    {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)"], "max": 1},                          # không có (?P<u>) thì phải có unit
    {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)"], "unit": "mA"},                      # không có min lẫn max
    {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)"], "unit": "mA", "max": 1, "match": "most"},
    {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)"], "unit": "mA", "max": 1, "unit_out": "MHz"},
    {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)"], "unit": "mA", "max": "1"},
    {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)"], "unit": "mA", "min": 2, "max": 1},
    {"id": "p", "type": "pll", "desc": "d", "sysclk_hz": 170000000},
    {"id": "p", "type": "pll", "desc": "d", "hse_hz": 0, "sysclk_hz": 170000000},
    {"id": "p", "type": "pll", "desc": "d", "hse_hz": 8000000, "sysclk_hz": 170000000, "tol_pct": -1},
    {"id": "g", "type": "one_of_groups", "desc": "d", "groups": [["a"], []], "min_groups": 1},
    {"id": "g", "type": "one_of_groups", "desc": "d", "groups": [["a"], ["b"]], "min_groups": 3},
    {"id": "g", "type": "one_of_groups", "desc": "d", "groups": [["a"], ["("]], "min_groups": 1},
    {"id": "b", "type": "bullets_min", "desc": "d", "count": 0},
    {"id": "b", "type": "bullets_min", "desc": "d", "count": 2.5}])
def test_bad_checklist_items_are_rejected(bad):
    with pytest.raises(ValueError, match="checklist"):
        Task.from_dict(with_checklist(bad))


def test_checklist_item_ids_are_unique():
    with pytest.raises(ValueError, match="duplicate"):
        Task.from_dict(with_checklist(item(), item(any_of=["b"])))


def test_valid_items_of_every_type_load():
    t = Task.from_dict(with_checklist(
        item(id="m"), {"id": "f", "type": "forbids", "desc": "d", "patterns": ["x"]},
        {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+(?:\\.\\d+)?)\\s*(?P<u>[uµm]A)"], "unit": "uA", "max": 0.00001,
         "match": "all", "required": True},
        {"id": "q2", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)\\s*MHz"], "unit": "MHz", "unit_out": "MHz", "max": 170},
        {"id": "p", "type": "pll", "desc": "d", "hse_hz": 8000000, "sysclk_hz": 170000000, "tol_pct": 0.1},
        {"id": "g", "type": "one_of_groups", "desc": "d", "groups": [["a"], ["b"]], "min_groups": 2},
        {"id": "b", "type": "bullets_min", "desc": "d", "count": 5}))
    assert [i["type"] for i in t.expected["checklist"]] == ["mentions", "forbids", "quantity", "quantity", "pll", "one_of_groups", "bullets_min"]


# ------------------------------------------------------------------ clock spec: hse_hz
def test_clock_spec_accepts_a_positive_integer_hse_hz():
    assert Task.from_dict(base()).expected["spec"][0]["hse_hz"] == 8000000


@pytest.mark.parametrize("bad", [0, -8000000, 8.5e6, "8 MHz", True])
def test_clock_spec_hse_hz_must_be_a_positive_integer(bad):
    d = base()
    d["expected"]["spec"][0]["hse_hz"] = bad
    with pytest.raises(ValueError, match="hse_hz"):
        Task.from_dict(d)


def test_conflicting_hse_hz_between_expected_and_the_clock_spec_is_rejected():
    d = base()
    d["expected"]["hse_hz"] = 24000000
    with pytest.raises(ValueError, match="hse_hz"):
        Task.from_dict(d)
    d["expected"]["hse_hz"] = 8000000
    Task.from_dict(d)


def test_hse_hz_is_still_not_allowed_on_a_pwm_item():
    d = base()
    d["expected"]["spec"].append({"type": "pwm", "pin": "PA8", "freq_hz": 1000, "hse_hz": 8000000})
    with pytest.raises(ValueError, match="unknown spec key"):
        Task.from_dict(d)


# ------------------------------------------------------------------ oracle-info
def test_derive_oracle_follows_the_contract_exactly():
    t = Task.from_dict(base())
    o = derive_oracle(t)
    assert o.id == "C5-901-O" and o.split == t.split and o.category == "C5"
    assert o.turns[0]["user"] == t.turns[0]["user"] + ORACLE_PREFIX + "The board has an 8 MHz crystal on HSE."
    assert ORACLE_PREFIX == " Additional information from the user: "
    assert o.human_policy["clarify"] == {} and o.human_policy["approval"] == "approve" and o.human_policy["max_answers"] == 3
    assert o.graders == ["checklist", "functional_sim"] and o.tags == [*t.tags, "oracle_info"]
    assert o.hidden_info == [] and o.expected == t.expected
    assert t.human_policy["clarify"] and t.turns[0]["user"] != o.turns[0]["user"]          # task gốc không bị sửa
    assert derive_oracle(t) == o                                                           # tất định


def test_oracle_joins_answers_in_hidden_info_order_and_skips_items_without_an_answer():
    d = base()
    d["hidden_info"] = [{"id": "vdd", "keywords": ["supply"], "value_patterns": ["1\\.8"]}, d["hidden_info"][0],
                        {"id": "opt", "keywords": ["colour"], "required": False}]
    d["human_policy"]["clarify"] = {"hse_hz": "8 MHz crystal.", "vdd": "The sensor runs at 1.8 V."}
    o = derive_oracle(Task.from_dict(d))
    assert o.turns[0]["user"].endswith(ORACLE_PREFIX + "The sensor runs at 1.8 V. 8 MHz crystal.")


def test_a_multi_turn_task_only_extends_the_first_turn():
    d = base(turns=[{"user": "Goal."}, {"user": "Now write the code."}])
    o = derive_oracle(Task.from_dict(d))
    assert o.turns == [{"user": "Goal." + ORACLE_PREFIX + "The board has an 8 MHz crystal on HSE."}, {"user": "Now write the code."}]


def test_complete_info_tasks_have_no_oracle_variant():
    t = Task.from_dict(yaml.safe_load((FIX / "c5_tiny.yaml").read_text(encoding="utf-8"))[1])
    with pytest.raises(ValueError, match="hidden_info"):
        derive_oracle(t)


def test_load_tasks_returns_base_tasks_by_default_and_oracle_variants_on_request():
    assert [t.id for t in load_tasks(FIX)] == ["C5-901", "C5-902"]
    assert [t.id for t in load_tasks(FIX, oracle=True)] == ["C5-901", "C5-901-O", "C5-902"]
    assert [t.id for t in load_tasks(FIX, split="dev", oracle=True)] == ["C5-901", "C5-901-O"]
    assert [t.id for t in load_tasks(FIX, split="test", oracle=True)] == ["C5-902"]
    assert [t.id for t in load_tasks(FIX, categories=["C1"], oracle=True)] == []


def test_a_hand_written_task_cannot_collide_with_a_derived_oracle_id(tmp_path):
    d = base()
    clash = base(id="C5-901-O")
    (tmp_path / "x.yaml").write_text(yaml.safe_dump([d, clash]), encoding="utf-8")
    load_tasks(tmp_path)                                                                 # không có oracle: hai id khác nhau
    with pytest.raises(ValueError, match="duplicate"):
        load_tasks(tmp_path, oracle=True)


def test_needs_human_filter_applies_to_the_derived_variant(tmp_path):
    (tmp_path / "x.yaml").write_text(yaml.safe_dump([base(review_status="needs_human")]), encoding="utf-8")
    assert load_tasks(tmp_path, oracle=True) == []
    assert [t.id for t in load_tasks(tmp_path, oracle=True, include_needs_human=True)] == ["C5-901", "C5-901-O"]


def test_pll_source_key_is_validated():
    pll = {"id": "p", "type": "pll", "desc": "d", "hse_hz": 16000000, "sysclk_hz": 170000000}
    assert Task.from_dict(with_checklist({**pll, "source": "HSI16"})).expected["checklist"][0]["source"] == "HSI16"
    Task.from_dict(with_checklist({**pll, "hse_hz": 8000000, "source": "HSE"}))
    for bad in ({**pll, "source": "MSI"}, {**pll, "hse_hz": 8000000, "source": "HSI16"}):
        with pytest.raises(ValueError, match="checklist"):
            Task.from_dict(with_checklist(bad))


def test_long_time_units_are_known_to_quantity_items():
    item = {"id": "q", "type": "quantity", "desc": "d", "patterns": ["(?P<v>\\d+)\\s*(?P<u>years?|months?|days?|hours?|h)"], "unit_out": "year", "min": 2, "max": 3}
    Task.from_dict(with_checklist(item))
    with pytest.raises(ValueError, match="unit_out"):
        Task.from_dict(with_checklist({**item, "unit_out": "fortnight"}))
