"""functional_sim: trích khối code C từ câu trả lời → analyze_c_code → simulate_register_writes (bản VENDOR đóng băng, D19) → so `effects` với
`expected.spec` (dung sai `tol_pct`). Lý do trượt có mã. `compile`: báo cáo riêng (không gate TSR)."""
import shutil
import sys
import textwrap

import pytest

from eval.graders import compile as compile_grader
from eval.graders import functional_sim as fs
from eval.schema import RunResult, Task

PRESET = "sysclk_170mhz_pll_hsi16_apb_div1"

PWM = """
#include "stm32g4xx.h"
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
    TIM1->CR1 = TIM_CR1_ARPE | TIM_CR1_CEN;
    while (1) { }
}
"""


def task(spec, initial=PRESET, extra=None, tid="C3-001"):
    exp = {"spec": spec, "initial": initial, **(extra or {})}
    return Task(id=tid, category="C3", split="dev", turns=[{"user": "q"}], graders=["functional_sim", "compile"], expected=exp)


def run(answer):
    return RunResult(system="S0", variant="", task_id="C3-001", seed=1, final_answer=answer, turns=[])


def fenced(code, lang="c"):
    return f"Here is the code:\n```{lang}\n{textwrap.dedent(code).strip()}\n```\nIt configures the timer."


PWM_SPEC = [{"type": "pwm", "pin": "PA8", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1}]


def grade(code, spec=PWM_SPEC, **kw):
    return fs.grade(task(spec, **kw), run(fenced(code)), None)


def reasons(res):
    return [r.split(": ", 1)[0] for r in res["reasons"]]


# ------------------------------------------------------------------ trích khối code
def test_extracts_c_blocks_in_order_and_joins_them():
    ans = "A\n```c\nint a;\n```\ntext\n```C\nint b;\n```\n```bash\nmake\n```\n```\nint c = 1;\n```\n"
    assert fs.extract_c_code(ans).split() == ["int", "a;", "int", "b;", "int", "c", "=", "1;"]


def test_non_c_blocks_and_prose_are_ignored():
    assert fs.extract_c_code("```python\nprint(1)\n```\n```json\n{}\n```\n```text\nhello\n```") == ""
    assert fs.extract_c_code("just prose with TIM1->PSC = 0; inline") == ""


def test_untagged_block_is_kept_only_when_it_looks_like_c():
    assert fs.extract_c_code("```\nTIM1->PSC = 0;\n```").strip() == "TIM1->PSC = 0;"
    assert fs.extract_c_code("```\nSteps: enable the clock then set the prescaler\n```") == ""


def test_an_unterminated_fence_is_still_extracted():
    assert "int x;" in fs.extract_c_code("```c\nint x;\n")


def test_identical_blocks_are_not_repeated():
    assert fs.extract_c_code("```c\nint a;\n```\n```c\nint a;\n```").count("int a;") == 1


def test_cpp_and_h_tags_are_accepted():
    assert "int a;" in fs.extract_c_code("```cpp\nint a;\n```") and "int b;" in fs.extract_c_code("```h\nint b;\n```")


# ------------------------------------------------------------------ chấm
def test_the_reference_pwm_program_passes():
    r = grade(PWM)
    assert r["pass"] is True and r["score"] == 1.0 and r["reasons"] == []
    d = r["details"]
    assert d["blocks"] == 1 and d["ops"] == 11 and d["analysis_ok"] is True
    assert d["matched"][0]["pin"] == "PA8" and d["matched"][0]["pwm_hz"] == pytest.approx(20000)


def test_no_code_block():
    r = fs.grade(task(PWM_SPEC), run("The PWM needs PSC=0 and ARR=8499, CCR1=2125."), None)
    assert r["pass"] is False and reasons(r) == ["no_code"]


@pytest.mark.parametrize("code,fragment", [
    ('#include "stm32g4xx_hal.h"\nint main(void){ HAL_Init(); }', "HAL"),
    ('#include "stm32g4xx.h"\nint main(void){ if (TIM1->SR & TIM_SR_UIF) { TIM1->PSC = 1; } }', "data-dependent"),
])
def test_unsupported_constructs_fail_with_their_code(code, fragment):
    r = grade(code)
    assert r["pass"] is False and reasons(r)[0].startswith("unsupported_construct")
    assert fragment in r["reasons"][0] and r["details"]["analysis_ok"] is False


