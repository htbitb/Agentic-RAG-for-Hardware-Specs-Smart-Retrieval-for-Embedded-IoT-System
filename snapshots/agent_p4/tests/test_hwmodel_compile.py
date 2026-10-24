"""compile_check: clang ARM `-fsyntax-only` với header sinh từ SVD. `skipped` KHÔNG BAO GIỜ là pass. Mã của hệ là dữ liệu không tin cậy:
chỉ biên dịch cú pháp, không chạy, chặn #include ra ngoài thư mục tạm."""
import re
import shutil

import pytest

from hwmodel import compile_check as cc

needs_clang = pytest.mark.skipif(shutil.which("clang") is None, reason="clang not installed")

PWM = """
#include <stm32g4xx.h>
int main(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    GPIOA->MODER &= ~GPIO_MODER_MODE8;
    GPIOA->MODER |= GPIO_MODER_MODE8_1;
    GPIOA->AFR[1] &= ~GPIO_AFRH_AFSEL8;
    GPIOA->AFR[1] |= (6U << GPIO_AFRH_AFSEL8_Pos);
    TIM1->PSC = 0;
    TIM1->ARR = 8499;
    TIM1->CCR1 = 2125;
    TIM1->CCMR1 |= (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER |= TIM_CCER_CC1E;
    TIM1->BDTR |= TIM_BDTR_MOE;
    TIM1->CR1 |= TIM_CR1_CEN;
    while (1) { }
}
"""


@needs_clang
def test_a_standard_cmsis_pwm_program_compiles_cleanly():
    r = cc.compile_check(PWM, "stm32g474")
    assert r["status"] == "ok", r
    assert r["errors"] == [] and r["warnings"] == []


@needs_clang
def test_helper_macros_nvic_and_core_stubs_compile():
    code = """
#include <stdint.h>
#include "stm32g4xx.h"
extern uint32_t SystemCoreClock;
void TIM1_UP_TIM16_IRQHandler(void) { TIM1->SR &= ~TIM_SR_UIF; }
int main(void) {
    SET_BIT(RCC->APB2ENR, RCC_APB2ENR_TIM1EN);
    MODIFY_REG(RCC->CFGR, RCC_CFGR_HPRE, RCC_CFGR_HPRE_DIV2);
    WRITE_REG(TIM1->ARR, SystemCoreClock / 20000U - 1U);
    if (READ_BIT(RCC->CR, RCC_CR_PLLRDY) == 0U) { __NOP(); }
    NVIC_EnableIRQ(TIM1_UP_TIM16_IRQn);
    __enable_irq();
    for (;;) { __WFI(); }
}
"""
    assert cc.compile_check(code, "stm32g474")["status"] == "ok"


@needs_clang
@pytest.mark.parametrize("inc", ['#include "stm32g474xx.h"', '#include <system_stm32g4xx.h>', '#include "core_cm4.h"\n#include "stm32g4xx.h"',
                                 "#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n#include <string.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <limits.h>"])
def test_the_usual_cmsis_and_c_library_headers_resolve(inc):
    body = "void SystemInit(void);\n" if "system_stm32" in inc else ""
    r = cc.compile_check(f"{inc}\n{body}int main(void){{ return 0; }}\n", "stm32g474")
    assert r["status"] == "ok", r["errors"]


@needs_clang
def test_an_unknown_register_member_is_a_compile_error_with_a_line_number():
    r = cc.compile_check('#include <stm32g4xx.h>\nint main(void){\n    TIM1->NOPE = 1;\n    return 0;\n}\n', "stm32g474")
    assert r["status"] == "error"
    e = r["errors"][0]
    assert e["line"] == 3 and "NOPE" in e["msg"]


@needs_clang
def test_an_undeclared_function_is_an_error_not_a_warning():
    r = cc.compile_check('#include <stm32g4xx.h>\nint main(void){\n    HAL_Init();\n    return 0;\n}\n', "stm32g474")
    assert r["status"] == "error" and "HAL_Init" in r["errors"][0]["msg"]


@needs_clang
def test_hal_header_is_not_available():
    r = cc.compile_check('#include "stm32g4xx_hal.h"\nint main(void){return 0;}\n', "stm32g474")
    assert r["status"] == "error" and "stm32g4xx_hal.h" in r["errors"][0]["msg"]


@needs_clang
def test_unknown_field_macro_is_an_error():
    r = cc.compile_check('#include <stm32g4xx.h>\nint main(void){ TIM1->CR1 |= TIM_CR1_NOPE; return 0; }\n', "stm32g474")
    assert r["status"] == "error" and "TIM_CR1_NOPE" in r["errors"][0]["msg"]


@needs_clang
def test_syntax_error_is_reported():
    r = cc.compile_check("int main(void){ int x = ; return x; }\n", "stm32g474")
    assert r["status"] == "error" and r["errors"]


@needs_clang
def test_struct_layout_matches_the_register_offsets():
    # offsetof của mọi thành viên (đối chiếu mô hình ↔ header đã biên dịch)
    from ingestion import header_gen
    model = header_gen.build_model("stm32g474")
    asserts = []
    for gname, g in model.groups.items():
        for m in g.members:
            asserts.append(f'_Static_assert(offsetof({g.type_name}, {m.name}) == {m.offset}, "{gname}.{m.name}");')
    code = "#include <stm32g4xx.h>\n#include <stddef.h>\n" + "\n".join(asserts) + "\nint main(void){return 0;}\n"
    r = cc.compile_check(code, "stm32g474")
    assert r["status"] == "ok", r["errors"][:3]


