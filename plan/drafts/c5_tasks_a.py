"""Task C5-001 … C5-006: THIẾU thông tin bắt buộc (hidden_info), cho build_c5_draft.py."""
from c5_common import (ESP_COMPAT_EXTRA, AUTHOR, CONV, FMT_PLAN, fmt_code, steps, pll, BOOST, FLASH_WS, LOW_POWER, STANDBY_ONLY, NOT_SHUTDOWN, sleep_total,
                       compat, level_shifter, no_direct_generic, ESP32_OFF, hse_hidden, clock_code_boost, ev, no_false_claim, trade_offs,
                       _NUM, _SKIP, CUR_U)

FENCE = "```"

# =====================================================================================================================  C5-001
T001_CODE = (FENCE + "c\n#include \"stm32g4xx.h\"\n\nint main(void)\n{\n" + clock_code_boost("HSE", 24, 6, 85) + """
    /* peripheral clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN | RCC_APB2ENR_USART1EN;

    /* PA8 = TIM1_CH1 (AF6), PA9 = USART1_TX (AF7), PA10 = USART1_RX (AF7) */
    GPIOA->MODER = (GPIOA->MODER & ~(GPIO_MODER_MODE8 | GPIO_MODER_MODE9 | GPIO_MODER_MODE10)) | GPIO_MODER_MODE8_1 | GPIO_MODER_MODE9_1 | GPIO_MODER_MODE10_1;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~(GPIO_AFRH_AFSEL8 | GPIO_AFRH_AFSEL9 | GPIO_AFRH_AFSEL10)) | (6U << GPIO_AFRH_AFSEL8_Pos) | (7U << GPIO_AFRH_AFSEL9_Pos) | (7U << GPIO_AFRH_AFSEL10_Pos);

    /* TIM1 CH1: 170 MHz / 10625 = 16 kHz, 40 % duty */
    TIM1->PSC = 0;
    TIM1->ARR = 10624;
    TIM1->CCR1 = 4250;
    TIM1->CCMR1 = (TIM1->CCMR1 & ~TIM_CCMR1_OC1M) | (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER |= TIM_CCER_CC1E;
    TIM1->BDTR |= TIM_BDTR_MOE;
    TIM1->CR1 |= TIM_CR1_ARPE;
    TIM1->EGR = TIM_EGR_UG;
    TIM1->CR1 |= TIM_CR1_CEN;

    /* USART1: 115200 baud 8N1 from PCLK2 = 170 MHz (written while UE = 0) */
    USART1->BRR = 1476;
    USART1->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;

    while (1) { }
}
""" + FENCE)

T001_STEP6 = """6. **Low-power mode and sleep budget (< 50 µA).** Stop 1 alone draws 80.5 µA typical (DS12288 Table 30, 3 V, 25 °C), more than the whole budget, so the STM32 goes to Standby mode with the RTC clocked by the LSE and the RTC wake-up timer set to 600 s; Standby with the RTC on the LSE crystal draws 0.655 µA typical (Table 32).
   - STM32G474, Standby + RTC (LSE): 0.66 µA
   - ESP32, Deep-sleep with RTC timer + RTC memory: 10 µA (ESP32 datasheet Table 4-2)
   - Motor driver module, sleep: 1 µA

   Total sleep current = 0.66 + 10 + 1 = 11.7 µA, well below the 50 µA budget. Standby does not keep the clock configuration, so the initialisation below runs again after every wake-up."""

T001_REF = """Thanks: with the 24 MHz HSE crystal and the 16 kHz PWM that the driver module needs, the design is as follows.

1. **Clock tree (24 MHz HSE -> 170 MHz).** The PLL input must stay within 2.66-16 MHz and the VCO within 96-344 MHz (DS12288 Table 46). PLLM = 6 gives 24 MHz / 6 = 4 MHz, PLLN = 85 gives a 340 MHz VCO and PLLR = 2 gives SYSCLK = 170 MHz (PLLSRC = HSE). Above 150 MHz the regulator must be in Range 1 boost mode (clear PWR_CR5.R1MODE), the Flash needs LATENCY = 4 wait states (RM0440 Table 9), and the AHB prescaler is set to /2 during the switch and back to /1 after at least 1 µs. AHB, APB1 and APB2 then all run at 170 MHz.
2. **Pin allocation.** PA8 = TIM1_CH1 (AF6) to the driver PWM input; PA9 = USART1_TX (AF7) to the ESP32 RX; PA10 = USART1_RX (AF7) from the ESP32 TX; PF0/PF1 = OSC_IN/OSC_OUT for the 24 MHz crystal; PC14/PC15 = OSC32_IN/OSC32_OUT for the 32.768 kHz LSE crystal. No pin is shared between two functions.
3. **PWM at 16 kHz, 40 %.** TIM1 sits on APB2 (prescaler 1), so TIM1CLK = 170 MHz and 170 MHz / 16 kHz = 10625 ticks: PSC = 0, ARR = 10624, CCR1 = 0.40 x 10625 = 4250. TIM1 is an advanced timer, so BDTR.MOE must be set.
4. **USART1 at 115200 baud.** USART1 is clocked by PCLK2 = 170 MHz with OVER8 = 0: BRR = 170000000 / 115200 = 1475.7, rounded to 1476 (115176 baud, -0.02 %).
5. **Logic levels of the ESP32 link.** Both chips run their I/O at 3.3 V. STM32 VOH >= VDD - 0.4 = 2.9 V is above the ESP32 VIH of 0.75 x 3.3 = 2.48 V, and STM32 VOL <= 0.4 V is below the ESP32 VIL of 0.25 x 3.3 = 0.83 V; the ESP32 VOH >= 0.8 x 3.3 = 2.64 V is above the STM32 VIH of 0.7 x 3.3 = 2.31 V and its VOL <= 0.33 V is below the STM32 VIL of 0.99 V. The levels are compatible, so TX/RX are wired directly (crossed) with a common ground and no level shifter.
""" + T001_STEP6 + """
7. **Firmware.** The program below brings up the clock tree, the PWM and USART1 from reset:

""" + T001_CODE + "\n"

