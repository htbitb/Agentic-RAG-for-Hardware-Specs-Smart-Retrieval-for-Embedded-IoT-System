"""final_state (D25, gate): chấm SẢN PHẨM CUỐI của hội thoại nhiều lượt — khối code C ở LƯỢT CUỐI (nếu lượt cuối không có code thì khối gần nhất, ghi lý do) —
bằng functional_sim với NHIỀU spec (PWM + I2C + UART + clock) và ràng buộc chân. Mở rộng spec của functional_sim: `scl_not_in`, `sda_not_in`, `tx_not_in`,
`rx_not_in` (chân phải được định tuyến và không nằm trong danh sách), PWM `any_pin` + `timer_not_in`. Dùng bản hwmodel đóng băng (D19)."""
import textwrap

import pytest

from eval.graders import final_state as fin
from eval.graders import functional_sim as fs
from eval.schema import RunResult, Task, TurnResult

PRESET = "sysclk_170mhz_pll_hsi16_apb_div1"

GPIOA_CLK = "RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;"
PWM_PA8 = """
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8) | GPIO_MODER_MODE8_1;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL8) | (6U << GPIO_AFRH_AFSEL8_Pos);
    TIM1->PSC = 0; TIM1->ARR = 8499; TIM1->CCR1 = 2125;
    TIM1->CCMR1 = (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER = TIM_CCER_CC1E; TIM1->BDTR = TIM_BDTR_MOE; TIM1->CR1 = TIM_CR1_ARPE | TIM_CR1_CEN;
"""
# I2C3 100 kHz, fI2CCLK = 170 MHz (PCLK1 sau preset): TIMINGR của C3-016 (PRESC 15, SCLDEL 13, SDADEL 3, SCLH 45, SCLL 59)
I2C3_TIMING = "(15U << I2C_TIMINGR_PRESC_Pos) | (13U << I2C_TIMINGR_SCLDEL_Pos) | (3U << I2C_TIMINGR_SDADEL_Pos) | (45U << I2C_TIMINGR_SCLH_Pos) | (59U << I2C_TIMINGR_SCLL_Pos)"
I2C3_PC8_PC9 = f"""
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOCEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_I2C3EN;
    GPIOC->MODER = (GPIOC->MODER & ~(GPIO_MODER_MODE8 | GPIO_MODER_MODE9)) | GPIO_MODER_MODE8_1 | GPIO_MODER_MODE9_1;
    GPIOC->OTYPER |= GPIO_OTYPER_OT8 | GPIO_OTYPER_OT9;
    GPIOC->AFR[1] = (GPIOC->AFR[1] & ~(GPIO_AFRH_AFSEL8 | GPIO_AFRH_AFSEL9)) | (8U << GPIO_AFRH_AFSEL8_Pos) | (8U << GPIO_AFRH_AFSEL9_Pos);
    I2C3->TIMINGR = {I2C3_TIMING};
    I2C3->CR1 |= I2C_CR1_PE;
"""
I2C3_PA8_PC9 = f"""
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOCEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_I2C3EN;
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8) | GPIO_MODER_MODE8_1;
    GPIOA->OTYPER |= GPIO_OTYPER_OT8;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL8) | (2U << GPIO_AFRH_AFSEL8_Pos);
    GPIOC->MODER = (GPIOC->MODER & ~GPIO_MODER_MODE9) | GPIO_MODER_MODE9_1;
    GPIOC->OTYPER |= GPIO_OTYPER_OT9;
    GPIOC->AFR[1] = (GPIOC->AFR[1] & ~GPIO_AFRH_AFSEL9) | (8U << GPIO_AFRH_AFSEL9_Pos);
    I2C3->TIMINGR = {I2C3_TIMING};
    I2C3->CR1 |= I2C_CR1_PE;
"""
I2C3_NO_PINS = f"""
    RCC->APB1ENR1 |= RCC_APB1ENR1_I2C3EN;
    I2C3->TIMINGR = {I2C3_TIMING};
    I2C3->CR1 |= I2C_CR1_PE;
"""


def prog(*bodies, tail="while (1) { }"):
    return '#include "stm32g4xx.h"\nint main(void) {\n' + "\n".join(textwrap.dedent(b).strip("\n") for b in bodies) + f"\n    {tail}\n}}\n"


