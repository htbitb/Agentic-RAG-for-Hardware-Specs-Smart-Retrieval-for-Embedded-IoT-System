### STM32G474 TIM1 Channel 1 (PA8) 20 kHz, 25% Duty PWM Configuration

#### 1. Clock and Timer Calculations
- **Timer Kernel Clock ($f_{\text{TIMCLK}}$)**:
  - System clock: $\text{SYSCLK} = 170\text{ MHz}$
  - APB2 prescaler = 1 $\implies f_{\text{PCLK2}} = 170\text{ MHz}$.
  - When APB prescaler is 1, timer clock equals PCLK: $f_{\text{TIM1CLK}} = 170\text{ MHz}$.
- **PWM Frequency Calculation ($f = 20\text{ kHz}$)**:
  $$f_{\text{PWM}} = \frac{f_{\text{TIM1CLK}}}{(\text{PSC} + 1) \cdot (\text{ARR} + 1)}$$
  Choosing $\text{PSC} = 0$:
  $$\text{ARR} + 1 = \frac{170\,000\,000}{20\,000} = 8500 \implies \text{ARR} = 8499$$
- **Duty Cycle Calculation ($25\%$)**:
  $$\text{Duty} = \frac{\text{CCR1}}{\text{ARR} + 1} = \frac{\text{CCR1}}{8500} = 0.25 \implies \text{CCR1} = 2125$$
  - PWM mode 1 (active while $\text{CNT} < \text{CCR1}$) yields exactly $20\,000\text{ Hz}$ with $25.0000\%$ duty cycle ($0\%$ error).

---

#### 2. Saved Configuration Header (`pwm_pa8_cfg.h`)
Per your request, the register configuration values are saved in `pwm_pa8_cfg.h`:

```c
#ifndef PWM_PA8_CFG_H
#define PWM_PA8_CFG_H

/* STM32G474 TIM1 Channel 1 (PA8) PWM Configuration
 * System Clock: 170 MHz (all APB prescalers = 1)
 * PWM Target Frequency: 20 kHz
 * PWM Target Duty Cycle: 25 %
 */

#define TIM1_PSC_VAL           0U
#define TIM1_ARR_VAL           8499U
#define TIM1_CCR1_VAL          2125U

#define TIM1_CCMR1_VAL         0x00000068U  /* OC1M = PWM mode 1 (0110b), OC1PE = 1 */
#define TIM1_CCER_VAL          0x00000001U  /* CC1E = 1 (Channel 1 output enable) */
#define TIM1_BDTR_VAL          0x00008000U  /* MOE = 1 (Main Output Enable) */
#define TIM1_CR1_VAL           0x00000081U  /* ARPE = 1, CEN = 1 (Counter enable) */

#define GPIOA_AFRH_AF6_PA8     0x00000006U  /* AFRH8 = AF6 (TIM1_CH1) */
#define GPIOA_MODER_AF_PA8     0x00020000U  /* MODER8 = 10b (Alternate function) */

#endif /* PWM_PA8_CFG_H */
```

---

#### 3. Complete Bare-Metal C Initialization Function

```c
#include "stm32g4xx.h"

#define TIM1_PSC_VAL           0U
#define TIM1_ARR_VAL           8499U
#define TIM1_CCR1_VAL          2125U

/**
 * @brief Configure TIM1 CH1 on PA8 for 20 kHz, 25% duty PWM.
 */
void tim1_pa8_pwm_init(void) {
    /* 1. Enable peripheral clocks for GPIOA and TIM1 */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;

    /* 2. Configure PA8 alternate function AF6 (TIM1_CH1) */
    GPIOA->MODER &= ~GPIO_MODER_MODE8_Msk;
    GPIOA->MODER |= (2U << GPIO_MODER_MODE8_Pos); /* AF mode: 10b */

    GPIOA->AFR[1] &= ~(0xFU << GPIO_AFRH_AFSEL8_Pos);
    GPIOA->AFR[1] |= (6U << GPIO_AFRH_AFSEL8_Pos);  /* AF6 */

    /* 3. Configure Time Base: PSC = 0, ARR = 8499 -> 20 kHz */
    TIM1->PSC = TIM1_PSC_VAL;
    TIM1->ARR = TIM1_ARR_VAL;

    /* 4. Configure Channel 1: CCR1 = 2125 (25%), PWM Mode 1, Preload Enable */
    TIM1->CCR1 = TIM1_CCR1_VAL;
    TIM1->CCMR1 &= ~TIM_CCMR1_OC1M_Msk;
    TIM1->CCMR1 |= (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;

    /* 5. Enable Channel 1 Output */
    TIM1->CCER |= TIM_CCER_CC1E;

    /* 6. Advanced Timer Output Enable: MOE bit in BDTR */
    TIM1->BDTR |= TIM_BDTR_MOE;

    /* 7. Enable Auto-reload preload and Counter */
    TIM1->CR1 |= TIM_CR1_ARPE | TIM_CR1_CEN;
}
```

---

#### 4. Verification and DRC Status
- **Register Simulation**: Verified via register simulator against preset `sysclk_170mhz_pll_hsi16_apb_div1`. Resulting output on PA8 is `TIM1_CH1` at exactly $20\,000\text{ Hz}$ with $25.0\%$ duty cycle.
- **Syntax Check**: Verified via `compile_check` against CMSIS device headers for STM32G4 with `-Wall -Werror`.
- **Design Rule Checks (DRC)**: All checks (`DRC-CLK-01`, `DRC-CLK-02`, `DRC-PIN-01`, `DRC-PIN-02`, `DRC-PIN-03`, `DRC-REQ-01`) passed with 0 errors and 0 warnings.