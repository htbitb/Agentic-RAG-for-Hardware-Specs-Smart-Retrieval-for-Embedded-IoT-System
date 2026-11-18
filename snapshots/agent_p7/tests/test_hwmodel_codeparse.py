"""analyze_c_code: C kiểu CMSIS → danh sách `ops` theo thứ tự. KHÔNG đoán: cấu trúc không hỗ trợ ⇒ `unsupported_construct` kèm dòng.
Mã được tiền xử lý (clang -E) và phân tích (pycparser); KHÔNG BAO GIỜ được chạy."""
import pytest

from hwmodel.codeparse import analyze_c_code
from hwmodel.sim import simulate_register_writes

HDR = "#include <stm32g4xx.h>\n"
CLK170 = "sysclk_170mhz_pll_hsi16_apb_div1"


def ops_of(body: str, header: str = HDR, **kw):
    r = analyze_c_code(header + body, "stm32g474", **kw)
    assert r["ok"], r["unsupported"]
    return [(o["op"], o.get("reg"), (o["mask"], o["value"]) if o["op"] == "modify" else o.get("mask", o.get("value"))) for o in r["ops"]], r


def fails(body: str, header: str = HDR):
    r = analyze_c_code(header + body, "stm32g474")
    assert not r["ok"], r["ops"]
    return r


# ------------------------------------------------------------------ chương trình PWM chuẩn
PWM = HDR + """
int main(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    GPIOA->MODER &= ~GPIO_MODER_MODE8;
    GPIOA->MODER |= GPIO_MODER_MODE8_1;
    GPIOA->AFR[1] &= ~(0xFU << 0);
    GPIOA->AFR[1] |= (6U << GPIO_AFRH_AFSEL8_Pos);
    TIM1->PSC = 0;
    TIM1->ARR = 8499;
    TIM1->CCR1 = 2125;
    TIM1->CCMR1 |= (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER |= TIM_CCER_CC1E;
    TIM1->BDTR |= TIM_BDTR_MOE;
    TIM1->CR1 |= TIM_CR1_ARPE;
    TIM1->EGR |= TIM_EGR_UG;
    TIM1->CR1 |= TIM_CR1_CEN;
    while (1) { }
}
"""


def test_cmsis_pwm_program_becomes_the_expected_ops_in_order():
    r = analyze_c_code(PWM, "stm32g474")
    assert r["ok"] and r["unsupported"] == [] and r["complete"] is True
    got = [(o["op"], o["reg"], o.get("mask", o.get("value"))) for o in r["ops"]]
    assert got == [
        ("set_bits", "RCC_AHB2ENR", 0x1), ("set_bits", "RCC_APB2ENR", 0x800),
        ("clear_bits", "GPIOA_MODER", 0x30000), ("set_bits", "GPIOA_MODER", 0x20000),
        ("clear_bits", "GPIOA_AFRH", 0xF), ("set_bits", "GPIOA_AFRH", 0x6),
        ("write", "TIM1_PSC", 0), ("write", "TIM1_ARR", 8499), ("write", "TIM1_CCR1", 2125),
        ("set_bits", "TIM1_CCMR1", 0x68), ("set_bits", "TIM1_CCER", 0x1), ("set_bits", "TIM1_BDTR", 0x8000),
        ("set_bits", "TIM1_CR1", 0x80), ("set_bits", "TIM1_EGR", 0x1), ("set_bits", "TIM1_CR1", 0x1)]
    assert r["ops"][0]["addr"] == 0x4002_104C and r["ops"][4]["addr"] == 0x4800_0024      # RCC_AHB2ENR (p.306), GPIOA_AFRH (p.355)
    assert [o["line"] for o in r["ops"]][:3] == [4, 5, 6]
    assert r["ops"][0]["src"] == "RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN"


def test_analyzed_pwm_program_simulates_to_20khz_25pct():
    r = analyze_c_code(PWM, "stm32g474")
    res = simulate_register_writes("stm32g474", r["ops"], initial=CLK170)
    pwm = [e for e in res["effects"] if e["kind"] == "pwm" and e["pin"] == "PA8"][0]
    assert pwm["active"] and pwm["pwm_hz"] == pytest.approx(20_000.0) and pwm["duty_pct"] == pytest.approx(25.0)
    assert res["violations"] == []