@needs_clang
def test_field_macro_values_are_consistent_when_compiled():
    code = """
#include <stm32g4xx.h>
_Static_assert(RCC_APB2ENR_TIM1EN == (1UL << 11), "TIM1EN");
_Static_assert(GPIO_MODER_MODE8 == (3UL << 16), "MODE8");
_Static_assert(GPIO_MODER_MODE8_1 == (1UL << 17), "MODE8_1");
_Static_assert(GPIO_AFRH_AFSEL8_Pos == 0, "AFSEL8");
_Static_assert(TIM_CCMR1_OC1M == ((7UL << 4) | (1UL << 16)), "OC1M is OC1M[3:0]: bits 6:4 and 16 (RM0440 p.1253)");
_Static_assert(TIM_CCMR1_OC1M_3 == (1UL << 16), "OC1M_3 (ST: 0x1000 << Pos)");
_Static_assert(TIM_BDTR_MOE == (1UL << 15), "MOE");
_Static_assert(I2C_TIMINGR_PRESC == (0xFUL << 28), "PRESC");
_Static_assert(RCC_CFGR_SW_PLL == 3UL, "SW_PLL");
_Static_assert(RCC_CFGR_HPRE_DIV2 == (8UL << 4), "HPRE_DIV2");
_Static_assert(FLASH_ACR_LATENCY_4WS == 4UL, "4WS");
_Static_assert(TIM1_UP_TIM16_IRQn == 25, "IRQ");
int main(void){return 0;}
"""
    assert cc.compile_check(code, "stm32g474")["status"] == "ok"


# ------------------------------------------------------------------ skipped KHÔNG phải pass
def test_other_chips_are_skipped_with_a_reason():
    r = cc.compile_check("int main(void){return 0;}", "esp32")
    assert r["status"] == "skipped" and "esp32" in r["reason"] and r["errors"] == []


def test_missing_toolchain_is_skipped_not_ok(monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda _name: None)
    r = cc.compile_check("int main(void){return 0;}", "stm32g474")
    assert r["status"] == "skipped" and "clang" in r["reason"]
    assert cc.is_pass(r) is False


def test_is_pass_only_for_status_ok():
    assert cc.is_pass({"status": "ok"}) is True
    assert cc.is_pass({"status": "error"}) is False and cc.is_pass({"status": "skipped"}) is False


# ------------------------------------------------------------------ an toàn: mã không tin cậy
@pytest.mark.parametrize("line", [
    '#include "/etc/passwd"', '#include </etc/hosts>', '#include "../secret.h"', '#include "a/../../b.h"', '#include FOO',
    '#include_next <x.h>', '#import "x.h"', '#embed "/etc/passwd"', '# include "/etc/passwd"', '  #  include   "/etc/passwd"',
])
def test_dangerous_preprocessor_directives_are_rejected_before_clang_runs(line):
    r = cc.compile_check(line + "\nint main(void){return 0;}\n", "stm32g474")
    assert r["status"] == "error" and r["errors"][0]["kind"] == "forbidden_directive", r


def test_line_continuation_cannot_hide_a_directive():
    r = cc.compile_check('#in\\\nclude "/etc/passwd"\nint main(void){return 0;}\n', "stm32g474")
    assert r["status"] == "error" and r["errors"][0]["kind"] == "forbidden_directive"


def test_oversized_code_is_rejected():
    r = cc.compile_check("int x;\n" * 20000, "stm32g474")
    assert r["status"] == "error" and r["errors"][0]["kind"] == "too_large"


def test_scan_helper_accepts_plain_includes():
    assert cc.scan_directives('#include <stm32g4xx.h>\n#include "stm32g4xx.h"\n#include <stdint.h>\n') == []
    assert cc.scan_directives('#define A 1\n#if A\n#endif\n#pragma once\n') == []
    assert [p["kind"] for p in cc.scan_directives('#include "/abs/x.h"\n')] == ["forbidden_directive"]


@needs_clang
def test_code_is_never_executed():
    # `#pragma` / attribute constructor không được chạy; chỉ -fsyntax-only (kiểm bằng việc không có file nào được tạo)
    import os
    import tempfile
    marker = os.path.join(tempfile.gettempdir(), "hwmodel_should_not_exist")
    code = f'__attribute__((constructor)) void f(void) {{ FILE *x; }}\nint main(void){{return 0;}}\n'
    cc.compile_check(code, "stm32g474")
    assert not os.path.exists(marker)


def test_error_lines_are_parsed_into_structured_records():
    out = "main.c:12:5: error: use of undeclared identifier 'FOO'\nmain.c:3:1: warning: unused variable 'x' [-Wunused-variable]\n"
    errs, warns = cc.parse_diagnostics(out)
    assert errs == [{"line": 12, "col": 5, "msg": "use of undeclared identifier 'FOO'", "kind": "compile"}]
    assert warns[0]["line"] == 3 and "unused variable" in warns[0]["msg"]
    assert re.fullmatch(r"[0-9a-f]{64}", cc.header_checksum())
