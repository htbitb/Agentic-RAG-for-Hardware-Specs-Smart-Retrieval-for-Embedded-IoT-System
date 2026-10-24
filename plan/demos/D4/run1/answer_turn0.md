# STM32G474 DC Motor & ESP32 Node Design Plan

This document details the complete design of the STM32G474 node driving a DC motor with a 20 kHz PWM, communicating via UART with an ESP32 at 115,200 baud, and operating within a 50 µA sleep-current budget.

---

### Step 1: Target Hardware & Power Rails
1. **Microcontroller**: STM32G474 (LQFP64 package), powered from a stabilized **VDD = 3.3 V** rail (recommended operating range: 1.71 V to 3.6 V [STM32G474_Datasheet p.84]; absolute maximum is 4.0 V [STM32G474_Datasheet p.82]).
2. **Co-processor**: ESP32, powered from the common **VDD = 3.3 V** rail (DC characteristics specified at 3.3 V [ESP32_Datasheet p.52]).
3. **Common Ground**: Shared ground plane between the STM32G474 and ESP32.

---

### Step 2: System Clock and PLL Configuration (Max SYSCLK = 170 MHz)
1. **Clock Source**: External 8 MHz crystal oscillator (HSE) on OSC_IN/OSC_OUT pins [STM32G474_Datasheet p.117].
2. **Core Voltage Scaling**: Range 1 Boost mode enabled via `PWR_CR5_R1MODE = 0` to permit operation up to the maximum 170 MHz [STM32G474_Datasheet p.84].
3. **Flash Latency**: Set to **4 wait states (WS)** (5 CPU cycles access time) required for 170 MHz in Range 1 Boost mode [STM32G474_RM0440 p.98].
4. **PLL Configuration**:
   - HSE frequency: $f_{\text{HSE}} = 8\text{ MHz}$
   - PLL input divider: $M = 2 \implies f_{\text{VCO\_IN}} = 8\text{ MHz} / 2 = 4\text{ MHz}$
   - PLL multiplication factor: $N = 85 \implies f_{\text{VCO}} = 4\text{ MHz} \times 85 = 340\text{ MHz}$
   - PLL 'R' output divider: $R = 2 \implies f_{\text{PLL\_R}} = 340\text{ MHz} / 2 = 170\text{ MHz}$
   - Switch SYSCLK source to PLL_R: **$\text{SYSCLK} = 170\text{ MHz}$** [STM32G474_Datasheet p.84].
5. **Bus Prescalers**:
   - AHB Prescaler: $/1 \implies \text{HCLK} = 170\text{ MHz}$
   - APB1 Prescaler: $/1 \implies \text{PCLK1} = 170\text{ MHz}$
   - APB2 Prescaler: $/1 \implies \text{PCLK2} = 170\text{ MHz}$
   - Timer Clocks: Since APB prescalers are 1, $\text{TIMxCLK} = \text{PCLK} = 170\text{ MHz}$.

---

### Step 3: 20 kHz PWM Generation for DC Motor
1. **Peripheral Selection**: Advanced Control Timer **TIM1**, Channel 1.
2. **Pin Assignment**:
   - **PA8** (Pin 42 in LQFP64): configured as Alternate Function 6 (`AF6`, `TIM1_CH1`), push-pull output [STM32G474_Datasheet p.73].
3. **Register Configuration**:
   - Timer clock: $f_{\text{TIM}} = 170\text{ MHz}$.
   - Target PWM frequency: $f_{\text{PWM}} = 20,000\text{ Hz}$.
   - Prescaler: $\text{PSC} = 0$ (clock prescaler = 1).
   - Period / Auto-reload:
     $$\text{ARR} = (170000000\text{ Hz} / (1 \times 20000\text{ Hz})) - 1 = 8500 - 1 = 8499$$
   - Duty resolution: 8500 discrete steps (~13.05 bits).
   - 50% Duty Cycle: $\text{CCR1} = 4250$ (since $4250 / 8500 = 0.5$).
   - For TIM1, the Main Output Enable bit (`BDTR.MOE`) and `CCER.CC1E` must be set to drive the pin.

---