# ------------------------------------------------------------------ các dạng đọc-sửa-ghi
@pytest.mark.parametrize("stmt,expected", [
    ("RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;", [("set_bits", "RCC_APB2ENR", 0x800)]),
    ("RCC->APB2ENR = RCC->APB2ENR | RCC_APB2ENR_TIM1EN;", [("set_bits", "RCC_APB2ENR", 0x800)]),
    ("RCC->APB2ENR = RCC_APB2ENR_TIM1EN | RCC->APB2ENR;", [("set_bits", "RCC_APB2ENR", 0x800)]),
    ("RCC->CFGR &= ~RCC_CFGR_HPRE;", [("clear_bits", "RCC_CFGR", 0xF0)]),
    ("RCC->CFGR = RCC->CFGR & ~RCC_CFGR_HPRE;", [("clear_bits", "RCC_CFGR", 0xF0)]),
    ("RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_DIV2;", [("modify", "RCC_CFGR", (0xF0, 0x80))]),
    ("MODIFY_REG(RCC->CFGR, RCC_CFGR_HPRE, RCC_CFGR_HPRE_DIV2);", [("modify", "RCC_CFGR", (0xF0, 0x80))]),
    ("SET_BIT(RCC->CR, RCC_CR_PLLON);", [("set_bits", "RCC_CR", 1 << 24)]),
    ("CLEAR_BIT(RCC->CR, RCC_CR_PLLON);", [("clear_bits", "RCC_CR", 1 << 24)]),
    ("WRITE_REG(TIM1->PSC, 7);", [("write", "TIM1_PSC", 7)]),
    ("CLEAR_REG(TIM1->PSC);", [("write", "TIM1_PSC", 0)]),
    ("GPIOA->ODR ^= (1U << 5);", [("toggle_bits", "GPIOA_ODR", 0x20)]),
    ("GPIOA->BSRR = GPIO_BSRR_BS5;", [("write", "GPIOA_BSRR", 0x20)]),
    ("(*TIM1).PSC = 3;", [("write", "TIM1_PSC", 3)]),
])
def test_read_modify_write_forms(stmt, expected):
    got, _ = ops_of(f"int main(void){{ {stmt} return 0; }}")
    assert got == expected


def test_read_modify_write_through_a_temporary():
    got, _ = ops_of("int main(void){ uint32_t t = RCC->CFGR; t &= ~RCC_CFGR_HPRE; t |= RCC_CFGR_HPRE_DIV2; RCC->CFGR = t; return 0; }")
    assert got == [("modify", "RCC_CFGR", (0xF0, 0x80))]


def test_stale_snapshot_is_not_guessed():
    r = fails("int main(void){ uint32_t t = RCC->CFGR; RCC->CFGR = 0; RCC->CFGR = t | 1; return 0; }")
    assert r["unsupported"][0]["kind"] == "unsupported_construct" and "stale" in r["unsupported"][0]["msg"]


# ------------------------------------------------------------------ biểu thức hằng
@pytest.mark.parametrize("expr,value", [
    ("170000000UL / 20000UL - 1", 8499), ("(uint32_t)(170000000.0 / 20000.0) - 1", 8499), ("(1 << 4) | (3 << 8)", 0x310),
    ("(uint16_t)70000", 70000 & 0xFFFF), ("~0xFU & 0xFFU", 0xF0), ("(5 > 3) ? 10 : 20", 10), ("sizeof(uint32_t)", 4),
    ("0x40000000UL + 0x28", 0x40000028), ("100 % 7", 2), ("-3 + 5", 2), ("(8499 + 1) / 4", 2125), ("'A'", 65),
    ("(int)3.9", 3), ("(F_CPU / 1000) - 1", 169999),
])
def test_constant_expressions_are_evaluated(expr, value):
    got, _ = ops_of(f"#define F_CPU 170000000UL\nint main(void){{ TIM1->ARR = {expr}; return 0; }}")
    assert got == [("write", "TIM1_ARR", value & 0xFFFFFFFF)]