T001 = {
    "id": "C5-001", "split": "test", "difficulty": "hard", "chips": ["stm32g474", "esp32"],
    "tags": ["system_goal", "missing_info", "code", "pll", "hse", "pwm", "uart", "current_budget", "logic_level"],
    "user": ("Help me design a motor-control node end to end. Hardware: an STM32G474 on our own PCB (VDD = 3.3 V) drives the PWM input of a brushed-DC "
             "motor driver module from TIM1 channel 1 on PA8 (edge-aligned PWM mode 1, active-high, 40 % duty cycle to start with, no dead time), and talks "
             "to an ESP32 Wi-Fi module (ESP32 I/O supply 3.3 V) over USART1 with TX on PA9 and RX on PA10 at 115200 baud, 8 data bits, no parity, 1 stop bit, "
             "oversampling by 16, transmitter and receiver enabled. The STM32 has a crystal on its HSE pins and must run SYSCLK = HCLK = PCLK1 = PCLK2 = "
             "170 MHz from the main PLL fed by HSE (all frequencies within 0.1 %). The PWM frequency must be the one the motor driver module needs (within "
             "±1 %). Idle phase: the motor is off, the driver module sleeps at 1 µA, the ESP32 is in Deep-sleep with the RTC timer and RTC memory on, and the "
             "STM32 still has to wake up every 10 minutes from its RTC (a 32.768 kHz LSE crystal is fitted); the whole node must draw less than 50 µA in this "
             "phase. The plan must cover the clock tree with the PLL M/N/R values, the pin allocation, the logic-level compatibility of the ESP32 link, the STM32 "
             "low-power mode and a sleep-current budget with the total. " + CONV + " "
             + fmt_code("the clock tree, the PWM and USART1; describe the low-power entry in the plan instead of coding it")),
    "human_policy": {"approval": "approve", "choice": {"prefer": "standby"},
                     "clarify": {"hse_hz": "The crystal on the STM32's HSE pins is 24 MHz.",
                                 "pwm_hz": "The motor driver module needs a 16 kHz PWM input signal."},
                     "max_answers": 3},
    "hidden_info": [hse_hidden(24),
                    {"id": "pwm_hz", "required": True,
                     "keywords": ["PWM frequency", "switching frequency", "PWM rate", "carrier frequency", "frequency of the PWM", "frequency for the PWM",
                                  "frequency should the PWM", "PWM input", "input frequency", "frequency should TIM1", "TIM1 frequency",
                                  "frequency does the driver", "frequency does the motor driver", "driver frequency", "driver module"],
                     "exclude": ["logic", "3.3 V"],
                     "value_patterns": [r"\b16\s*kHz\b", r"\b16\s*000\s*Hz\b"]}],
    "expected": {
        "initial": "reset", "hse_hz": 24000000,
        "spec": [{"type": "clock", "hse_hz": 24000000, "sysclk_hz": 170000000, "hclk_hz": 170000000, "pclk1_hz": 170000000, "pclk2_hz": 170000000, "tol_pct": 0.1},
                 {"type": "pwm", "pin": "PA8", "freq_hz": 16000, "duty_pct": 40, "tol_pct": 1},
                 {"type": "uart", "instance": "USART1", "baud": 115200, "tol_pct": 2, "tx_pin": "PA9", "rx_pin": "PA10", "frame": "8N1", "te": True, "re": True, "over8": 0}],
        "checklist": [steps(), pll(24e6, 170e6), BOOST, FLASH_WS,
                      {"id": "pwm_freq", "type": "quantity", "match": "any", "unit_out": "Hz", "min": 15840, "max": 16160,
                       "patterns": [r"PWM[^\n]{0,60}?" + _NUM + r"\s*-?\s*(?P<u>kHz|Hz)\b", _NUM + r"\s*-?\s*(?P<u>kHz)\s+PWM"],
                       "desc": "the PWM frequency used is the 16 kHz the driver module needs (±1 %)"},
                      LOW_POWER, sleep_total(11, 20), compat("esp_link_compat", "STM32-ESP32 UART link", extra=ESP_COMPAT_EXTRA)],
    },
    "graders": ["checklist", "clarify", "functional_sim", "compile"],
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("ahb_div2"), ev("brr"), ev("pwm_mode1"),
                 ev("stop1"), ev("standby_rtc"), ev("stm_vih"), ev("stm_voh"), ev("esp_dc"), ev("esp_modes"), ev("osc_pins"),
                 ev("pins_pa", "PA8 MCO - I2C3_SCL - I2C2_SDA I2S2_MCK TIM1_CH1", "PA9 - - I2C3_SMBA - I2C2_SCL I2S3_MCK TIM1_CH2 USART1_TX",
                    "PA10 - TIM17_BKIN - USB_CRS_SYNC I2C2_SMBA SPI2_MISO TIM1_CH3 USART1_RX")],
    "reference_calc": (
        "Thông tin ẩn: HSE = 24 MHz, PWM của driver = 16 kHz (không tra được: thuộc bo/module của người dùng; đề không nêu tên module). "
        "PLL (RM0440 p.291-293; DS12288 Table 46 p.123): f_in sau M ∈ [2,66; 16] MHz, VCO ∈ [96; 344] MHz, R ∈ {2,4,6,8}, M 1..16, N 8..127. "
        "24 MHz → 170 MHz: duy nhất M = 6 (4 MHz), N = 85 (VCO 340), R = 2 (liệt kê toàn bộ trong c5_handcalc.py). Đoán 8 MHz (M=2,N=85,R=2) với HSE thật 24 MHz "
        "→ 510 MHz; đoán 16 MHz (M=4) → 255 MHz; đoán 25 MHz (M=5,N=68) → 163,2 MHz (−4 %) ⇒ mục pll và spec clock đều trượt. 170 MHz > 150 MHz ⇒ boost "
        "(R1MODE = 0, RM Table 38 p.232), bước AHB/2 (p.233), 4 WS (RM Table 9 p.98). PWM: TIM1CLK = PCLK2 = 170 MHz; 170e6/16e3 = 10625 ⇒ PSC 0, ARR 10624, "
        "CCR1 = 0,4 × 10625 = 4250 (RM p.1179); đoán 20 kHz ⇒ ARR 8499 ⇒ trượt pwm_freq + spec pwm. USART1: BRR = 170e6/115200 = 1475,7 → 1476 ⇒ 115176 baud "
        "(−0,02 %, RM p.1708). Chân: PA8 AF6 TIM1_CH1, PA9 AF7 USART1_TX, PA10 AF7 USART1_RX (DS Table 13 p.73), PF0/PF1 OSC_IN/OUT, PC14/PC15 OSC32 (DS p.50). "
        "Mức logic 3,3 V: STM32 VOH ≥ VDD−0,4 = 2,9 V (DS Table 55 p.130) > ESP32 VIH 0,75×3,3 = 2,475 V; ESP32 VOH ≥ 0,8×3,3 = 2,64 V > STM32 VIH 0,7×3,3 = 2,31 V "
        "(DS Table 54 p.128); VOL 0,4/0,33 V < VIL 0,825/0,99 V ⇒ nối thẳng. Ngủ (3 V, 25 °C, typ): Stop 1 = 80,5 µA (DS Table 30 p.102) > 50 µA ⇒ Standby + RTC "
        "LSE (low drive) 0,655 µA (DS Table 32 p.104); ESP32 Deep-sleep RTC timer + RTC memory 10 µA (ESP32 DS Table 4-2 p.30); driver 1 µA ⇒ tổng 11,66 µA ≤ 50 µA. "
        "Biến thể Stop 1: 80,5 (hoặc 84,5 với LSE) + 11 ≈ 92-96 µA > 50 µA."),
    "variants": [
        {"name": "guessed_hse_8mhz", "must_fail": ["pll"],
         "edits": [("with the 24 MHz HSE crystal and the 16 kHz PWM", "assuming the usual 8 MHz HSE crystal, and with the 16 kHz PWM"),
                   ("(24 MHz HSE -> 170 MHz)", "(8 MHz HSE -> 170 MHz)"),
                   ("PLLM = 6 gives 24 MHz / 6 = 4 MHz", "PLLM = 2 gives 8 MHz / 2 = 4 MHz"),
                   ("for the 24 MHz crystal", "for the 8 MHz crystal"),
                   ("/* 24 MHz / 6 = 4 MHz", "/* 8 MHz / 2 = 4 MHz"),
                   ("(5U << RCC_PLLCFGR_PLLM_Pos)", "(1U << RCC_PLLCFGR_PLLM_Pos)")]},
        {"name": "guessed_pwm_20khz", "must_fail": ["pwm_freq"],
         "edits": [("16 kHz", "20 kHz"), ("10625", "8500"), ("10624", "8499"), ("4250", "3400")]},
        {"name": "stop1_over_budget", "must_fail": ["low_power_mode", "sleep_total"],
         "edits": [(T001_STEP6, """6. **Low-power mode and sleep budget (< 50 µA).** The STM32 goes to Stop 1 mode with the RTC clocked by the LSE and the RTC wake-up timer set to 600 s; Stop 1 keeps SRAM and the register contents, so no re-initialisation is needed after a wake-up.
   - STM32G474, Stop 1 + RTC (LSE): 84.5 µA
   - ESP32, Deep-sleep with RTC timer + RTC memory: 10 µA (ESP32 datasheet Table 4-2)
   - Motor driver module, sleep: 1 µA

   Total sleep current = 84.5 + 10 + 1 = 95.5 µA.""")]},
    ],
    "ref": T001_REF,
}

# =====================================================================================================================  C5-002
T002_CODE = (FENCE + "c\n#include \"stm32g4xx.h\"\n\nint main(void)\n{\n" + clock_code_boost("HSE", 12, 3, 85) + """
    /* peripheral clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN | RCC_APB1ENR1_I2C1EN;

    /* PA2 = USART2_TX, PA3 = USART2_RX (AF7) */
    GPIOA->MODER = (GPIOA->MODER & ~(GPIO_MODER_MODE2 | GPIO_MODER_MODE3)) | GPIO_MODER_MODE2_1 | GPIO_MODER_MODE3_1;
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~(GPIO_AFRL_AFSEL2 | GPIO_AFRL_AFSEL3)) | (7U << GPIO_AFRL_AFSEL2_Pos) | (7U << GPIO_AFRL_AFSEL3_Pos);

    /* PA15 = I2C1_SCL, PB7 = I2C1_SDA (AF4, open drain) */
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE15) | GPIO_MODER_MODE15_1;
    GPIOA->OTYPER |= GPIO_OTYPER_OT15;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL15) | (4U << GPIO_AFRH_AFSEL15_Pos);
    GPIOB->MODER = (GPIOB->MODER & ~GPIO_MODER_MODE7) | GPIO_MODER_MODE7_1;
    GPIOB->OTYPER |= GPIO_OTYPER_OT7;
    GPIOB->AFR[0] = (GPIOB->AFR[0] & ~GPIO_AFRL_AFSEL7) | (4U << GPIO_AFRL_AFSEL7_Pos);

    /* USART2: 921600 baud 8N1 from PCLK1 = 170 MHz (written while UE = 0) */
    USART2->BRR = 184;
    USART2->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;

    /* I2C1: 100 kHz standard mode, fI2CCLK = PCLK1 = 170 MHz, TIMINGR written while PE = 0 */
    I2C1->TIMINGR = (15U << I2C_TIMINGR_PRESC_Pos) | (13U << I2C_TIMINGR_SCLDEL_Pos) | (3U << I2C_TIMINGR_SDADEL_Pos) | (45U << I2C_TIMINGR_SCLH_Pos) | (59U << I2C_TIMINGR_SCLL_Pos);
    I2C1->CR1 |= I2C_CR1_PE;

    while (1) { }
}
""" + FENCE)

T002_STEP6 = """6. **3.3 V current budget.** Worst-case peak on the 3.3 V rail = 240 mA (ESP32 802.11b transmit, ESP32 datasheet Table 5-4) + 29.5 mA (STM32G474 Run at 170 MHz, DS12288 Table 21) + 1 mA (sensor) = 270.5 mA, above the 250 mA rating of the LDO. The ESP32 datasheet (Table 5-2) also asks for an external supply that can deliver at least 0.5 A. The 250 mA LDO is therefore not adequate: use a 3.3 V regulator rated at least 500 mA (for example a 600 mA LDO or a small buck converter) with bulk capacitance close to the ESP32."""

