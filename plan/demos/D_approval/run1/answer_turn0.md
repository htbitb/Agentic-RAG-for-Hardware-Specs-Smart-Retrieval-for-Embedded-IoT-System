### STM32G474 TIM1_CH1 (PA8) 20 kHz, 25% Duty PWM Configuration

#### 1. Clock and Timer Parameter Calculations
- **Timer Kernel Clock ($f_{\text{TIM1CLK}}$)**:
  - $SYSCLK = 170\text{ MHz}$, $AHB_{\text{PRESC}} = 1$, $APB2_{\text{PRESC}} = 1$.
  - When APB prescaler is 1, timer clock equals PCLK: $f_{\text{TIM1CLK}} = 170\text{ MHz}$.
- **Target PWM Frequency ($f_{\text{PWM}}$)**: $20\text{ kHz}$
- **Counter Counts per Period**:
  $$\text{Period Counts} = \frac{f_{\text{TIM1CLK}}}{f_{\text{PWM}}} = \frac{170\,000\,000}{20\,000} = 8500$$
- **Prescaler & Auto-Reload**:
  - Setting $\text{PSC} = 0$ (timer clock divider = 1) yields maximum duty cycle resolution (8500 steps, ~13 bits).
  - $\text{ARR} = 8500 - 1 = 8499$.
- **Compare Value for 25% Duty Cycle**:
  - In edge-aligned PWM Mode 1 (up-counting):
    $$\text{CCR1} = 8500 \times 0.25 = 2125$$
  - Frequency error: $0.0\%$, Duty error: $0.0\%$.

#### 2. Pin Routing
- **Pin**: `PA8`
- **Alternate Function**: `AF6` (`TIM1_CH1` per STM32G474 datasheet Table 13)
- **Mode**: Alternate Function Push-Pull (`MODER[17:16] = 10b`, `AFRH[3:0] = 0110b`).

#### 3. Advanced Timer Specifics
- Since **TIM1** is an advanced-control timer, `TIM1->BDTR |= TIM_BDTR_MOE` (Main Output Enable) must be set for the output channels to be connected to the I/O pads.

---

### Firmware Code (`pwm_pa8.c`)

```c
#include "stm32g4xx.h"

/**
 * @brief Initialize PA8 as TIM1_CH1 for 20 kHz PWM with 25% duty cycle.
 *        Assumes SYSCLK = HCLK = PCLK1 = PCLK2 = 170 MHz.
 */
void tim1_pa8_pwm_init(void) {
    /* 1. Enable peripheral clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;

    /* 2. Configure PA8 alternate function AF6 (TIM1_CH1) */
    GPIOA->MODER &= ~(3U << (8 * 2));
    GPIOA->MODER |= (2U << (8 * 2));

    GPIOA->AFR[1] &= ~(0xFU << ((8 - 8) * 4));
    GPIOA->AFR[1] |= (6U << ((8 - 8) * 4));

    GPIOA->OSPEEDR |= (3U << (8 * 2));

    /* 3. Configure TIM1 time base and PWM output
     * TIM1CLK = 170 MHz
     * Target frequency = 20 kHz -> Counter period = 170,000,000 / 20,000 = 8500 counts
     * Prescaler PSC = 0
     * Auto-reload ARR = 8500 - 1 = 8499
     * Duty cycle = 25% -> CCR1 = 8500 * 0.25 = 2125
     */
    TIM1->PSC = 0;
    TIM1->ARR = 8499;
    TIM1->CCR1 = 2125;

    /* Output Compare 1 Mode: PWM mode 1 (OC1M = 0110b), enable preload (OC1PE) */
    TIM1->CCMR1 &= ~(TIM_CCMR1_OC1M | TIM_CCMR1_CC1S);
    TIM1->CCMR1 |= (TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2);
    TIM1->CCMR1 |= TIM_CCMR1_OC1PE;

    /* Enable Channel 1 output */
    TIM1->CCER |= TIM_CCER_CC1E;

    /* Enable Main Output (MOE) in BDTR - required for TIM1 advanced-control timer */
    TIM1->BDTR |= TIM_BDTR_MOE;

    /* Enable auto-reload preload and start counter */
    TIM1->CR1 |= TIM_CR1_ARPE;
    TIM1->CR1 |= TIM_CR1_CEN;

    /* Generate update event to load preloaded registers immediately */
    TIM1->EGR |= TIM_EGR_UG;
}
```

The file `pwm_pa8.c` has been generated and saved into the workspace. All design rules and register simulations have been executed and passed.