def test_global_constants_enums_and_arrays():
    code = """
static const uint32_t CLOCK = 170000000UL;
enum { PWM_HZ = 20000, DUTY = 25 };
static const uint16_t lut[3] = { 100, 200, 300 };
int main(void){
    uint32_t period = CLOCK / PWM_HZ;
    TIM1->ARR = period - 1;
    TIM1->CCR1 = period * DUTY / 100;
    TIM1->CCR2 = lut[2];
    return 0;
}"""
    got, _ = ops_of(code)
    assert got == [("write", "TIM1_ARR", 8499), ("write", "TIM1_CCR1", 2125), ("write", "TIM1_CCR2", 300)]


def test_local_variable_arithmetic_and_increments():
    got, _ = ops_of("int main(void){ int i = 2; i += 3; i++; i <<= 1; TIM1->PSC = i; return 0; }")
    assert got == [("write", "TIM1_PSC", 12)]


# ------------------------------------------------------------------ luồng điều khiển
def test_constant_conditions_choose_a_branch():
    got, _ = ops_of("#define FAST 1\nint main(void){ if (FAST) { TIM1->PSC = 1; } else { TIM1->PSC = 2; } return 0; }")
    assert got == [("write", "TIM1_PSC", 1)]


def test_counted_loops_are_unrolled():
    got, _ = ops_of("int main(void){ for (int i = 0; i < 3; i++) { TIM1->CCR1 = i * 10; } return 0; }")
    assert got == [("write", "TIM1_CCR1", 0), ("write", "TIM1_CCR1", 10), ("write", "TIM1_CCR1", 20)]


def test_switch_with_constant_selector():
    got, _ = ops_of("int main(void){ switch (2) { case 1: TIM1->PSC = 1; break; case 2: TIM1->PSC = 2; break; default: TIM1->PSC = 9; } return 0; }")
    assert got == [("write", "TIM1_PSC", 2)]


def test_register_polling_loops_are_skipped_and_noted():
    code = """int main(void){
        RCC->CR |= RCC_CR_PLLON;
        while (!(RCC->CR & RCC_CR_PLLRDY));
        RCC->CFGR |= RCC_CFGR_SW_PLL;
        while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL) { }
        do { } while (!(RCC->CR & RCC_CR_HSERDY));
        return 0; }"""
    got, r = ops_of(code)
    assert got == [("set_bits", "RCC_CR", 1 << 24), ("set_bits", "RCC_CFGR", 3)]
    notes = [n for n in r["notes"] if n["kind"] == "poll_loop_skipped"]
    assert [n["line"] for n in notes] == [4, 6, 7]       # dòng 1 là #include; mỗi vòng chờ nằm trên dòng riêng
    assert "RDY" in notes[0]["msg"] or "assumed" in notes[0]["msg"]


def test_polling_loop_with_a_timeout_counter_is_still_a_polling_loop():
    code = """int main(void){ uint32_t timeout = 100000;
        RCC->CR |= RCC_CR_HSEON;
        while (!(RCC->CR & RCC_CR_HSERDY) && --timeout) { }
        TIM1->PSC = 4; return 0; }"""
    got, r = ops_of(code)
    assert got == [("set_bits", "RCC_CR", 1 << 16), ("write", "TIM1_PSC", 4)]


def test_delay_loops_without_register_access_are_skipped_and_noted():
    got, r = ops_of("int main(void){ RCC->CR |= 1; for (volatile int i = 0; i < 1000000; i++); TIM1->PSC = 1; return 0; }")
    assert got == [("set_bits", "RCC_CR", 1), ("write", "TIM1_PSC", 1)]
    assert any(n["kind"] == "delay_loop_skipped" for n in r["notes"])