T002_REF = """Thanks: the HSE crystal is 12 MHz and the ESP32 bridge firmware runs at 921600 baud 8N1, so the design is:

1. **Clock tree (12 MHz HSE -> 170 MHz).** PLL input 2.66-16 MHz and VCO 96-344 MHz (DS12288 Table 46): PLLM = 3 gives 12 MHz / 3 = 4 MHz, PLLN = 85 gives a 340 MHz VCO and PLLR = 2 gives SYSCLK = 170 MHz with PLLSRC = HSE. 170 MHz needs Range 1 boost mode (clear PWR_CR5.R1MODE), LATENCY = 4 wait states (RM0440 Table 9) and the AHB /2 step during the switch; PCLK1 = PCLK2 = 170 MHz.
2. **Pin allocation.** USART2: PA2 = USART2_TX (AF7) to the ESP32 RX, PA3 = USART2_RX (AF7) from the ESP32 TX. I2C1: PA15 = I2C1_SCL (AF4) and PB7 = I2C1_SDA (AF4), both open-drain (PB8/PB9 also carry I2C1, but PB8 is BOOT0). PF0/PF1 = OSC_IN/OSC_OUT for the crystal; PA13/PA14 stay free for SWD.
3. **USART2 at 921600 baud.** USART2 is clocked by PCLK1 = 170 MHz with OVER8 = 0: BRR = 170000000 / 921600 = 184.46, rounded to 184, giving 923913 baud (+0.25 %, inside ±2 %).
4. **I2C1 at 100 kHz.** With fI2CCLK = PCLK1 = 170 MHz: PRESC = 15 (tPRESC = 94.1 ns), SCLL = 59 (tLOW about 5.6 µs >= 4.7 µs), SCLH = 45 (tHIGH about 4.3 µs >= 4.0 µs), SCLDEL = 13, SDADEL = 3; TIMINGR is written while PE = 0. The module's 4.7 kΩ pull-ups to 3.3 V are enough for 100 kHz.
5. **Logic levels.** Every device here has 3.3 V I/O. For the ESP32 link: STM32 VOH >= VDD - 0.4 = 2.9 V > ESP32 VIH = 0.75 x 3.3 = 2.48 V and ESP32 VOH >= 0.8 x 3.3 = 2.64 V > STM32 VIH = 0.7 x 3.3 = 2.31 V; the VOL limits (0.4 V and 0.33 V) are below the VIL limits (0.83 V and 0.99 V). The levels are compatible, so both links are wired directly, without any level shifter.
""" + T002_STEP6 + """
7. **Firmware.** The code below configures the clock tree, USART2 and I2C1 from reset:

""" + T002_CODE + "\n"

T002 = {
    "id": "C5-002", "split": "dev", "difficulty": "hard", "chips": ["stm32g474", "esp32"],
    "tags": ["system_goal", "missing_info", "code", "pll", "hse", "uart", "i2c", "current_budget", "logic_level"],
    "user": ("Help me design a data-acquisition node end to end. An STM32G474 on our own PCB (VDD = 3.3 V) reads a digital pressure-sensor module "
             "(3.3 V I/O, 4.7 kΩ pull-ups on the module) over I2C1 in standard mode (100 kHz, controller, open-drain pins) and forwards every sample to an "
             "ESP32-WROOM module (3.3 V I/O) over USART2 (8 data bits, no parity, 1 stop bit, oversampling by 16, transmitter and receiver enabled). The ESP32 "
             "runs a fixed UART-to-Wi-Fi bridge firmware written by a colleague, so the STM32 side has to match its UART settings; the baud rate must be within "
             "±2 %. Choose the I2C1 and USART2 pins yourself. The STM32 has a crystal on its HSE pins and must run SYSCLK = HCLK = PCLK1 = PCLK2 = 170 MHz "
             "from the main PLL fed by HSE (within 0.1 %). The node is powered from a USB port through a 3.3 V LDO rated 250 mA that supplies the STM32, the "
             "sensor module (1 mA) and the ESP32: check whether that regulator is adequate. The plan must cover the clock tree with the PLL M/N/R values, the "
             "pin allocation, the logic-level compatibility of both links, the UART baud-rate register value and the 3.3 V current budget. " + CONV + " "
             + fmt_code("the clock tree, USART2 and I2C1")),
    "human_policy": {"approval": "approve", "choice": {"prefer": "500 mA"},
                     "clarify": {"hse_hz": "The crystal on the STM32's HSE pins is 12 MHz.",
                                 "esp_baud": "The ESP32 bridge firmware uses 921600 baud, 8 data bits, no parity, 1 stop bit."},
                     "max_answers": 3},
    "hidden_info": [hse_hidden(12),
                    {"id": "esp_baud", "required": True,
                     "keywords": ["baud", "bit rate", "bitrate", "bps", "UART speed", "serial speed", "UART settings", "UART configuration", "serial link",
                                  "data rate", "UART run", "link speed", "how fast is the serial", "how fast is the UART", "how fast is the link"],
                     "value_patterns": [r"\b921\s*600\b", r"\b921\.6\s*k"]}],
    "expected": {
        "initial": "reset", "hse_hz": 12000000,
        "spec": [{"type": "clock", "hse_hz": 12000000, "sysclk_hz": 170000000, "hclk_hz": 170000000, "pclk1_hz": 170000000, "pclk2_hz": 170000000, "tol_pct": 0.1},
                 {"type": "uart", "instance": "USART2", "baud": 921600, "tol_pct": 2, "frame": "8N1", "te": True, "re": True, "over8": 0, "require_pins": True},
                 {"type": "i2c", "instance": "I2C1", "scl_hz": 100000, "tol_pct": 5, "mode": "Sm", "open_drain": True, "require_pins": True}],
        "checklist": [steps(), pll(12e6, 170e6), BOOST, FLASH_WS,
                      {"id": "baud", "type": "mentions",
                       "any_of": [r"(?<![\d.,])921[,\u202f ]?600\b", r"(?<![\d.,])921\.6\s*k(?:baud|bps|bit/s|Bd)\b"],
                       "desc": "the UART is set to the 921600 baud of the ESP32 bridge firmware"},
                      compat("esp_link_compat", "STM32-ESP32 UART link", extra=ESP_COMPAT_EXTRA),
                      {"id": "supply_rating", "type": "mentions",
                       "any_of": [r"(?:≥|>=|at least|minimum(?:\s+of)?|min\.?)\s*(?:0\.5\s*A|500\s*mA)\b", r"(?:0\.5\s*A|500\s*mA)\s+(?:or more|or higher|minimum)",
                                  r"(?<![\d.,])(?:[5-9]\d\d\s*mA|[1-3](?:\.\d+)?\s*A)\s+(?:\w+\s+)?(?:LDO|regulator|buck|converter|DC-?DC)",
                                  r"(?:LDO|regulator|buck|converter)\s+(?:rated\s+)?(?:for\s+)?(?:at least\s+)?(?<![\d.,])(?:[5-9]\d\d\s*mA|[1-3](?:\.\d+)?\s*A)\b"],
                       "desc": "the 3.3 V supply must deliver at least 0.5 A (ESP32 datasheet Table 5-2), so the 250 mA LDO is inadequate"},
                      {"id": "peak_current", "type": "quantity", "match": "any", "unit_out": "mA", "min": 251, "max": 700,
                       "patterns": [r"\b(?:peaks?|peaking|worst[- ]case|totals?|sum|maximum|max\.)\b[^\n]{0,200}?" + _NUM + r"\s*(?P<u>mA|A)\b" + _SKIP,
                                    _NUM + r"\s*(?P<u>mA|A)[ \t]+(?:in[ \t]+|at[ \t]+)?(?:total|peak|worst[- ]case|maximum)\b",
                                    # post-run (dev_baseline_v2): kết quả của một tổng dòng "a mA + b mA = X mA" (không cần từ khoá)
                                    r"(?<![\d.,])\d+(?:\.\d+)?\s*m?A\b[^\n=≈]{0,80}?\+[^\n=≈]{0,200}?(?:=|≈)\s*(?:about\s+|roughly\s+|~\s*)?" + _NUM
                                    + r"\s*(?P<u>mA|A)\b" + _SKIP,
                                    # post-run: giá trị sau = / ≈ / ~ / → trên dòng có từ khoá đỉnh/tổng (dải "A to B ≈ X to Y" lấy X)
                                    r"\b(?:peaks?|peaking|worst[- ]case|totals?|sum|maximum)\b[^\n]{0,200}?(?:≈|=|~|→)\s*(?:about\s+|roughly\s+)?" + _NUM + r"\s*(?P<u>mA|A)\b"],
                       "desc": "worst-case 3.3 V current above the 250 mA LDO rating (ESP32 TX 240 mA + STM32 29.5 mA + sensor 1 mA = 270.5 mA; module figures up to ~0.5 A also valid)"},
                      {"id": "no_ldo_ok_claim", "type": "forbids",
                       "patterns": [r"(?<!not )(?<!n't )(?:250\s*mA\s+)?(?:LDO|regulator)\s+(?:is|will\s+be|should\s+be|remains|stays)\s+(?:still\s+)?(?:adequate|sufficient|enough|fine|ok(?:ay)?)\b",
                                    r"\bfits\s+(?:within\s+)?the\s+250\s*mA\b",
                                    r"(?<!not )\b250\s*mA\s+(?:is|will\s+be|should\s+be)\s+(?:still\s+)?(?:enough|sufficient|adequate|fine|ok(?:ay)?)\b",
                                    r"(?:\bthe\s+|\b250\s*mA\s+|\bexisting\s+|\bcurrent\s+)(?:LDO|regulator)\s+(?:can|will|should)\s+(?:easily\s+)?(?:handle|cope|cover|manage)\b",
                                    r"\bno\s+need\s+to\s+(?:change|replace|upgrade)\s+the\s+(?:250\s*mA\s+)?(?:LDO|regulator)",
                                    r"\bkeep\w*\s+the\s+(?:existing\s+)?(?:250\s*mA\s+)?(?:LDO|regulator)\s+(?:is\s+)?(?:acceptable|fine|ok(?:ay)?)"],
                       "desc": "must not conclude that the 250 mA LDO is adequate (G11)"}],
    },
    "graders": ["checklist", "clarify", "functional_sim", "compile"],
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("ahb_div2"), ev("brr"), ev("i2c_tscl"),
                 ev("stm_vih"), ev("stm_voh"), ev("esp_dc"), ev("esp_tx"), ev("esp_supply"), ev("run_170"), ev("osc_pins"),
                 ev("pins_pa", "PA2 - TIM2_CH3 TIM5_CH3 - - - - USART2_TX", "PA3 - TIM2_CH4 TIM5_CH4 SAI1_CK1 - - - USART2_RX",
                    "PA15 JTDI TIM2_CH1 TIM8_CH1 - I2C1_SCL"),
                 ev("pins_pb", "PB7 - TIM17_CH1N TIM4_CH2 I2C4_SDA I2C1_SDA")],
    "reference_calc": (
        "Thông tin ẩn: HSE = 12 MHz, baud của firmware ESP32 = 921600 (không tra được: thuộc bo và firmware của đồng nghiệp người dùng). "
        "PLL (RM0440 p.291-293; DS12288 Table 46 p.123): 12 MHz → 170 MHz chỉ có M = 3 (4 MHz), N = 85 (VCO 340 MHz), R = 2. Đoán 8 MHz (M = 2) → 255 MHz; "
        "đoán 16 MHz (M = 4) → 127,5 MHz; đoán 24 MHz (M = 6) → PLL in 2 MHz < 2,66 MHz ⇒ mục pll/spec clock trượt. Boost + 4 WS + AHB/2 như C5-001. "
        "USART2 (APB1, PCLK1 = 170 MHz, OVER8 = 0, RM p.1708): BRR = 170e6/921600 = 184,46 → 184 ⇒ 923913 baud (+0,25 %); đoán 115200 ⇒ BRR 1476 ⇒ trượt "
        "mục baud và spec uart. I2C1 100 kHz @170 MHz: PRESC 15, SCLL 59, SCLH 45, SCLDEL 13, SDADEL 3 (cùng phép tính C4-001/C3-016, RM p.1645). "
        "Chân (DS Table 13 p.73-74): PA2/PA3 AF7 USART2, PA15 AF4 I2C1_SCL, PB7 AF4 I2C1_SDA. Mức logic như C5-001 (3,3 V cả hai phía ⇒ nối thẳng). "
        "Dòng đỉnh 3,3 V: ESP32 TX 802.11b 240 mA (ESP32 DS Table 5-4 p.52) + STM32 Run 170 MHz 29,5 mA typ (DS Table 21 p.89) + cảm biến 1 mA = 270,5 mA > 250 mA; "
        "ESP32 DS Table 5-2 p.51: nguồn ngoài phải cấp ≥ 0,5 A ⇒ LDO 250 mA không đủ, cần ≥ 500 mA."),
    "variants": [
        {"name": "guessed_hse_8mhz", "must_fail": ["pll"],
         "edits": [("the HSE crystal is 12 MHz and", "assuming an 8 MHz HSE crystal, and since"),
                   ("(12 MHz HSE -> 170 MHz)", "(8 MHz HSE -> 170 MHz)"),
                   ("PLLM = 3 gives 12 MHz / 3 = 4 MHz", "PLLM = 2 gives 8 MHz / 2 = 4 MHz"),
                   ("/* 12 MHz / 3 = 4 MHz", "/* 8 MHz / 2 = 4 MHz"),
                   ("(2U << RCC_PLLCFGR_PLLM_Pos)", "(1U << RCC_PLLCFGR_PLLM_Pos)")]},
        {"name": "guessed_115200_baud", "must_fail": ["baud"],
         "edits": [("runs at 921600 baud 8N1", "probably uses the common 115200 baud 8N1"),
                   ("**USART2 at 921600 baud.**", "**USART2 at 115200 baud.**"),
                   ("BRR = 170000000 / 921600 = 184.46, rounded to 184, giving 923913 baud (+0.25 %, inside ±2 %)",
                    "BRR = 170000000 / 115200 = 1475.7, rounded to 1476, giving 115176 baud (-0.02 %)"),
                   ("USART2->BRR = 184;", "USART2->BRR = 1476;"),
                   ("/* USART2: 921600 baud", "/* USART2: 115200 baud")]},
        {"name": "ldo_judged_adequate", "must_fail": ["supply_rating", "peak_current", "no_ldo_ok_claim"],
         "edits": [(T002_STEP6, "6. **3.3 V current budget.** The STM32 draws 29.5 mA at 170 MHz (DS12288 Table 21), the sensor 1 mA and the ESP32 about 100 mA on average while receiving, so the total of about 130.5 mA fits the 250 mA LDO.")]},
    ],
    "ref": T002_REF,
}

