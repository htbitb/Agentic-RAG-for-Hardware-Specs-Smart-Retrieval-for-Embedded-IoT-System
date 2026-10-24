### STM32G474 DC Motor & UART Node Design

---

### 1. Board Parameters & Hardware Setup
- **HSE Crystal**: 12 MHz external crystal on OSC_IN / OSC_OUT.
- **Target MCU**: STM32G474 in LQFP64 package, supplied at $V_{DD} = 3.3\text{ V}$.
- **Peer MCU**: ESP32 supplied at $V_{DD} = 3.3\text{ V}$.

---

### 2. Clock Tree & PLL Configuration
To reach the maximum SYSCLK frequency of **170 MHz** ([STM32G474_Datasheet p. 84]):
1. **Voltage Range & Boost Mode**:
   - VCORE Range 1 Boost mode enabled (`PWR_CR5_R1MODE = 0`, `PWR_CR1_VOS = 1`).
2. **Flash Wait States (Latency)**:
   - For 170 MHz operation in Range 1 Boost mode, 4 wait states (5 CPU cycles) are required (`FLASH_ACR_LATENCY = 4`) ([STM32G474_RM0440 p. 98, Table 9]).
3. **PLL Calculation**:
   - Input clock: $f_{IN} = 12\text{ MHz}$ (from HSE).
   - Division factor $M = 3 \implies 12\text{ MHz} / 3 = 4\text{ MHz}$ VCO input (within the allowed $2.66\text{ MHz}$ to $16\text{ MHz}$ range [STM32G474_Datasheet p. 123]).
   - Multiplication factor $N = 85 \implies 4\text{ MHz} \times 85 = 340\text{ MHz}$ VCO output (within the Range 1 range of $96\text{ MHz}$ to $344\text{ MHz}$ [STM32G474_Datasheet p. 123]).
   - Division factor $R = 2 \implies 340\text{ MHz} / 2 = 170\text{ MHz}$ PLL output ($f_{SYSCLK} = 170\text{ MHz}$).
   - Prescalers: AHB prescaler = 1 ($HCLK = 170\text{ MHz}$), APB1 prescaler = 1 ($PCLK1 = 170\text{ MHz}$), APB2 prescaler = 1 ($PCLK2 = 170\text{ MHz}$).

---

### 3. Peripheral Pinout & Configurations

#### A. 20 kHz Motor PWM (TIM1 Channel 1)
- **Pin**: **PA8** (Pin 42 in LQFP64, AF6 = `TIM1_CH1`, Push-Pull).
- **Timer Settings**:
  - Timer clock: $170\text{ MHz}$.
  - Target frequency: $20000\text{ Hz}$.
  - Prescaler: `TIM1_PSC = 0` (divide by 1).
  - Auto-reload: `TIM1_ARR = 8499` (calculated as $170000000 / 20000 - 1 = 8499$).
  - Resulting frequency: $170000000 / ((0 + 1) \times (8499 + 1)) = 20000\text{ Hz}$ (0.0% error).
  - For a 50% duty cycle: `TIM1_CCR1 = 4250` (calculated as $8500 \times 0.5 = 4250$).
  - Main output enabled: `TIM1_BDTR |= TIM_BDTR_MOE`.

#### B. UART Communication with ESP32 (USART1 at 115200 Baud)
- **TX Pin**: **PA9** (Pin 43 in LQFP64, AF7 = `USART1_TX`, Push-Pull).
- **RX Pin**: **PA10** (Pin 44 in LQFP64, AF7 = `USART1_RX`, Input Floating / Pull-Up).
- **Baud Rate Calculation**:
  - Clock source: $PCLK2 = 170\text{ MHz}$.
  - Target baud: $115200\text{ baud}$.
  - Divider: $170000000 / 115200 \approx 1475.694 \implies \text{BRR} = 1476$.
  - Resulting baud: $170000000 / 1476 \approx 115176\text{ baud}$ (relative error $-0.02\%$).

---

### 4. Logic-Level Compatibility Analysis (STM32G474 $\leftrightarrow$ ESP32 at 3.3 V)
Both devices are powered from a 3.3 V supply:
1. **STM32 TX (PA9) $\rightarrow$ ESP32 RX**:
   - High-level: $V_{OH,min}(\text{STM32}) = 2.9\text{ V} \ge V_{IH,min}(\text{ESP32}) = 2.475\text{ V}$ $\implies$ **PASS** (noise margin: $2.9\text{ V} - 2.475\text{ V} = 0.425\text{ V}$).
   - Low-level: $V_{OL,max}(\text{STM32}) = 0.4\text{ V} \le V_{IL,max}(\text{ESP32}) = 0.825\text{ V}$ $\implies$ **PASS** (noise margin: $0.825\text{ V} - 0.4\text{ V} = 0.425\text{ V}$).
   - Overvoltage: $V_{OH,max}(\text{STM32}) = 3.3\text{ V} \le V_{IN,max}(\text{ESP32}) = 3.6\text{ V}$ $\implies$ **PASS**.
2. **ESP32 TX $\rightarrow$ STM32 RX (PA10)**:
   - PA10 is an FT (5 V tolerant) input accepting up to $5.5\text{ V}$ ([STM32G474_Datasheet p. 84]).
   - High-level: $V_{OH,min}(\text{ESP32}) = 2.64\text{ V} \ge V_{IH,min}(\text{STM32}) = 2.31\text{ V}$ $\implies$ **PASS** (noise margin: $2.64\text{ V} - 2.31\text{ V} = 0.33\text{ V}$).
   - Low-level: $V_{OL,max}(\text{ESP32}) = 0.33\text{ V} \le V_{IL,max}(\text{STM32}) = 0.99\text{ V}$ $\implies$ **PASS** (noise margin: $0.99\text{ V} - 0.33\text{ V} = 0.66\text{ V}$).
   - Overvoltage: $V_{OH,max}(\text{ESP32}) = 3.3\text{ V} \le V_{IN,max}(\text{STM32}) = 5.5\text{ V}$ $\implies$ **PASS**.
