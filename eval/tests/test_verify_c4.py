"""verify_tasks cho C4: hội thoại tham chiếu pass final_state + conflict_detected (chủ động) + biên dịch được, người dùng không nêu xung đột, sự thật xung đột khớp DB + trang PDF,
mỗi biến thể sai trượt ĐÚNG mã. Cộng với kiểm toàn bộ file C4 thật."""
import copy
from pathlib import Path

import pytest

from eval.context import GradeContext
from eval.schema import load_tasks
from eval.tools import verify_tasks as V

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ctx():
    return GradeContext.load()


@pytest.fixture(scope="module")
def tasks():
    return {t.id: t for t in load_tasks(ROOT / "eval" / "tasks", categories=["C4"], include_needs_human=True)}


def fresh(tasks, tid="C4-001"):
    return copy.deepcopy(tasks[tid])


def test_the_real_c4_file_has_fifteen_tasks_and_no_problems(tasks, ctx):
    assert len(tasks) == 15
    bad = {tid: V.verify_c4(t, ctx) for tid, t in tasks.items()}
    assert {k: v for k, v in bad.items() if v} == {}


def test_split_is_about_thirty_percent_dev_and_covers_several_conflict_families(tasks):
    dev = [t for t in tasks.values() if t.split == "dev"]
    assert len(dev) == 5 and {t.tags[0] for t in dev} >= {"pin_conflict", "no_such_af", "non_ft", "timer_shared", "clock_limit"}
    assert all(3 <= len(t.turns) <= 6 for t in tasks.values())


def test_every_task_has_at_least_one_variant_per_graded_dimension_and_a_planted_conflict(tasks):
    for t in tasks.values():
        kinds = {v["grader"] for v in t.provenance["wrong_variants"]}
        assert kinds == {"final_state", "conflict_detected"}, t.id
        assert t.expected["must_detect"] and all(0 <= m["turn"] < len(t.turns) for m in t.expected["must_detect"]), t.id


def test_a_user_turn_that_already_raises_the_conflict_is_a_problem(tasks, ctx):
    t = fresh(tasks)
    t.turns[1]["user"] += " Note that PA8 is already used by the PWM output, so I2C3_SCL cannot also be placed on PA8."
    assert any("already raises PIN_CONFLICT:PA8" in p for p in V.verify_c4(t, ctx))


def test_conventions_of_the_first_and_last_turn_are_checked(tasks, ctx):
    t = fresh(tasks)
    t.turns[0]["user"] = t.turns[0]["user"].replace("CMSIS", "register")
    assert any("first turn must mention 'CMSIS'" in p for p in V.verify_c4(t, ctx))
    t = fresh(tasks)
    t.turns[-1]["user"] = "Please send the final code."
    probs = V.verify_c4(t, ctx)
    assert any("last turn must ask for the 'complete'" in p for p in probs) and any("'C code block'" in p for p in probs)


def test_a_reference_conversation_that_fails_a_grader_is_a_problem(tasks, ctx):
    t = fresh(tasks)
    t.provenance["reference_solution"]["turns"][2] = t.provenance["reference_solution"]["turns"][2].replace("GPIOC->OTYPER |= GPIO_OTYPER_OT8 | GPIO_OTYPER_OT9;", "")
    assert any("does not pass final_state" in p for p in V.verify_c4(t, ctx))
    t = fresh(tasks)
    t.provenance["reference_solution"]["turns"][1] = "Here is the I2C3 code."
    assert any("does not pass conflict_detected" in p and "conflict_missed" in p for p in V.verify_c4(t, ctx))


def test_conflict_facts_are_cross_checked_against_the_database(tasks, ctx):
    t = fresh(tasks)
    t.provenance["conflict_facts"] = [{"type": "af", "pin": "PA8", "signal": "I2C3_SCL", "af": 6}]
    assert any("not in the database" in p for p in V.verify_c4(t, ctx))
    t.provenance["conflict_facts"] = [{"type": "no_af", "pin": "PA8", "signal": "I2C3_SCL"}]
    assert any("is false" in p for p in V.verify_c4(t, ctx))
    t.provenance["conflict_facts"] = [{"type": "ft", "pin": "PA8", "tolerant": False}]
    assert any("does not match the database" in p for p in V.verify_c4(t, ctx))
    t.provenance["conflict_facts"] = []
    assert any("conflict_facts is missing" in p for p in V.verify_c4(t, ctx))


def test_variants_must_fail_the_named_grader_with_the_expected_code(tasks, ctx):
    t = fresh(tasks)
    t.provenance["wrong_variants"][0]["expect"] = ["sim_violation:SIM-TIM-MOE"]
    assert any(t.provenance["wrong_variants"][0]["name"] in p and "expected fail code" in p for p in V.verify_c4(t, ctx))
    t = fresh(tasks)
    t.provenance["wrong_variants"] = [{"name": "harmless", "grader": "final_state", "edits": [{"turn": 2, "find": "TIM1->PSC = 0;", "replace": "TIM1->PSC = 0; /* same */"}], "expect": []},
                                      {"name": "needs_both", "grader": "conflict_detected", "edits": [{"turn": 1, "find": "Two things to flag before the code:", "replace": "Two things:"}], "expect": []}]
    probs = V.verify_c4(t, ctx)
    assert any("harmless" in p and "should fail final_state but passes" in p for p in probs) and any("needs_both" in p and "should fail conflict_detected but passes" in p for p in probs)
    t = fresh(tasks)
    t.provenance["wrong_variants"] = [v for v in t.provenance["wrong_variants"] if v["grader"] != "conflict_detected"]
    assert any("no wrong_variants with grader 'conflict_detected'" in p for p in V.verify_c4(t, ctx))
    t = fresh(tasks)
    t.provenance["wrong_variants"][0]["edits"] = [{"turn": 2, "find": "text that is not there", "replace": "x"}]
    assert any("edit text not found" in p for p in V.verify_c4(t, ctx))


def test_a_wrong_variant_without_expect_is_a_problem(tasks, ctx):
    t = fresh(tasks)
    t.provenance["wrong_variants"][0].pop("expect")
    assert any("non-empty `expect`" in p for p in V.verify_c4(t, ctx))


def test_a_valid_alternative_fix_must_pass_final_state(tasks, ctx):
    """valid_variants: cách sửa hợp lệ khác lời giải tham chiếu mà spec loại oan => vấn đề của task."""
    t = fresh(tasks, "C4-014")
    assert t.provenance["valid_variants"], "C4-014 documents the TX+RX-on-PA9/PA10 alternative"
    assert V.verify_c4(t, ctx) == []
    t.expected["spec"][0]["tx_pin"] = "PC4"                       # spec cũ (loại oan cách sửa PA9/PA10)
    assert any("valid alternative fix is rejected" in p for p in V.verify_c4(t, ctx))


def test_c4_010_accepts_both_directions_of_the_pin_fix(tasks, ctx):
    t = tasks["C4-010"]
    assert {v["name"] for v in t.provenance["valid_variants"]} == {"pwm_moved_to_pd12_pd13_usart1_keeps_pb6_pb7"}
    assert V.verify_c4(t, ctx) == []