# =====================================================================================================================  C5-003
T003_STEP7 = """7. **Options to reach 3 years** (one of them is enough, or combine them):
   - a larger battery: at least 521 mAh, about 650 mAh with a 20 % margin;
   - a longer wake-up interval: at least 1215 s (about 21 minutes) instead of 15 minutes, with the same 2 s / 8 mA active phase;
   - a shorter active phase: at most about 1.48 s at 8 mA per 15-minute cycle (e.g. lower BLE TX power, shorter advertising, a faster probe read).

   My recommendation is the larger cell if the enclosure allows it, otherwise the 21-minute interval."""

T003_STEP6 = """6. **Battery life.** 400 mAh / 0.0198 mA = 20170 h, i.e. about 2.3 years (27.6 months). The 3-year target is not met: 3 years need about 19.8 µA x 26280 h = 521 mAh, or an average current of at most 400 mAh / 26280 h = 15.2 µA."""

T003_REF = """Thanks: with a 400 mAh cell (fully usable) the numbers are as follows.

1. **Pin allocation.** STM32 USART1: PA9 = TX and PA10 = RX (AF7) to the nRF52840 UARTE (its pins are freely assignable); PB0 (push-pull output) drives an nRF52840 GPIO configured as the wake-up (DETECT) source for leaving System OFF; PB1 (push-pull output) drives the enable input of the probe's load switch; PC14/PC15 = OSC32_IN/OSC32_OUT for the LSE crystal.
2. **Logic levels.** Both chips share the 3.0 V rail. STM32 VOH >= VDD - 0.4 = 2.6 V is above the nRF52840 VIH of 0.7 x 3.0 = 2.1 V, and the nRF52840 VOH >= VDD - 0.4 = 2.6 V is above the STM32 VIH of 0.7 x 3.0 = 2.1 V; both VOL limits (0.4 V) are below the VIL limits (0.3 x 3.0 = 0.9 V). The levels are compatible, so the UART and wake-up lines are wired directly.
3. **STM32 low-power mode.** Standby with the RTC on the LSE crystal draws 0.655 µA typical at 3 V (DS12288 Table 32) and keeps the brown-out reset active, which matters on a battery (the BOR is not available in Shutdown). Stop 1 (80.5 µA typical, Table 30) would dominate the whole budget.
4. **Sleep-current table (3.0 V, 25 °C, typical).**
   - STM32G474, Standby + RTC (LSE): 0.655 µA
   - nRF52840, System OFF without RAM retention: 0.40 µA (nRF52840 PS, IOFF_RAMOFF_RESET)
   - LDO quiescent current: 1 µA
   - Probe behind its load switch: 0 µA

   Total sleep current = 0.655 + 0.40 + 1 = 2.06 µA.
5. **Average current over one 15-minute cycle.** Active charge per cycle = 8 mA x 2 s = 16 mC; sleep charge = 2.06 µA x 898 s = 1.85 mC. Average current = (16 mC + 1.85 mC) / 900 s = 19.8 µA.
""" + T003_STEP6 + "\n" + T003_STEP7 + "\n"