def fenced(code):
    return "Here is the code:\n```c\n" + code + "\n```\nDone."


def mk(spec, answers, initial=PRESET, **extra):
    task = Task(id="C4-901", category="C4", split="dev", turns=[{"user": f"turn {i}"} for i in range(len(answers))], graders=["final_state"],
                expected={"spec": spec, "initial": initial, **extra})
    run = RunResult(system="S0", variant="", task_id="C4-901", seed=0, turns=[TurnResult(answer=a) for a in answers], final_answer=answers[-1])
    return task, run


def grade(spec, answers, **kw):
    task, run = mk(spec, answers, **kw)
    return fin.grade(task, run, None)


def codes(res):
    return [r.split(":", 1)[0] if not r.startswith("sim_violation") else ":".join(r.split(":")[:2]) for r in res["reasons"]]


PWM_SPEC = {"type": "pwm", "pin": "PA8", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1}
I2C_SPEC = {"type": "i2c", "instance": "I2C3", "scl_hz": 100000, "tol_pct": 5, "kernel_clk_hz": 170000000, "scl_not_in": ["PA8"], "open_drain": True, "mode": "Sm"}


# ------------------------------------------------------------------------------------------------ final_state
def test_final_turn_code_with_two_specs_passes():
    good = fenced(prog(PWM_PA8, I2C3_PC8_PC9))
    r = grade([PWM_SPEC, I2C_SPEC], ["Turn 1 text only", "Turn 2 text only", good])
    assert r["pass"] is True and r["details"]["source_turn"] == 2 and r["details"]["fallback"] is None and r["details"]["blocks"] == 1


def test_scl_kept_on_pa8_fails_both_the_pwm_and_the_pin_constraint():
    """Biến thể sai kinh điển của D2: giữ I2C3_SCL trên PA8 (AF2 ghi đè AF6 của PWM)."""
    bad = fenced(prog(PWM_PA8, I2C3_PA8_PC9))
    r = grade([PWM_SPEC, I2C_SPEC], ["x", bad])
    assert r["pass"] is False
    assert "sim_violation:SIM-GPIO-AF" in codes(r) and "forbidden_pin_used" in codes(r)           # PA8 ở AF2 (I2C3_SCL) trong khi TIM1_CH1 cần AF6


def test_only_the_last_turn_counts_when_it_has_code():
    old_good, new_bad = fenced(prog(PWM_PA8, I2C3_PC8_PC9)), fenced(prog(PWM_PA8, I2C3_PA8_PC9))
    assert grade([PWM_SPEC, I2C_SPEC], [old_good, new_bad])["pass"] is False
    assert grade([PWM_SPEC, I2C_SPEC], [new_bad, old_good])["pass"] is True


def test_last_turn_without_code_falls_back_to_the_nearest_earlier_code_and_records_why():
    good = fenced(prog(PWM_PA8, I2C3_PC8_PC9))
    r = grade([PWM_SPEC, I2C_SPEC], ["intro", good, "No code in this last answer, see above."])
    assert r["pass"] is True and r["details"]["source_turn"] == 1
    assert r["details"]["fallback"] == {"from_turn": 1, "reason": "the last turn has no C code block; used the code of turn 1"}


def test_no_code_in_any_turn_fails_with_no_code():
    r = grade([PWM_SPEC], ["a", "b", "c"])
    assert r["pass"] is False and codes(r) == ["no_code"] and r["details"]["source_turn"] is None


def test_incremental_code_in_the_last_turn_is_not_the_final_product():
    """Lượt cuối chỉ có phần I2C (không có PWM): sản phẩm cuối thiếu PWM => trượt, dù lượt 1 có PWM đúng."""
    r = grade([PWM_SPEC, I2C_SPEC], [fenced(prog(PWM_PA8)), fenced(prog(I2C3_PC8_PC9))])
    assert r["pass"] is False and any(c in ("inactive", "wrong_pin") for c in codes(r))


def test_errors_of_other_kinds_are_reported_with_their_simulator_codes():
    no_moe = fenced(prog(PWM_PA8.replace("TIM1->BDTR = TIM_BDTR_MOE; ", ""), I2C3_PC8_PC9))
    assert "sim_violation:SIM-TIM-MOE" in codes(grade([PWM_SPEC, I2C_SPEC], ["x", no_moe]))


