"""verify_tasks cho C3: lời giải tham chiếu phải pass functional_sim (+ compile ok), có phép tính tay và bằng chứng trang, đề nêu quy ước D20,
mỗi biến thể sai phải trượt ĐÚNG mã. Cộng với kiểm toàn bộ file task C3 thật."""
import copy
import shutil
from pathlib import Path

import pytest

from eval.context import GradeContext
from eval.schema import Task, load_tasks
from eval.tools import verify_tasks as V

ROOT = Path(__file__).resolve().parents[2]
CODE = """#include "stm32g4xx.h"
int main(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8) | GPIO_MODER_MODE8_1;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL8) | (6U << GPIO_AFRH_AFSEL8_Pos);
    TIM1->PSC = 0;
    TIM1->ARR = 8499;
    TIM1->CCR1 = 2125;
    TIM1->CCMR1 = (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER = TIM_CCER_CC1E;
    TIM1->BDTR = TIM_BDTR_MOE;
    TIM1->CR1 = TIM_CR1_CEN;
    while (1) { }
}
"""
TEXT = ("Write bare-metal C for the STM32G474 that accesses registers the CMSIS way (e.g. `TIM1->PSC = ...;`) using the names of ST's `stm32g4xx.h`. "
        "Do not use HAL or LL drivers, `SystemCoreClock` or any other library function. Initial state: SYSCLK = 170 MHz. Task: PWM 20 kHz 25 % on PA8 with TIM1 channel 1. "
        "Answer with one complete C code block (`#include \"stm32g4xx.h\"`, then a `main()` that ends with `while (1)`), followed by a short explanation.")


def make(**over):
    d = dict(id="C3-900", category="C3", split="dev", turns=[{"user": TEXT}], graders=["functional_sim", "compile"], chips=["stm32g474"],
             expected={"initial": "sysclk_170mhz_pll_hsi16_apb_div1", "spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1}]},
             provenance={"reference_solution": CODE, "reference_calc": "170e6 / 20e3 = 8500 nhịp => ARR = 8499; 25 % x 8500 = 2125 (RM0440 p.1179). PA8 = AF6 (DS p.73).",
                         "evidence": [{"doc_id": "STM32G474_RM0440", "page": 1179, "contains": ["high as long as TIMx_CNT < TIMx_CCRx"]}],
                         "wrong_variants": [{"name": "no_moe", "patches": [{"find": "TIM1->BDTR = TIM_BDTR_MOE;", "replace": ""}], "expect": ["sim_violation:SIM-TIM-MOE"]}]},
             review_status="verified")
    d.update(over)
    return Task.from_dict(d)


@pytest.fixture(scope="module")
def ctx():
    return GradeContext.load()


def test_a_well_formed_task_has_no_problems(ctx):
    assert V.verify_c3(make(), ctx) == []


def test_missing_reference_solution_or_hand_calculation_is_a_problem(ctx):
    t = make()
    del t.provenance["reference_solution"]
    assert any("reference_solution" in p for p in V.verify_c3(t, ctx))
    t = make()
    t.provenance["reference_calc"] = "ok"
    assert any("reference_calc" in p for p in V.verify_c3(t, ctx))


def test_a_reference_solution_that_does_not_pass_is_a_problem(ctx):
    t = make()
    t.provenance["reference_solution"] = CODE.replace("TIM1->BDTR = TIM_BDTR_MOE;", "")
    probs = V.verify_c3(t, ctx)
    assert any("reference solution" in p and "SIM-TIM-MOE" in p for p in probs)


def test_a_variant_that_wrongly_passes_is_a_problem(ctx):
    t = make()
    t.provenance["wrong_variants"] = [{"name": "harmless", "patches": [{"find": "TIM1->PSC = 0;", "replace": "TIM1->PSC = 0; /* same */"}], "expect": []}]
    assert any("harmless" in p and "should fail" in p for p in V.verify_c3(t, ctx))


def test_a_variant_must_fail_with_the_expected_code(ctx):
    t = make()
    t.provenance["wrong_variants"] = [{"name": "no_moe", "patches": [{"find": "TIM1->BDTR = TIM_BDTR_MOE;", "replace": ""}], "expect": ["sim_violation:SIM-GPIO-AF"]}]
    assert any("no_moe" in p and "SIM-GPIO-AF" in p for p in V.verify_c3(t, ctx))


def test_a_patch_that_does_not_apply_is_a_problem(ctx):
    t = make()
    t.provenance["wrong_variants"] = [{"name": "stale", "patches": [{"find": "NO_SUCH_TEXT", "replace": "x"}], "expect": []}]
    assert any("stale" in p and "patch" in p for p in V.verify_c3(t, ctx))


def test_statement_must_state_the_conventions(ctx):
    for needle in ("CMSIS", "HAL", "Initial state", "C code block"):
        t = make(turns=[{"user": TEXT.replace(needle, "")}])
        assert any(needle in p for p in V.verify_c3(t, ctx)), needle


def test_unknown_initial_preset_and_empty_spec_are_problems(ctx):
    assert any("initial" in p for p in V.verify_c3(make(expected={"initial": "sysclk_999", "spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1, "tol_pct": 1}]}), ctx))
    assert any("spec" in p for p in V.verify_c3(make(expected={"initial": "reset", "spec": []}), ctx))


def test_evidence_snippet_must_be_on_the_cited_page(ctx):
    t = make()
    t.provenance["evidence"] = [{"doc_id": "STM32G474_RM0440", "page": 1179, "contains": ["this sentence is not in the manual"]}]
    assert any("snippet not found" in p for p in V.verify_c3(t, ctx))


def test_c3_tasks_require_evidence(ctx):
    t = make()
    t.provenance["evidence"] = []
    assert any("evidence" in p for p in V.verify_c3(t, ctx))


# ------------------------------------------------------------------ các task C3 thật
def real():
    return load_tasks(ROOT / "eval" / "tasks", categories=["C3"], include_needs_human=True)


def test_there_are_twenty_c3_tasks_with_unique_ids_and_gating_grader():
    tasks = real()
    assert len(tasks) == 20 and len({t.id for t in tasks}) == 20
    assert all("functional_sim" in t.graders and "compile" in t.graders for t in tasks)
    assert all(t.chips == ["stm32g474"] for t in tasks)


def test_split_is_about_thirty_percent_dev_and_covers_every_task_type():
    tasks = real()
    dev = [t for t in tasks if t.split == "dev"]
    assert len(dev) == 6
    assert {t.tags[0] for t in dev} == {"pwm", "combo", "uart", "i2c", "pll"}


def test_every_c3_task_passes_the_full_verification(ctx):
    problems = [p for t in real() for p in V.verify_c3(t, ctx)]
    assert problems == []


def test_every_task_has_at_least_one_classic_wrong_variant():
    for t in real():
        assert t.provenance["wrong_variants"], t.id
        assert all(v["expect"] for v in t.provenance["wrong_variants"] if v["name"] not in {"harmless"}), t.id


def test_prompts_never_leak_register_values():
    # D19/§3: spec chức năng, đề không được nêu giá trị thanh ghi (PSC/ARR/CCR/BRR/TIMINGR/PLLN...) của lời giải
    import re
    for t in real():
        q = t.turns[0]["user"]
        assert not re.search(r"\b(PSC|ARR|CCR\d|BRR|PLLN|PLLM)\s*=\s*\d", q), t.id
        assert "0x30420F13" not in q