T003 = {
    "id": "C5-003", "split": "test", "difficulty": "medium", "chips": ["stm32g474", "nrf52840"],
    "tags": ["system_goal", "missing_info", "plan", "current_budget", "battery_life", "logic_level", "trade_off"],
    "user": ("Help me plan a battery-powered soil-moisture logger. An STM32G474 (VDD = 3.0 V from a low-dropout regulator whose quiescent current is 1 µA) "
             "wakes up every 15 minutes, switches on the moisture probe through a GPIO-controlled load switch, takes a reading and sends it over Bluetooth LE "
             "through an nRF52840 that shares the same 3.0 V rail (Normal Voltage mode) and talks to the STM32 over a UART at 115200 baud. One wake-up cycle lasts 2 s and the "
             "whole node then draws 8 mA on average (measured on our prototype). Between cycles the probe is switched off (0 µA), the nRF52840 sits in System OFF "
             "without RAM retention and is woken by a GPIO from the STM32, and the STM32 waits in its lowest-power mode that still keeps the RTC running from a "
             "32.768 kHz LSE crystal and a brown-out reset active. The node runs from the battery that fits our enclosure and must last at least 3 years without "
             "a battery change. The plan must cover the pin allocation (UART, wake-up and load-switch control lines), the logic-level compatibility between the "
             "two chips, the STM32 low-power mode, a sleep-current table with the total, the average current over one cycle, the expected battery life, and what "
             "to change if the 3-year target is not met. " + FMT_PLAN),
    "human_policy": {"approval": "approve", "choice": {"prefer": "larger battery"},
                     "clarify": {"battery_mah": "The battery is a 400 mAh primary lithium cell; treat the full 400 mAh as usable (no derating needed)."},
                     "max_answers": 3},
    "hidden_info": [{"id": "battery_mah", "required": True,
                     "keywords": ["battery", "battery capacity", "capacity", "mAh", "battery size", "which battery", "what battery", "battery type", "battery is",
                                  "battery do you", "battery fits", "cell capacity", "which cell", "what cell", "coin cell", "AA", "cell size",
                                  "energy storage", "CR2032", "CR2450", "CR2477"],
                     "exclude": ["LDO", "regulator", "charger"],
                     "value_patterns": [r"\b400\s*mAh\b"]}],
    "expected": {
        "checklist": [steps(), compat("nrf_link_compat", "STM32-nRF52840 link"), STANDBY_ONLY, NOT_SHUTDOWN, sleep_total(1.8, 3.2),
                      {"id": "avg_current", "type": "quantity", "match": "any", "unit_out": "uA", "min": 18.5, "max": 21.5,
                       "patterns": [r"\b(?:average|mean)\b[^\n]{0,200}?" + _NUM + r"\s*" + CUR_U + _SKIP, r"\bI_?avg\b[^\n]{0,80}?" + _NUM + r"\s*" + CUR_U + _SKIP,
                                    _NUM + r"\s*" + CUR_U + r"[ \t]+(?:on[ \t]+)?average\b"],
                       "desc": "average current over a 15-minute cycle = 8 mA x 2 s / 900 s + sleep, about 19.8 uA"},
                      {"id": "lifetime", "type": "quantity", "match": "any", "unit_out": "year", "min": 2.0, "max": 2.6,
                       "patterns": [r"(?:\b(?:life(?:time)?|lasts?|lasting|runtime|run[- ]time)\b|\bi\.e\.)[^\n]{0,200}?" + _NUM
                                    + r"\s*(?P<u>years?|yrs?|months?|days?|hours?|h)\b" + _SKIP,
                                    _NUM + r"\s*(?P<u>years?|yrs?|months?)[ \t]+(?:of[ \t]+)?(?:battery[ \t]+)?(?:life|lifetime|operation|runtime)\b"],
                       "desc": "battery life with the real 400 mAh cell is about 2.3 years (20170 h)"},
                      trade_offs("3"), no_false_claim(r"(?:3|three)", "3")],
    },
    "graders": ["checklist", "clarify"],
    "evidence": [ev("standby_rtc"), ev("stop1"), ev("bor"), ev("stm_vih"), ev("stm_voh"), ev("nrf_gpio"), ev("nrf_sleep"), ev("osc_pins"),
                 ev("pins_pa", "PA9 - - I2C3_SMBA - I2C2_SCL I2S3_MCK TIM1_CH2 USART1_TX", "PA10 - TIM17_BKIN - USB_CRS_SYNC I2C2_SMBA SPI2_MISO TIM1_CH3 USART1_RX")],
    "reference_calc": (
        "Thông tin ẩn: dung lượng pin = 400 mAh (pin 'vừa vỏ hộp' của người dùng, không tra được; đề không nêu loại pin). Ngủ (3 V, 25 °C, typ): STM32 "
        "Standby + RTC LSE low drive 0,655 µA (DS12288 Table 32 p.104; Standby giữ BOR, Shutdown không có BOR — DS p.25), nRF52840 System OFF không giữ RAM "
        "0,40 µA (PS p.76), LDO 1 µA ⇒ 2,055 µA. Trung bình: 8 mA × 2 s / 900 s = 17,78 µA + 2,055 × 898/900 = 2,05 µA ⇒ 19,83 µA. Tuổi thọ: 400 mAh / 0,01983 mA "
        "= 20173 h = 2,30 năm < 3 năm; cần 521 mAh, hoặc I_avg ≤ 400/26280 h = 15,22 µA ⇒ chu kỳ ≥ 16 mC/13,16 µA = 1215 s, hoặc pha hoạt động ≤ 1,48 s ở 8 mA. "
        "Đoán 2000 mAh ⇒ 11,5 năm, 1000 mAh ⇒ 5,8 năm (đều 'đạt' sai và nằm ngoài [2,0; 2,6] năm); đoán 225 mAh ⇒ 1,3 năm (ngoài khoảng). Mức logic 3,0 V hai "
        "phía: STM32 VOH ≥ VDD−0,4 = 2,6 V (DS Table 55 p.130, VDD ≥ 2,7 V) > nRF VIH 0,7×3,0 = 2,1 V (PS p.370); nRF VOH ≥ 2,6 V > STM32 VIH 2,1 V (DS p.128) ⇒ nối thẳng."),
    "variants": [
        {"name": "guessed_2000mah", "must_fail": ["lifetime", "trade_offs", "no_false_claim"],
         "edits": [("with a 400 mAh cell (fully usable)", "assuming a typical 2000 mAh cell"),
                   (T003_STEP6, "6. **Battery life.** 2000 mAh / 0.0198 mA = 100860 h, i.e. about 11.5 years (138 months). This meets the 3-year target with a large margin."),
                   (T003_STEP7, "7. **Margin.** No change is needed; the 15-minute interval can stay as it is.")]},
        {"name": "no_remedies_offered", "must_fail": ["trade_offs"],
         "edits": [(T003_STEP7, "7. **Next step.** Please confirm the enclosure and I will prepare the firmware plan.")]},
    ],
    "ref": T003_REF,
}

# =====================================================================================================================  C5-004
T004_CODE = (FENCE + "c\n#include \"stm32g4xx.h\"\n\nint main(void)\n{\n" + clock_code_boost("HSE", 12, 3, 85) + """
    /* peripheral clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOBEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_USART3EN;

    /* PB10 = USART3_TX, PB11 = USART3_RX (AF7) */
    GPIOB->MODER = (GPIOB->MODER & ~(GPIO_MODER_MODE10 | GPIO_MODER_MODE11)) | GPIO_MODER_MODE10_1 | GPIO_MODER_MODE11_1;
    GPIOB->AFR[1] = (GPIOB->AFR[1] & ~(GPIO_AFRH_AFSEL10 | GPIO_AFRH_AFSEL11)) | (7U << GPIO_AFRH_AFSEL10_Pos) | (7U << GPIO_AFRH_AFSEL11_Pos);

    /* USART3: 1 Mbaud 8N1 from PCLK1 = 170 MHz (written while UE = 0) */
    USART3->BRR = 170;
    USART3->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;

    while (1) { }
}
""" + FENCE)

T004_INTRO = "Thanks: the nRF52840 runs from the Li-ion cell on VDDH with REGOUT0 unprogrammed, which changes the interface design."
T004_STEP4 = "4. **I/O voltage of the nRF52840.** In High Voltage mode (supply on VDDH) the nRF52840 GPIO high level equals the REG0 output set by UICR.REGOUT0 (nRF52840 PS, GPIO levels), and an erased REGOUT0 (0xFFFFFFFF, VOUT = 7) selects the default 1.8 V. So the nRF52840 I/O runs at 1.8 V while the STM32 I/O runs at 3.3 V."
T004_STEP5_A = "5. **Logic-level check.** STM32 -> nRF52840: the STM32 drives up to 3.3 V, above the nRF52840 absolute maximum of VDD + 0.3 = 2.1 V on an I/O pin, which would damage it. nRF52840 -> STM32: the nRF52840 output high is at most 1.8 V, below the STM32 VIH of 0.7 x 3.3 = 2.31 V, so the STM32 would not read a reliable high."
T004_STEP5_B = " The link therefore needs a level shifter: a dual-supply translator (VCCA = 1.8 V from the nRF52840 VDD pin, VCCB = 3.3 V) rated for at least 1 Mbit/s on TX and RX."
T004_STEP6 = "6. **Why not reprogram REGOUT0?** Setting REGOUT0 to 3.3 V (VOUT = 5) requires VDDH at least 0.3 V above VDD, i.e. VDDH >= 3.6 V (PS, REG0 stage), but the Li-ion cell falls to 3.0 V, so the nRF52840 rail would sag below 3.3 V late in the discharge while the STM32 still drives 3.3 V. Lower settings (e.g. 2.7 V) keep the headroom but still leave the 3.3 V STM32 output above VDD + 0.3 V."
T004_STEP6_END = " The translator is the robust choice."
T004_STEP7 = "7. **Firmware.** The STM32 code below sets up the clock tree and USART3; the translator needs no firmware:"

T004_REF = (T004_INTRO + "\n\n"
            "1. **Clock tree (12 MHz HSE -> 170 MHz).** PLLSRC = HSE; PLLM = 3 gives 12 MHz / 3 = 4 MHz (PLL input 2.66-16 MHz), PLLN = 85 gives a 340 MHz VCO "
            "(96-344 MHz) and PLLR = 2 gives SYSCLK = 170 MHz (DS12288 Table 46, RM0440 7.4.4). Range 1 boost mode (clear PWR_CR5.R1MODE), LATENCY = 4 wait states "
            "(RM0440 Table 9) and the AHB /2 step during the switch; PCLK1 = PCLK2 = 170 MHz.\n"
            "2. **Pin allocation.** PB10 = USART3_TX (AF7) and PB11 = USART3_RX (AF7) (DS12288 Table 13); on the nRF52840 side the UARTE pins are freely assignable GPIOs; PF0/PF1 = OSC_IN/OSC_OUT for the 12 MHz crystal.\n"
            "3. **USART3 at 1 Mbaud.** The USART3 kernel clock is PCLK1 = 170 MHz with OVER8 = 0: BRR = 170000000 / 1000000 = 170 (exact, 0 % error).\n"
            + T004_STEP4 + "\n" + T004_STEP5_A + T004_STEP5_B + "\n" + T004_STEP6 + T004_STEP6_END + "\n" + T004_STEP7 + "\n\n" + T004_CODE + "\n")