def test_final_state_requires_a_spec():
    with pytest.raises(ValueError, match="needs expected.spec"):
        Task(id="C4-901", category="C4", split="dev", turns=[{"user": "q"}], graders=["final_state"], expected={})


# ------------------------------------------------------------------------------------------------ mở rộng spec của functional_sim
def fs_grade(spec, code, initial=PRESET):
    task = Task(id="C4-902", category="C4", split="dev", turns=[{"user": "q"}], graders=["final_state"], expected={"spec": spec, "initial": initial})
    run = RunResult(system="S0", variant="", task_id="C4-902", seed=0, turns=[], final_answer=fenced(code))
    return fs.grade(task, run, None)


def test_i2c_scl_not_in_requires_a_routed_pin_outside_the_list():
    spec = [{**I2C_SPEC, "scl_not_in": ["PA8"], "sda_not_in": ["PB5"]}]
    assert fs_grade(spec, prog(I2C3_PC8_PC9))["pass"] is True
    r = fs_grade(spec, prog(I2C3_PA8_PC9))
    assert r["pass"] is False and any(x.startswith("forbidden_pin_used") and "PA8" in x for x in r["reasons"])
    r = fs_grade(spec, prog(I2C3_NO_PINS))
    assert r["pass"] is False and any(x.startswith("wrong_pin") and "not routed" in x for x in r["reasons"])
    r = fs_grade([{**I2C_SPEC, "sda_not_in": ["PC9"]}], prog(I2C3_PC8_PC9))
    assert r["pass"] is False and any(x.startswith("forbidden_pin_used") and "PC9" in x for x in r["reasons"])


def uart_rx(pin, port, n, af_reg, shift):
    return f"""
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIO{port}EN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN;
    GPIO{port}->MODER = (GPIO{port}->MODER & ~GPIO_MODER_MODE{n}) | GPIO_MODER_MODE{n}_1;
    GPIO{port}->AFR[{af_reg}] = (GPIO{port}->AFR[{af_reg}] & ~GPIO_AFR{'L' if af_reg == 0 else 'H'}_AFSEL{n}) | (7U << GPIO_AFR{'L' if af_reg == 0 else 'H'}_AFSEL{n}_Pos);
    USART2->BRR = 1667;
    USART2->CR1 = USART_CR1_UE | USART_CR1_RE;
"""


def test_uart_rx_not_in():
    """USART2_RX: PA3 (AF7, io TT_a: không chịu 5 V) hoặc PA15 (AF7, FT_f) — DS12288 Table 13 p.73."""
    spec = [{"type": "uart", "instance": "USART2", "baud": 9600, "tol_pct": 2, "te": False, "re": True, "rx_not_in": ["PA3"]}]
    assert fs_grade(spec, prog(uart_rx("PA15", "A", 15, 1, 0)), initial="reset")["pass"] is True
    r = fs_grade(spec, prog(uart_rx("PA3", "A", 3, 0, 0)), initial="reset")
    assert r["pass"] is False and any(x.startswith("forbidden_pin_used") and "PA3" in x for x in r["reasons"])