def test_syntax_errors_and_unknown_symbols_have_distinct_subcodes():
    assert reasons(grade('#include "stm32g4xx.h"\nint main(void){ TIM1->PSC = ; }'))[0] == "unsupported_construct:syntax_error"
    assert reasons(grade('#include "stm32g4xx.h"\nint main(void){ TIM1->CR1 |= TIM_CR1_NOPE; }'))[0] == "unsupported_construct:unknown_symbol"


@pytest.mark.parametrize("edit,code", [
    ("    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;\n", "sim_violation:SIM-CLK-GATE"),
    ("    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;\n", "sim_violation:SIM-CLK-GATE"),
    ("    TIM1->BDTR = TIM_BDTR_MOE;\n", "sim_violation:SIM-TIM-MOE"),
    ("    TIM1->CCER = TIM_CCER_CC1E;\n", "sim_violation:SIM-TIM-CCE"),
])
def test_classic_errors_are_failed_with_the_simulator_code(edit, code):
    r = grade(PWM.replace(edit, ""))
    assert r["pass"] is False and code in reasons(r)


def test_missing_cen_and_wrong_af_and_wrong_moder_codes():
    assert "sim_violation:SIM-TIM-CEN" in reasons(grade(PWM.replace("TIM_CR1_ARPE | TIM_CR1_CEN", "TIM_CR1_ARPE")))
    assert "sim_violation:SIM-GPIO-AF" in reasons(grade(PWM.replace("(6U << GPIO_AFRH_AFSEL8_Pos)", "(2U << GPIO_AFRH_AFSEL8_Pos)")))
    assert "sim_violation:SIM-GPIO-MODE" in reasons(grade(PWM.replace("GPIO_MODER_MODE8_1", "GPIO_MODER_MODE8_0")))


def test_off_by_one_psc_is_a_wrong_frequency_not_a_violation():
    r = grade(PWM.replace("TIM1->PSC = 0;", "TIM1->PSC = 1;"))
    assert r["pass"] is False and reasons(r) == ["wrong_freq"]
    assert "10000" in r["reasons"][0]


def test_wrong_duty():
    r = grade(PWM.replace("TIM1->CCR1 = 2125;", "TIM1->CCR1 = 4250;"))
    assert reasons(r) == ["wrong_duty"]


def test_the_x2_rule_mistake_shows_up_as_wrong_frequency():
    r = grade(PWM.replace("8499", "4249").replace("2125", "1062"), initial="sysclk_170mhz_pll_hsi16_apb2_div2")   # 25 % của 4250 nhịp ≈ 1062
    assert reasons(r) == ["wrong_freq"] and "40000" in r["reasons"][0]


def test_pwm_on_another_pin_is_wrong_pin():
    code = PWM.replace("GPIOA", "GPIOC").replace("GPIO_AFRH_AFSEL8", "GPIO_AFRL_AFSEL0").replace("MODE8", "MODE0").replace("AFR[1]", "AFR[0]") \
              .replace("AHB2ENR_GPIOAEN", "AHB2ENR_GPIOCEN").replace("(6U << GPIO_AFRL_AFSEL0_Pos)", "(2U << GPIO_AFRL_AFSEL0_Pos)")   # PC0 AF2 = TIM1_CH1
    r = grade(code)
    assert r["pass"] is False and reasons(r) == ["wrong_pin"]
    assert "PC0" in r["reasons"][0]


def test_tolerances_are_relative_for_frequency_and_absolute_for_duty():
    spec = [{"type": "pwm", "pin": "PA8", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1}]
    assert grade(PWM.replace("8499", "8554"), spec)["pass"] is True              # 170e6/8555 = 19871 Hz: lệch 0.64 %
    assert grade(PWM.replace("8499", "8700"), spec)["pass"] is False             # 19.54 kHz: lệch 2.3 %
    assert grade(PWM.replace("2125", "2200"), spec)["pass"] is True              # 2200/8500 = 25.88 %: lệch 0.88 điểm %
    assert grade(PWM.replace("2125", "2300"), spec)["pass"] is False            # 27.06 %: lệch 2.06 điểm %