def test_the_terminal_infinite_loop_ends_analysis_and_its_body_is_not_executed():
    got, r = ops_of("int main(void){ TIM1->PSC = 1; while (1) { TIM1->CCR1 = 5; } TIM1->PSC = 9; }")
    assert got == [("write", "TIM1_PSC", 1)]
    assert any(n["kind"] == "terminal_loop_not_executed" for n in r["notes"])


def test_a_long_loop_that_writes_registers_is_unsupported_not_guessed():
    r = fails("int main(void){ for (int i = 0; i < 100000; i++) { TIM1->CCR1 = i; } return 0; }")
    assert r["unsupported"][0]["kind"] == "unsupported_construct" and "loop" in r["unsupported"][0]["msg"]


# ------------------------------------------------------------------ hàm, con trỏ
def test_functions_are_inlined_with_constant_arguments():
    code = """
static void pin_af(GPIO_TypeDef *port, uint32_t pin, uint32_t af) {
    port->MODER &= ~(3U << (pin * 2U));
    port->MODER |= (2U << (pin * 2U));
    if (pin < 8U) { port->AFR[0] |= af << (pin * 4U); } else { port->AFR[1] |= af << ((pin - 8U) * 4U); }
}
static void clocks(void) { RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN; }
int main(void){ clocks(); pin_af(GPIOA, 8, 6); return 0; }"""
    got, _ = ops_of(code)
    assert got == [("set_bits", "RCC_AHB2ENR", 1), ("clear_bits", "GPIOA_MODER", 3 << 16), ("set_bits", "GPIOA_MODER", 2 << 16),
                   ("set_bits", "GPIOA_AFRH", 6)]


def test_function_return_values_and_pointer_variables():
    code = """
static uint32_t period(uint32_t hz) { return 170000000UL / hz; }
int main(void){ TIM_TypeDef *t = TIM1; t->ARR = period(20000) - 1; t->PSC = 0; return 0; }"""
    got, _ = ops_of(code)
    assert got == [("write", "TIM1_ARR", 8499), ("write", "TIM1_PSC", 0)]


def test_raw_addresses_and_register_macros():
    code = """
#define REG32(addr) (*(volatile uint32_t *)(addr))
#define RCC_APB2ENR_ADDR 0x40021060UL
int main(void){ REG32(RCC_APB2ENR_ADDR) |= (1U << 11); *(volatile uint32_t *)0x40012C28UL = 5; return 0; }"""
    got, r = ops_of(code)
    assert got == [("set_bits", "RCC_APB2ENR", 0x800), ("write", "TIM1_PSC", 5)]
    assert r["ops"][0]["addr"] == 0x4002_1060


def test_pointer_arithmetic_on_a_register_array():
    got, _ = ops_of("int main(void){ volatile uint32_t *p = (volatile uint32_t *)TIM1_BASE; p[10] = 7; *(p + 11) = 8; return 0; }")
    assert got == [("write", "TIM1_PSC", 7), ("write", "TIM1_ARR", 8)]                     # 0x28 = word 10, 0x2C = word 11


def test_address_of_a_register_is_a_constant():
    got, _ = ops_of("int main(void){ uint32_t a = (uint32_t)&USART1->TDR; TIM1->CCR1 = a & 0xFFFF; return 0; }")
    assert got == [("write", "TIM1_CCR1", (0x4001_3800 + 0x28) & 0xFFFF)]


def test_interrupt_handlers_are_never_executed():
    code = """
void TIM1_UP_TIM16_IRQHandler(void) { TIM1->SR &= ~TIM_SR_UIF; TIM1->CCR1 = 99; }
int main(void){ TIM1->PSC = 1; NVIC_EnableIRQ(TIM1_UP_TIM16_IRQn); while(1); }"""
    got, r = ops_of(code)
    assert got == [("write", "TIM1_PSC", 1)]
    assert any(n["kind"] == "no_op_call" and "NVIC_EnableIRQ" in n["msg"] for n in r["notes"])