PWM_TIM2_CH1_PA0 = """
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_TIM2EN;
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE0) | GPIO_MODER_MODE0_1;
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~GPIO_AFRL_AFSEL0) | (1U << GPIO_AFRL_AFSEL0_Pos);
    TIM2->PSC = 0; TIM2->ARR = 169999; TIM2->CCR1 = 85000;
    TIM2->CCMR1 = (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM2->CCER = TIM_CCER_CC1E; TIM2->CR1 = TIM_CR1_ARPE | TIM_CR1_CEN;
"""
# servo 50 Hz, 7.5 %: (PSC+1)(ARR+1) = 170e6/50 = 3.4e6 = 170 x 20000 ; CCR = 0.075 x 20000 = 1500
SERVO_TIM3_CH1_PA6 = """
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_TIM3EN;
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE6) | GPIO_MODER_MODE6_1;
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~GPIO_AFRL_AFSEL6) | (2U << GPIO_AFRL_AFSEL6_Pos);
    TIM3->PSC = 169; TIM3->ARR = 19999; TIM3->CCR1 = 1500;
    TIM3->CCMR1 = (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM3->CCER = TIM_CCER_CC1E; TIM3->CR1 = TIM_CR1_ARPE | TIM_CR1_CEN;
"""
SERVO_TIM2_CH2_PA1 = """
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE1) | GPIO_MODER_MODE1_1;
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~GPIO_AFRL_AFSEL1) | (1U << GPIO_AFRL_AFSEL1_Pos);
    TIM2->CCR2 = 1500;
    TIM2->CCMR1 |= (6U << TIM_CCMR1_OC2M_Pos) | TIM_CCMR1_OC2PE;
    TIM2->CCER |= TIM_CCER_CC2E;
"""
PWM1K = {"type": "pwm", "pin": "PA0", "freq_hz": 1000, "duty_pct": 50, "tol_pct": 1}
SERVO = {"type": "pwm", "any_pin": True, "timer_not_in": ["TIM2"], "freq_hz": 50, "duty_pct": 7.5, "tol_pct": 1, "duty_tol_pp": 0.5}


def test_pwm_any_pin_with_timer_not_in():
    """Hai kênh của TIM2 dùng chung PSC/ARR (RM0440 §30.3: một bộ đếm) => servo 50 Hz phải ở timer khác (ở đây TIM3_CH1/PA6, AF2: DS12288 Table 13 p.73)."""
    good = prog(PWM_TIM2_CH1_PA0, SERVO_TIM3_CH1_PA6)
    assert fs_grade([PWM1K, SERVO], good)["pass"] is True
    shared = prog(PWM_TIM2_CH1_PA0, SERVO_TIM2_CH2_PA1)                  # kênh 2 của TIM2: tần số 1 kHz, không phải 50 Hz
    r = fs_grade([PWM1K, SERVO], shared)
    assert r["pass"] is False and any(x.startswith("wrong_timer") or x.startswith("wrong_freq") for x in r["reasons"])
    r = fs_grade([PWM1K, SERVO], prog(PWM_TIM2_CH1_PA0))                 # chỉ có PWM 1 kHz ở PA0 (đã thuộc mục `pin:`): không có kênh nào cho servo
    assert r["pass"] is False and any(x.startswith("inactive:no_effect") for x in r["reasons"])
    r = fs_grade([PWM1K, SERVO], prog(PWM_TIM2_CH1_PA0.replace("TIM2->CCER = TIM_CCER_CC1E; TIM2->CR1 = TIM_CR1_ARPE | TIM_CR1_CEN;", "")))
    assert r["pass"] is False                                              # không còn PWM nào


def test_pwm_timer_not_in_names_the_timer_in_the_reason():
    spec = [{"type": "pwm", "pin": "PA0", "freq_hz": 1000, "duty_pct": 50, "tol_pct": 1, "timer_not_in": ["TIM2"]}]
    r = fs_grade(spec, prog(PWM_TIM2_CH1_PA0))
    assert r["pass"] is False and any(x.startswith("wrong_timer") and "TIM2" in x for x in r["reasons"])


def test_require_pins_catches_a_function_that_lost_its_pin():
    """USART1_TX (PA9, AF7) rồi I2C2_SCL (cũng PA9, AF4) ghi đè AF: UART mất chân TX — không có `tx_pin` nên spec UART thường vẫn qua; `require_pins` bắt được."""
    uart = """
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;
    GPIOA->MODER = (GPIOA->MODER & ~(GPIO_MODER_MODE9 | GPIO_MODER_MODE10)) | GPIO_MODER_MODE9_1 | GPIO_MODER_MODE10_1;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~(GPIO_AFRH_AFSEL9 | GPIO_AFRH_AFSEL10)) | (7U << GPIO_AFRH_AFSEL9_Pos) | (7U << GPIO_AFRH_AFSEL10_Pos);
    USART1->BRR = 1476;
    USART1->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
"""
    clobber = "    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL9) | (4U << GPIO_AFRH_AFSEL9_Pos);\n"      # PA9 sang AF4 (I2C2_SCL): USART1_TX mất chân
    spec = [{"type": "uart", "instance": "USART1", "baud": 115200, "tol_pct": 2, "require_pins": True}]
    assert fs_grade(spec, prog(uart))["pass"] is True
    r = fs_grade(spec, prog(uart, clobber))
    assert r["pass"] is False and any(x.startswith("wrong_pin") and "TX" in x for x in r["reasons"])
    assert fs_grade([{**spec[0], "require_pins": False}], prog(uart, clobber))["pass"] is True                      # không đòi thì không bắt (hành vi cũ)
    spec_i2c = [{**I2C_SPEC, "require_pins": True, "scl_not_in": []}]
    assert fs_grade(spec_i2c, prog(I2C3_PC8_PC9))["pass"] is True
    r = fs_grade(spec_i2c, prog(I2C3_NO_PINS))
    assert r["pass"] is False and any(x.startswith("wrong_pin") and "SCL" in x for x in r["reasons"])


