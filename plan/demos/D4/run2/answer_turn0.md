### Executive Summary & System Overview

This document presents the complete engineering design for an embedded node featuring the **STM32G474** microcontroller. The node drives a DC motor using 20 kHz PWM, communicates with an **ESP32** over full-duplex UART at 115200 baud, runs at the maximum allowable system frequency (170 MHz) generated from an 8 MHz external crystal (HSE) via the PLL, and operates within a **50 uA sleep-current budget**.

---

### Numbered Design Plan

#### Step 1: Clock Tree and Maximum SYSCLK Configuration
1. **Target Frequency Identification**:
   - The STM32G474 maximum operating frequency is **170 MHz** for AHB (HCLK), APB1 (PCLK1), and APB2 (PCLK2) in **Range 1 Boost Mode** [STM32G474_Datasheet p.84, Table 17].
2. **Crystal Oscillator (HSE)**:
   - External crystal frequency: $f_{\text{OSC\_IN}} = 8\text{ MHz}$ (recommended range: 4 MHz to 48 MHz [STM32G474_Datasheet p.117]).
3. **Phase-Locked Loop (PLL) Calculations**:
   - PLL input division factor: $M = 2$, giving $8\text{ MHz} / 2 = 4\text{ MHz}$ (within the 2.66 MHz to 16 MHz input range [STM32G474_Datasheet p.123]).
   - Voltage Controlled Oscillator (VCO): Multiplication factor $N = 85$, giving $4\text{ MHz} \times 85 = 340\text{ MHz}$ (within the 96 MHz to 344 MHz Range 1 limit [STM32G474_Datasheet p.123]).
   - Main PLL output divider: $R = 2$, giving $340\text{ MHz} / 2 = 170\text{ MHz}$ (maximum SYSCLK).
4. **Flash Latency and Dynamic Voltage Scaling**:
   - Dynamic voltage scaling: Range 1 Boost mode is selected by clearing `R1MODE` in `PWR_CR5` [STM32G474_RM0440 p.232].
   - Flash wait states: Configured to **4 wait states (4 WS)** in `FLASH_ACR` (required for $150\text{ MHz} < f_{\text{HCLK}} \le 170\text{ MHz}$ in Range 1 Boost mode [STM32G474_RM0440 p.98, Table 9]).
5. **Bus Prescalers**:
   - $\text{AHB PRESC} = /1 \implies \text{HCLK} = 170\text{ MHz}$.
   - $\text{APB1 PRESC} = /1 \implies \text{PCLK1} = 170\text{ MHz}$.
   - $\text{APB2 PRESC} = /1 \implies \text{PCLK2} = 170\text{ MHz}$.

---

#### Step 2: DC Motor 20 kHz PWM Configuration
1. **Timer Selection**:
   - Advanced Control Timer **TIM1** on APB2.
   - Timer clock: $f_{\text{TIM\_CLK}} = 170\text{ MHz}$.
2. **PWM Frequency Calculation**:
   - Prescaler: $\text{PSC} = 0$.
   - Auto-Reload Register:
     $$\text{ARR} = \frac{170000000\text{ Hz}}{20000\text{ Hz}} - 1 = 8500 - 1 = 8499$$
   - Resulting PWM frequency: $\frac{170000000\text{ Hz}}{(0 + 1) \times (8499 + 1)} = 20000\text{ Hz}$ (0.0% error).
3. **Pin Assignment**:
   - **PA8** allocated to `TIM1_CH1` (Alternate Function AF6, 5 V tolerant FT_a pin) [STM32G474_Datasheet p.73].
   - Configured in Edge-aligned PWM mode 1 (`OC1M = 0110b`), main output enabled (`MOE = 1` in `TIM1_BDTR`).

---

#### Step 3: UART Interface to ESP32
1. **Peripheral & Baud Rate**:
   - Peripheral: **USART1** (clocked by $\text{PCLK2} = 170\text{ MHz}$).
   - Target baud rate: 115200 baud.
   - Baud rate divisor:
     $$\text{USARTDIV} = \frac{170000000}{115200} \approx 1475.694 \implies \text{USART1\_BRR} = 1476$$
2. **Pin Assignment**:
   - **PA9** allocated to `USART1_TX` (AF7, 5 V tolerant FT_fda) [STM32G474_Datasheet p.73].
   - **PA10** allocated to `USART1_RX` (AF7, 5 V tolerant FT_fda) [STM32G474_Datasheet p.73].

---

#### Step 4: Logic-Level Compatibility Analysis
Operating both devices at a nominal $V_{\text{DD}} = 3.3\text{ V}$:

1. **STM32G474 (PA9 TX) driving ESP32 (RX)**:
   - High level: $V_{\text{OH, min}} (\text{STM32}) = 2.9\text{ V}$ [STM32G474_Datasheet p.130] exceeds $V_{\text{IH, min}} (\text{ESP32}) = 2.475\text{ V}$ [ESP32_Datasheet p.52] (PASS).
   - Low level: $V_{\text{OL, max}} (\text{STM32}) = 0.4\text{ V}$ [STM32G474_Datasheet p.130] is below $V_{\text{IL, max}} (\text{ESP32}) = 0.825\text{ V}$ [ESP32_Datasheet p.52] (PASS).
   - Overvoltage safety: STM32 maximum output of 3.3 V is below the ESP32 maximum input rating of 3.6 V [ESP32_Datasheet p.52] (PASS).

