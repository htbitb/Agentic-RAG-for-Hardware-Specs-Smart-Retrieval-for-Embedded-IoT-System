"""Hỗ trợ chung cho test Gate v3 (không chứa test): `call` thật tới các server, `call` giả để tiêm lỗi, mã C mẫu, dựng observation."""
import json

import pytest

PWM_C = """#include "stm32g4xx.h"
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
}"""

UART_C = """#include "stm32g4xx.h"
int main(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN;
    GPIOA->MODER &= ~(GPIO_MODER_MODE2 | GPIO_MODER_MODE3);
    GPIOA->MODER |= GPIO_MODER_MODE2_1 | GPIO_MODER_MODE3_1;
    GPIOA->AFR[0] |= (7U << GPIO_AFRL_AFSEL2_Pos) | (7U << GPIO_AFRL_AFSEL3_Pos);
    USART2->BRR = 0x683;
    USART2->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
    while (1) { }
}"""

# I2C3 trên PC8 (SCL, AF8) / PC9 (SDA, AF8), 100 kHz từ HSI16 (TIMINGR theo ví dụ RM0440 Table 360, fI2CCLK = 16 MHz, Standard-mode)
I2C_C = """#include "stm32g4xx.h"
int main(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOCEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_I2C3EN;
    GPIOC->MODER &= ~(GPIO_MODER_MODE8 | GPIO_MODER_MODE9);
    GPIOC->MODER |= GPIO_MODER_MODE8_1 | GPIO_MODER_MODE9_1;
    GPIOC->OTYPER |= GPIO_OTYPER_OT8 | GPIO_OTYPER_OT9;
    GPIOC->AFR[1] |= (8U << GPIO_AFRH_AFSEL8_Pos) | (8U << GPIO_AFRH_AFSEL9_Pos);
    I2C3->TIMINGR = 0x30420F13;
    I2C3->CR1 |= I2C_CR1_PE;
    while (1) { }
}"""

CLK170 = "sysclk_170mhz_pll_hsi16_apb_div1"

# Code của bản nháp #1 trong demo D1 thật (bỏ chú thích): tự cấu hình clock 170 MHz rồi PWM 20 kHz / 25 % trên PA8 (gate_review.md C2)
D1_DRAFT1_C = """#include "stm32g4xx.h"
void SystemClock_Config(void)
{
    FLASH->ACR &= ~FLASH_ACR_LATENCY;
    FLASH->ACR |= FLASH_ACR_LATENCY_4WS;
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    PWR->CR1 &= ~PWR_CR1_VOS;
    PWR->CR1 |= PWR_CR1_VOS_0;
    PWR->CR5 &= ~PWR_CR5_R1MODE;
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_1 |
                   ((4U - 1U) << RCC_PLLCFGR_PLLM_Pos) |
                   (85U << RCC_PLLCFGR_PLLN_Pos) |
                   (0U << RCC_PLLCFGR_PLLR_Pos) |
                   RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));
    RCC->CFGR &= ~RCC_CFGR_SW;
    RCC->CFGR |= RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL);
}
void TIM1_PA8_PWM_Init(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    GPIOA->MODER &= ~(GPIO_MODER_MODE8_Msk);
    GPIOA->MODER |= (2U << GPIO_MODER_MODE8_Pos);
    GPIOA->AFR[1] &= ~(GPIO_AFRH_AFSEL8_Msk);
    GPIOA->AFR[1] |= (6U << GPIO_AFRH_AFSEL8_Pos);
    GPIOA->OSPEEDR |= (3U << GPIO_OSPEEDR_OSPEED8_Pos);
    GPIOA->PUPDR &= ~(GPIO_PUPDR_PUPD8_Msk);
    TIM1->PSC = 0;
    TIM1->ARR = 8500 - 1;
    TIM1->CCR1 = 2125;
    TIM1->CCMR1 &= ~(TIM_CCMR1_OC1M_Msk | TIM_CCMR1_CC1S_Msk);
    TIM1->CCMR1 |= (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER |= TIM_CCER_CC1E;
    TIM1->CR1 |= TIM_CR1_ARPE;
    TIM1->BDTR |= TIM_BDTR_MOE;
    TIM1->EGR |= TIM_EGR_UG;
    TIM1->CR1 |= TIM_CR1_CEN;
}
int main(void)
{
    SystemClock_Config();
    TIM1_PA8_PWM_Init();
    while (1)
    {
    }
}"""

# PWM 20 kHz / 25 % trên PA9 = TIM1_CH2 (AF6): chân và kênh khác với PWM_C
PWM_PA9_C = PWM_C.replace("MODE8", "MODE9").replace("AFSEL8", "AFSEL9").replace("CCR1", "CCR2").replace("OC1M", "OC2M").replace("OC1PE", "OC2PE") \
    .replace("CC1E", "CC2E")


def fenced(code: str, intro: str = "Here is the initialisation code.") -> str:
    return f"{intro}\n\n```c\n{code}\n```\n"


def obs(tool: str, result, **args) -> dict:
    return {"tool": tool, "args": args, "result": result}


def real_tools() -> dict:
    from mcp_servers import board_state_server as bs
    from mcp_servers import hw_knowledge_server as hk
    from mcp_servers import hw_sandbox_server as sb
    return {"get_board_state": bs.get_board_state, "run_drc": bs.run_drc, "analyze_c_code": sb.analyze_c_code,
            "simulate_register_writes": sb.simulate_register_writes, "compile_check": sb.compile_check,
            "get_electrical_specs": hk.get_electrical_specs, "get_clock_limits": hk.get_clock_limits}


class Recorder:
    """`call` thật (dispatch tới hàm server) có ghi lại lời gọi; `overrides` thay kết quả của một tool (tiêm lỗi)."""

    def __init__(self, overrides: dict | None = None):
        self.tools = real_tools()
        self.overrides = overrides or {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, args: dict) -> dict:
        self.calls.append((name, json.loads(json.dumps(args))))
        if name in self.overrides:
            o = self.overrides[name]
            if isinstance(o, Exception):
                raise o
            return o(args) if callable(o) else o
        return self.tools[name](**args)

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


@pytest.fixture()
def board(monkeypatch, tmp_path):
    """Board State thật trong một DB tạm (giống test_board_state_server)."""
    monkeypatch.setenv("BOARD_STATE_DB", str(tmp_path / "bs.sqlite"))
    monkeypatch.setenv("BOARD_STATE_PROJECT", "gate")
    from mcp_servers import board_state_server as srv
    return srv