T004 = {
    "id": "C5-004", "split": "test", "difficulty": "hard", "chips": ["stm32g474", "nrf52840"],
    "tags": ["system_goal", "missing_info", "code", "pll", "hse", "uart", "logic_level", "level_shift", "nrf_vddh", "safe_default"],
    "user": ("Help me design the radio side of a data logger. An STM32G474 on our own PCB (VDD = 3.3 V) with a 12 MHz crystal on its HSE pins must run SYSCLK = "
             "HCLK = PCLK1 = PCLK2 = 170 MHz from the main PLL fed by HSE (within 0.1 %) and exchanges packets with an nRF52840 (aQFN73 package, soldered on the same PCB, "
             "running our own BLE firmware) over USART3 with TX on PB10 and RX on PB11 at 1 Mbaud (within ±2 %), 8 data bits, no parity, 1 stop bit, "
             "oversampling by 16, transmitter and receiver enabled. The plan must cover the clock tree with the PLL M/N/R values, the pin allocation, the "
             "logic-level compatibility of the UART link between the two chips (with the datasheet thresholds you rely on) and whether anything has to be fitted or "
             "configured on the board for the link to be safe and reliable. " + CONV + " " + fmt_code("the clock tree and USART3")),
    "human_policy": {"approval": "approve", "choice": {"prefer": "level shifter"},
                     "clarify": {"nrf_supply": "The nRF52840 is powered directly from the single Li-ion cell (3.0 V to 4.2 V) on its VDDH pin, and its UICR.REGOUT0 register has never been programmed."},
                     "max_answers": 3},
    "hidden_info": [{"id": "nrf_supply", "required": True,
                     "keywords": ["VDDH", "REGOUT0", "REG0", "nRF52840 supply", "nRF supply", "supply of the nRF", "supply voltage of the nRF", "nRF52840 powered",
                                  "nRF powered", "powers the nRF", "power the nRF", "same rail", "rail as the STM32", "nRF rail", "nRF VDD", "high voltage mode", "normal voltage mode",
                                  "I/O voltage", "IO voltage", "GPIO voltage", "logic level", "logic-level", "voltage level", "VDD of the nRF", "nRF52840 VDD",
                                  "nRF52840 run", "nRF run"],
                     "value_patterns": [r"VDDH[^\n]{0,80}(?:Li-ion|battery|cell)", r"(?:Li-ion|battery|cell)[^\n]{0,80}VDDH",
                                        r"REGOUT0[^\n]{0,80}(?:default|1\.8\s*V)", r"(?:nRF52840|nRF)[^\n]{0,60}\b1\.8\s*V\b"]}],
    "expected": {
        "initial": "reset", "hse_hz": 12000000,
        "spec": [{"type": "clock", "hse_hz": 12000000, "sysclk_hz": 170000000, "hclk_hz": 170000000, "pclk1_hz": 170000000, "pclk2_hz": 170000000, "tol_pct": 0.1},
                 {"type": "uart", "instance": "USART3", "baud": 1000000, "tol_pct": 2, "tx_pin": "PB10", "rx_pin": "PB11", "frame": "8N1", "te": True, "re": True, "over8": 0}],
        "checklist": [steps(), pll(12e6, 170e6), BOOST, FLASH_WS,
                      {"id": "regout0", "type": "mentions", "any_of": [r"REGOUT0", r"\bREG0\b"],
                       "desc": "the nRF52840 I/O level in High Voltage mode is set by REG0/UICR.REGOUT0 (default 1.8 V)"},
                      {"id": "nrf_io_1v8", "type": "mentions", "any_of": [r"\b1\.8\s*V\b"],
                       "desc": "the nRF52840 I/O level that follows from the board's supply arrangement (1.8 V REGOUT0 default) is stated"},
                      level_shifter("level_shifter", "STM32 (3.3 V) - nRF52840 (1.8 V) UART link"),
                      no_direct_generic("no_direct", "STM32 - nRF52840 UART link")],
    },
    "graders": ["checklist", "clarify", "functional_sim", "compile"],
    "limitations": "G13 (review): TSR không tách được 'hỏi' với 'thiết kế bảo thủ': một câu trả lời không hỏi mà luôn lắp translator vẫn có thể đạt checklist (và functional_sim). Giảm nhẹ: mục nrf_io_1v8 đòi nêu mức I/O 1,8 V của nRF; năng lực hỏi đo bằng recall của `clarify` (không gate).",
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("ahb_div2"), ev("brr"), ev("stm_vih"), ev("stm_voh"),
                 ev("osc_pins"), ev("nrf_regout0"), ev("nrf_gpio_hv"), ev("nrf_reg0_drop"), ev("nrf_gpio"), ev("nrf_absmax"),
                 ev("pins_pb", "PB10 - TIM2_CH3 - - - - - USART3_TX", "PB11 - TIM2_CH4 - - - - - USART3_RX")],
    "reference_calc": (
        "Thông tin ẩn: nRF52840 cấp nguồn từ pin Li-ion vào VDDH (High Voltage mode), UICR.REGOUT0 chưa ghi (cách cấp nguồn trên bo của người dùng — không tra "
        "được; đề chỉ nói aQFN73 để HV mode khả dĩ, QFN48 nối tắt VDD/VDDH — PS p.970). PS p.82: ở HV mode mức cao GPIO = mức REGOUT0; PS p.63: REGOUT0 reset "
        "0xFFFFFFFF, DEFAULT = 7 ⇒ 1,8 V. STM32 → nRF: VOH tới 3,3 V > VI/O max = VDD + 0,3 = 2,1 V (PS p.972) ⇒ hỏng chân; nRF → STM32: VOH ≤ 1,8 V < VIH = 0,7×3,3 "
        "= 2,31 V (DS Table 54 p.128; cả giá trị thiết kế 0,49×3,3+0,26 = 1,88 V > 1,8 V) ⇒ cần level shifter. REGOUT0 = 3,3 V cần VDDH ≥ 3,3 + 0,3 = 3,6 V "
        "(PS p.155) nhưng Li-ion xuống 3,0 V ⇒ không bảo đảm; REGOUT0 = 2,7 V ⇒ VI/O max 3,0 V < 3,3 V vẫn vượt. Đoán 'nRF chạy 3,3 V' ⇒ kết luận nối thẳng ⇒ "
        "trượt regout0/level_shifter/no_direct. Clock (cho sẵn): HSE 12 MHz /3 = 4 MHz ×85 = 340 MHz /2 = 170 MHz (duy nhất; RM p.293 PLLSRC 11 = HSE; HSE 4-48 MHz DS p.117), boost + 4 WS + AHB/2. "
        "USART3 (APB1): BRR = 170e6/1e6 = 170 (0 %). PB10/PB11 AF7 = USART3_TX/RX (DS p.74)."),
    "variants": [
        {"name": "assumed_nrf_at_3v3", "must_fail": ["regout0", "nrf_io_1v8", "level_shifter", "no_direct"],
         "edits": [(T004_INTRO, "I assume the nRF52840 also runs its I/O at 3.3 V, like most designs."),
                   (T004_STEP4, "4. **I/O voltage of the nRF52840.** The nRF52840 shares the 3.3 V level of the STM32 (its VDD range is 1.7-3.6 V)."),
                   (T004_STEP5_A + T004_STEP5_B, "5. **Logic-level check.** The nRF52840 VIH of 0.7 x 3.3 = 2.31 V is below the STM32 VOH of 2.9 V, and the STM32 VIH of 2.31 V is below the nRF52840 VOH of VDD - 0.4 = 2.9 V, so the two chips are directly compatible and no level shifter is needed."),
                   (T004_STEP6 + T004_STEP6_END, "6. **Board.** Route TX/RX with a common ground; no extra parts are required."),
                   ("; the translator needs no firmware:", ":")]},
        {"name": "series_resistor_instead_of_shifter", "must_fail": ["level_shifter"],
         "edits": [(T004_STEP5_B, " A 1 kΩ series resistor on the STM32 TX line limits the current into the nRF52840 pin, which is enough at 1 Mbaud."),
                   (T004_STEP6_END, " The series resistor is the cheapest choice."),
                   ("; the translator needs no firmware:", "; the resistor needs no firmware:")]},
    ],
    "ref": T004_REF,
}

