"""Task C5-007 … C5-012: ĐỦ thông tin (không có hidden_info), cho build_c5_draft.py."""
from c5_common import (ESP_COMPAT_EXTRA, CONV, FMT_PLAN, fmt_code, steps, pll, BOOST, NO_BOOST_CLAIM, FLASH_WS, LOW_POWER, STANDBY_ONLY, NOT_SHUTDOWN, sleep_total,
                       IDLE_CURRENT_RX, compat, level_shifter, no_direct_generic, no_direct_near, ESP32_OFF, HEADROOM, clock_code_boost,
                       clock_code_normal, ev, no_false_claim, trade_offs, _NUM, _SKIP, CUR_U)

FENCE = "```"

# =====================================================================================================================  C5-007
T007_CODE = (FENCE + "c\n#include \"stm32g4xx.h\"\n\nint main(void)\n{\n" + clock_code_boost("HSE", 8, 2, 85) + """
    /* peripheral clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN | RCC_APB2ENR_USART1EN;

    /* PA8 = TIM1_CH1 (AF6), PA9 = USART1_TX (AF7), PA10 = USART1_RX (AF7) */
    GPIOA->MODER = (GPIOA->MODER & ~(GPIO_MODER_MODE8 | GPIO_MODER_MODE9 | GPIO_MODER_MODE10)) | GPIO_MODER_MODE8_1 | GPIO_MODER_MODE9_1 | GPIO_MODER_MODE10_1;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~(GPIO_AFRH_AFSEL8 | GPIO_AFRH_AFSEL9 | GPIO_AFRH_AFSEL10)) | (6U << GPIO_AFRH_AFSEL8_Pos) | (7U << GPIO_AFRH_AFSEL9_Pos) | (7U << GPIO_AFRH_AFSEL10_Pos);

    /* TIM1 CH1: 170 MHz / 8500 = 20 kHz, 25 % duty */
    TIM1->PSC = 0;
    TIM1->ARR = 8499;
    TIM1->CCR1 = 2125;
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

T007_STEP6 = """6. **Low-power mode and sleep budget (< 50 µA).** Stop 1 alone draws 80.5 µA typical (DS12288 Table 30, 3 V, 25 °C), more than the budget, so the STM32 uses Standby mode with the RTC on the LSI and the RTC wake-up timer set to 300 s. Shutdown is not an option here: it switches the LSI off and there is no LSE crystal to keep the RTC running. Standby with the RTC on the LSI draws 0.885 µA typical at 3 V (Table 32).
   - STM32G474, Standby + RTC (LSI): 0.885 µA
   - ESP32, Deep-sleep with RTC timer + RTC memory: 10 µA (ESP32 datasheet Table 4-2)
   - Motor driver module, sleep: 2 µA

   Total sleep current = 0.885 + 10 + 2 = 12.9 µA, well below the 50 µA budget. Standby loses the clock configuration, so the initialisation below runs again after each wake-up."""

T007_REF = """Here is the design.

1. **Clock tree (8 MHz HSE -> 170 MHz).** The PLL input must stay within 2.66-16 MHz and the VCO within 96-344 MHz (DS12288 Table 46). PLLM = 2 gives 8 MHz / 2 = 4 MHz, PLLN = 85 gives a 340 MHz VCO and PLLR = 2 gives SYSCLK = 170 MHz (PLLSRC = HSE). Above 150 MHz the regulator must be in Range 1 boost mode (clear PWR_CR5.R1MODE), the Flash needs LATENCY = 4 wait states (RM0440 Table 9), and the AHB prescaler is /2 during the switch and back to /1 after at least 1 µs.
2. **Pin allocation.** PA8 = TIM1_CH1 (AF6) to the driver PWM input; PA9 = USART1_TX (AF7) to the ESP32 RX; PA10 = USART1_RX (AF7) from the ESP32 TX; PF0/PF1 = OSC_IN/OSC_OUT for the 8 MHz crystal. No pin is shared.
3. **PWM at 20 kHz, 25 %.** TIM1 is on APB2 (prescaler 1), so TIM1CLK = 170 MHz and 170 MHz / 20 kHz = 8500 ticks: PSC = 0, ARR = 8499, CCR1 = 0.25 x 8500 = 2125; BDTR.MOE must be set because TIM1 is an advanced timer.
4. **USART1 at 115200 baud.** PCLK2 = 170 MHz, OVER8 = 0: BRR = 170000000 / 115200 = 1475.7, rounded to 1476 (115176 baud, -0.02 %).
5. **Logic levels of the ESP32 link.** Both chips run their I/O at 3.3 V: STM32 VOH >= VDD - 0.4 = 2.9 V > ESP32 VIH = 0.75 x 3.3 = 2.48 V; ESP32 VOH >= 0.8 x 3.3 = 2.64 V > STM32 VIH = 0.7 x 3.3 = 2.31 V; the VOL limits (0.4 V, 0.33 V) are below the VIL limits (0.83 V, 0.99 V). The levels are compatible, so TX/RX are wired directly with a common ground.
""" + T007_STEP6 + """
7. **Firmware.** The program below brings up the clock tree, the PWM and USART1 from reset:

""" + T007_CODE + "\n"

T007 = {
    "id": "C5-007", "split": "test", "difficulty": "hard", "chips": ["stm32g474", "esp32"],
    "tags": ["system_goal", "complete_info", "code", "pll", "hse", "pwm", "uart", "current_budget", "logic_level"],
    "user": ("Help me design a motor-control node end to end. Hardware: an STM32G474 on our own PCB (VDD = 3.3 V) with an 8 MHz crystal on its HSE pins drives "
             "the PWM input of a brushed-DC motor driver module from TIM1 channel 1 on PA8 at 20 kHz (within ±1 %) with a 25 % duty cycle (edge-aligned PWM "
             "mode 1, active-high, no dead time), and talks to an ESP32 Wi-Fi module (ESP32 I/O supply 3.3 V) over USART1 with TX on PA9 and RX on PA10 at "
             "115200 baud (within ±2 %), 8 data bits, no parity, 1 stop bit, oversampling by 16, transmitter and receiver enabled. SYSCLK = HCLK = PCLK1 = PCLK2 "
             "must be 170 MHz from the main PLL fed by the 8 MHz HSE (within 0.1 %). Idle phase: the motor is off, the driver module sleeps at 2 µA, the ESP32 is "
             "in Deep-sleep with the RTC timer and RTC memory on, and the STM32 still has to wake up every 5 minutes from its RTC clocked by the LSI (no LSE "
             "crystal is fitted); the whole node must draw less than 50 µA in this phase. The plan must cover the clock tree with the PLL M/N/R values, the pin "
             "allocation, the logic-level compatibility of the ESP32 link, the STM32 low-power mode and a sleep-current budget with the total. " + CONV + " "
             + fmt_code("the clock tree, the PWM and USART1; describe the low-power entry in the plan instead of coding it")),
    "human_policy": {"approval": "approve", "choice": {"prefer": "standby"}, "clarify": {}, "max_answers": 3},
    "expected": {
        "initial": "reset", "hse_hz": 8000000,
        "spec": [{"type": "clock", "hse_hz": 8000000, "sysclk_hz": 170000000, "hclk_hz": 170000000, "pclk1_hz": 170000000, "pclk2_hz": 170000000, "tol_pct": 0.1},
                 {"type": "pwm", "pin": "PA8", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1},
                 {"type": "uart", "instance": "USART1", "baud": 115200, "tol_pct": 2, "tx_pin": "PA9", "rx_pin": "PA10", "frame": "8N1", "te": True, "re": True, "over8": 0}],
        "checklist": [steps(), pll(8e6, 170e6), BOOST, FLASH_WS, STANDBY_ONLY, NOT_SHUTDOWN, sleep_total(12, 20), compat("esp_link_compat", "STM32-ESP32 UART link", extra=ESP_COMPAT_EXTRA)],
    },
    "graders": ["checklist", "clarify", "functional_sim", "compile"],
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("ahb_div2"), ev("brr"), ev("pwm_mode1"),
                 ev("stop1"), ev("standby_rtc"), ev("shutdown_lsi_off"), ev("shutdown_rm"), ev("stm_vih"), ev("stm_voh"), ev("esp_dc"), ev("esp_modes"), ev("osc_pins"),
                 ev("pins_pa", "PA8 MCO - I2C3_SCL - I2C2_SDA I2S2_MCK TIM1_CH1", "PA9 - - I2C3_SMBA - I2C2_SCL I2S3_MCK TIM1_CH2 USART1_TX",
                    "PA10 - TIM17_BKIN - USB_CRS_SYNC I2C2_SMBA SPI2_MISO TIM1_CH3 USART1_RX")],
    "reference_calc": (
        "Đủ thông tin (đối chứng của C5-001). PLL 8 MHz → 170 MHz: duy nhất M = 2 (4 MHz), N = 85 (VCO 340), R = 2 (M = 1: N = 42,5; M = 3: N = 127,5 không nguyên); "
        "boost (RM Table 38 p.232), 4 WS (RM Table 9 p.98), AHB/2 (p.233). PWM: 170e6/20e3 = 8500 ⇒ ARR 8499, CCR1 2125 (RM p.1179). USART1 BRR 1476 (115176 baud). "
        "Ngủ (3 V, 25 °C, typ): Stop 1 80,5 µA (DS Table 30 p.102) > 50; không có LSE nên Shutdown không giữ được RTC (LSI tắt trong Shutdown, DS p.25) ⇒ Standby + "
        "RTC LSI 0,885 µA (DS Table 32 p.104) + ESP32 Deep-sleep 10 µA (ESP32 DS p.30) + driver 2 µA = 12,885 µA ≤ 50 µA. Mức logic 3,3 V hai phía như C5-001."),
    "variants": [
        {"name": "stop1_over_budget", "must_fail": ["low_power_mode", "sleep_total"],
         "edits": [(T007_STEP6, """6. **Low-power mode and sleep budget (< 50 µA).** The STM32 uses Stop 1 with the RTC on the LSI and the RTC wake-up timer set to 300 s, which keeps SRAM and all registers.
   - STM32G474, Stop 1 + RTC (LSI): 81.5 µA
   - ESP32, Deep-sleep with RTC timer + RTC memory: 10 µA (ESP32 datasheet Table 4-2)
   - Motor driver module, sleep: 2 µA

   Total sleep current = 81.5 + 10 + 2 = 93.5 µA.""")]},
        {"name": "pll_input_below_minimum", "must_fail": ["pll"],
         "edits": [("PLLM = 2 gives 8 MHz / 2 = 4 MHz", "PLLM = 4 gives 8 MHz / 4 = 2 MHz"),
                   ("/* 8 MHz / 2 = 4 MHz, x 85 = 340 MHz VCO", "/* 8 MHz / 4 = 2 MHz, x 85 = 170 MHz VCO"),
                   ("(1U << RCC_PLLCFGR_PLLM_Pos)", "(3U << RCC_PLLCFGR_PLLM_Pos)")]},
    ],
    "ref": T007_REF,
}

# =====================================================================================================================  C5-008
T008_CODE = (FENCE + "c\n#include \"stm32g4xx.h\"\n\nint main(void)\n{\n" + clock_code_boost("HSE", 16, 4, 85) + """
    /* peripheral clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOCEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN | RCC_APB1ENR1_I2C3EN;

    /* PA2 = USART2_TX, PA3 = USART2_RX (AF7) */
    GPIOA->MODER = (GPIOA->MODER & ~(GPIO_MODER_MODE2 | GPIO_MODER_MODE3)) | GPIO_MODER_MODE2_1 | GPIO_MODER_MODE3_1;
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~(GPIO_AFRL_AFSEL2 | GPIO_AFRL_AFSEL3)) | (7U << GPIO_AFRL_AFSEL2_Pos) | (7U << GPIO_AFRL_AFSEL3_Pos);

    /* PC8 = I2C3_SCL, PC9 = I2C3_SDA (AF8, open drain) */
    GPIOC->MODER = (GPIOC->MODER & ~(GPIO_MODER_MODE8 | GPIO_MODER_MODE9)) | GPIO_MODER_MODE8_1 | GPIO_MODER_MODE9_1;
    GPIOC->OTYPER |= GPIO_OTYPER_OT8 | GPIO_OTYPER_OT9;
    GPIOC->AFR[1] = (GPIOC->AFR[1] & ~(GPIO_AFRH_AFSEL8 | GPIO_AFRH_AFSEL9)) | (8U << GPIO_AFRH_AFSEL8_Pos) | (8U << GPIO_AFRH_AFSEL9_Pos);

    /* USART2: 1 Mbaud 8N1 from PCLK1 = 170 MHz (written while UE = 0) */
    USART2->BRR = 170;
    USART2->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;

    /* I2C3: 100 kHz standard mode, fI2CCLK = PCLK1 = 170 MHz, TIMINGR written while PE = 0 */
    I2C3->TIMINGR = (15U << I2C_TIMINGR_PRESC_Pos) | (13U << I2C_TIMINGR_SCLDEL_Pos) | (3U << I2C_TIMINGR_SDADEL_Pos) | (45U << I2C_TIMINGR_SCLH_Pos) | (59U << I2C_TIMINGR_SCLL_Pos);
    I2C3->CR1 |= I2C_CR1_PE;

    while (1) { }
}
""" + FENCE)

T008_STEP4 = "4. **Humidity-sensor interface (1.8 V).** The humidity sensor's high level is at most 1.8 V, below the STM32 VIH minimum of 0.7 x 3.3 = 2.31 V (DS12288 Table 54), and a 3.3 V level from the STM32 side would exceed its 1.8 V I/O rating, so I fit a bidirectional I2C level shifter (e.g. PCA9306) between PC8/PC9 and the sensor, with pull-ups to 1.8 V on the sensor side and to 3.3 V on the MCU side."
T008_STEP6 = """6. **Sleep mode and budget (10 µA).** Stop 1 alone draws 80.5 µA typical (DS12288 Table 30), so the STM32 uses Standby with the RTC on the LSE and a 600 s wake-up timer.
   - STM32G474, Standby + RTC (LSE): 0.655 µA
   - nRF52840, System OFF without RAM retention: 0.40 µA (nRF52840 PS)
   - Humidity sensor, sleep: 1 µA

   Total sleep current = 0.655 + 0.40 + 1 = 2.06 µA, well inside the 10 µA budget"""
T008_STEP6_END = " (the remaining margin also covers the leakage of the level shifter)."

T008_REF = ("Here is the design.\n\n"
            "1. **Clock tree (16 MHz HSE -> 170 MHz).** PLLSRC = HSE; PLLM = 4 gives 16 MHz / 4 = 4 MHz (PLL input 2.66-16 MHz), PLLN = 85 gives a 340 MHz VCO "
            "(96-344 MHz) and PLLR = 2 gives SYSCLK = 170 MHz (DS12288 Table 46). Range 1 boost mode (clear PWR_CR5.R1MODE), LATENCY = 4 wait states (RM0440 Table 9) "
            "and the AHB /2 step during the switch; PCLK1 = PCLK2 = 170 MHz.\n"
            "2. **Pin allocation.** USART2: PA2 = TX and PA3 = RX (AF7) as specified. I2C3: PC8 = I2C3_SCL (AF8) and PC9 = I2C3_SDA (AF8), open-drain (PA8 also "
            "carries I2C3_SCL but stays free). PF0/PF1 = OSC_IN/OSC_OUT for the 16 MHz crystal, PC14/PC15 = OSC32_IN/OSC32_OUT for the LSE crystal.\n"
            "3. **Peripheral timing.** USART2 at 1 Mbaud from PCLK1 = 170 MHz with OVER8 = 0: BRR = 170 (exact). I2C3 at 100 kHz from fI2CCLK = 170 MHz: PRESC = 15, "
            "SCLL = 59, SCLH = 45, SCLDEL = 13, SDADEL = 3 (tLOW about 5.6 µs and tHIGH about 4.3 µs, above the standard-mode minimums).\n"
            + T008_STEP4 + "\n"
            "5. **nRF52840 interface (3.3 V).** The QFN48 nRF52840 has VDD and VDDH shorted inside the package, so it runs in Normal Voltage mode and its GPIO high "
            "level equals its 3.3 V VDD. nRF52840 VIH = 0.7 x 3.3 = 2.31 V is below the STM32 VOH (>= 2.9 V); the STM32 VIH of 2.31 V is below the nRF52840 VOH "
            "(>= VDD - 0.4 = 2.9 V); VOL 0.4 V is below both VIL limits (0.99 V); and the 3.3 V STM32 high level stays below the nRF52840 limit of VDD + 0.3 = 3.6 V. "
            "The UART levels are compatible, so TX/RX are wired directly with a common ground.\n"
            + T008_STEP6 + T008_STEP6_END + "\n"
            "7. **Firmware.** The program below configures the clock tree, I2C3 and USART2 (the low-power entry follows step 6):\n\n" + T008_CODE + "\n")

T008 = {
    "id": "C5-008", "split": "dev", "difficulty": "hard", "chips": ["stm32g474", "nrf52840"],
    "tags": ["system_goal", "complete_info", "code", "pll", "hse", "uart", "i2c", "current_budget", "logic_level", "level_shift"],
    "user": ("Help me design a sensor node end to end. An STM32G474 on our own PCB (VDD = 3.3 V) with a 16 MHz crystal on its HSE pins must run SYSCLK = HCLK = "
             "PCLK1 = PCLK2 = 170 MHz from the main PLL fed by HSE (within 0.1 %). It reads a humidity sensor whose I/O supply is 1.8 V over I2C3 in standard mode "
             "(100 kHz, controller, open-drain pins; choose the I2C3 pins yourself), and it exchanges data with an nRF52840 (QFN48 package, supplied from the same "
             "3.3 V rail) over USART2 with TX on PA2 and RX on PA3 at 1 Mbaud (within ±2 %), 8 data bits, no parity, 1 stop bit, oversampling by 16, transmitter "
             "and receiver enabled. Sleep phase: the STM32 waits in a low-power mode with its RTC running from a 32.768 kHz LSE crystal (wake-up every 10 minutes), "
             "the nRF52840 is in System OFF without RAM retention, and the sensor sleeps at 1 µA; the sleep-current budget of the whole node is 10 µA. The plan "
             "must cover the clock tree with the PLL M/N/R values, the pin allocation, the logic-level compatibility of both links (with the datasheet "
             "thresholds), the STM32 low-power mode and a sleep-current table with the total. " + CONV + " "
             + fmt_code("the clock tree, I2C3 and USART2; describe the low-power entry in the plan instead of coding it")),
    "human_policy": {"approval": "approve", "choice": {"prefer": "level shifter"}, "clarify": {}, "max_answers": 3},
    "expected": {
        "initial": "reset", "hse_hz": 16000000,
        "spec": [{"type": "clock", "hse_hz": 16000000, "sysclk_hz": 170000000, "hclk_hz": 170000000, "pclk1_hz": 170000000, "pclk2_hz": 170000000, "tol_pct": 0.1},
                 {"type": "uart", "instance": "USART2", "baud": 1000000, "tol_pct": 2, "tx_pin": "PA2", "rx_pin": "PA3", "frame": "8N1", "te": True, "re": True, "over8": 0},
                 {"type": "i2c", "instance": "I2C3", "scl_hz": 100000, "tol_pct": 5, "mode": "Sm", "open_drain": True, "require_pins": True}],
        "checklist": [steps(), pll(16e6, 170e6), BOOST, FLASH_WS,
                      level_shifter("level_shifter", "humidity sensor (1.8 V) I2C lines"),
                      no_direct_near("no_direct_sensor", ["sensor", "humidity"], "1.8 V humidity sensor"),
                      compat("nrf_link_compat", "STM32-nRF52840 UART link (QFN48, 3.3 V)"),
                      LOW_POWER, sleep_total(1.5, 6)],
    },
    "graders": ["checklist", "clarify", "functional_sim", "compile"],
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("ahb_div2"), ev("brr"), ev("i2c_tscl"),
                 ev("stop1"), ev("standby_rtc"), ev("stm_vih"), ev("stm_voh"), ev("nrf_qfn48"), ev("nrf_gpio"), ev("nrf_absmax"), ev("nrf_sleep"),
                 ev("pins_pa", "PA2 - TIM2_CH3 TIM5_CH3 - - - - USART2_TX", "PA3 - TIM2_CH4 TIM5_CH4 SAI1_CK1 - - - USART2_RX"),
                 ev("pins_pc", "PC8 - - TIM3_CH3 HRTIM1_CHE1 TIM8_CH3 - TIM20_CH3 COMP7_OUT I2C3_SCL",
                    "PC9 - - TIM3_CH4 HRTIM1_CHE2 TIM8_CH4 I2SCKIN TIM8_BKIN2 - I2C3_SDA")],
    "reference_calc": (
        "Đủ thông tin (đối chứng của C5-002/C5-005). PLL 16 MHz → 170 MHz: duy nhất M = 4, N = 85, R = 2; boost, 4 WS, AHB/2. USART2 1 Mbaud: BRR = 170e6/1e6 = 170. "
        "I2C3 100 kHz @170 MHz: PRESC 15, SCLL 59, SCLH 45, SCLDEL 13, SDADEL 3 (như C4-001, RM p.1645). PC8/PC9 AF8 = I2C3 (DS p.75). Cảm biến 1,8 V: < VIH 2,31 V "
        "(DS p.128) ⇒ level shifter. nRF52840 QFN48: VDD/VDDH nối tắt trong vỏ (PS p.970) ⇒ Normal Voltage mode, GPIO = 3,3 V; nRF VIH 0,7×3,3 = 2,31 V (PS p.370) "
        "< STM32 VOH 2,9 V; STM32 3,3 V ≤ VDD + 0,3 = 3,6 V (PS p.972) ⇒ nối thẳng. Ngủ: Standby + RTC LSE 0,655 µA (DS p.104) + nRF System OFF 0,40 µA (PS p.76) "
        "+ cảm biến 1 µA = 2,055 µA ≤ 10 µA; Stop 1 80,5 µA (DS p.102) > 10."),
    "variants": [
        {"name": "sensor_wired_directly", "must_fail": ["level_shifter", "no_direct_sensor"],
         "edits": [(T008_STEP4, "4. **Humidity-sensor interface (1.8 V).** The STM32 I2C pins are open-drain, so the humidity sensor can be wired directly to PC8/PC9 with pull-ups to 1.8 V."),
                   (T008_STEP6_END, ".")]},
        {"name": "stop1_over_budget", "must_fail": ["low_power_mode", "sleep_total"],
         "edits": [(T008_STEP6, """6. **Sleep mode and budget (10 µA).** The STM32 uses Stop 1 with the RTC on the LSE and a 600 s wake-up timer, so SRAM and all registers are kept.
   - STM32G474, Stop 1 + RTC (LSE): 84.5 µA
   - nRF52840, System OFF without RAM retention: 0.40 µA (nRF52840 PS)
   - Humidity sensor, sleep: 1 µA

   Total sleep current = 84.5 + 0.40 + 1 = 85.9 µA""")]},
        {"name": "pll_for_8mhz_input", "must_fail": ["pll"],
         "edits": [("PLLM = 4 gives 16 MHz / 4 = 4 MHz", "PLLM = 2 gives 16 MHz / 2 = 8 MHz"),
                   ("/* 16 MHz / 4 = 4 MHz, x 85 = 340 MHz VCO", "/* 16 MHz / 2 = 8 MHz, x 85 = 680 MHz VCO"),
                   ("(3U << RCC_PLLCFGR_PLLM_Pos)", "(1U << RCC_PLLCFGR_PLLM_Pos)")]},
    ],
    "ref": T008_REF,
}

# =====================================================================================================================  C5-009
T009_STEP3 = "3. **STM32 low-power mode.** Standby with the RTC on the LSE crystal draws 0.655 µA typical at 3 V (DS12288 Table 32) and keeps the brown-out reset active (the BOR is not available in Shutdown). Stop 1 (80.5 µA typical, Table 30) would dominate the whole budget."
T009_STEP4 = """4. **Sleep-current table (3.0 V, 25 °C, typical).**
   - STM32G474, Standby + RTC (LSE): 0.655 µA
   - nRF52840, System OFF without RAM retention: 0.40 µA (nRF52840 PS, IOFF_RAMOFF_RESET)
   - LDO quiescent current: 2 µA
   - Probe behind its load switch: 0 µA

   Total sleep current = 0.655 + 0.40 + 2 = 3.06 µA."""
T009_STEP5 = "5. **Average current over one 10-minute cycle.** Active charge per cycle = 10 mA x 1.5 s = 15 mC; sleep charge = 3.06 µA x 598.5 s = 1.83 mC. Average current = (15 mC + 1.83 mC) / 600 s = 28.0 µA."
T009_STEP6 = "6. **Battery life.** 2600 mAh / 0.0280 mA = 92700 h, i.e. about 10.6 years (127 months). The 12-year target is not met: 12 years need about 28.0 µA x 105120 h = 2948 mAh, or an average current of at most 2600 mAh / 105120 h = 24.7 µA."
T009_STEP7 = """7. **Options to reach 12 years** (one of them is enough, or combine them):
   - a larger battery: at least 2948 mAh, e.g. a 3600 mAh cell of the same chemistry for margin;
   - a longer wake-up interval: at least 692 s (about 12 minutes) instead of 10 minutes, with the same 1.5 s / 10 mA active phase;
   - a shorter active phase: at most about 1.3 s at 10 mA per 10-minute cycle (lower BLE TX power, shorter connection, faster probe read).

   The 12-minute interval is the cheapest change if the application accepts it."""

T009_REF = ("Here is the plan.\n\n"
            "1. **Pin allocation.** STM32 USART1: PA9 = TX and PA10 = RX (AF7) to the nRF52840 UARTE (its pins are freely assignable); PB0 (push-pull output) drives an "
            "nRF52840 GPIO configured as the wake-up (DETECT) source for leaving System OFF; PB1 (push-pull output) drives the enable input of the probe's load switch; "
            "PC14/PC15 = OSC32_IN/OSC32_OUT for the LSE crystal.\n"
            "2. **Logic levels.** Both chips share the 3.0 V rail. STM32 VOH >= VDD - 0.4 = 2.6 V is above the nRF52840 VIH of 0.7 x 3.0 = 2.1 V, and the nRF52840 VOH "
            ">= VDD - 0.4 = 2.6 V is above the STM32 VIH of 0.7 x 3.0 = 2.1 V; both VOL limits (0.4 V) are below the VIL limits (0.3 x 3.0 = 0.9 V). The levels are "
            "compatible, so the UART and wake-up lines are wired directly.\n"
            + T009_STEP3 + "\n" + T009_STEP4 + "\n" + T009_STEP5 + "\n" + T009_STEP6 + "\n" + T009_STEP7 + "\n")

T009 = {
    "id": "C5-009", "split": "test", "difficulty": "medium", "chips": ["stm32g474", "nrf52840"],
    "tags": ["system_goal", "complete_info", "plan", "current_budget", "battery_life", "logic_level", "trade_off"],
    "user": ("Help me plan a battery-powered soil-moisture logger. An STM32G474 (VDD = 3.0 V from a low-dropout regulator whose quiescent current is 2 µA) "
             "wakes up every 10 minutes, switches on the moisture probe through a GPIO-controlled load switch, takes a reading and sends it over Bluetooth LE "
             "through an nRF52840 that shares the same 3.0 V rail (Normal Voltage mode) and talks to the STM32 over a UART at 115200 baud. One wake-up cycle lasts 1.5 s and the "
             "whole node then draws 10 mA on average (measured on our prototype). Between cycles the probe is switched off (0 µA), the nRF52840 sits in System "
             "OFF without RAM retention and is woken by a GPIO from the STM32, and the STM32 waits in its lowest-power mode that still keeps the RTC running from "
             "a 32.768 kHz LSE crystal and a brown-out reset active. The node runs from a 2600 mAh lithium primary cell (treat the full 2600 mAh as usable, no "
             "derating) and must last at least 12 years without a battery change. The plan must cover the pin allocation (UART, wake-up and load-switch control "
             "lines), the logic-level compatibility between the two chips, the STM32 low-power mode, a sleep-current table with the total, the average current "
             "over one cycle, the expected battery life, and what to change if the 12-year target is not met. " + FMT_PLAN),
    "human_policy": {"approval": "approve", "choice": {"prefer": "interval"}, "clarify": {}, "max_answers": 3},
    "expected": {
        "checklist": [steps(), compat("nrf_link_compat", "STM32-nRF52840 link"), STANDBY_ONLY, NOT_SHUTDOWN, sleep_total(2.8, 4.2),
                      {"id": "avg_current", "type": "quantity", "match": "any", "unit_out": "uA", "min": 26.5, "max": 30.0,
                       "patterns": [r"\b(?:average|mean)\b[^\n]{0,200}?" + _NUM + r"\s*" + CUR_U + _SKIP, r"\bI_?avg\b[^\n]{0,80}?" + _NUM + r"\s*" + CUR_U + _SKIP,
                                    _NUM + r"\s*" + CUR_U + r"[ \t]+(?:on[ \t]+)?average\b"],
                       "desc": "average current over a 10-minute cycle = 10 mA x 1.5 s / 600 s + sleep, about 28 uA"},
                      {"id": "lifetime", "type": "quantity", "match": "any", "unit_out": "year", "min": 10.0, "max": 11.2,
                       "patterns": [r"(?:\b(?:life(?:time)?|lasts?|lasting|runtime|run[- ]time)\b|\bi\.e\.)[^\n]{0,200}?" + _NUM
                                    + r"\s*(?P<u>years?|yrs?|months?|days?|hours?|h)\b" + _SKIP,
                                    _NUM + r"\s*(?P<u>years?|yrs?|months?)[ \t]+(?:of[ \t]+)?(?:battery[ \t]+)?(?:life|lifetime|operation|runtime)\b"],
                       "desc": "battery life with 2600 mAh is about 10.6 years (92700 h)"},
                      trade_offs("12"), no_false_claim(r"(?:12|twelve)", "12")],
    },
    "graders": ["checklist", "clarify"],
    "evidence": [ev("standby_rtc"), ev("stop1"), ev("bor"), ev("bor_rm"), ev("shutdown_rm"), ev("stm_vih"), ev("stm_voh"), ev("nrf_gpio"), ev("nrf_sleep"), ev("osc_pins"),
                 ev("pins_pa", "PA9 - - I2C3_SMBA - I2C2_SCL I2S3_MCK TIM1_CH2 USART1_TX", "PA10 - TIM17_BKIN - USB_CRS_SYNC I2C2_SMBA SPI2_MISO TIM1_CH3 USART1_RX")],
    "reference_calc": (
        "Đủ thông tin (đối chứng của C5-003). Ngủ: 0,655 (Standby + RTC LSE, DS p.104) + 0,40 (nRF System OFF, PS p.76) + 2 (LDO) = 3,055 µA. Trung bình: "
        "10 mA × 1,5/600 = 25 µA + 3,055 × 598,5/600 = 3,05 µA ⇒ 28,05 µA. Tuổi thọ 2600/0,02805 = 92692 h = 10,58 năm < 12 năm; cần 2948 mAh hoặc I_avg ≤ "
        "2600/105120 = 24,73 µA ⇒ chu kỳ ≥ 15 mC/21,68 µA = 692 s, hoặc pha hoạt động ≤ 1,30 s ở 10 mA. Mức logic 3,0 V như C5-003."),
    "variants": [
        {"name": "no_remedies_offered", "must_fail": ["trade_offs"],
         "edits": [(T009_STEP7, "7. **Next step.** Please confirm and I will prepare the firmware plan.")]},
        {"name": "stop1_sleep", "must_fail": ["low_power_mode", "sleep_total", "avg_current", "lifetime"],
         "edits": [(T009_STEP3, "3. **STM32 low-power mode.** Stop 1 with the RTC on the LSE keeps SRAM and wakes up fast: 84.5 µA typical at 3 V (DS12288 Table 30)."),
                   (T009_STEP4, """4. **Sleep-current table (3.0 V, 25 °C, typical).**
   - STM32G474, Stop 1 + RTC (LSE): 84.5 µA
   - nRF52840, System OFF without RAM retention: 0.40 µA (nRF52840 PS, IOFF_RAMOFF_RESET)
   - LDO quiescent current: 2 µA
   - Probe behind its load switch: 0 µA

   Total sleep current = 84.5 + 0.40 + 2 = 86.9 µA."""),
                   (T009_STEP5, "5. **Average current over one 10-minute cycle.** Active charge per cycle = 10 mA x 1.5 s = 15 mC; sleep charge = 86.9 µA x 598.5 s = 52.0 mC. Average current = (15 mC + 52.0 mC) / 600 s = 111.7 µA."),
                   (T009_STEP6, "6. **Battery life.** 2600 mAh / 0.1117 mA = 23280 h, i.e. about 2.7 years (32 months). The 12-year target is not met: 12 years would need about 11740 mAh.")]},
    ],
    "ref": T009_REF,
}

# =====================================================================================================================  C5-010
T010_CODE = (FENCE + "c\n#include \"stm32g4xx.h\"\n\nint main(void)\n{\n" + clock_code_normal(25, 5, 60) + """
    /* peripheral clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_TIM3EN | RCC_APB1ENR1_USART3EN;

    /* PA6 = TIM3_CH1 (AF2) */
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE6) | GPIO_MODER_MODE6_1;
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~GPIO_AFRL_AFSEL6) | (2U << GPIO_AFRL_AFSEL6_Pos);

    /* PB10 = USART3_TX, PB11 = USART3_RX (AF7) */
    GPIOB->MODER = (GPIOB->MODER & ~(GPIO_MODER_MODE10 | GPIO_MODER_MODE11)) | GPIO_MODER_MODE10_1 | GPIO_MODER_MODE11_1;
    GPIOB->AFR[1] = (GPIOB->AFR[1] & ~(GPIO_AFRH_AFSEL10 | GPIO_AFRH_AFSEL11)) | (7U << GPIO_AFRH_AFSEL10_Pos) | (7U << GPIO_AFRH_AFSEL11_Pos);

    /* TIM3 CH1: 150 MHz / 37500 = 4 kHz, 50 % duty */
    TIM3->PSC = 0;
    TIM3->ARR = 37499;
    TIM3->CCR1 = 18750;
    TIM3->CCMR1 = (TIM3->CCMR1 & ~TIM_CCMR1_OC1M) | (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM3->CCER |= TIM_CCER_CC1E;
    TIM3->CR1 |= TIM_CR1_ARPE;
    TIM3->EGR = TIM_EGR_UG;
    TIM3->CR1 |= TIM_CR1_CEN;

    /* USART3: 460800 baud 8N1 from PCLK1 = 150 MHz (written while UE = 0) */
    USART3->BRR = 326;
    USART3->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;

    while (1) { }
}
""" + FENCE)

T010_STEP5 = "5. **nRF52840 I/O level.** In High Voltage mode the nRF52840 GPIO level equals the REG0 output set by UICR.REGOUT0 (nRF52840 PS); REGOUT0 = 3.3 V (VOUT = 5) is valid here because REG0 needs VDDH at least 0.3 V above VDD and the 4.0 V rail leaves 0.7 V of headroom. The nRF52840 I/O therefore runs at 3.3 V, the same as the STM32."
T010_STEP6 = "6. **Logic-level check.** STM32 VOH >= 2.9 V > nRF52840 VIH = 0.7 x 3.3 = 2.31 V; nRF52840 VOH >= VDD - 0.4 = 2.9 V > STM32 VIH = 2.31 V; VOL 0.4 V < VIL 0.99 V on both sides; and the 3.3 V STM32 output stays below the nRF52840 limit of VDD + 0.3 = 3.6 V. The levels are compatible, so the UART is wired directly with no level shifter. The production script must program REGOUT0 before the STM32 starts driving the UART, otherwise a blank nRF52840 runs at the 1.8 V default. Corner case: REG0 has a -10/+5 % output tolerance (nRF52840 PS), so in the worst case the nRF52840 VDD is 2.97 V and its pin limit 3.27 V, about 30 mV below a full 3.3 V STM32 high; a 100-330 Ω series resistor on the STM32 TX line covers that corner."

T010_REF = ("Here is the design.\n\n"
            "1. **Clock tree (25 MHz HSE -> 150 MHz, Range 1 normal mode).** PLLSRC = HSE; PLLM = 5 gives 25 MHz / 5 = 5 MHz (PLL input 2.66-16 MHz), PLLN = 60 gives "
            "a 300 MHz VCO (96-344 MHz) and PLLR = 2 gives SYSCLK = 150 MHz (DS12288 Table 46). 150 MHz is allowed in Range 1 normal mode, so R1MODE keeps its reset "
            "value 1, and the Flash needs LATENCY = 4 wait states (RM0440 Table 9). Because HCLK ends up above 80 MHz, the switch to the PLL still goes through the "
            "AHB /2 transition state for at least 1 µs before HPRE returns to /1 (RM0440 7.2.7). PCLK1 = PCLK2 = 150 MHz.\n"
            "2. **Pin allocation.** PA6 = TIM3_CH1 (AF2) to the buzzer driver; PB10 = USART3_TX (AF7) and PB11 = USART3_RX (AF7) to the nRF52840; PF0/PF1 = "
            "OSC_IN/OSC_OUT for the 25 MHz crystal.\n"
            "3. **Buzzer PWM at 4 kHz, 50 %.** TIM3 is on APB1 (prescaler 1), so TIM3CLK = 150 MHz and 150 MHz / 4 kHz = 37500 ticks, which fits the 16-bit counter: "
            "PSC = 0, ARR = 37499, CCR1 = 18750.\n"
            "4. **USART3 at 460800 baud.** PCLK1 = 150 MHz, OVER8 = 0: BRR = 150000000 / 460800 = 325.5, rounded to 326, i.e. 460123 baud (-0.15 %).\n"
            + T010_STEP5 + "\n" + T010_STEP6 + "\n"
            "7. **Firmware.** The program below configures the clock tree, the buzzer PWM and USART3 from reset:\n\n" + T010_CODE + "\n")

T010 = {
    "id": "C5-010", "split": "test", "difficulty": "hard", "chips": ["stm32g474", "nrf52840"],
    "tags": ["system_goal", "complete_info", "code", "pll", "hse", "pwm", "uart", "logic_level", "nrf_vddh"],
    "user": ("Help me design the main board of a BLE-connected alarm unit. An STM32G474 on our own PCB (VDD = 3.3 V) with a 25 MHz crystal on its HSE pins must "
             "run SYSCLK = HCLK = PCLK1 = PCLK2 = 150 MHz from the main PLL fed by HSE in voltage Range 1 normal mode (within 0.1 %). It drives the input of a "
             "piezo-buzzer driver with a 4 kHz, 50 % PWM from TIM3 channel 1 on PA6 (within ±1 %; edge-aligned PWM mode 1, active-high) and exchanges data with "
             "an nRF52840 (aQFN73 package) over USART3 with TX on PB10 and RX on PB11 at 460800 baud (within ±2 %), 8 data bits, no parity, 1 stop bit, "
             "oversampling by 16, transmitter and receiver enabled. The nRF52840 is supplied on its VDDH pin from a regulated 4.0 V rail, and our production "
             "script programs UICR.REGOUT0 to 3.3 V (VOUT = 5). The plan must cover the clock tree with the PLL M/N/R values and the Flash wait states, the pin "
             "allocation, and the logic-level compatibility of the UART link (with the datasheet thresholds and the regulator headroom). " + CONV + " "
             + fmt_code("the clock tree, the buzzer PWM and USART3")),
    "human_policy": {"approval": "approve", "clarify": {}, "max_answers": 3},
    "expected": {
        "initial": "reset", "hse_hz": 25000000,
        "spec": [{"type": "clock", "hse_hz": 25000000, "sysclk_hz": 150000000, "hclk_hz": 150000000, "pclk1_hz": 150000000, "pclk2_hz": 150000000, "tol_pct": 0.1},
                 {"type": "pwm", "pin": "PA6", "freq_hz": 4000, "duty_pct": 50, "tol_pct": 1},
                 {"type": "uart", "instance": "USART3", "baud": 460800, "tol_pct": 2, "tx_pin": "PB10", "rx_pin": "PB11", "frame": "8N1", "te": True, "re": True, "over8": 0}],
        "checklist": [steps(), pll(25e6, 150e6), FLASH_WS,
                      {"id": "regout0", "type": "mentions", "any_of": [r"REGOUT0", r"\bREG0\b"],
                       "desc": "the nRF52840 GPIO level in High Voltage mode follows REG0/UICR.REGOUT0"},
                      HEADROOM,
                      compat("nrf_link_compat", "STM32-nRF52840 UART link (REGOUT0 = 3.3 V)")],
    },
    "graders": ["checklist", "clarify", "functional_sim", "compile"],
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("brr"), ev("pwm_mode1"), ev("stm_vih"), ev("stm_voh"),
                 ev("nrf_regout0"), ev("nrf_gpio_hv"), ev("nrf_reg0_drop"), ev("reg0_err"), ev("nrf_gpio"), ev("nrf_absmax"), ev("osc_pins"),
                 ev("ahb_transition"), ev("ahb_transition2"),
                 ev("pins_pa", "PA6 - TIM16_CH1 TIM3_CH1"), ev("pins_pb", "PB10 - TIM2_CH3 - - - - - USART3_TX", "PB11 - TIM2_CH4 - - - - - USART3_RX")],
    "reference_calc": (
        "Đủ thông tin (đối chứng của C5-004). PLL 25 MHz → 150 MHz: 8 cấu hình hợp lệ, chọn M = 5 (5 MHz), N = 60 (300 MHz), R = 2; Range 1 normal (R1MODE = 1 mặc "
        "định, RM Table 38 p.232), 4 WS (RM Table 9 p.98), vẫn qua trạng thái trung gian AHB/2 ≥ 1 µs vì HCLK > 80 MHz (RM 7.2.7 p.279-280; review C5-010 (b)); dung sai REG0 −10/+5 % (PS p.155) ⇒ VDD nRF xấu nhất 2,97 V, VI/O max 3,27 V — ghi chú điện trở nối tiếp, không đổi kết luận. TIM3 (APB1, 16 bit): 150e6/4e3 = 37500 ⇒ ARR 37499, "
        "CCR1 18750. USART3: 150e6/460800 = 325,5 → 326 ⇒ 460123 baud (−0,15 %). PA6 AF2 TIM3_CH1 (DS p.73), PB10/PB11 AF7 USART3 (DS p.74). nRF52840 HV mode: GPIO "
        "= REGOUT0 (PS p.82); REGOUT0 = 3,3 V (VOUT 5, PS p.63) cần VDDH − VDD ≥ 0,3 V (PS p.155): 4,0 − 3,3 = 0,7 V ✓ ⇒ I/O 3,3 V; nRF VIH 2,31 V (PS p.370), "
        "VI/O max 3,6 V (PS p.972) ⇒ nối thẳng."),
    "variants": [
        {"name": "pll_for_8mhz_crystal", "must_fail": ["pll"],
         "edits": [("PLLM = 5 gives 25 MHz / 5 = 5 MHz", "PLLM = 2 gives 8 MHz / 2 = 4 MHz"), ("PLLN = 60 gives", "PLLN = 75 gives"),
                   ("/* 25 MHz / 5 = 5 MHz, x 60", "/* 8 MHz / 2 = 4 MHz, x 75"),
                   ("(4U << RCC_PLLCFGR_PLLM_Pos) | (60U << RCC_PLLCFGR_PLLN_Pos)", "(1U << RCC_PLLCFGR_PLLM_Pos) | (75U << RCC_PLLCFGR_PLLN_Pos)")]},
        {"name": "ignores_programmed_regout0", "must_fail": ["headroom", "nrf_link_compat"],
         "edits": [(T010_STEP5, "5. **nRF52840 I/O level.** With the supply on VDDH the nRF52840 GPIO level follows REGOUT0, and I keep its 1.8 V default."),
                   (T010_STEP6, "6. **Logic-level check.** The 1.8 V nRF52840 output is below the STM32 VIH of 2.31 V and the 3.3 V STM32 output is above the nRF52840 limit of VDD + 0.3 = 2.1 V, so a level shifter is required on TX and RX.")]},
    ],
    "ref": T010_REF,
}

# =====================================================================================================================  C5-011
T011_PIN_CHIPPU = "PB0 = push-pull output to the ESP32 CHIP_PU (enable) pin, with a 10 kΩ pull-down; "
T011_STEP3 = "3. **Gas-sensor interface (1.8 V).** The gas sensor's high level is at most 1.8 V, below the STM32 VIH minimum of 0.7 x 3.3 = 2.31 V (DS12288 Table 54), and the 3.3 V MCU side would exceed the sensor's 1.8 V I/O rating, so a bidirectional I2C level shifter (e.g. PCA9306 or LSF0102, pull-ups to 1.8 V on the sensor side and to 3.3 V on the MCU side, sized for 400 kHz) sits between PA15/PB7 and the gas sensor."
T011_CHIPPU_SENT = " The CHIP_PU input is held low by the pull-down (the ESP32 shuts down below 0.6 V on CHIP_PU) and driven high by PB0 to boot the ESP32."
T011_STEP5 = "5. **Low-power states.** ESP32 Deep-sleep (10 µA) would exceed the 8 µA budget on its own, and Hibernation (5 µA) leaves too little room for the other loads (8.2 µA with them), so the ESP32 is switched fully off with CHIP_PU low (Power off: 1 µA, ESP32 datasheet Table 4-2) and re-booted for each report. The STM32 uses Standby with the RTC on the LSE (0.655 µA typical at 3 V, DS12288 Table 32) and an 1800 s RTC wake-up; Stop 1 (80.5 µA) is far above the budget."
T011_ROW_ESP = "   - ESP32, power off (CHIP_PU low): 1 µA"
T011_TOTAL = "   Total sleep current = 0.655 + 1 + 1.5 + 1 = 4.16 µA, inside the 8 µA budget"
T011_TOTAL_END = " (about 3.8 µA of margin, which also covers the leakage of the level shifter)."

T011_REF = ("Here is the plan.\n\n"
            "1. **Clock tree (12 MHz HSE -> 160 MHz).** PLLSRC = HSE; PLLM = 3 gives 12 MHz / 3 = 4 MHz (PLL input 2.66-16 MHz), PLLN = 80 gives a 320 MHz VCO (96-344 MHz) and "
            "PLLR = 2 gives SYSCLK = 160 MHz (DS12288 Table 46). 160 MHz is above the 150 MHz limit of Range 1 normal mode, so Range 1 boost mode is needed (clear "
            "PWR_CR5.R1MODE, with the AHB /2 step during the switch), and the Flash needs LATENCY = 4 wait states (RM0440 Table 9: 136 < 160 <= 170 MHz in boost mode).\n"
            "2. **Pin allocation.** I2C1: PA15 = I2C1_SCL (AF4) and PB7 = I2C1_SDA (AF4), open-drain; USART1: PA9 = TX and PA10 = RX (AF7) to the ESP32; "
            + T011_PIN_CHIPPU + "PF0/PF1 = OSC_IN/OSC_OUT for the 12 MHz crystal; PC14/PC15 = OSC32_IN/OSC32_OUT for the LSE crystal; PA13/PA14 stay free for SWD.\n"
            + T011_STEP3 + "\n"
            "4. **ESP32 interface (3.3 V).** STM32 VOH >= VDD - 0.4 = 2.9 V > ESP32 VIH = 0.75 x 3.3 = 2.48 V; ESP32 VOH >= 0.8 x 3.3 = 2.64 V > STM32 VIH = 2.31 V; "
            "VOL 0.4 V / 0.33 V are below VIL 0.83 V / 0.99 V. The UART levels are compatible, so TX/RX are wired directly with a common ground." + T011_CHIPPU_SENT + "\n"
            + T011_STEP5 + "\n"
            "6. **Sleep-current table (typical, 3 V, 25 °C).**\n"
            "   - STM32G474, Standby + RTC (LSE): 0.655 µA\n" + T011_ROW_ESP + "\n"
            "   - Gas sensor, sleep: 1.5 µA\n   - LDO quiescent current: 1 µA\n\n" + T011_TOTAL + T011_TOTAL_END + "\n")

T011 = {
    "id": "C5-011", "split": "dev", "difficulty": "medium", "chips": ["stm32g474", "esp32"],
    "tags": ["system_goal", "complete_info", "plan", "pll", "hse", "current_budget", "logic_level", "level_shift", "power_gating"],
    "user": ("Help me plan an environmental-monitoring node. An STM32G474 on our own PCB (VDD = 3.3 V from an LDO with 1 µA quiescent current, a 12 MHz crystal "
             "on its HSE pins and a 32.768 kHz LSE crystal) must run SYSCLK at 160 MHz from the main PLL fed by HSE. It reads a gas sensor whose I/O supply is 1.8 V over "
             "I2C1 (400 kHz) and reports every 30 minutes over Wi-Fi through an ESP32 module (3.3 V I/O) on USART1 at 115200 baud. Between reports the sensor sleeps at 1.5 µA, "
             "the STM32 waits for its RTC wake-up, and the sleep-current budget of the whole node is 8 µA. The plan must cover the clock tree with the PLL M/N/R "
             "values, the voltage-scaling mode and the Flash wait states, the pin allocation (I2C1, USART1 and any control lines you need), the logic-level "
             "compatibility of both links (with the datasheet thresholds), the low-power state of the STM32 and of the ESP32, and a sleep-current table with the "
             "total compared to the budget. " + FMT_PLAN),
    "human_policy": {"approval": "approve", "choice": {"prefer": "level shifter"}, "clarify": {}, "max_answers": 3},
    "expected": {
        "checklist": [steps(), pll(12e6, 160e6), BOOST, FLASH_WS,
                      level_shifter("level_shifter", "gas sensor (1.8 V) I2C lines"),
                      no_direct_near("no_direct_sensor", ["sensor", "gas"], "1.8 V gas sensor"),
                      compat("esp_link_compat", "STM32-ESP32 UART link", extra=ESP_COMPAT_EXTRA), ESP32_OFF, LOW_POWER, sleep_total(3.0, 7.0), NO_BOOST_CLAIM],
    },
    "graders": ["checklist", "clarify"],
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("ahb_div2"), ev("standby_rtc"), ev("stop1"), ev("stm_vih"),
                 ev("stm_voh"), ev("esp_dc"), ev("esp_modes"), ev("esp_chip_pu"), ev("osc_pins"),
                 ev("pins_pa", "PA15 JTDI TIM2_CH1 TIM8_CH1 - I2C1_SCL", "PA9 - - I2C3_SMBA - I2C2_SCL I2S3_MCK TIM1_CH2 USART1_TX"),
                 ev("pins_pb", "PB7 - TIM17_CH1N TIM4_CH2 I2C4_SDA I2C1_SDA")],
    "reference_calc": (
        "Đủ thông tin (đối chứng của C5-005/C5-006). PLL HSE 12 MHz → 160 MHz: duy nhất M = 3 (4 MHz), N = 80 (VCO 320), R = 2 (c5_handcalc.py). 160 > 150 "
        "⇒ boost (RM Table 38 p.232), AHB/2 (p.233), 4 WS (RM Table 9 p.98: 136 < 160 ≤ 170). Cảm biến 1,8 V < VIH 2,31 V ⇒ level shifter. ESP32 3,3 V như C5-001. "
        "Ngủ: Standby + RTC LSE 0,655 + ESP32 power off 1 (ESP32 DS p.30) + cảm biến 1,5 + LDO 1 = 4,155 µA ≤ 8; Deep-sleep ⇒ 13,16 µA, Hibernation ⇒ 8,16 µA > 8 "
        "⇒ phải tắt hẳn ESP32 qua CHIP_PU (≤ 0,6 V, ESP32 DS p.52)."),
    "variants": [
        {"name": "esp32_left_in_deep_sleep", "must_fail": ["esp32_off", "sleep_total"],
         "edits": [(T011_PIN_CHIPPU, ""), (T011_CHIPPU_SENT, ""),
                   (T011_STEP5, "5. **Low-power states.** The ESP32 waits in Deep-sleep with the RTC timer and RTC memory on (10 µA, ESP32 datasheet Table 4-2) and wakes itself every 30 minutes. The STM32 uses Standby with the RTC on the LSE (0.655 µA typical at 3 V, DS12288 Table 32) and an 1800 s RTC wake-up."),
                   (T011_ROW_ESP, "   - ESP32, Deep-sleep: 10 µA"),
                   (T011_TOTAL, "   Total sleep current = 0.655 + 10 + 1.5 + 1 = 13.16 µA, slightly above the 8 µA budget but acceptable")]},
        {"name": "sensor_wired_directly", "must_fail": ["level_shifter", "no_direct_sensor"],
         "edits": [(T011_STEP3, "3. **Gas-sensor interface (1.8 V).** The STM32 I2C pins are open-drain, so the gas sensor can be wired directly to PA15/PB7 with pull-ups to 1.8 V."),
                   (T011_TOTAL_END, " (about 3.8 µA of margin).")]},
    ],
    "ref": T011_REF,
}

# =====================================================================================================================  C5-012
T012_STEP3 = "3. **nRF52840 I/O level.** The nRF52840 is supplied on VDDH, i.e. High Voltage mode, where the GPIO high level equals the REG0 output set by UICR.REGOUT0 (nRF52840 PS); an erased REGOUT0 (VOUT = 7) selects the 1.8 V default. So the nRF52840 GPIOs swing 0-1.8 V while the STM32 GPIOs swing 0-3.3 V."
T012_STEP4 = "4. **Logic-level check.** STM32 -> nRF52840 (TX, RTS): a 3.3 V high exceeds the nRF52840 absolute maximum of VDD + 0.3 = 2.1 V. nRF52840 -> STM32 (RX, CTS, wake-up): a 1.8 V high is below the STM32 VIH minimum of 0.7 x 3.3 = 2.31 V. All five signals therefore go through a level shifter: a dual-supply translator with VCCA = 1.8 V from the nRF52840 VDD pin and VCCB = 3.3 V, 1 Mbit/s capable, with TX/RTS translated 3.3 V -> 1.8 V and RX/CTS/wake-up translated 1.8 V -> 3.3 V."
T012_STEP5 = "5. **Why REGOUT0 = 3.3 V is not the fix.** REG0 needs VDDH at least 0.3 V above its output, so a 3.3 V setting needs VDDH >= 3.6 V; the Li-ion cell goes down to 3.0 V, so the nRF52840 supply would drop below 3.3 V late in the discharge while the STM32 keeps driving 3.3 V."
T012_STEP6 = "6. **STM32 idle mode and current.** Standby keeps SRAM2 when PWR_CR3.RRS = 1 and wakes on WKUP1 (PA0) without the RTC; Shutdown would lose SRAM2 and Stop 1 draws 80.5 µA. At 3 V and 25 °C: Standby without RTC 0.13 µA + SRAM2 retention 0.305 µA (DS12288 Table 32). Total STM32 idle current = 0.13 + 0.305 = 0.44 µA, within the 2 µA allowance"
T012_STEP6_END = " (the translator's VCCB leakage must fit in the remaining 1.5 µA)."

T012_REF = ("Here is the plan.\n\n"
            "1. **Clock tree (8 MHz HSE -> 160 MHz).** PLLSRC = HSE; PLLM = 2 gives 8 MHz / 2 = 4 MHz (PLL input 2.66-16 MHz), PLLN = 80 gives a 320 MHz VCO "
            "(96-344 MHz) and PLLR = 2 gives SYSCLK = 160 MHz (DS12288 Table 46). 160 MHz needs Range 1 boost mode (clear PWR_CR5.R1MODE, AHB /2 during the switch) "
            "and LATENCY = 4 wait states (RM0440 Table 9).\n"
            "2. **Pin allocation.** USART1 with flow control: PA9 = TX, PA10 = RX, PA12 = RTS, PA11 = CTS (all AF7, DS12288 Table 13); PA0 = WKUP1 for the wake-up "
            "line from the nRF52840; PF0/PF1 = OSC_IN/OSC_OUT for the 8 MHz crystal.\n"
            + T012_STEP3 + "\n" + T012_STEP4 + "\n" + T012_STEP5 + "\n" + T012_STEP6 + T012_STEP6_END + "\n")

T012 = {
    "id": "C5-012", "split": "test", "difficulty": "medium", "chips": ["stm32g474", "nrf52840"],
    "tags": ["system_goal", "complete_info", "plan", "pll", "hse", "logic_level", "level_shift", "nrf_vddh", "current_budget"],
    "user": ("Help me plan the interface between the two chips of an asset tracker. An STM32G474 (VDD = 3.3 V from an LDO, 8 MHz crystal on its HSE pins) must "
             "run SYSCLK at 160 MHz from the main PLL fed by HSE. It exchanges data with an nRF52840 (aQFN73 package) over USART1 with hardware flow control "
             "(RTS/CTS) at 1 Mbaud. The nRF52840 is powered directly from the single Li-ion cell (3.0 V to 4.2 V) on its VDDH pin, and its UICR.REGOUT0 register "
             "is left erased (never programmed). When idle, the STM32 must sit in its lowest-power mode that keeps the SRAM2 content, without RTC, and be woken by "
             "the nRF52840 through a wake-up pin; the STM32 itself may draw at most 2 µA in this state. The plan must cover the clock tree with the PLL M/N/R values, "
             "the voltage-scaling mode and the Flash wait states, the pin allocation (USART1 TX/RX/RTS/CTS and the wake-up line), the logic-level compatibility "
             "of the link with the datasheet thresholds, whether anything has to be fitted or configured on the board, and the STM32 idle current. " + FMT_PLAN),
    "human_policy": {"approval": "approve", "choice": {"prefer": "level shifter"}, "clarify": {}, "max_answers": 3},
    "expected": {
        "checklist": [steps(), pll(8e6, 160e6), BOOST, FLASH_WS,
                      {"id": "regout0", "type": "mentions", "any_of": [r"REGOUT0", r"\bREG0\b"],
                       "desc": "the nRF52840 GPIO level in High Voltage mode follows REG0/UICR.REGOUT0"},
                      {"id": "nrf_io_1v8", "type": "mentions", "any_of": [r"\b1\.8\s*V\b"],
                       "desc": "the erased REGOUT0 gives the 1.8 V default I/O level"},
                      level_shifter("level_shifter", "STM32 (3.3 V) - nRF52840 (1.8 V) link"),
                      no_direct_generic("no_direct", "STM32 - nRF52840 link"),
                      {"id": "standby", "type": "mentions", "any_of": [r"\bstandby\b"],
                       "desc": "Standby with SRAM2 retention (RRS) is the lowest mode that keeps SRAM2 (Shutdown loses it, Stop 1 is ~80 uA)"},
                      NOT_SHUTDOWN, sleep_total(0.3, 1.5, "STM32 idle current", extra=[IDLE_CURRENT_RX]), NO_BOOST_CLAIM],
    },
    "graders": ["checklist", "clarify"],
    "evidence": [ev("hse_range"), ev("pll_limits"), ev("pllm"), ev("pllr"), ev("flash_ws"), ev("boost"), ev("ahb_div2"), ev("standby"), ev("standby_rtc"),
                 ev("rrs"), ev("stop1"), ev("stm_vih"), ev("wkup1"), ev("nrf_regout0"), ev("nrf_gpio_hv"), ev("nrf_reg0_drop"), ev("nrf_absmax"), ev("osc_pins"),
                 ev("pins_pa", "PA9 - - I2C3_SMBA - I2C2_SCL I2S3_MCK TIM1_CH2 USART1_TX", "PA10 - TIM17_BKIN - USB_CRS_SYNC I2C2_SMBA SPI2_MISO TIM1_CH3 USART1_RX",
                    "PA11 - - - - - SPI2_MOSI/I2S2_SD TIM1_CH1N USART1_CTS", "PA12 - TIM16_CH1 - - - I2SCKIN TIM1_CH2N USART1_RTS_DE")],
    "reference_calc": (
        "Đủ thông tin (đối chứng của C5-004). PLL 8 MHz → 160 MHz: (M,N,R) = (1,40,2), (2,80,2), (3,120,2) hợp lệ; chọn M = 2, N = 80. 160 > 150 ⇒ boost + AHB/2, 4 WS. "
        "nRF HV mode, REGOUT0 xoá ⇒ 1,8 V (PS p.63, p.82); STM32 → nRF: 3,3 V > VDD + 0,3 = 2,1 V (PS p.972); nRF → STM32: 1,8 V < VIH 2,31 V (DS p.128) ⇒ level "
        "shifter cho 5 tín hiệu (TX, RTS, RX, CTS, wake). REGOUT0 = 3,3 V cần VDDH ≥ 3,6 V (PS p.155) ⇒ không đủ khi Li-ion 3,0 V. STM32 nghỉ: Standby không RTC "
        "0,13 µA + giữ SRAM2 0,305 µA (DS Table 32 p.103-104; RRS RM p.255) = 0,435 µA ≤ 2 µA; Stop 1 80,5 µA; Shutdown mất SRAM2. Chân: PA9/PA10/PA12/PA11 AF7 "
        "USART1 TX/RX/RTS_DE/CTS (DS p.73), PA0 = WKUP1 (DS p.59)."),
    "variants": [
        {"name": "assumed_nrf_at_3v3", "must_fail": ["regout0", "nrf_io_1v8", "level_shifter", "no_direct"],
         "edits": [(T012_STEP3, "3. **nRF52840 I/O level.** The nRF52840 VDD range is 1.7-3.6 V and I assume it runs at 3.3 V like the STM32."),
                   (T012_STEP4, "4. **Logic-level check.** The nRF52840 VIH of 0.7 x 3.3 = 2.31 V is below the STM32 VOH of 2.9 V and the STM32 VIH of 2.31 V is below the nRF52840 VOH of 2.9 V, so the signals are directly compatible and wired directly."),
                   (T012_STEP5, "5. **Board.** No extra parts are needed between the two chips."),
                   (T012_STEP6_END, ".")]},
        {"name": "stop1_idle", "must_fail": ["standby", "sleep_total"],
         "edits": [(T012_STEP6 + T012_STEP6_END, "6. **STM32 idle mode and current.** Stop 1 keeps all SRAM and registers and wakes on an EXTI line from the nRF52840: 80.5 µA typical at 3 V (DS12288 Table 30). Total STM32 idle current = 80.5 µA.")]},
    ],
    "ref": T012_REF,
}

TASKS_B = [T007, T008, T009, T010, T011, T012]