def test_without_main_the_parameterless_functions_run_in_source_order():
    got, r = ops_of("void clk_init(void){ RCC->APB2ENR |= RCC_APB2ENR_TIM1EN; }\nvoid pwm_init(void){ TIM1->PSC = 0; }\nstatic void helper(int x){ TIM1->ARR = x; }")
    assert got == [("set_bits", "RCC_APB2ENR", 0x800), ("write", "TIM1_PSC", 0)]
    assert any(n["kind"] == "no_main" for n in r["notes"])


def test_no_function_at_all_is_an_error():
    r = fails("")
    assert r["unsupported"][0]["kind"] == "no_entry"


def test_inline_assembly_is_ignored_and_noted():
    got, r = ops_of('int main(void){ __asm volatile ("nop; nop"); __asm__ __volatile__("dsb" ::: "memory"); TIM1->PSC = 2; return 0; }')
    assert got == [("write", "TIM1_PSC", 2)]
    assert [n["kind"] for n in r["notes"]].count("inline_asm_ignored") == 2


# ------------------------------------------------------------------ cấu trúc không hỗ trợ: không đoán
@pytest.mark.parametrize("body,fragment", [
    ("int main(void){ HAL_Init(); return 0; }", "HAL"),
    ("int main(void){ LL_APB2_GRP1_EnableClock(LL_APB2_GRP1_PERIPH_TIM1); return 0; }", "LL"),
    ("int main(void){ if (TIM1->SR & TIM_SR_UIF) { TIM1->PSC = 1; } return 0; }", "data-dependent"),
    ("int main(void){ TIM1->CCR1 += 5; return 0; }", "arithmetic"),
    ("int main(void){ TIM1->CCR1 = (TIM1->ARR + 1) / 4; return 0; }", "arithmetic"),
    ("int main(void){ TIM1->CCR1 = TIM1->CNT; return 0; }", "another register"),
    ("int main(void){ uint32_t x = foo(); TIM1->PSC = x; return 0; }", "foo"),
    ("int main(void){ goto end; end: return 0; }", "goto"),
    ("int main(void){ *(volatile uint16_t *)0x40012C28UL = 1; return 0; }", "16-bit"),
    ("int main(void){ *(volatile uint8_t *)0x40012C28UL = 1; return 0; }", "8-bit"),
    ("typedef struct { int a; } S; int main(void){ S s = {1}; TIM1->PSC = s.a; return 0; }", "struct"),
    ("int main(void){ void (*fp)(void) = 0; fp(); return 0; }", "function pointer"),
    ("static int f(int n){ return f(n); } int main(void){ f(1); return 0; }", "recursion"),
    ("int main(void){ int n = TIM1->PSC; TIM1->ARR = n; return 0; }", "register"),
])
def test_unsupported_constructs_are_reported_with_kind_and_line(body, fragment):
    r = fails(body)
    u = r["unsupported"][0]
    assert u["kind"] == "unsupported_construct" and isinstance(u["line"], int) and u["line"] >= 2
    assert fragment.lower() in (u["msg"] + u.get("construct", "")).lower()
    assert r["complete"] is False


def test_ops_before_the_unsupported_construct_are_still_returned():
    r = analyze_c_code(HDR + "int main(void){ TIM1->PSC = 1; HAL_Init(); TIM1->ARR = 2; return 0; }", "stm32g474")
    assert [o["reg"] for o in r["ops"]] == ["TIM1_PSC"] and r["ok"] is False and r["unsupported"][0]["line"] == 2


def test_hal_headers_are_reported_as_unsupported():
    r = analyze_c_code('#include "stm32g4xx_hal.h"\nint main(void){ HAL_Init(); return 0; }', "stm32g474")
    assert r["ok"] is False and "HAL" in r["unsupported"][0]["msg"]


def test_syntax_errors_are_reported_with_a_line():
    r = analyze_c_code(HDR + "int main(void){\n    TIM1->PSC = ;\n}\n", "stm32g474")
    assert r["ok"] is False and r["unsupported"][0]["kind"] == "syntax_error" and r["unsupported"][0]["line"] == 3


def test_unknown_register_member_is_reported():
    r = analyze_c_code(HDR + "int main(void){ TIM1->NOPE = 1; return 0; }", "stm32g474")
    assert r["ok"] is False and "NOPE" in r["unsupported"][0]["msg"]