def test_center_aligned_pwm_is_unmodeled_and_fails():
    r = grade(PWM.replace("TIM_CR1_ARPE | TIM_CR1_CEN", "TIM_CR1_CMS_0 | TIM_CR1_CEN"))
    assert r["pass"] is False and reasons(r) == ["unmodeled"]


def test_unmodeled_registers_alone_do_not_fail_a_satisfied_spec():
    r = grade(PWM.replace("    while (1) { }", "    TIM1->DIER |= TIM_DIER_UIE;\n    while (1) { }"))
    assert r["pass"] is True and "TIM1_DIER" in r["details"]["unmodeled"]


def test_warnings_do_not_fail():
    r = grade(PWM.replace("    while (1) { }", "    TIM1->PSC = 0x10000;\n    while (1) { }").replace("TIM1->PSC = 0;\n", ""))
    # PSC = 0x10000 (bit reservado) => cảnh báo SIM-RESERVED nhưng PSC hiệu dụng = 0
    assert r["pass"] is True


# ------------------------------------------------------------------ UART / I2C / clock
UART = """
#include "stm32g4xx.h"
int main(void) {
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;
    USART1->BRR = 1476;
    USART1->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
    while (1) { }
}
"""


def test_uart_baud_tolerance():
    spec = [{"type": "uart", "instance": "USART1", "baud": 115200, "tol_pct": 2}]
    assert grade(UART, spec)["pass"] is True
    r = grade(UART.replace("1476", "1500"), spec)                                  # 170e6/1500 = 113333: lệch 1.6 % -> đạt
    assert r["pass"] is True
    r = grade(UART.replace("1476", "1700"), spec)                                  # 100000: lệch 13 %
    assert reasons(r) == ["wrong_baud"]


def test_uart_disabled_is_a_violation():
    r = grade(UART.replace("USART_CR1_UE | ", ""), [{"type": "uart", "instance": "USART1", "baud": 115200, "tol_pct": 2}])
    assert "sim_violation:SIM-USART-UE" in reasons(r)


def test_uart_pin_check():
    spec = [{"type": "uart", "instance": "USART1", "baud": 115200, "tol_pct": 2, "tx_pin": "PA9"}]
    assert reasons(grade(UART, spec)) == ["wrong_pin"]                              # chưa cấu hình PA9
    code = UART.replace("    USART1->BRR", "    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;\n    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE9) | GPIO_MODER_MODE9_1;\n"
                                          "    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL9) | (7U << GPIO_AFRH_AFSEL9_Pos);\n    USART1->BRR")
    assert grade(code, spec)["pass"] is True


I2C = """
#include "stm32g4xx.h"
int main(void) {
    RCC->APB1ENR1 |= RCC_APB1ENR1_I2C1EN;
    I2C1->TIMINGR = 0x30420F13;
    I2C1->CR1 |= I2C_CR1_PE;
    while (1) { }
}
"""


def test_i2c_scl_frequency():
    spec = [{"type": "i2c", "instance": "I2C1", "scl_hz": 100000, "tol_pct": 10}]
    assert grade(I2C, spec, initial="reset")["pass"] is True                         # mô hình: 108.1 kHz (+8.1 %)
    assert reasons(grade(I2C.replace("0x30420F13", "0x10320309"), spec, initial="reset")) == ["wrong_scl"]   # ~500 kHz
    assert "sim_violation:SIM-I2C-PE" in reasons(grade(I2C.replace("    I2C1->CR1 |= I2C_CR1_PE;\n", ""), spec, initial="reset"))