- Direct digital connection between the two MCUs is fully verified and compatible.

---

### 5. Sleep Current Budget Verification ($50\ \mu\text{A}$ Budget)
Per STM32G474 Datasheet Section 5.3.5 ([STM32G474_Datasheet p. 102-105]):
- Standard Sleep mode with Flash ON consumes $> 100\ \mu\text{A}$, which exceeds the $50\ \mu\text{A}$ budget.
- Stop 1 mode consumes approximately $81\ \mu\text{A}$ typical at $25^\circ\text{C}$ ($V_{DD} = 3.0\text{ V}$ to $3.6\text{ V}$, Table 30 [STM32G474_Datasheet p. 102]).
- **Standby Mode** consumes:
  - $130\text{ nA}$ typical ($240\text{ nA}$ maximum) at $25^\circ\text{C}$, $V_{DD} = 3\text{ V}$ with RTC disabled (Table 32 [STM32G474_Datasheet p. 103]).
  - With SRAM2 retention enabled: adds $305\text{ nA}$ typical at $25^\circ\text{C}$ (Table 32 [STM32G474_Datasheet p. 104]), keeping total consumption well below $1\ \mu\text{A}$.
- **Shutdown Mode** consumes:
  - $43\text{ nA}$ typical ($130\text{ nA}$ maximum) at $25^\circ\text{C}$, $V_{DD} = 3\text{ V}$ (Table 33 [STM32G474_Datasheet p. 105]).
- To remain under the $50\ \mu\text{A}$ sleep current budget, the STM32G474 should enter **Standby Mode** (optionally with SRAM2 retention), achieving $< 1\ \mu\text{A}$ current draw and meeting the requirement with substantial margin.

---

### 6. Firmware Configuration Code (`stm32g474_motor_node_config.c`)

```c
#include "stm32g4xx.h"

void SystemClock_Config_170MHz_HSE(void) {
    /* 1. Enable HSE and wait for ready */
    RCC->CR |= RCC_CR_HSEON;
    while (!(RCC->CR & RCC_CR_HSERDY));

    /* 2. Configure Power regulator for Range 1 Boost mode */
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    PWR->CR1 = (PWR->CR1 & ~PWR_CR1_VOS) | PWR_CR1_VOS_0; /* Range 1 normal */
    PWR->CR5 &= ~PWR_CR5_R1MODE; /* Enable Boost mode */

    /* 3. Configure Flash Latency: 4 wait states for 170 MHz */
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;
    while ((FLASH->ACR & FLASH_ACR_LATENCY) != FLASH_ACR_LATENCY_4WS);

    /* 4. Configure PLL: HSE = 12 MHz, M = 3, N = 85, R = 2 -> SYSCLK = 170 MHz */
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE |
                   ((3 - 1) << RCC_PLLCFGR_PLLM_Pos) |
                   (85 << RCC_PLLCFGR_PLLN_Pos) |
                   (0 << RCC_PLLCFGR_PLLR_Pos) | /* PLLR = 2 */
                   RCC_PLLCFGR_PLLREN;

    /* 5. Enable PLL and wait for lock */
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));

    /* 6. Switch SYSCLK to PLL */
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL);
}

void Motor_PWM_TIM1_Init(void) {
    /* Enable GPIOA and TIM1 clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;

    /* Configure PA8: AF6 (TIM1_CH1), High Speed, Push-Pull */
    GPIOA->MODER &= ~(3U << (8 * 2));
    GPIOA->MODER |=  (2U << (8 * 2)); /* Alternate Function */
    GPIOA->AFR[1] &= ~(0xFU << ((8 - 8) * 4));
    GPIOA->AFR[1] |=  (6U << ((8 - 8) * 4)); /* AF6 */
    GPIOA->OSPEEDR |= (3U << (8 * 2));

    /* Configure TIM1 for 20 kHz PWM, 50% duty */
    TIM1->PSC = 0;
    TIM1->ARR = 8499;   /* 170 MHz / (8499 + 1) = 20 kHz */
    TIM1->CCR1 = 4250;  /* 50% duty */

    /* PWM Mode 1, preload enable */
    TIM1->CCMR1 = (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER |= TIM_CCER_CC1E;
    TIM1->BDTR |= TIM_BDTR_MOE; /* Main Output Enable */
    TIM1->CR1 |= TIM_CR1_ARPE | TIM_CR1_CEN;
}

void USART1_Init_115200(void) {
    /* PA9 -> TX (AF7), PA10 -> RX (AF7) */
    GPIOA->MODER &= ~((3U << (9 * 2)) | (3U << (10 * 2)));
    GPIOA->MODER |=  ((2U << (9 * 2)) | (2U << (10 * 2)));
    GPIOA->AFR[1] &= ~((0xFU << ((9 - 8) * 4)) | (0xFU << ((10 - 8) * 4)));
    GPIOA->AFR[1] |=  ((7U << ((9 - 8) * 4)) | (7U << ((10 - 8) * 4)));

    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;

    /* Baud rate: 170 MHz / 115200 = 1475.69 -> BRR = 1476 */
    USART1->BRR = 1476;
    USART1->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
}
```