# =====================================================================================================================  C5-005
T005_INTRO = "Thanks: the breakout runs the sensor I/O at 1.8 V with no translator on board, so the interface needs care."
T005_STEP3 = "3. **Logic-level check.** The sensor's high level is at most 1.8 V, below the STM32 VIH minimum of 0.7 x VDD = 2.31 V at VDD = 3.3 V (DS12288 Table 54; even the design value 0.49 x VDD + 0.26 = 1.88 V is above 1.8 V), so the STM32 cannot read a guaranteed high. In the other direction a 3.3 V level on SCL/SDA/INT would exceed the sensor's 1.8 V I/O rating. The breakout therefore cannot be wired to the STM32 pins as it is."
T005_STEP4 = "4. **Interface fix.** Put a level shifter between the two domains: a bidirectional I2C translator for SCL/SDA (e.g. PCA9306 or LSF0102, with pull-ups to 1.8 V on the sensor side and to 3.3 V on the MCU side, about 2.2 kΩ for 400 kHz) and a unidirectional channel for the interrupt line. Alternatives: power the whole STM32 from 1.8 V (its VDD range starts at 1.71 V) if nothing else on the board needs 3.3 V, or buy a 3.3 V version of the breakout."
T005_STEP5 = "5. **I2C bus wiring.** Fast mode at 400 kHz: keep the bus short, use one pull-up pair per voltage side and configure PA15/PB7 as open-drain AF4 without the internal pull-ups."

T005_REF = (T005_INTRO + "\n\n"
            "1. **Clock tree (16 MHz HSE -> 150 MHz, Range 1 normal mode).** PLLSRC = HSE; PLLM = 4 gives 16 MHz / 4 = 4 MHz (PLL input 2.66-16 MHz), PLLN = 75 gives a 300 MHz VCO "
            "(96-344 MHz) and PLLR = 2 gives SYSCLK = 150 MHz (DS12288 Table 46). 150 MHz is the Range 1 normal-mode limit, so R1MODE stays at its reset value 1, and "
            "the Flash needs LATENCY = 4 wait states (RM0440 Table 9: 4 WS up to 150 MHz in normal mode).\n"
            "2. **Pin allocation.** I2C1: PA15 = I2C1_SCL (AF4) and PB7 = I2C1_SDA (AF4), open-drain. Sensor interrupt -> PA0 (WKUP1, also an EXTI line), so the "
            "sensor can wake the STM32 from Standby as well as from Stop. LED -> PB0 (push-pull output). USART1 debug port on PA9/PA10 (AF7) as given; PF0/PF1 = OSC_IN/OSC_OUT for the 16 MHz crystal; PA13/PA14 stay free for SWD.\n"
            + T005_STEP3 + "\n" + T005_STEP4 + "\n" + T005_STEP5 + "\n"
            "6. **Firmware plan.** Clock tree first (step 1), then GPIO/AF setup, I2C1 TIMINGR for 400 kHz written while PE = 0, the WKUP1/EXTI configuration for the "
            "sensor interrupt, and finally the LED and the debug UART.\n")

T005 = {
    "id": "C5-005", "split": "dev", "difficulty": "medium", "chips": ["stm32g474"],
    "tags": ["system_goal", "missing_info", "plan", "pll", "hse", "i2c", "logic_level", "level_shift", "safe_default"],
    "user": ("Help me plan a vibration-monitoring node. An STM32G474 on our own PCB (VDD = 3.3 V, 16 MHz crystal on its HSE pins) must run SYSCLK at 150 MHz "
             "from the main PLL fed by HSE in voltage Range 1 normal mode. It reads a MEMS accelerometer breakout board that we bought from a local vendor (no schematic is "
             "published for it) over I2C1 in Fast mode (400 kHz), and the breakout's interrupt output goes to an STM32 pin so that the sensor can wake the MCU "
             "from its low-power mode. The STM32 also drives a status LED and has a USART1 debug port on PA9/PA10 (115200 baud). The plan must cover the clock tree with the "
             "PLL M/N/R values and the Flash wait states, the pin allocation (I2C1 SCL/SDA, the interrupt/wake-up line, the LED), the logic-level compatibility "
             "between the breakout and the STM32 with the datasheet thresholds, and the wiring of the I2C bus (pull-ups). " + FMT_PLAN),
    "human_policy": {"approval": "approve", "choice": {"prefer": "level shifter"},
                     "clarify": {"sensor_io_v": "The breakout runs the sensor's I/O at 1.8 V (it has its own 1.8 V regulator and no level translator on board)."},
                     "max_answers": 3},
    "hidden_info": [{"id": "sensor_io_v", "required": True,
                     "keywords": ["I/O voltage", "IO voltage", "logic level", "logic-level", "VDDIO", "VIO", "1.8", "voltage does the breakout",
                                  "voltage does the sensor", "breakout run", "sensor run", "voltage level", "level translator", "level shifter", "VDD of the breakout",
                                  "VDD of the sensor", "VDD of the accelerometer",
                                  "breakout VDD", "breakout voltage", "sensor voltage", "3.3 V compatible", "breakout powered", "sensor powered",
                                  "supply voltage of the breakout", "supply voltage of the sensor", "breakout supply", "sensor supply"],
                     "value_patterns": [r"\b1\.8\s*V\b"]}],
    "expected": {
        "checklist": [steps(), pll(16e6, 150e6), FLASH_WS,
                      level_shifter("level_shifter", "breakout (1.8 V) - STM32 (3.3 V) I2C/INT lines",
                                    extra=[r"(?:power|run|supply)\w*\s+(?:the\s+(?:whole\s+)?)?(?:STM32\w*|MCU)\s+(?:from|at)\s+1\.8\s*V"]),
                      no_direct_generic("no_direct", "breakout - STM32 connection"),
                      {"id": "vih_reason", "type": "mentions",
                       "any_of": [r"2\.31\s*V", r"0\.7\s*[x×*·]?\s*V\s?DD", r"70\s*%\s*of\s*V\s?DD", r"1\.88\s*V"],
                       "desc": "the STM32 VIH threshold (0.7 x VDD = 2.31 V) is used to show that a 1.8 V high is not recognised"},
                      {"id": "sensor_1v8", "type": "mentions", "any_of": [r"\b1\.8\s*V\b"],
                       "desc": "the breakout's actual 1.8 V I/O level is stated"}],
    },
    "graders": ["checklist", "clarify"],
    "limitations": "G13 (review): một câu trả lời không hỏi mà luôn lắp translator vẫn có thể đạt checklist; giảm nhẹ bằng mục sensor_1v8 (phải nêu mức 1,8 V); năng lực hỏi đo bằng recall của `clarify` (không gate).",
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("stm_vih"), ev("vdd_range"), ev("wkup1"), ev("osc_pins"),
                 ev("pins_pa", "PA15 JTDI TIM2_CH1 TIM8_CH1 - I2C1_SCL"), ev("pins_pb", "PB7 - TIM17_CH1N TIM4_CH2 I2C4_SDA I2C1_SDA")],
    "reference_calc": (
        "Thông tin ẩn: breakout chạy I/O 1,8 V (module mua ở cửa hàng, không có sơ đồ ⇒ không tra được). STM32 @3,3 V: VIH min = 0,7×3,3 = 2,31 V (DS Table 54 p.128), "
        "giá trị thiết kế 0,49×3,3 + 0,26 = 1,877 V — cả hai > 1,8 V ⇒ không đọc được mức cao; chiều ngược lại 3,3 V vượt định mức I/O 1,8 V của cảm biến ⇒ level "
        "shifter (hoặc cấp STM32 1,8 V: VDD min 1,71 V, DS Table 17 p.84). Đoán 3,3 V ⇒ nối thẳng ⇒ trượt level_shifter + no_direct. Clock: HSE 16 MHz /4 = 4 MHz ×75 = "
        "300 MHz /2 = 150 MHz (cấu hình duy nhất, c5_handcalc.py); 150 MHz ≤ giới hạn Range 1 normal (DS Table 46 p.123; RM Table 38 p.232) ⇒ R1MODE = 1; "
        "4 WS (RM Table 9 p.98: ≤150 MHz normal). Chân: PA15 AF4 I2C1_SCL, PB7 AF4 I2C1_SDA (DS p.73-74), PA0 = WKUP1 (DS p.59)."),
    "variants": [
        {"name": "assumed_3v3_breakout", "must_fail": ["level_shifter", "no_direct", "sensor_1v8"],
         "edits": [(T005_INTRO, "I assume the breakout runs at 3.3 V like most hobby boards."),
                   (T005_STEP3, "3. **Logic-level check.** At 3.3 V the sensor's high level is above the STM32 VIH minimum of 0.7 x VDD = 2.31 V and the STM32 output stays within the sensor's 3.3 V I/O rating, so the levels are compatible."),
                   (T005_STEP4, "4. **Interface.** No level shifter is needed: the breakout can be wired directly to PA15/PB7 and PA0."),
                   ("use one pull-up pair per voltage side", "use 2.2 kΩ pull-ups to 3.3 V")]},
        {"name": "pullups_to_1v8_only", "must_fail": ["level_shifter"],
         "edits": [(T005_STEP4, "4. **Interface fix.** Because SCL/SDA are open-drain, simply pull them up to 1.8 V instead of 3.3 V; the STM32 never drives them high, so no extra part is used. The interrupt line goes straight to PA0.")]},
    ],
    "ref": T005_REF,
}

# =====================================================================================================================  C5-006
T006_INTRO = "Thanks: the HSE crystal is 25 MHz and the night budget is 5 µA for the whole node."
T006_PIN_CHIPPU = "PB0 (push-pull output) drives the ESP32 CHIP_PU (enable) pin, with a 10 kΩ pull-down that keeps the ESP32 off while the STM32 sleeps; "
T006_STEP4 = "4. **Low-power states.** ESP32 Deep-sleep (10 µA with RTC timer + RTC memory) or even Hibernation (5 µA) alone would use up the whole 5 µA budget, so the ESP32 is switched fully off between reports by holding CHIP_PU low (Power off: 1 µA, ESP32 datasheet Table 4-2) and re-booted every hour. The STM32 uses Standby mode with the RTC on the LSE and the RTC wake-up timer set to 3600 s: 0.655 µA typical at 3 V (DS12288 Table 32); Stop 1 (80.5 µA) is far above the budget."
T006_ROW_ESP = "   - ESP32, power off (CHIP_PU low): 1 µA"
T006_TOTAL = "   Total sleep current = 0.655 + 1 + 0.6 + 1 = 3.26 µA, inside the 5 µA budget with about 1.7 µA of margin."
T006_SEQ = "-> raise CHIP_PU, let the ESP32 boot and report over USART2 -> drop CHIP_PU ->"