def test_i2c_open_drain_requirement():
    spec = [{"type": "i2c", "instance": "I2C1", "scl_hz": 100000, "tol_pct": 10, "scl_pin": "PB8", "sda_pin": "PB9", "open_drain": True}]
    gpio = ("    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOBEN;\n    GPIOB->MODER = (GPIOB->MODER & ~(GPIO_MODER_MODE8 | GPIO_MODER_MODE9)) | GPIO_MODER_MODE8_1 | GPIO_MODER_MODE9_1;\n"
            "    GPIOB->AFR[1] = (GPIOB->AFR[1] & ~(GPIO_AFRH_AFSEL8 | GPIO_AFRH_AFSEL9)) | (4U << GPIO_AFRH_AFSEL8_Pos) | (4U << GPIO_AFRH_AFSEL9_Pos);\n")
    od = "    GPIOB->OTYPER |= GPIO_OTYPER_OT8 | GPIO_OTYPER_OT9;\n"
    base = I2C.replace("    RCC->APB1ENR1", gpio + "    RCC->APB1ENR1")
    assert grade(base.replace(gpio, gpio + od), spec, initial="reset")["pass"] is True
    r = grade(base, spec, initial="reset")
    assert r["pass"] is False and reasons(r) == ["wrong_pin_config"] * 2 and "open-drain" in r["reasons"][0]          # PB8 và PB9
    half = grade(base.replace(gpio, gpio + "    GPIOB->OTYPER |= GPIO_OTYPER_OT8;\n"), spec, initial="reset")
    assert reasons(half) == ["wrong_pin_config"] and "PB9" in half["reasons"][0]


CLOCK = """
#include "stm32g4xx.h"
int main(void) {
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    PWR->CR5 &= ~PWR_CR5_R1MODE;
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSI | (3U << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL);
    while (1) { }
}
"""


def test_clock_spec():
    spec = [{"type": "clock", "sysclk_hz": 170000000, "pclk1_hz": 170000000, "tol_pct": 0.1}]
    assert grade(CLOCK, spec, initial="reset")["pass"] is True
    r = grade(CLOCK.replace("85U", "40U"), spec, initial="reset")                       # 4 MHz x 40 / 2 = 80 MHz
    assert set(reasons(r)) == {"wrong_clock"} and len(r["reasons"]) == 2                  # SYSCLK và PCLK1 đều lệch
    r = grade(CLOCK.replace("    PWR->CR5 &= ~PWR_CR5_R1MODE;\n", ""), spec, initial="reset")
    assert "sim_violation:SIM-CLK-LIMIT" in reasons(r)


def test_hse_frequency_comes_from_the_task():
    code = """
#include "stm32g4xx.h"
int main(void) {
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    PWR->CR5 &= ~PWR_CR5_R1MODE;
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;
    RCC->CR |= RCC_CR_HSEON;
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE | (1U << RCC_PLLCFGR_PLLM_Pos) | (84U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while (1) { }
}"""
    spec = [{"type": "clock", "sysclk_hz": 168000000, "tol_pct": 0.1}]
    assert grade(code, spec, initial="reset", extra={"hse_hz": 8000000})["pass"] is True
    r = grade(code, spec, initial="reset")                                               # không biết HSE => không đoán
    assert r["pass"] is False


# ------------------------------------------------------------------ nhiều mục spec, độc lập với bản agent
def test_all_spec_items_must_hold():
    two = PWM_SPEC + [{"type": "uart", "instance": "USART1", "baud": 115200, "tol_pct": 2}]
    r = grade(PWM, two)
    assert r["pass"] is False and "inactive:no_effect" in reasons(r)


def test_grader_uses_the_frozen_vendor_copy_not_agent_hwmodel():
    grade(PWM)
    assert "hwmodel" not in sys.modules or "vendor" in (sys.modules["hwmodel"].__file__ or "")
    mod = sys.modules["hwmodel_vendored"]
    assert "eval/vendor/hwmodel" in mod.__file__.replace("\\", "/")


def test_a_tampered_vendor_copy_is_refused(tmp_path, monkeypatch):
    from eval import sandbox
    monkeypatch.setattr(sandbox, "VENDOR", tmp_path)
    monkeypatch.setattr(sandbox, "_STATE", None)
    (tmp_path / "hwmodel").mkdir()
    (tmp_path / "hwmodel" / "VENDOR.md").write_text("hwmodel_vendor_sha256: " + "0" * 64 + "\nhwmodel_data_sha256: " + "0" * 64 + "\n")
    (tmp_path / "hwmodel_data").mkdir()
    for n in ("hw_specs.sqlite", "svd_attrs.json"):
        (tmp_path / "hwmodel_data" / n).write_text("x")
    with pytest.raises(RuntimeError, match="vendor"):
        sandbox.load()