def test_unknown_macro_name_is_reported_as_an_unknown_symbol():
    r = analyze_c_code(HDR + "int main(void){ TIM1->CR1 |= TIM_CR1_NOPE; return 0; }", "stm32g474")
    assert r["ok"] is False and r["unsupported"][0]["kind"] == "unknown_symbol" and "TIM_CR1_NOPE" in r["unsupported"][0]["msg"]


# ------------------------------------------------------------------ an toàn
@pytest.mark.parametrize("line", ['#include "/etc/passwd"', '#include "../x.h"', "#embed \"/etc/passwd\"", "#include FOO"])
def test_forbidden_directives_never_reach_clang(line):
    r = analyze_c_code(line + "\nint main(void){return 0;}\n", "stm32g474")
    assert r["ok"] is False and r["unsupported"][0]["kind"] == "forbidden_directive"


def test_other_chips_are_not_supported():
    r = analyze_c_code("int main(void){return 0;}", "esp32")
    assert r["ok"] is False and r["unsupported"][0]["kind"] == "unsupported_chip"


def test_code_is_not_executed_only_analysed():
    # một chương trình tự gọi system() không có tác dụng gì: không có header, và chỉ phân tích
    r = analyze_c_code("int system(const char *c);\nint main(void){ system(\"touch /tmp/hwmodel_should_not_exist\"); return 0; }", "stm32g474")
    import os
    assert not os.path.exists("/tmp/hwmodel_should_not_exist")
    assert r["ok"] is False


def test_oversized_input_is_rejected():
    r = analyze_c_code("int x;\n" * 20000, "stm32g474")
    assert r["ok"] is False and r["unsupported"][0]["kind"] == "too_large"


# ------------------------------------------------------------------ thống kê
def test_result_has_a_coverage_summary():
    r = analyze_c_code(PWM, "stm32g474")
    assert r["stats"]["ops"] == 15 and r["stats"]["unsupported"] == 0 and r["stats"]["poll_loops_skipped"] == 0


# ------------------------------------------------------------------ ngữ nghĩa: op sinh ra == biểu thức C (thuộc tính, trên nhiều giá trị cũ)
@pytest.mark.parametrize("expr,fn", [
    ("(TIM2->ARR & 0xFF) | 0x0F", lambda r: (r & 0xFF) | 0x0F),                      # bit 0–3 được ÉP về 1 dù nằm trong phần giữ lại
    ("TIM2->ARR & ~0xF0", lambda r: r & ~0xF0),
    ("(TIM2->ARR | 0x3) & ~0x8", lambda r: (r | 0x3) & ~0x8),
    ("(TIM2->ARR & 0xFF00FF) | 0x0F000000", lambda r: (r & 0xFF00FF) | 0x0F000000),
    ("TIM2->ARR ^ 0xF0", lambda r: r ^ 0xF0),
    ("~TIM2->ARR", lambda r: ~r),
    ("(TIM2->ARR ^ 0xFF) | 0xF", lambda r: (r ^ 0xFF) | 0xF),
    ("((TIM2->ARR & ~0xFF) | 0x12) & ~0x1", lambda r: ((r & ~0xFF) | 0x12) & ~0x1),
])
@pytest.mark.parametrize("old", [0xDEADBEEF, 0x12345678, 0x0, 0xFFFFFFFF])
def test_emitted_ops_have_the_same_effect_as_the_c_expression(expr, fn, old):
    from hwmodel.regmap import RegisterFile, load_regmap
    r = analyze_c_code(HDR + f"int main(void){{ TIM2->ARR = {expr}; return 0; }}", "stm32g474")
    assert r["ok"], r["unsupported"]
    rf = RegisterFile(load_regmap("stm32g474"))
    rf.set_state("TIM2_ARR", old)
    for op in r["ops"]:
        rf.apply(op)
    assert rf.value("TIM2_ARR") == fn(old) & 0xFFFFFFFF, r["ops"]