### Step 4: UART Communication with ESP32 (115,200 baud)
1. **Peripheral Selection**: **USART1**.
2. **Pin Assignment**:
   - **PA9** (Pin 43 in LQFP64): `AF7` (`USART1_TX`), Push-Pull $\rightarrow$ connects to ESP32 RX [STM32G474_Datasheet p.73].
   - **PA10** (Pin 44 in LQFP64): `AF7` (`USART1_RX`), Floating/Pull-up input $\rightarrow$ connects to ESP32 TX [STM32G474_Datasheet p.73].
3. **Baud Rate Configuration**:
   - USART clock: $f_{\text{USART1}} = \text{PCLK2} = 170\text{ MHz}$.
   - Baud rate: 115,200 bps.
   - Baud Rate Register:
     $$\text{USARTDIV} = 170000000 / 115200 \approx 1475.694 \implies \text{BRR} = 1476$$
     Achieved baud rate: $170000000 / 1476 \approx 115176.15\text{ bps}$ (error: $-0.02\%$, well within UART $\pm 2\%$ tolerance).

---

### Step 5: Logic-Level Compatibility Analysis
Both chips run at $V_{DD} = 3.3\text{ V}$.

1. **STM32G474 (PA9 TX) $\rightarrow$ ESP32 (RX)**:
   - Output High $V_{OH,\text{min}}$ (STM32): $2.9\text{ V}$ ($I_{OH} = 8\text{ mA}$) [STM32G474_Datasheet p.130]
   - Input High $V_{IH,\text{min}}$ (ESP32): $0.75 \times 3.3\text{ V} = 2.475\text{ V}$ [ESP32_Datasheet p.52]
   - High-level margin: $2.9\text{ V} \ge 2.475\text{ V}$ (**PASS**)
   - Output Low $V_{OL,\text{max}}$ (STM32): $0.4\text{ V}$ ($I_{OL} = 8\text{ mA}$) [STM32G474_Datasheet p.130]
   - Input Low $V_{IL,\text{max}}$ (ESP32): $0.25 \times 3.3\text{ V} = 0.825\text{ V}$ [ESP32_Datasheet p.52]
   - Low-level margin: $0.4\text{ V} \le 0.825\text{ V}$ (**PASS**)
   - Overvoltage safety: STM32 output $3.3\text{ V} \le 3.6\text{ V}$ (ESP32 max input voltage $V_{DD}+0.3\text{ V} = 3.6\text{ V}$) [ESP32_Datasheet p.52] (**PASS**)

2. **ESP32 (TX) $\rightarrow$ STM32G474 (PA10 RX)**:
   - Output High $V_{OH,\text{min}}$ (ESP32): $0.8 \times 3.3\text{ V} = 2.64\text{ V}$ [ESP32_Datasheet p.52]
   - Input High $V_{IH,\text{min}}$ (STM32): $0.7 \times 3.3\text{ V} = 2.31\text{ V}$ [STM32G474_Datasheet p.128]
   - High-level margin: $2.64\text{ V} \ge 2.31\text{ V}$ (**PASS**)
   - Output Low $V_{OL,\text{max}}$ (ESP32): $0.1 \times 3.3\text{ V} = 0.33\text{ V}$ [ESP32_Datasheet p.52]
   - Input Low $V_{IL,\text{max}}$ (STM32): $0.3 \times 3.3\text{ V} = 0.99\text{ V}$ [STM32G474_Datasheet p.128]
   - Low-level margin: $0.33\text{ V} \le 0.99\text{ V}$ (**PASS**)
   - Overvoltage safety: PA10 is an `FT_fda` 5 V-tolerant pin (absolute max $V_{DD}+4.0\text{ V}$ up to 5.5 V) [STM32G474_Datasheet p.82] (**PASS**).

**Verdict**: The UART lines interface directly without any level shifters.

---

### Step 6: Sleep-Current Budget Verification (< 50 µA)
From the STM32G474 supply current tables in the datasheet:
1. **Sleep / Low-Power Sleep Mode**:
   - In Low-power sleep mode with Flash in power-down at 250 kHz: $I_{DD,\text{typ}} = 120\text{ µA}$ at 25 °C [STM32G474_Datasheet p.101], which exceeds the 50 µA budget.