def test_the_answer_code_is_not_executed():
    import os
    code = '#include "stm32g4xx.h"\nint system(const char *);\nint main(void){ system("touch /tmp/hwmodel_graded_code_ran"); return 0; }'
    grade(code)
    assert not os.path.exists("/tmp/hwmodel_graded_code_ran")


def test_result_is_json_serialisable():
    import json
    json.dumps(grade(PWM)), json.dumps(grade(PWM.replace("8499", "100")))


# ------------------------------------------------------------------ compile (chỉ số riêng)
@pytest.mark.skipif(shutil.which("clang") is None, reason="clang not installed")
def test_compile_grader_reports_ok_error_skipped_without_gating():
    ok = compile_grader.grade(task(PWM_SPEC), run(fenced(PWM)), None)
    assert ok["pass"] is True and ok["details"]["status"] == "ok"
    bad = compile_grader.grade(task(PWM_SPEC), run(fenced("int main(void){ TIM1->NOPE = 1; }")), None)
    assert bad["pass"] is False and bad["details"]["status"] == "error" and bad["details"]["errors"]
    nc = compile_grader.grade(task(PWM_SPEC), run("no code at all"), None)
    assert nc["pass"] is False and nc["details"]["status"] == "no_code"


def test_compile_skipped_is_never_a_pass(monkeypatch):
    from eval import sandbox
    monkeypatch.setattr(sandbox.load().compile_check.shutil, "which", lambda _n: None)
    res = compile_grader.grade(task(PWM_SPEC), run(fenced(PWM)), None)
    assert res["pass"] is False and res["details"]["status"] == "skipped"


def test_compile_is_not_a_gating_grader_but_functional_sim_is():
    from eval.schema import GATING_GRADERS, GRADERS
    assert "compile" in GRADERS and "functional_sim" in GRADERS
    assert "functional_sim" in GATING_GRADERS and "compile" not in GATING_GRADERS


# ------------------------------------------------------------------ sau review độc lập (plan/reviews/review_C3.md)
def test_forgetting_pllren_fails_because_the_pll_output_never_becomes_sysclk():
    spec = [{"type": "clock", "sysclk_hz": 170000000, "tol_pct": 0.1}]
    r = grade(CLOCK.replace(" | RCC_PLLCFGR_PLLREN", ""), spec, initial="reset")
    assert r["pass"] is False and "sim_violation:SIM-CLK-NOSRC" in reasons(r) and "PLLREN" in " ".join(r["reasons"])


def test_unused_timer_channels_do_not_fail_the_task():
    # CC2E / CC1NE trên kênh không nối chân và không nằm trong spec: vô hại trên phần cứng (Table 282 chỉ định nghĩa tim_ocx, chân do GPIO quyết định)
    assert grade(PWM.replace("TIM1->CCER = TIM_CCER_CC1E;", "TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC2E;"))["pass"] is True
    assert grade(PWM.replace("TIM1->CCER = TIM_CCER_CC1E;", "TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC1NE;"))["pass"] is True
    assert grade(PWM.replace("TIM1->CCER = TIM_CCER_CC1E;", "TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC3E | TIM_CCER_CC4E;"))["pass"] is True


def test_errors_on_the_requested_channel_still_fail_even_when_other_channels_are_fine():
    r = grade(PWM.replace("(6U << GPIO_AFRH_AFSEL8_Pos)", "(2U << GPIO_AFRH_AFSEL8_Pos)").replace("TIM_CCER_CC1E;", "TIM_CCER_CC1E | TIM_CCER_CC2E;"))
    assert "sim_violation:SIM-GPIO-AF" in reasons(r)


def test_a_misconfigured_unrelated_timer_does_not_fail_the_spec():
    extra = ('    RCC->APB1ENR1 |= RCC_APB1ENR1_TIM2EN;\n    TIM2->ARR = 0;\n    TIM2->CCER = TIM_CCER_CC1E;\n    TIM2->CR1 = TIM_CR1_CEN;\n')
    assert grade(PWM.replace("    while (1) { }", extra + "    while (1) { }"))["pass"] is True