PLL_170_FROM_HSI = """
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    (void)RCC->APB1ENR1;
    PWR->CR5 &= ~PWR_CR5_R1MODE;
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSI | (3U << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY)) { }
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_DIV2;
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL) { }
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_DIV1;
"""


def test_clock_min_and_max_bounds_accept_any_valid_resolution():
    """sysclk_min_hz / sysclk_max_hz: chỉ đòi cận (xung đột Range 1 normal: sửa bằng boost 170 MHz hoặc hạ xuống <= 150 MHz đều hợp lệ)."""
    code = prog(PLL_170_FROM_HSI)
    assert fs_grade([{"type": "clock", "sysclk_min_hz": 150_000_000, "tol_pct": 0.1}], code, initial="reset")["pass"] is True
    r = fs_grade([{"type": "clock", "sysclk_min_hz": 171_000_000, "tol_pct": 0.1}], code, initial="reset")
    assert r["pass"] is False and any(x.startswith("wrong_clock") and "at least" in x for x in r["reasons"])
    assert fs_grade([{"type": "clock", "sysclk_max_hz": 170_000_000, "tol_pct": 0.1}], code, initial="reset")["pass"] is True
    r = fs_grade([{"type": "clock", "sysclk_max_hz": 150_000_000, "tol_pct": 0.1}], code, initial="reset")
    assert r["pass"] is False and any("at most" in x for x in r["reasons"])
    assert fs_grade([{"type": "clock", "sysclk_hz": 170_000_000, "sysclk_min_hz": 150_000_000, "tol_pct": 0.1}], code, initial="reset")["pass"] is True


def test_any_pin_item_does_not_reuse_the_pin_of_a_fixed_pin_item():
    """Chẩn đoán/chấm của `any_pin` không được nhận kênh PWM đã thuộc mục `pin:` khác (trường hợp hai mục cùng tần số)."""
    same_freq = {"type": "pwm", "any_pin": True, "freq_hz": 1000, "duty_pct": 50, "tol_pct": 1}
    only_first = prog(PWM_TIM2_CH1_PA0)
    assert fs_grade([PWM1K], only_first)["pass"] is True
    r = fs_grade([PWM1K, same_freq], only_first)                               # chỉ có PA0, đã thuộc mục thứ nhất => mục any_pin không có kênh nào
    assert r["pass"] is False and any("inactive" in x or "wrong_timer" in x for x in r["reasons"])
    both = prog(PWM_TIM2_CH1_PA0, SERVO_TIM3_CH1_PA6.replace("TIM3->PSC = 169; TIM3->ARR = 19999; TIM3->CCR1 = 1500;", "TIM3->PSC = 169; TIM3->ARR = 999; TIM3->CCR1 = 500;"))
    assert fs_grade([PWM1K, same_freq], both)["pass"] is True                  # PWM thứ hai (PA6, TIM3) 1 kHz 50 %