T006_REF = (T006_INTRO + "\n\n"
            "1. **Clock tree (25 MHz HSE -> 150 MHz, Range 1 normal mode).** PLLSRC = HSE; PLLM = 5 gives 25 MHz / 5 = 5 MHz (PLL input 2.66-16 MHz), PLLN = 60 gives "
            "a 300 MHz VCO (96-344 MHz) and PLLR = 2 gives SYSCLK = 150 MHz (DS12288 Table 46). R1MODE stays 1 (Range 1 normal mode is enough up to 150 MHz) and the "
            "Flash needs LATENCY = 4 wait states (RM0440 Table 9).\n"
            "2. **Pin allocation.** PA2 = USART2_TX (AF7) to the ESP32 RX and PA3 = USART2_RX (AF7) from the ESP32 TX; " + T006_PIN_CHIPPU +
            "PB1/PB2 drive the latching-valve driver (open/close pulses); PF0/PF1 = OSC_IN/OSC_OUT for the 25 MHz crystal; PC14/PC15 = OSC32_IN/OSC32_OUT for the LSE.\n"
            "3. **Logic levels of the ESP32 link.** Both sides run at 3.3 V: STM32 VOH >= VDD - 0.4 = 2.9 V > ESP32 VIH = 0.75 x 3.3 = 2.48 V, ESP32 VOH >= 0.8 x 3.3 = "
            "2.64 V > STM32 VIH = 0.7 x 3.3 = 2.31 V, and both VOL limits (0.4 V, 0.33 V) are below the VIL limits (0.83 V, 0.99 V). The levels are compatible: TX/RX "
            "are wired directly with a common ground.\n"
            + T006_STEP4 + "\n"
            "5. **Sleep-current table (typical, 3 V, 25 °C).**\n"
            "   - STM32G474, Standby + RTC (LSE): 0.655 µA\n" + T006_ROW_ESP + "\n"
            "   - Soil sensor, idle: 0.6 µA\n   - Buck regulator quiescent current: 1 µA\n   - Latching valve, idle: 0 µA\n\n" + T006_TOTAL + "\n"
            "6. **Wake-up sequence.** RTC wake-up -> run the clock setup again (Standby loses it) -> read the sensor -> pulse the valve " + T006_SEQ + " back to Standby.\n")

T006 = {
    "id": "C5-006", "split": "test", "difficulty": "medium", "chips": ["stm32g474", "esp32"],
    "tags": ["system_goal", "missing_info", "plan", "pll", "hse", "current_budget", "logic_level", "power_gating"],
    "user": ("Help me plan an irrigation-valve controller. An STM32G474 on our own PCB (VDD = 3.3 V from a buck regulator with 1 µA quiescent current) keeps "
             "the schedule; it has a crystal on its HSE pins for accurate timing and must run SYSCLK at 150 MHz from the main PLL fed by HSE in voltage Range 1 "
             "normal mode, plus a 32.768 kHz LSE crystal for the RTC. Once per hour it wakes up, reads a soil sensor (0.6 µA when idle), opens or closes a "
             "latching valve (0 µA when idle) and reports over Wi-Fi through an ESP32 module (3.3 V I/O) connected to USART2 at 115200 baud. At night everything sleeps between "
             "the hourly wake-ups, and the whole node must stay within the sleep-current budget that our system designer fixed for the night phase. The plan must "
             "cover the clock tree with the PLL M/N/R values and the Flash wait states, the pin allocation (USART2 to the ESP32 and any control lines you need), "
             "the logic-level compatibility of the ESP32 link, the low-power state of the STM32 and of the ESP32, and a sleep-current table with the total "
             "compared to the budget. " + FMT_PLAN),
    "human_policy": {"approval": "approve", "choice": {"prefer": "CHIP_PU"},
                     "clarify": {"hse_hz": "The crystal on the STM32's HSE pins is 25 MHz.",
                                 "sleep_budget": "The night-time sleep-current budget for the whole node is 5 µA."},
                     "max_answers": 3},
    "hidden_info": [hse_hidden(25),
                    {"id": "sleep_budget", "required": True,
                     "keywords": ["current budget", "sleep budget", "night budget", "budget for the night", "budget for the whole node", "node budget",
                                  "what budget", "sleep current", "sleep-current", "current limit", "allowed current", "maximum current", "how much current",
                                  "standby current", "night current", "target current", "consumption allowed", "allowed consumption"],
                     "value_patterns": [r"\b5\s*[µμu]A\s+(?:budget|limit)", r"budget[^\n]{0,30}\b5\s*[µμu]A\b"]}],
    "expected": {
        "checklist": [steps(), pll(25e6, 150e6), FLASH_WS, LOW_POWER, ESP32_OFF, sleep_total(2.0, 4.5),
                      compat("esp_link_compat", "STM32-ESP32 UART link", extra=ESP_COMPAT_EXTRA)],
    },
    "graders": ["checklist", "clarify"],
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("standby_rtc"), ev("stop1"), ev("esp_modes"),
                 ev("esp_chip_pu"), ev("esp_dc"), ev("stm_vih"), ev("stm_voh"), ev("osc_pins"),
                 ev("pins_pa", "PA2 - TIM2_CH3 TIM5_CH3 - - - - USART2_TX", "PA3 - TIM2_CH4 TIM5_CH4 SAI1_CK1 - - - USART2_RX")],
    "reference_calc": (
        "Thông tin ẩn: HSE = 25 MHz, ngân sách ngủ = 5 µA (do người thiết kế hệ thống của người dùng đặt — không tra được). Clock: 25 MHz → 150 MHz có 8 cấu hình "
        "hợp lệ (M,N,R) = (2,24,2)…(9,108,2) (c5_handcalc.py); chọn M = 5 (5 MHz), N = 60 (VCO 300), R = 2. Đoán 8 MHz (M=2,N=75) với HSE thật 25 MHz → 468,75 MHz; "
        "16 MHz (M=4,N=75) → 234 MHz; 24 MHz (M=6,N=75) → 156,25 MHz ⇒ trượt pll. 150 MHz: Range 1 normal (R1MODE = 1), 4 WS (RM Table 9 p.98). Ngủ (3 V, 25 °C, "
        "typ): ESP32 Deep-sleep 10 µA / Hibernation 5 µA / Power off (CHIP_PU thấp) 1 µA (ESP32 DS Table 4-2 p.30); STM32 Standby + RTC LSE 0,655 µA (DS Table 32 "
        "p.104); cảm biến 0,6; buck 1 ⇒ tổng 3,255 µA ≤ 5. Giữ Deep-sleep ⇒ 12,26 µA; Hibernation ⇒ 7,26 µA (đều > 5) ⇒ phải tắt hẳn ESP32. Đoán ngân sách 50 µA "
        "⇒ giữ Deep-sleep ⇒ trượt esp32_off + sleep_total. CHIP_PU tắt chip khi ≤ 0,6 V (ESP32 DS p.52); STM32 VOL ≤ 0,4 V. Mức logic 3,3 V như C5-001."),
    "variants": [
        {"name": "guessed_50ua_budget", "must_fail": ["esp32_off", "sleep_total"],
         "edits": [(T006_INTRO, "Thanks: the HSE crystal is 25 MHz; I assume the usual 50 µA night budget."),
                   (T006_PIN_CHIPPU, ""),
                   (T006_STEP4, "4. **Low-power states.** The ESP32 waits in Deep-sleep with the RTC timer and RTC memory on (10 µA, ESP32 datasheet Table 4-2) and keeps its Wi-Fi credentials, and the STM32 uses Standby mode with the RTC on the LSE and the RTC wake-up timer set to 3600 s: 0.655 µA typical at 3 V (DS12288 Table 32)."),
                   (T006_ROW_ESP, "   - ESP32, Deep-sleep (RTC timer + RTC memory): 10 µA"),
                   (T006_TOTAL, "   Total sleep current = 0.655 + 10 + 0.6 + 1 = 12.26 µA, inside the 50 µA budget."),
                   (T006_SEQ, "-> wake the ESP32 and report over USART2 -> send the ESP32 back to Deep-sleep ->")]},
        {"name": "guessed_hse_8mhz", "must_fail": ["pll"],
         "edits": [("the HSE crystal is 25 MHz and", "assuming an 8 MHz HSE crystal, and since"),
                   ("(25 MHz HSE -> 150 MHz", "(8 MHz HSE -> 150 MHz"),
                   ("PLLM = 5 gives 25 MHz / 5 = 5 MHz", "PLLM = 2 gives 8 MHz / 2 = 4 MHz"),
                   ("PLLN = 60 gives a 300 MHz VCO", "PLLN = 75 gives a 300 MHz VCO"),
                   ("for the 25 MHz crystal", "for the 8 MHz crystal")]},
    ],
    "ref": T006_REF,
}

TASKS_A = [T001, T002, T003, T004, T005, T006]
