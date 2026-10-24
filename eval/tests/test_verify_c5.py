"""verify_tasks cho C5 (fixture tí hon eval/tests/fixtures/c5): lời giải tham chiếu pass checklist (+ functional_sim), biến thể sai trượt ĐÚNG các mục,
giá trị ẩn không lộ trong đề, câu trả lời clarify khớp value_patterns của chính nó, biến thể oracle-info suy ra đúng."""
import copy
from pathlib import Path

from eval import schema
from eval.context import GradeContext
from eval.schema import load_tasks
from eval.tools import verify_tasks as V

FIX = Path(__file__).parent / "fixtures" / "c5"
CTX = GradeContext(manifest=[])
TASKS = {t.id: t for t in load_tasks(FIX)}


def fresh(tid="C5-901"):
    return copy.deepcopy(TASKS[tid])


def test_the_fixture_tasks_verify_clean_and_dispatch_through_verify_task():
    for t in TASKS.values():
        assert V.verify_c5(t, CTX) == [], t.id
        assert V.verify_task(t, CTX) == []


def test_a_reference_answer_that_fails_the_checklist_or_functional_sim_is_a_problem():
    t = fresh()
    ref = t.provenance["reference_solution"]
    ref["answer"] = ref["answer"].replace("(1U << RCC_PLLCFGR_PLLM_Pos)", "(0U << RCC_PLLCFGR_PLLM_Pos)")
    probs = V.verify_c5(t, CTX)
    assert any("does not pass checklist" in p and "item pll" in p for p in probs)
    t = fresh()
    t.provenance["reference_solution"]["answer"] = t.provenance["reference_solution"]["answer"].replace("    RCC->CR |= RCC_CR_HSEON;\n", "")
    assert any("does not pass functional_sim" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.provenance["reference_solution"] = {"turns": ["x"]}
    assert any("reference_solution.answer" in p for p in V.verify_c5(t, CTX))


def test_wrong_variants_must_fail_exactly_the_declared_items():
    t = fresh()
    t.provenance["wrong_variants"][0]["must_fail"] = ["pll", "steps"]
    assert any("guessed_25mhz_crystal" in p and "fails checklist items ['pll']" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.provenance["wrong_variants"][1]["must_fail"] = ["pll"]
    assert any("pll_on_hsi_three_steps" in p and "must_fail is ['pll']" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.provenance["wrong_variants"][0]["answer"] = t.provenance["reference_solution"]["answer"]
    assert any("identical to the reference" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.provenance["wrong_variants"][0]["must_fail"] = ["no_such_item"]
    assert any("unknown checklist item" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.provenance["wrong_variants"][0].pop("must_fail")
    assert any("non-empty `must_fail`" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.provenance["wrong_variants"] = []
    assert any("no wrong_variants" in p for p in V.verify_c5(t, CTX))


def test_a_harmless_variant_that_passes_everything_is_a_problem():
    t = fresh()
    t.provenance["wrong_variants"][0]["answer"] = t.provenance["reference_solution"]["answer"] + "\nThanks."
    assert any("fails checklist items []" in p for p in V.verify_c5(t, CTX))


def test_hidden_values_must_not_appear_in_the_user_turns():
    t = fresh()
    t.turns[0]["user"] += " The crystal is 8 MHz."
    assert any("user turn 0 already reveals hidden_info 'hse_hz'" in p for p in V.verify_c5(t, CTX))


def test_the_clarify_answer_must_match_its_own_value_patterns_and_patterns_are_required():
    t = fresh()
    t.human_policy["clarify"]["hse_hz"] = "It is a 25 MHz crystal."
    assert any("does not match its own value_patterns" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.hidden_info[0]["value_patterns"] = []
    assert any("has no value_patterns" in p for p in V.verify_c5(t, CTX))


def test_structure_rules_clarify_grader_steps_and_reference_calc():
    t = fresh()
    t.graders = ["checklist", "functional_sim"]
    assert any("must list the clarify grader" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.expected["checklist"] = [i for i in t.expected["checklist"] if i["type"] != "bullets_min"]
    for v in t.provenance["wrong_variants"]:
        v["must_fail"] = [m for m in v["must_fail"] if m != "steps"]
    assert any("bullets_min item with count >= 5" in p for p in V.verify_c5(t, CTX))
    t = fresh()
    t.provenance["reference_calc"] = "short"
    assert any("reference_calc" in p for p in V.verify_c5(t, CTX))


def test_a_broken_oracle_derivation_is_caught(monkeypatch):
    real = schema.derive_oracle

    def broken(task):
        o = real(task)
        o.graders = [*o.graders, "clarify"]
        return o

    monkeypatch.setattr(schema, "derive_oracle", broken)
    assert any("oracle-info variant is not derived as specified" in p for p in V.verify_c5(fresh(), CTX))


def test_the_derived_oracle_variant_itself_verifies_clean():
    o = load_tasks(FIX, oracle=True)[1]
    assert o.id == "C5-901-O" and V.verify_c5(o, CTX) == []


def test_verify_main_runs_on_the_fixture_directory(capsys, monkeypatch):
    monkeypatch.setattr(V.GradeContext, "load", classmethod(lambda cls: CTX))
    assert V.main(["--tasks", str(FIX), "--categories", "C5", "--include-needs-human"]) == 0
    assert "2 task kiểm tra, 0 vấn đề" in capsys.readouterr().out