2. **ESP32 (TX) driving STM32G474 (PA10 RX)**:
   - High level: $V_{\text{OH, min}} (\text{ESP32}) = 2.64\text{ V}$ [ESP32_Datasheet p.52] exceeds $V_{\text{IH, min}} (\text{STM32}) = 2.31\text{ V}$ [STM32G474_Datasheet p.128] (PASS).
   - Low level: $V_{\text{OL, max}} (\text{ESP32}) = 0.33\text{ V}$ [ESP32_Datasheet p.52] is below $V_{\text{IL, max}} (\text{STM32}) = 0.99\text{ V}$ [STM32G474_Datasheet p.128] (PASS).
   - Overvoltage safety: ESP32 maximum output of 3.3 V is safely below the STM32 FT pin maximum input limit of 5.5 V [STM32G474_Datasheet p.84] (PASS).

Both signal directions pass digital input/output voltage compatibility checks with positive margins.

---

#### Step 5: Sleep-Current Budget Evaluation
The design specifies a sleep-current budget of **50 uA**.
According to the STM32G474 supply current specifications:
- **Sleep mode** at 16 MHz consumes 830 uA typical [STM32G474_Datasheet p.100, Table 28], which exceeds the 50 uA budget.
- **Low-power sleep mode** at 62.5 kHz consumes 110 uA typical [STM32G474_Datasheet p.101, Table 29], which exceeds the 50 uA budget.
- **Stop 0 mode** consumes 190 uA typical at 3.0 V, 25 °C [STM32G474_Datasheet p.102, Table 31], exceeding the budget.
- **Stop 1 mode** consumes 80.5 uA typical at 3.0 V, 25 °C [STM32G474_Datasheet p.102, Table 30], exceeding the budget.
- **Standby mode** consumes 130 nA typical at 3.0 V (180 nA at 3.6 V), with a maximum of 360 nA at 25 °C [STM32G474_Datasheet p.103, Table 32], well below 50 uA. Even with SRAM2 retained (adding 305 nA typical) or RTC enabled, current remains below 3 uA.
- **Shutdown mode** consumes 43 nA typical at 3.0 V (87 nA at 3.6 V) [STM32G474_Datasheet p.105, Table 33], well below 50 uA.

**Recommendation**: To satisfy the 50 uA budget requirement, the node must be placed into **Standby Mode** (with SRAM2 retention if state needs to be preserved) or **Shutdown Mode**. Wakeup is achieved via the ESP32 triggering a WKUP pin or via RTC periodic wakeup.

---

### Firmware Configuration Snippet

```c
#include "stm32g4xx.h"

void SystemClock_Config_170MHz_HSE(void) {
    // 1. Enable Power interface clock and configure Range 1 Boost mode
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    PWR->CR5 &= ~PWR_CR5_R1MODE; // 0: Range 1 Boost mode (up to 170 MHz)

    // 2. Configure Flash Latency to 4 wait states (for 170 MHz in Boost mode)
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;

    // 3. Enable HSE (8 MHz external crystal) and wait for ready
    RCC->CR |= RCC_CR_HSEON;
    while (!(RCC->CR & RCC_CR_HSERDY));

    // 4. Configure PLL: Source=HSE (8 MHz), M=/2 (4 MHz), N=85 (340 MHz VCO), R=/2 (170 MHz)
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE |
                   (1 << RCC_PLLCFGR_PLLM_Pos)   | // M = 2
                   (85 << RCC_PLLCFGR_PLLN_Pos)  | // N = 85
                   (0 << RCC_PLLCFGR_PLLR_Pos)   | // R = 2
                   RCC_PLLCFGR_PLLREN;             // Enable PLLCLK output

    // 5. Enable PLL and wait for lock
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));

    // 6. Set AHB/APB prescalers to div 1 and select PLL as system clock source
    RCC->CFGR |= RCC_CFGR_HPRE_DIV1 | RCC_CFGR_PPRE1_DIV1 | RCC_CFGR_PPRE2_DIV1;
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL);
}

void Motor_PWM_Init_20kHz(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;

    // Configure PA8 as AF6 (TIM1_CH1)
    GPIOA->MODER &= ~GPIO_MODER_MODE8;
    GPIOA->MODER |= GPIO_MODER_MODE8_1;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL8) | (6 << GPIO_AFRH_AFSEL8_Pos);

    // 20 kHz PWM: f_tim = 170 MHz, PSC = 0, ARR = 8499
    TIM1->PSC = 0;
    TIM1->ARR = 8499;
    TIM1->CCR1 = 4250; // 50% initial duty cycle

    TIM1->CCMR1 |= (6 << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER |= TIM_CCER_CC1E;
    TIM1->BDTR |= TIM_BDTR_MOE;
    TIM1->CR1 |= TIM_CR1_ARPE | TIM_CR1_CEN;
}

void ESP32_UART_Init_115200(void) {
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;

    // Configure PA9 (TX) and PA10 (RX) as AF7
    GPIOA->MODER &= ~(GPIO_MODER_MODE9 | GPIO_MODER_MODE10);
    GPIOA->MODER |= (GPIO_MODER_MODE9_1 | GPIO_MODER_MODE10_1);
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~(GPIO_AFRH_AFSEL9 | GPIO_AFRH_AFSEL10)) |
                    (7 << GPIO_AFRH_AFSEL9_Pos) | (7 << GPIO_AFRH_AFSEL10_Pos);

    // BRR = 170,000,000 / 115200 = 1476
    USART1->BRR = 1476;
    USART1->CR1 |= USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
}
```