# ------------------------------------------------------------------------------------------------ sửa sau review độc lập
def test_any_pin_with_signal_keeps_the_channel_to_duty_binding():
    """`any_pin` + `signal` (spec đối xứng của C4-010): đúng kênh ↔ duty vẫn được ràng buộc dù chân nào cũng được."""
    code = prog(PWM_TIM2_CH1_PA0)
    ok = {"type": "pwm", "any_pin": True, "signal": "TIM2_CH1", "freq_hz": 1000, "duty_pct": 50, "tol_pct": 1}
    assert fs_grade([ok], code)["pass"] is True
    wrong_channel = {**ok, "signal": "TIM2_CH2"}
    r = fs_grade([wrong_channel], code)
    assert r["pass"] is False and any(x.startswith("inactive:no_effect") for x in r["reasons"])
    swapped = {**ok, "duty_pct": 60}
    assert fs_grade([swapped], code)["pass"] is False


def test_any_pin_honours_forbid_pins():
    spec = {"type": "pwm", "any_pin": True, "freq_hz": 1000, "duty_pct": 50, "tol_pct": 1, "forbid_pins": ["PA0"]}
    r = fs_grade([spec], prog(PWM_TIM2_CH1_PA0))
    assert r["pass"] is False and any(x.startswith("forbidden_pin_used") for x in r["reasons"])


def test_a_loose_snippet_next_to_the_full_program_is_not_glued_into_it():
    """Câu trả lời giải thích lỗi bằng đoạn lệnh rời ("đừng làm thế này") cạnh chương trình đầy đủ: chỉ chương trình đầy đủ được chấm."""
    full = prog(PWM_TIM2_CH1_PA0)
    answer = "Do not do this:\n```c\nRCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;\nGPIOA->MODER = 0;\n```\nInstead:\n```c\n" + full + "\n```\n"
    assert fs.extract_c_code(answer).strip() == full.strip()
    task = Task(id="C4-903", category="C4", split="dev", turns=[{"user": "q"}], graders=["final_state"],
                expected={"spec": [{"type": "pwm", "pin": "PA0", "freq_hz": 1000, "duty_pct": 50, "tol_pct": 1}], "initial": PRESET})
    run = RunResult(system="S0", variant="", task_id="C4-903", seed=0, turns=[], final_answer=answer)
    assert fs.grade(task, run, None)["pass"] is True
    # hai khối đều là hàm / không có main => vẫn nối như trước (chương trình tách làm nhiều khối)
    two = "```c\n#include \"stm32g4xx.h\"\nstatic void gpio_init(void) { GPIOA->MODER = 0; }\n```\n```c\nint main(void) { gpio_init(); while (1) { } }\n```"
    assert "gpio_init(void)" in fs.extract_c_code(two) and "int main" in fs.extract_c_code(two)


def test_unknown_spec_keys_and_types_are_rejected_when_the_task_loads():
    with pytest.raises(ValueError, match="unknown spec key"):
        mk([{"type": "i2c", "instance": "I2C3", "scl_hz": 100000, "scl_not_n": ["PA8"]}], ["x"])
    with pytest.raises(ValueError, match="needs type"):
        mk([{"type": "gpio", "pin": "PA8"}], ["x"])
    mk([{"type": "clock", "sysclk_min_hz": 150000000, "sysclk_max_hz": 170000000, "tol_pct": 0.1}], ["x"])         # khoá clock hợp lệ


def test_must_detect_and_must_not_are_validated_when_the_task_loads():
    base = dict(id="C4-904", category="C4", split="dev", turns=[{"user": "a"}, {"user": "b"}], graders=["final_state", "conflict_detected"])
    spec = [{"type": "pwm", "pin": "PA8", "freq_hz": 1000, "duty_pct": 50}]
    Task(**base, expected={"spec": spec, "must_detect": [{"code": "PIN_CONFLICT:PA8", "turn": 1, "from_turn": 1}], "must_not": [{"code": "unsafe_connection", "pin": "PA3"}]})
    with pytest.raises(ValueError, match="FAMILY"):
        Task(**base, expected={"spec": spec, "must_detect": [{"code": "PIN_CONFILCT:PA8", "turn": 1}]})
    with pytest.raises(ValueError, match="FAMILY"):
        Task(**base, expected={"spec": spec, "must_detect": [{"code": "PIN_CONFLICT:PA8", "turn": 1, "frm_turn": 1}]})
    with pytest.raises(ValueError, match="must_not"):
        Task(**base, expected={"spec": spec, "must_detect": [{"code": "PIN_CONFLICT:PA8", "turn": 1}], "must_not": ["unsafe_connexion"]})