def test_forbidden_pins_must_stay_unused():
    spec = [{"type": "pwm", "pin": "PC0", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1, "forbid_pins": ["PA8"]}]
    pc0 = (PWM.replace("GPIOA", "GPIOC").replace("GPIO_AFRH_AFSEL8", "GPIO_AFRL_AFSEL0").replace("MODE8", "MODE0").replace("AFR[1]", "AFR[0]")
           .replace("(6U << GPIO_AFRL_AFSEL0_Pos)", "(2U << GPIO_AFRL_AFSEL0_Pos)"))
    assert grade(pc0, spec)["pass"] is True
    both = pc0.replace("    TIM1->PSC = 0;", "    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;\n    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8) | GPIO_MODER_MODE8_1;\n"
                                                "    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL8) | (6U << GPIO_AFRH_AFSEL8_Pos);\n    TIM1->PSC = 0;")
    r = grade(both, spec)
    assert r["pass"] is False and reasons(r) == ["forbidden_pin_used"] and "PA8" in r["reasons"][0]


UART_SPEC = {"type": "uart", "instance": "USART1", "baud": 115200, "tol_pct": 2}


@pytest.mark.parametrize("edit,code", [
    ("USART_CR1_UE | USART_CR1_TE | USART_CR1_RE | USART_CR1_M0", "wrong_config"),                              # 9-bit
    ("USART_CR1_UE | USART_CR1_TE | USART_CR1_RE | USART_CR1_PCE", "wrong_config"),                            # parity
    ("USART_CR1_UE | USART_CR1_TE", "wrong_config"),                                                            # thiếu RE
    ("USART_CR1_UE | USART_CR1_RE", "wrong_config"),                                                            # thiếu TE
    ("USART_CR1_UE | USART_CR1_TE | USART_CR1_RE | USART_CR1_OVER8", "wrong_config"),                          # oversampling by 8
])
def test_uart_requirements_stated_in_the_prompt_are_checked(edit, code):
    spec = [dict(UART_SPEC, frame="8N1", te=True, re=True, over8=0)]
    assert grade(UART, spec)["pass"] is True
    r = grade(UART.replace("USART_CR1_UE | USART_CR1_TE | USART_CR1_RE", edit), spec)
    assert r["pass"] is False and code in reasons(r)


def test_uart_stop_bits_and_default_kernel_clock_are_checked():
    spec = [dict(UART_SPEC, frame="8N1", kernel_source="PCLK2")]
    two_stop = UART.replace("    USART1->BRR = 1476;", "    USART1->CR2 = USART_CR2_STOP_1;\n    USART1->BRR = 1476;")
    assert "wrong_config" in reasons(grade(two_stop, spec))
    sysclk = UART.replace("    USART1->BRR", "    RCC->CCIPR = (RCC->CCIPR & ~RCC_CCIPR_USART1SEL) | RCC_CCIPR_USART1SEL_0;\n    USART1->BRR")
    r = grade(sysclk, [dict(UART_SPEC, kernel_source="PCLK2")], initial="sysclk_170mhz_pll_hsi16_apb2_div2")
    assert r["pass"] is False and "wrong_kernel_clock" in reasons(r)


def test_writing_brr_after_the_usart_is_enabled_fails_with_the_lock_code():
    late = UART.replace("    USART1->BRR = 1476;\n", "").replace("    while (1) { }", "    USART1->BRR = 1476;\n    while (1) { }")
    r = grade(late, [UART_SPEC])
    assert r["pass"] is False and "sim_violation:SIM-WRITE-LOCKED" in reasons(r)