2. **Stop 1 Mode**:
   - Supply current in Stop 1 mode (RTC disabled, 3.0 V, 25 °C): $I_{DD,\text{typ}} = 80.5\text{ µA}$, and at 3.6 V, 25 °C: $I_{DD,\text{typ}} = 81.5\text{ µA}$ [STM32G474_Datasheet p.102]. Both exceed the 50 µA budget.
3. **Standby Mode / Shutdown Mode (Selected Low-Power Mode)**:
   - Shutdown mode (at 3 V, 25 °C): $I_{DD,\text{typ}} = 43\text{ nA}$ ($0.043\text{ µA}$) [STM32G474_Datasheet p.105], well under 50 µA.
   - Standby mode (at 3 V, 25 °C with RTC disabled): typically under $2\text{ µA}$, well under the 50 µA budget.

**Conclusion**:
To stay strictly below the 50 µA sleep budget, the STM32G474 must enter **Standby Mode** (or Shutdown Mode) during idle periods. Wake-up is achieved via a dedicated wakeup pin (e.g., WKUP line from ESP32) or RTC wakeup timer.

---

### Firmware Configuration Snippet

```c
#include "stm32g4xx.h"

void Clock_Config_170MHz(void) {
    // 1. Enable HSE and wait for ready
    RCC->CR |= RCC_CR_HSEON;
    while (!(RCC->CR & RCC_CR_HSERDY));

    // 2. Enable Power interface clock and configure Range 1 Boost mode
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    PWR->CR1 &= ~PWR_CR1_VOS;
    PWR->CR1 |= PWR_CR1_VOS_0; // Range 1 normal
    PWR->CR5 &= ~PWR_CR5_R1MODE; // 0: Range 1 boost mode enabled

    // 3. Configure Flash latency: 4 WS for 170 MHz in Range 1 Boost
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;
    while ((FLASH->ACR & FLASH_ACR_LATENCY) != FLASH_ACR_LATENCY_4WS);

    // 4. Configure PLL: HSE = 8MHz, M = 2 (/2 -> 4MHz), N = 85 (*85 -> 340MHz), R = 2 (/2 -> 170MHz)
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE |
                   (1 << RCC_PLLCFGR_PLLM_Pos) |        // M = 2 (register field value 1)
                   (85 << RCC_PLLCFGR_PLLN_Pos) |       // N = 85
                   (0 << RCC_PLLCFGR_PLLR_Pos) |        // R = 2 (register field value 00)
                   RCC_PLLCFGR_PLLREN;

    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));

    // 5. Switch SYSCLK to PLL
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL);
}

void Motor_PWM_Init_20kHz(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;

    // Configure PA8 as AF6 (TIM1_CH1)
    GPIOA->MODER &= ~GPIO_MODER_MODE8_Msk;
    GPIOA->MODER |= (2 << GPIO_MODER_MODE8_Pos); // AF
    GPIOA->AFR[1] &= ~(0xF << GPIO_AFRH_AFSEL8_Pos);
    GPIOA->AFR[1] |= (6 << GPIO_AFRH_AFSEL8_Pos); // AF6

    // 170 MHz / 20 kHz = 8500 counts -> ARR = 8499, PSC = 0
    TIM1->PSC = 0;
    TIM1->ARR = 8499;
    TIM1->CCR1 = 4250; // 50% initial duty cycle

    // PWM mode 1 on CH1, enable output and main output
    TIM1->CCMR1 |= (6 << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER |= TIM_CCER_CC1E;
    TIM1->BDTR |= TIM_BDTR_MOE; // Main Output Enable required for TIM1
    TIM1->CR1 |= TIM_CR1_CEN;
}

void ESP32_UART_Init_115200(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;

    // Configure PA9 (TX) and PA10 (RX) as AF7
    GPIOA->MODER &= ~(GPIO_MODER_MODE9_Msk | GPIO_MODER_MODE10_Msk);
    GPIOA->MODER |= (2 << GPIO_MODER_MODE9_Pos) | (2 << GPIO_MODER_MODE10_Pos);
    GPIOA->AFR[1] |= (7 << GPIO_AFRH_AFSEL9_Pos) | (7 << GPIO_AFRH_AFSEL10_Pos);

    // 170 MHz / 115200 baud = 1475.69 -> BRR = 1476
    USART1->BRR = 1476;
    USART1->CR1 |= USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
}
```