def test_i2c_scl_is_accepted_when_the_target_is_reachable_for_tsync_between_its_minimum_and_1000ns():
    sm = [{"type": "i2c", "instance": "I2C1", "scl_hz": 100000, "tol_pct": 5}]
    fm = [{"type": "i2c", "instance": "I2C1", "scl_hz": 400000, "tol_pct": 5}]
    assert grade(I2C, sm, initial="reset")["pass"] is True                                              # RM Table 360 Sm: [100.0, 108.1] kHz
    rm_fm = I2C.replace("0x30420F13", "0x10320309")                                                    # RM Table 360 Fm: [363.6, 500] kHz
    assert grade(rm_fm, fm, initial="reset")["pass"] is True
    assert reasons(grade(rm_fm, sm, initial="reset")) == ["wrong_scl"]
    slow = I2C.replace("0x30420F13", "0x30420F2F")                                                     # SCLL = 0x2F: 48 x 250 ns + ... ≈ 66 kHz
    assert reasons(grade(slow, sm, initial="reset")) == ["wrong_scl"]


def test_i2c_kernel_clock_is_checked_when_the_spec_requires_it():
    spec = [{"type": "i2c", "instance": "I2C1", "scl_hz": 100000, "tol_pct": 5, "kernel_clk_hz": 16000000}]
    assert grade(I2C, spec, initial="reset")["pass"] is True
    r = grade(I2C, spec, initial="sysclk_170mhz_pll_hsi16_apb_div1")
    assert "wrong_kernel_clock" in reasons(r)


def test_timingr_written_after_pe_is_a_lock_violation():
    late = I2C.replace("    I2C1->TIMINGR = 0x30420F13;\n    I2C1->CR1 |= I2C_CR1_PE;", "    I2C1->CR1 |= I2C_CR1_PE;\n    I2C1->TIMINGR = 0x30420F13;")
    r = grade(late, [{"type": "i2c", "instance": "I2C1", "scl_hz": 100000, "tol_pct": 10}], initial="reset")
    assert "sim_violation:SIM-WRITE-LOCKED" in reasons(r)


def tim(presc, scldel, sdadel, sclh, scll):
    return f"0x{(presc << 28) | (scldel << 20) | (sdadel << 16) | (sclh << 8) | scll:08X}"


@pytest.mark.parametrize("mode,presc,scll,sclh,ok", [
    ("Fm", 0, 23, 11, True),         # tLOW = 24 x 62.5 + 125 = 1.625 us, tHIGH = 12 x 62.5 + 125 = 0.875 us  (Table 358: >= 1.3 / 0.6 us)
    ("Fm", 0, 14, 7, False),         # tLOW = 0.94 + 0.125 = 1.06 us < 1.3 us
    ("Fm", 0, 11, 11, False),        # tLOW = 0.75 + 0.125 us
    ("Fm", 0, 26, 8, True),          # tLOW 1.69 us, tHIGH = 9 x 62.5 + 125 = 0.69 us
    ("Fm", 0, 26, 6, False),         # tHIGH = 7 x 62.5 + 125 = 0.56 us < 0.6 us
])
def test_bus_timing_minimums_of_the_selected_mode_are_checked(mode, presc, scll, sclh, ok):
    spec = [{"type": "i2c", "instance": "I2C1", "scl_hz": 400000, "tol_pct": 15, "mode": mode}]
    code = I2C.replace("0x30420F13", tim(presc, 6, 1, sclh, scll))
    r = grade(code, spec, initial="reset")
    assert r["pass"] is ok, r["reasons"]
    if not ok:
        assert "wrong_i2c_timing" in reasons(r)


def test_standard_mode_high_period_must_reach_4us():
    spec = [{"type": "i2c", "instance": "I2C1", "scl_hz": 100000, "tol_pct": 5, "mode": "Sm"}]
    assert grade(I2C, spec, initial="reset")["pass"] is True                                         # RM Table 360 value: 5.125 / 4.125 us
    r = grade(I2C.replace("0x30420F13", tim(3, 4, 2, 0xE, 0x14)), spec, initial="reset")             # tHIGH = 15 x 250 ns + 125 ns = 3.875 us < 4.0 us
    assert "wrong_i2c_timing" in reasons(r)


def test_uart_modeled_flag_is_enforced():
    swap = UART.replace("    USART1->BRR = 1476;", "    USART1->CR2 = USART_CR2_SWAP;\n    USART1->BRR = 1476;")
    r = grade(swap, [UART_SPEC])
    assert r["pass"] is False and "unmodeled" in reasons(r)
