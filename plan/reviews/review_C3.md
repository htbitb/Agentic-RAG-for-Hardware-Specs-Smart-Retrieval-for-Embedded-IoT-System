# Review C3 (independent)

Reviewer: independent agent with fresh context. Read-only except this file. Sources: RM0440 page text (`corpus/.cache/pages/STM32G474_RM0440.jsonl`), DS12288 page text (`..._Datasheet.jsonl`) and the vendor SVD. Grader runs used `eval/graders/functional_sim.grade` (vendored hwmodel). `python -m eval.tools.verify_tasks --categories C3` printed "20 task kiểm tra, 0 vấn đề". I also checked mechanically that every `evidence.contains` snippet appears on its cited page: all 20 tasks pass that check. Test scripts are in the scratchpad (`h.py`, `h2.py`, `t_*.py`); they are not part of the repo.

## Summary

| Verdict | Count | Tasks |
|---|---|---|
| OK | 10 | C3-001, 002, 003, 004, 005, 006, 007, 008, 010, 019 |
| FIX | 9 | C3-009, 011, 012, 013, 014, 015, 016, 018, 020 |
| AMBIGUOUS | 1 | C3-017 |

All hand calculations recompute correctly: PSC/ARR/CCR, BRR, TIMINGR, PLL M/N/R, VCO and wait states. Every AF number matches DS12288 Table 13 (p.73–75). Every RCC/PWR bit position matches the SVD. Every wrong variant is genuinely wrong on hardware, and each one is reported under the stated failure kind. The problems are elsewhere. They are listed below from most to least serious.

1. **False pass (simulator): PLLREN is not modelled.** C3-018, C3-019 and C3-020 are affected. A clock-tree answer that never sets `RCC_PLLCFGR.PLLREN` still passes. I tested this on C3-018 by removing `| RCC_PLLCFGR_PLLREN`: the result was `pass=True`. The RM says PLLREN is the "PLL “R” clock output enable … (used as system clock)" (p.292). The PLL procedure also requires "5. Enable the desired PLL outputs by configuring PLLPEN, PLLQEN, PLLREN" (p.278). Forgetting PLLREN is a classic mistake, and with the R output disabled the system cannot run from PLLCLK.
2. **False pass (spec/grader): UART prompt requirements are not checked.** C3-011 to C3-014 are affected. All of these pass:
   - `M0` (9-bit words), `PCE` (parity) or `CR2.STOP = 2 stop bits`, although the prompt asks for 8N1.
   - `TE` only, although the prompt says "enable both the transmitter and the receiver".
   - `BRR` written after `UE = 1`. RM p.1755 says USART_BRR "can only be written when the USART is disabled (UE = 0)", but the simulator only issues a warning.
   - C3-013: `OVER8 = 1` passes although the prompt says "oversampling by 16".
   - C3-014: `USART1SEL = SYSCLK` with BRR = 1476 passes although the prompt says "Keep the default USART1 kernel clock source". This bypasses the trap the task is built around.
3. **False pass (spec): the I2C kernel-clock requirement is not checked.** C3-016 and C3-017 are affected. In C3-016, I removed the I2C3SEL line and retuned TIMINGR for PCLK1 = 85 MHz (SCLH = 22, SCLL = 29): the result was `pass=True`, although the prompt says "The I2C3 kernel clock must be SYSCLK (170 MHz), selected with RCC_CCIPR.I2C3SEL". Writing TIMINGR after `PE = 1` also passes, although RM p.1681 says "This register must be configured when the I2C peripheral is disabled (PE = 0)."
4. **Fairness: C3-017 rejects the RM's own setting.** RM Table 360 (p.1657) gives 0x10320309 for fI2CCLK = 16 MHz, Fm 400 kHz, and ST labels it "~2.5 µs". Under the task's minimum-tSYNC definition this setting gives 500 kHz, which is +25 %, so it fails ±15 %. A RAG system that copies the official table will fail.
5. **The I2C reference solutions violate RM timing conditions.** RM p.1631–1632 sets lower bounds on SCLDEL and SDADEL, with tr, tf and tSU;DAT taken from Table 356:
   - C3-016 (tPRESC = 94.1 ns): SCLDEL must be ≥ 13, but the reference uses 4. SDADEL must be ≥ 3, but the reference uses 2.
   - C3-017 (tPRESC = 62.5 ns): SCLDEL must be ≥ 6, but the reference uses 4.

   The grader does not model these fields, but the references are presented as hardware-correct.
6. **False fail (grader): extra enabled timer channels fail the task.** Setting CCxE (or CCxNE) on a channel that the spec does not mention, with no pin routed, fails the whole task with `sim_violation:SIM-GPIO-AF` and/or `SIM-TIM-OCM`. Tested cases:
   - C3-001 with `CC2E` or `CC1NE` added.
   - C3-006 with `CC1NE` added.
   - C3-010 with a generic init that sets `CC3E | CC4E`.

   On real hardware these settings are harmless.
7. **Minor issues in the clock-tree references (C3-018, C3-020).**
   - No delay after `PWREN` before accessing `PWR->CR5`. RM p.285: "Caution: Just after enabling the clock for a peripheral, software must wait for a delay before accessing the peripheral registers."
   - `HPRE` is restored without the "Wait at least 1 µs" required by RM p.280.
8. **Wrong page citations in the hand calculations.**
   - TIMINGR is on p.1681, not p.1672 (C3-015, 016, 017).
   - I2C3SEL is on p.323, not p.324 (C3-016).
   - For TIM4 channel 3 the TIM2–5 section applies: OC3M on p.1384 and CC3E on p.1385, not p.1257 and p.1260 (C3-008).

Two smaller points. C3-009 does not check that PA8 is left unused. Every task's provenance says "chưa review độc lập" while `review_status: verified`.

---

## Per task

Common to all prompts: the D20 boilerplate is present. It asks for the CMSIS style, forbids HAL, LL and `SystemCoreClock`, allows busy-waiting, and asks for one complete C block with `while (1)`. No prompt leaks a register value.

The initial-state sentences match `PRESETS` in `agent/hwmodel/sim.py`:

- `_PLL170` clears R1MODE, sets LATENCY = 4, PLLM code 3, N = 85, R = /2, PLLREN, PLLON and SW = PLL. The `apb2_div2` and `apb1_div2` presets add PPRE2 or PPRE1 = 100.
- The reset preset is consistent with RM: FLASH_ACR = 0x0004 0601, i.e. 1 WS (p.130); PWR_CR5 = 0x0000 0100, i.e. R1MODE = 1, normal mode (p.267); RCC_CCIPR = 0 (p.322).

Common PWM facts:

- Formula: "tim_ocxref is high as long as TIMx_CNT < TIMx_CCRx" (p.1179).
- Timer clock rule: "If the APB prescaler equals 1, the timer clock frequencies are set to the same frequency of the APB domain, otherwise, they are set to twice (×2)" (p.281).
- MOE description on p.1270 and Table 282 on p.1261 (TIM1/8/20); TIM15 MOE on p.1474; TIM16/17 MOE on p.1499.

Two alternative solutions were run for every PWM task (C3-001…010), and every one passed:

- **No preload variant:** removes OCxPE, ARPE and UG.
- **Different PSC/ARR split variant:**

  | Task | PSC |
  |---|---|
  | C3-001 | 1 |
  | C3-003 | 3 |
  | C3-004 | 9 |
  | C3-007 | 3 |
  | C3-008 | 1 |

### C3-001 — OK
- **Prompt.** Clear. The initial state matches the `sysclk_170mhz_pll_hsi16_apb_div1` preset. The spec is feasible.
- **Hand calculation.** 170e6 / 20e3 = 8500 ⇒ PSC 0, ARR 8499; CCR1 = 2125 (25.00 %). PA8 AF6 = TIM1_CH1: DS p.73 lists "PA8 MCO - I2C3_SCL - I2C2_SDA I2S2_MCK TIM1_CH1", which is AF0…AF6. TIM1EN is APB2ENR bit 11 and GPIOAEN is AHB2ENR bit 0 (SVD).
- **Reference solution.** Correct. MOE is set, RMW is used on MODER and AFR, and UG is issued before CEN.
- **Wrong variants.** All genuine.
  - `forgot_moe`: p.1270.
  - `wrong_af2`: PA8 AF2 is I2C3_SCL.
  - `psc_off_by_one`: 10 kHz.
  - `no_tim1_clock`.
  - `afr_shift_by_four`: PA8 stays AF0, which is MCO.
- **Alternative correct solutions tried.** All passed:
  - PSC = 16, ARR = 499, CCR = 125, with whole-register writes, no preload, `(void)RCC->APB2ENR` and `3U << 16` style masks.
  - `MODIFY_REG`, `SET_BIT` and a `gpio_af()` helper with `#define` arithmetic.
  - PSC = 9, ARR = 849, CCR = 212, giving 24.94 %.
  - `BDTR.AOE` instead of MOE.
  - Timer configured before GPIO, with CEN before MOE.
  - A temporary variable for RMW, a separate init function, `void main` with `for(;;)`, DIR = 1 (down-counting), and writes to CR2/DIER/SMCR/DCR = 0.
- **Plausible wrong answers.**
  - MOE written before TIM1EN: fails (CLK-GATE and MOE).
  - `CCMR1 = TIM_CCMR1_OC1M`, i.e. OC1M = 1111: fails, but as `unmodeled` rather than a mode error. This is acceptable.
  - CC1P = 1: fails `wrong_duty`.
- **Fairness.**
  - Extra unrouted channel enabled (`CC2E` or `CC1NE`): fails with `sim_violation` (Simulator issue S3).
  - `if (!(TIM1->CR1 & TIM_CR1_CEN)) ...` and `CCR1 = 0.25f*(TIM1->ARR+1)`: fail as `unsupported_construct`. This is a parser limitation; see the cross-cutting notes.

### C3-002 — OK
- **Prompt.** States APB2 = /2 and PCLK2 = 85 MHz explicitly. Matches the `apb2_div2` preset.
- **Hand calculation.** TIM1CLK = 2 × 85 = 170 MHz (p.281). PSC 0, ARR 8499, CCR1 2125. The forgot-×2 figure of 40 kHz is correct.
- **Reference solution.** Correct (identical to C3-001).
- **Wrong variants.** `forgot_x2_rule` (ARR 4249 ⇒ 40 kHz) and `forgot_moe`: both genuine.
- **Alternatives.**
  - PSC = 1, ARR = 4249: passes.
  - Clearing PPRE2 to /1 first and keeping 8499: passes. This is acceptable, since the prompt does not forbid changing the bus prescaler.

### C3-003 — OK
- **Hand calculation.** 170 000 ticks. TIM2 is 32-bit: RM p.1388 gives "TIMx_ARR (x = 2, 5) Reset value: 0xFFFF FFFF" and p.1389 "ARR[31:0]". CCR1 = 85 000. PA0 AF1 = TIM2_CH1 (DS p.73).
- **Reference solution.** Correct. TIM2 has no BDTR.
- **Wrong variants.** `wrong_timer_clock_bit` (TIM3EN), `factor_ten_error` (10 kHz) and `forgot_cen`: all genuine.
- **Alternatives.** PSC = 3, and the no-preload variant: both pass.

### C3-004 — OK
- **Hand calculation.**
  - 340 000 = 2⁵·5⁴·17. PSC + 1 = 8 gives ARR + 1 = 42 500 and CCR1 = 12 750 (30 %).
  - The "smallest divisor" reasoning is unnecessary but harmless; non-divisors also land within ±1 %.
  - TIM3 is 16-bit: ARR (x = 3, 4) reset is 0x0000 FFFF (p.1388).
  - PA6: AF1 is TIM16_CH1 and AF2 is TIM3_CH1 (DS p.73).
- **Reference solution.** Correct.
- **Wrong variants.** All genuine.
  - `no_prescaler_16bit_overflow`: SIM-TIM-RANGE is the right kind.
  - `arr_clamped_to_65535`: 2594 Hz.
  - `af1_is_tim16`.
- **Alternatives.** PSC = 9 (ARR 33 999), and no preload: both pass.

### C3-005 — OK
- **Hand calculation.** TIM8CLK = 170 MHz (×2 rule). 17 000 ticks, CCR1 = 6800. PC6 AF4 = TIM8_CH1: DS p.75 "PC6 - - TIM3_CH1 HRTIM1_EEV10 TIM8_CH1". GPIOCEN is bit 2 and TIM8EN is bit 13 (SVD).
- **Reference solution.** Correct; MOE is set.
- **Wrong variants.** `forgot_moe`, `enabled_tim1_clock_instead` and `forgot_x2_rule`: all genuine.
- **Alternatives.** Different split and no preload: both pass.

### C3-006 — OK
- **Hand calculation.** 34 000 ticks, CCR1 = 20 400. PA2 AF9 = TIM15_CH1 (DS p.73: "… USART2_TX COMP2_OUT TIM15_CH1" in AF7/AF8/AF9). TIM15 MOE is on p.1474.
- **Wrong variants.** `forgot_moe_on_tim15` is genuine and is the key point of the task. `af1_instead_of_af9` is genuine (PA2 AF1 is TIM2_CH3).
- **Alternatives.** Pass. The exception is enabling `CC1NE` as well, which fails (Simulator issue S3).

### C3-007 — OK
- **Hand calculation.** 85 000 > 65 536 ⇒ PSC = 1, ARR = 42 499, CCR1 = 31 875 (75 %). TIM16 non-dither ARR: "The register holds the auto-reload value in ARR[15:0]. The ARR[19:16] bits are reset." (p.1496). TIM16 MOE is on p.1499.
- **Wrong variants.** `no_prescaler_16bit_overflow`, `duty_is_low_time` (25 %) and `forgot_moe`: all genuine.
- **Alternatives.** PSC = 3, and no preload: both pass.

### C3-008 — OK (citation nit)
- **Hand calculation.** 3400 ticks, CCR3 = 340. PB8 AF2 = TIM4_CH3 (DS p.74: "PB8 - TIM16_CH1 TIM4_CH3 SAI1_CK1 I2C1_SCL").
- **Reference solution.** Correct. It uses CCMR2 for OC3M and OC3PE, and CC3E is CCER bit 8.
- **Wrong variants.** `ccmr1_pwm_mode_on_channel_1_bits` (SIM-TIM-OCM on channel 3) and `forgot_cc3e`: both genuine.
- **Proposed fix.** In `reference_calc`, replace "(RM p.1257, p.1260)" with "(RM p.1384 OC3M, p.1385 CC3E — TIM2–5 section)". The pages cited now belong to the TIM1/8/20 chapter, and CC3E there is on p.1259, not p.1260.

### C3-009 — FIX
- **Prompt.** Clear: "PC0 … (PA8 … must not be used)".
- **Hand calculation.** PC0 AF2 = TIM1_CH1 (DS p.75: "PC0 - LPTIM1_IN1 TIM1_CH1"). Timer values as in C3-001.
- **Reference solution.** Correct.
- **Wrong variants.** `still_on_pa8` (wrong_pin) and `af6_copied_from_pa8` (PC0 AF6 is "-"): both genuine.
- **False pass.** An answer that routes TIM1_CH1 to both PA8 (AF6) and PC0 (AF2) passes (`pass=True`), although the prompt forbids using PA8.
- **Proposed fix.** Add a negative constraint, for example `{"type": "pin_unused", "pin": "PA8"}`, or a `forbid_pins: [PA8]` field on the pwm item, checked against `effects`, which already carries pwm/pin_af effects for PA8. If the grader cannot be extended, change the prompt wording to "PA8 is used by another function and must be left in its reset state", so a reviewer can at least see the intent.

### C3-010 — OK
- **Hand calculation.** CCR1 = 2125 and CCR2 = 6375 with a shared ARR of 8499. PA9 AF6 = TIM1_CH2 (DS p.73). OC2M is at bits [14:12] plus bit 24, and OC2PE is bit 11.
- **Wrong variants.** `forgot_cc2e`, `pa9_not_alternate_function` and `same_duty_on_both`: all genuine.
- **Alternatives.**
  - A single CCMR1 write for both channels: passes.
  - A generic init that also sets `CC3E | CC4E`: fails with SIM-GPIO-AF and SIM-TIM-OCM for CH3 (S3).

### C3-011 — FIX
- **Prompt.** Clear: 8N1, TE and RE, ±2 %.
- **Hand calculation.** USART1 kernel = PCLK2 (RCC_CCIPR USART1SEL = 00 "PCLK", p.324). 170e6 / 115200 = 1475.69 ⇒ BRR 1476 ⇒ 115 176 baud (−0.021 %). "When OVER8 = 0, BRR = USARTDIV." (p.1708). PA9 and PA10 are AF7 (DS p.73).
- **Reference solution.** Correct. BRR is written before CR1 = UE | TE | RE.
- **Wrong variants.**
  - `forgot_usart_clock`, `forgot_ue` and `assumed_16mhz`: genuine.
  - `wrong_af`: PA9 AF4 is I2C2_SCL, so the result is wrong_pin. Genuine.
- **Alternatives (all pass).**
  - BRR = 0x5C3 with CR2/CR3/PRESC = 0, CR1 set step by step, waits on TEACK/REACK, and a TDR loop inside `while (1)`.
  - BRR as a rounding expression.
  - USART1SEL = SYSCLK with BRR 1476.
  - USART1SEL = HSI16 with BRR 139.
  - Correct OVER8 = 1 encoding.
- **False passes.** `CR1 |= M0` (9-bit), `PCE`, `CR2 = STOP_1` (2 stop bits), TE only, and BRR written after UE = 1 (RM p.1755).
- **Proposed fix.**
  - Extend the uart spec to `{"type":"uart", …, "frame":"8N1", "te":true, "re":true}`.
  - Have the grader read M0 (bit 12), M1 (bit 28), PCE (bit 10) and CR2.STOP[13:12]; the `te`/`re` flags are already present in the effect.
  - Promote `SIM-USART-BRR-UE` to an error, or make it a grader failure `wrong_sequence`.

  This applies to C3-011…014.

### C3-012 — FIX (same UART spec gap as C3-011)
- **Prompt.** The reset state is stated accurately.
- **Hand calculation.** 16e6 / 9600 = 1666.67 ⇒ 1667 ⇒ 9598.1 baud. PA2 and PA3 are AF7 (DS p.73). USART2EN is APB1ENR1 bit 17 (SVD).
- **Reference solution.** Correct.
- **Wrong variants.** `assumed_170mhz`, `forgot_gpio_clock` and `wrong_apb_register`: all genuine.
- **Alternatives.** BRR 0x683 and BRR 1666: both pass. TX on PA14 (also USART2_TX, AF7) fails with wrong_pin, which is correct.

### C3-013 — FIX
- **Hand calculation.** 170e6 / 921600 = 184.46 ⇒ 184 ⇒ 923 913 baud (+0.25 %). BRR 185 also passes (−0.29 %). PB10 and PB11 are AF7 (DS p.74). USART3EN is bit 18.
- **Reference solution.** Correct.
- **Wrong variants.** All genuine.
  - `oversampling8_with_unshifted_brr`: "BRR[3] must be kept cleared" (p.1708).
  - `baud_of_115200`.
  - `tx_on_wrong_pin_af`: PB10 AF1 is TIM2_CH3.
- **False pass.** OVER8 = 1 with a correctly encoded BRR passes, although the prompt demands "oversampling by 16".
- **Proposed fix.** Add `"over8": 0` to the spec and check it (the effect already contains `over8`), plus the frame/TE/RE check from C3-011.

### C3-014 — FIX
- **Hand calculation.** PCLK2 = 85 MHz with no ×2 for USART (p.281 applies only to "timer clock frequencies (tim_ker_ck)"). 85e6 / 115200 = 737.85 ⇒ 738 ⇒ 115 176 baud. The ×2-misapplied value of 1476 gives 57 588 baud: correct.
- **Wrong variants.** `x2_rule_misapplied` and `forgot_usart_clock`: both genuine.
- **False pass.** `RCC->CCIPR |= RCC_CCIPR_USART1SEL_0` (SYSCLK) with BRR = 1476 passes. The prompt says "Keep the default USART1 kernel clock source", so the task's main trap can be bypassed.
- **Proposed fix.** Add `"kernel_source": "PCLK2"` (or `"kernel_clk_hz": 85000000`) to the spec and check it against `effect.kernel_source`/`kernel_clk_hz`, which the simulator already reports.

### C3-015 — FIX (minor)
- **Prompt.** Clear. It defines fSCL with tSYNC at its minimum of 4·tI2CCLK and states the default kernel clock (PCLK1).
- **Hand calculation.** TIMINGR = 0x30420F13 is exactly the RM Table 360 Sm 100 kHz column (p.1657). tSCL = 5.0 + 4.0 + 0.25 = 9.25 µs ⇒ 108.1 kHz (+8.1 %, inside ±10 %). PB8 and PB9 are AF4 = I2C1_SCL/SDA (DS p.74). I2C1EN is bit 21.
- **Reference solution.** Correct and RM-compliant: SCLDEL 4 ⇒ 1250 ns ≥ tr + tSU;DAT = 1250 ns.
- **Wrong variants.**
  - `forgot_pe`, `push_pull_pins` and `forgot_i2c_clock`: genuine.
  - `timing_for_400khz` (PRESC 3→1): genuine, but it gives 210.5 kHz, not 400 kHz. Consider renaming it to `presc_too_small`.
- **Alternatives (all pass).**
  - 0x00503D58 (103.2 kHz).
  - PRESC 0 with SCLL = SCLH = 79 (97.6 kHz).
  - Pull-ups, OSPEEDR, PE cleared first, CR1 written whole.
  - DNF = 2 (105.3 kHz).
  - An additional CR2 address write.
- **False pass.** TIMINGR written after PE = 1 passes (RM p.1681 note).
- **Proposed fix.** In `reference_calc`, change "(p.1672)" to "(p.1681)". The same fix applies to C3-016 and C3-017. Optionally add a simulator check for TIMINGR written while PE = 1.

### C3-016 — FIX
- **Prompt.** Clear. The initial state matches the `apb1_div2` preset.
- **Hand calculation.**
  - Verified: tPRESC = 16/170 MHz = 94.12 ns, and (60 + 46) × 94.12 + 4 × 5.88 = 10 000 ns ⇒ 100.00 kHz. tLOW = 5.65 µs (≥ 4.7) and tHIGH = 4.33 µs (≥ 4.0).
  - Without I2C3SEL the kernel is 85 MHz, giving 50 kHz: correct.
  - PA8 AF2 = I2C3_SCL (DS p.73) and PC9 AF8 = I2C3_SDA (DS p.75). I2C3SEL is RCC_CCIPR[17:16] with 01 = SYSCLK, documented on **p.323** (the task says p.324).
- **Reference solution.** SCLDEL and SDADEL were copied from the 16 MHz table but are not scaled to tPRESC = 94.1 ns. RM p.1632 requires "{[tr(max) + tSU;DAT(min)] / [(PRESC+1) x tI2CCLK]} − 1 ≤ SCLDEL", and RM p.1631 requires "{tf(max) + tHD;DAT(min) − tAF(min) − [(DNF+3) x tI2CCLK]} / {(PRESC+1) x tI2CCLK} ≤ SDADEL". With Sm limits from Table 356 (tr = 1000 ns, tf = 300 ns, tSU;DAT = 250 ns) and tAF(min) = 50 ns (DS p.171), this gives SCLDEL ≥ 12.3 ⇒ **13** and SDADEL ≥ 2.47 ⇒ **3**. The reference uses 4 and 2.
- **Wrong variants.** `forgot_kernel_clock_selection` (50 kHz) and `sda_af2_instead_of_af8` (PC9 AF2 is TIM3_CH4): both genuine.
- **Alternatives (all pass).** RM-compliant SCLDEL 13 / SDADEL 3, a whole-register CCIPR write, and a guessed CubeMX-style value.
- **False pass.** I2C3SEL left at PCLK1 with TIMINGR retuned for 85 MHz passes (99.8 kHz).
- **Proposed fix.**
  - Reference: `(13U << I2C_TIMINGR_SCLDEL_Pos) | (3U << I2C_TIMINGR_SDADEL_Pos)`. The code comment and `reference_calc` should state the two RM inequalities.
  - Spec: add `"kernel_clk_hz": 170000000` (or `"kernel_source": "SYSCLK"`) and check it against `effect.i2cclk_hz`.
  - Citations: p.324 → p.323 for I2C3SEL, and p.1672 → p.1681.

### C3-017 — AMBIGUOUS
- **Prompt.** Internally consistent: fSCL is defined with the minimum tSYNC, the tolerance is ±15 %, and the kernel clock is HSI16.
- **Hand calculation.** Verified: (24 + 12) × 62.5 + 250 = 2500 ns ⇒ 400 kHz. tLOW = 1.5 µs (≥ 1.3) and tHIGH = 0.75 µs (≥ 0.6) (Table 358, p.1647). I2C1SEL = 10 is HSI16 (p.324).
- **Reference solution.** SCLDEL = 4 gives 312.5 ns, but RM p.1632 with Fm tr = 300 ns and tSU;DAT = 100 ns requires SCLDEL ≥ 5.4 ⇒ **6**. SDADEL = 1 is within the bounds 1.0 ≤ SDADEL ≤ 1.44 and is fine.
- **Wrong variants.** `forgot_kernel_clock_selection` (≈ 4.25 MHz) and `pclk1_assumed_for_the_formula` (800 kHz): both genuine.
- **Fairness problem.** RM Table 360 (p.1657), "Timing settings for fI2CCLK of 16 MHz", gives PRESC 1, SCLL 0x9, SCLH 0x3, SDADEL 2, SCLDEL 3 for Fm 400 kHz, i.e. 0x10320309, with "tSCL ~2.5 µs" and the note "Example with tSYNC1 + tSYNC2 = 750 ns". Under the task definition this setting gives 1/(14 × 125 ns + 250 ns) = 500 kHz ⇒ `wrong_scl` (+25 %). A system that retrieves and uses ST's official value fails. On real hardware the reference (≈ 333 kHz with tSYNC = 750 ns) is arguably *less* accurate than the RM value. The task is consistent only because of its artificial definition.
- **False pass.** As in C3-016, the kernel source is not checked. PCLK1 = 170 MHz with matching TIMINGR would pass.
- **Proposed fix (choose one).**
  - (a) Set `tol_pct: 30` and the prompt text to "±30 %". Both wrong variants still fail, and 0x10320309 (+25 %) passes.
  - (b) Grade a band: pass if 400 kHz lies between f(tSYNC = 4·tI2CCLK) and f(tSYNC = 4·tI2CCLK + 500 ns). This requires a grader change.

  In both cases, also fix SCLDEL to 6 in the reference, add the kernel-clock check and change p.1672 to p.1681.

### C3-018 — FIX (minor; also affected by simulator issue S1)
- **Prompt.** Clear. Leaving R1MODE and Flash latency for the solver to find is fair, because the RM states both requirements:
  - R1MODE: Table 38 (p.232) gives "SYSCLK ≤ 170 MHz → R1MODE 0".
  - PWR_CR5 resets to 0x100 (p.267).
  - Table 9 (p.98) has no normal-mode row above 150 MHz.
  - DS Table 46 (p.123) gives fPLL_R_OUT ≤ 150 MHz in Range 1 non-boost.

  RM p.232 and p.267 phrase R1MODE as "recommended". The 150 MHz caps in Table 9 and DS Table 46 make it effectively mandatory, so the ruling is defensible.
- **Hand calculation.** M = 4 ⇒ 4 MHz (within [2.66, 16]); N = 85 ⇒ VCO 340 MHz (≤ 344); R = 2 ⇒ 170 MHz; 4 WS (≤ 170 boost). Verified. This is the only integer solution: M = 8 gives 2 MHz, which is below the minimum, and M = 1 or 2 need a fractional N or a VCO above 344 MHz.
- **Reference solution.** Functionally right, with three gaps:
  1. `PWR->CR5` is accessed immediately after `PWREN`. RM p.285: "Just after enabling the clock for a peripheral, software must wait for a delay before accessing the peripheral registers". Add `(void)RCC->APB1ENR1;`.
  2. HPRE is restored right after the SWS loop. RM p.280 (Transition state): "Wait at least 1 µs and then reconfigure AHB prescaler bits". Add a short counted delay, for example `for (volatile int i = 0; i < 100; i++) {}`.
  3. Flash LATENCY is not read back (p.99 step 2). This is a nit.
- **Wrong variants.** All genuine.
  - `forgot_boost_mode`, `forgot_flash_latency` and `n_86_gives_172mhz`.
  - `switch_before_pll_ready_order`: the name is misleading, because the patch removes PLLON (so the PLLRDY loop would hang on hardware). Rename it to `forgot_pllon`.
- **Alternatives (all pass).**
  - No HPRE/2 dance: passes with only a SIM-CLK-PROC warning.
  - A Cube-like sequence: VOS write, VOSF wait, PLLREN set after PLLON, `FLASH->ACR` written whole with PRFTEN/ICEN/DCEN, a LATENCY read-back loop and `MODIFY_REG`.
  - HPRE/2 placed first, in the p.233 order.
- **False pass.** PLLREN omitted ⇒ `pass=True` (S1).

### C3-019 — OK (but affected by S1)
- **Hand calculation.** 16/4 × 40 = 160 MHz VCO (≥ 96), /2 = 80 MHz. Range 1 normal needs 2 WS (≤ 90, Table 9 p.98). PPRE1 = 100 ⇒ /2 (p.290). Verified. R1MODE can stay at 1. No HPRE transition is needed, since RM p.279 applies it only to "HCLK higher than 80 MHz".
- **Wrong variants.** `apb1_not_divided`, `latency_1_ws` and `n_80_gives_160mhz`: all genuine.
- **Alternatives (all pass).** M = 1, N = 20, R = 4 with 3 WS; prescalers written after the switch; boost mode with 2 WS.
- **False pass.** PLLREN omitted (S1).

### C3-020 — FIX (minor; also affected by S1)
- **Hand calculation.** HSE 8 MHz / 2 = 4 MHz, × 84 = 336 MHz (≤ 344), / 2 = 168 MHz ⇒ boost mode and 4 WS. PLLSRC = 11 is HSE (p.293). Verified.
- **Reference solution.** Same two gaps as C3-018: no delay after PWREN (p.285), and no ≥ 1 µs wait before restoring HPRE (p.280).
- **Wrong variants.** `hse_not_enabled` (NOSRC), `pll_source_left_on_hsi` (VCO 672 MHz) and `forgot_boost_mode`: all genuine.
- **Alternatives.** M = 1, N = 42 passes. CSSON with HSI16 turned off afterwards passes.
- **False passes.**
  - PLLREN omitted (S1).
  - `HSEBYP | HSEON` with a crystal passes. Per RM p.287, HSEBYP means "bypassed with external clock", which is wrong for a crystal. This is low priority.

---

## Simulator / grader issues (with page evidence)

- **S1 — PLLREN ignored (error-class gap, false pass).**
  - **Problem.** `clock_tree.decode` and `rcc.refresh_status` set SYSCLK = PLL R whenever SWS = 11 and PLLRDY, regardless of `RCC_PLLCFGR.PLLREN` (bit 24). The RM text is quoted under issue 1 in the Summary (p.292 and p.278 step 5). The RM also says "PLLREN cannot be cleared if PLLCLK is used as system clock" (p.278), so PLLREN is part of the documented system-clock path.
  - **Fix.** When SW = 11 and PLLREN = 0, either do not move SWS to PLL (then SW ≠ SWS ⇒ `SIM-CLK-NOSRC`), or report a new `SIM-CLK-PLLREN` error.
- **S2 — `SIM-USART-BRR-UE` is only a warning (false pass).**
  - **Problem.** RM p.1755: "USART_BRR … This register can only be written when the USART is disabled (UE = 0)". OVER8 (p.1741) and M1 (p.1740) say "This bit can only be written when the USART is disabled (UE = 0)". The simulator applies such writes and only warns.
  - **Fix.** Make it an error, or at least have the grader fail on it. Apply the same to OVER8/M/PCE writes while UE = 1, and to I2C_TIMINGR writes while PE = 1 (p.1681: "This register must be configured when the I2C peripheral is disabled (PE = 0)").
- **S3 — Extra channels fail the task (false fail).**
  - **Problem.** `tim._timer_effects` creates an effect and error violations for *every* channel with CCxE or CCxNE = 1, even if that channel is unrouted and absent from the spec. `grade()` then fails on any error-severity violation. Enabling a channel output that is not connected to any pin is harmless (RM Table 282 only defines the tim_ocx state; the pin depends on GPIO, p.1261 note).
  - **Fix.** For channels without a routed pin, downgrade SIM-GPIO-AF and SIM-TIM-OCM to warnings. Alternatively, have the grader only count violations whose `signal`/`pin` belongs to a spec item.
- **S4 — UART and I2C spec items lack fields for stated requirements.** Frame format, TE and RE, OVER8 and kernel source are not checked; see C3-011…017. The simulator already exposes `te`, `re`, `over8`, `kernel_source`, `kernel_clk_hz` and `i2cclk_hz`, so the grader can add these checks without simulator changes. M/PCE/STOP need decoding (CR2 is currently unmodeled).
- **S5 — The HPRE transition warning has the wrong threshold and citation (low impact, warning only).**
  - **Problem.** `SIM-CLK-PROC` fires only above 150 MHz and cites p.233. RM p.279–280 ("Clock source switching conditions: Switching from HSE or HSI16 to PLL with AHB frequency (HCLK) higher than 80 MHz … Transition state: Set the AHB prescaler HPRE[3:0] bits to divide the system frequency by 2 … Wait at least 1 µs") applies the rule above 80 MHz.
  - **Fix.** Align the threshold and the citation.
- **Check — R1MODE ruling: sound.** See the C3-018 notes. RM p.232 and p.267 use "recommended", but Table 38 (p.232), Table 9 (p.98) and DS Table 46 (p.123: fPLL_R_OUT "Voltage scaling Range 1 … 150" vs "Boost mode … 170") make > 150 MHz in normal mode out of spec.
- **Check — the following modelling decisions match the RM.**

  | Decision | RM evidence |
  |---|---|
  | Timer ×2 rule | p.281 |
  | Writes to a clock-gated peripheral are ignored | p.285 ("not supported") |
  | PLL fields are write-locked while PLLON = 1 | p.292–293 |
  | Flash WS checked at the moment of the change | p.99 sequence |
  | TIM2/5 have a 32-bit ARR | p.1388–1389 |
  | TIM16 ARR[19:16] are reset in non-dither mode | p.1496 |
  | PWM duty formulas, up- and down-counting | p.1179 |
  | OVER8 BRR encoding | p.1708 |

---

## Cross-cutting observations

1. **Tolerances.**
   - PWM (±1 %, ±1 pp duty) and UART (±2 %) are generous enough that every integer rounding choice passes; I tested truncation and rounding.
   - Clock ±0.1 % is fine, because the PLL gives exact frequencies.
   - I2C is the only fairness risk: C3-017 rejects the RM table value (see above).
2. **Leniency is systematically one-sided for UART and I2C.** The graders check only frequency and pins. Prompt requirements such as 8N1, TE + RE, OVER8 and the kernel source are free to violate. A system that ignores those constraints is never penalised, while a system that follows them gains nothing. Fix this via S4 before the test split is used, because C3-013, C3-014 and C3-017 are `test` tasks whose distinctive trap is exactly an unchecked requirement.
3. **Parser strictness can fail correct code (all tasks).** Correct code that branches on a register value it already wrote, or does arithmetic on one, fails as `unsupported_construct` rather than being scored. Examples: `if (!(TIM1->CR1 & TIM_CR1_CEN)) …` and `CCR1 = 0.25f * (TIM1->ARR + 1)`. Polling loops on status flags, `(void)reg` reads, temp-variable RMW, helper functions, `MODIFY_REG`/`SET_BIT`/`WRITE_REG`, `__NOP`/`__DSB`, `#define` arithmetic and float constants all work. Consider reporting `unsupported_construct` separately (abstain/invalid) rather than as a plain fail when comparing systems, or teach the interpreter to read back registers whose value it knows.
4. **Real-hardware hygiene is not graded, which is acceptable but worth stating in the paper.** The grader does not check:
   - the clock-enable delay (p.285);
   - the 1 µs HPRE transition wait (p.280);
   - SCLDEL/SDADEL compliance (p.1631–1632);
   - Fm/Sm tLOW/tHIGH minimums (Table 358);
   - a whole-register `GPIOA->MODER = …` write that turns PA13/PA14 (SWD) into inputs.
5. **Provenance consistency.** Every task says "chưa review độc lập" in `authored_by` but has `review_status: verified`. Update after applying fixes.
6. **Evidence integrity.** All 20 tasks' evidence snippets are present on the cited pages. The wrong page numbers that remain are only in free-text `reference_calc`: TIMINGR p.1672 → p.1681, I2C3SEL p.324 → p.323, and TIM4 OC3M/CC3E p.1257/1260 → p.1384/1385.

---

## Delta re-review

Method: I checked each fix against RM0440 and DS12288, not against the coordinator's claims. The vendored copy is identical to `agent/hwmodel` (only `VENDOR.md` differs). `verify_tasks --categories C3` reports 0 problems, and every evidence snippet is still present on its cited page. I re-ran all earlier probe scripts (`t_pwm`, `t_extra`, `t_uart`, `t_uart2`, `t_i2c`, `t_clk`, `t_parse`, `t_misc`) and added new ones (`t_delta.py`, `t_delta2.py`, `t_d3.py`) in the scratchpad.

### Status of the original items

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | PLLREN not modelled | **Resolved** | Omitting PLLREN now gives `SIM-CLK-NOSRC` plus `wrong_clock` (RM p.292; p.278 step 5). Setting PLLREN after PLLON (allowed by p.278) passes. Setting it after `SW = PLL` also passes, which is consistent with p.279: "the switch occurs when the clock source becomes ready". New `forgot_pllren` variants are present in C3-018/019/020. |
| 2 | UART requirements unchecked | **Resolved** (two small residuals: R1, R2) | 9-bit, 7E1 (`PCE` with M = 00: the parity bit replaces the MSB, RM p.1740), 8N2, TE only and OVER8 now fail with `wrong_config`. BRR written after UE fails with `SIM-WRITE-LOCKED`. C3-014 with SYSCLK fails with `wrong_kernel_clock`. Frame decoding is correct: M0 + PCE → 8E1, + PS → 8O1, M1 → 7N1. No false fails among these correct alternatives: CR2/CR3 written before UE; same-value rewrites of CR2 or BRR after UE (only changed locked bits are flagged); `CR1 \|= RXNEIE` after UE; UE first and then TE/RE; disable → BRR → enable; FIFOEN before UE; explicit `USART1SEL = 00`; PRESC /2 with BRR 369. |
| 3 | I2C kernel clock / TIMINGR after PE | **Resolved** | C3-016 retuned for PCLK1 fails with `wrong_kernel_clock`. TIMINGR after PE fails with `SIM-WRITE-LOCKED` (p.1681). |
| 4 | C3-017 rejects the RM table value | **Resolved, but the band rule creates new false passes** | 0x10320309 now passes. See N1. |
| 5 | I2C references violate SCLDEL/SDADEL bounds | **Resolved** | C3-016 now uses SCLDEL 13 / SDADEL 3 and C3-017 uses SCLDEL 6, matching my bounds of 12.3 → 13, 2.47 → 3 and 5.4 → 6. Nit: `reference_calc` in both tasks cites "Table 356 p.1630", but the table is on **p.1632** (RM TOC line 57 and the page text). |
| 6 | Unused timer channels fail the task | **Resolved** | CC2E or CC1NE in C3-001, CC1NE in C3-006 and CC3E\|CC4E in C3-010 now pass. `_relevant_violations` still keeps op-time errors and violations tied to signals that can appear on the spec pin, so all original wrong variants still fail. |
| 7 | Clock-reference hygiene | **Resolved** | A dummy `(void)RCC->APB1ENR1` read is added (p.285). The `volatile` 100-iteration loop runs at HCLK = 85 MHz and takes well over 1 µs (≥ ~5 cycles per iteration, so ≳ 6 µs; p.280). The `SIM-CLK-PROC` threshold is now HCLK > 80 MHz, matching p.279–280. |
| 8 | Citations and smaller items | **Resolved** | TIMINGR p.1681, I2C3SEL p.323 and TIM4 p.1384/1385 are fixed. C3-009 `forbid_pins` works: routing to PA8 too now fails with `forbidden_pin_used`, while PA8 as plain GPIO passes, which is acceptable. Variants are renamed (`forgot_pllon`, `presc_too_small`, `timing_computed_for_a_faster_clock`). `authored_by` no longer says "not independently reviewed". |

### New variants

All new variants are genuinely wrong, either per the RM or per a requirement the prompt states explicitly.

| Task | Variant | Basis |
|---|---|---|
| C3-011 | `nine_bit_word`, `transmitter_only` | Prompt requirements (8 data bits; TE and RE) |
| C3-011 | `brr_written_after_ue` | RM p.1755 |
| C3-012 | `parity_enabled` | Gives 7E1; prompt asks for 8N1 |
| C3-013 | `oversampling8_correctly_encoded` | Baud is correct, but the prompt says "oversampling by 16" |
| C3-014 | `kernel_clock_switched_to_sysclk` | Prompt says "keep the default" |
| C3-015 | `timingr_written_after_pe` | RM p.1681 |
| C3-016 | `retuned_for_pclk1_instead_of_sysclk` | Prompt requires the SYSCLK kernel |
| C3-017 | `timing_computed_for_a_faster_clock` | Band [500 kHz, 800 kHz] misses 400 kHz |
| C3-018/019/020 | `forgot_pllren` | RM p.292 |

### New findings

**N1 — The I2C band rule accepts designs that are too fast, especially at 400 kHz (C3-017).**

The rule passes whenever 400 kHz lies within ±5 % of [f(tSYNC = 1000 ns), f(tSYNC = 4·tI2CCLK)]. At 16 MHz and Fm, that range of tSYNC is 30–40 % of the period, so these designs now pass:

| SCLL / SCLH | Band | tLOW | tHIGH |
|---|---|---|---|
| 14 / 7 | [410, 593] kHz | 0.94 µs | 0.50 µs |
| 11 / 11 | [400, 571] kHz | 0.75 µs | 0.75 µs |

Both violate Table 358 (p.1647) Fm limits, tLOW ≥ 1.3 µs and tHIGH ≥ 0.6 µs, even after adding the minimum per-edge tSYNC of 2·tI2CCLK = 125 ns. With fast edges they run at about 570–590 kHz. In Sm the effect is smaller but present: C3-016 with SCLL 52 / SCLH 38 passes with band [103.5, 115.2] kHz, although tHIGH ≈ 3.69 µs < 4.0 µs.

The 1000 ns figure is an Sm example. Table 360's Fm example uses tSYNC = 750 ns (note 3, p.1657), and Fm tr(max) is 300 ns versus 1000 ns for Sm (Table 356, p.1632).

Two possible fixes:
- (a) Use a per-mode slow tSYNC, taken from the RM table notes: Sm 1000 ns, Fm 750 ns. With 750 ns, both too-fast designs above fail (457 and 444 kHz), while 0x10320309 ([400, 500] kHz) and the reference ([333, 400] kHz) still pass.
- (b) Also check the Table 358 minimums: tLOW ≥ 4.7/1.3 µs and tHIGH ≥ 4.0/0.6 µs, using tLOW = (SCLL+1)·tPRESC + 2·tI2CCLK and tHIGH = (SCLH+1)·tPRESC + 2·tI2CCLK. ST's own Table 359/360 values meet this; for example, Fm 16 MHz gives 1250 + 125 = 1375 ns and 500 + 125 = 625 ns. The C3-015/016/017 references also meet it, and the check would reject every case above.

The prompt wording is self-consistent, but under (a) it would need to say "1000 ns (Sm) / 750 ns (Fm)".

**R1 — USART_PRESC is not write-locked (low).** RM p.1772: "USART_PRESC … This register can only be written when the USART is disabled (UE = 0)." PRESC is modelled and changes the baud rate, yet writing it after UE passes (C3-014 with PRESC = /2 written after UE). Add `"PRESC": 0xF` to `usart.WRITE_LOCKED`.

**R2 — CR2.SWAP, TXINV and RXINV are ignored (low).** Since CR2 became "modelled", these writes no longer even appear as `unmodeled`. An answer with `CR2 = USART_CR2_SWAP` (TX/RX pin functions swapped, RM p.1749) passes the `tx_pin`/`rx_pin` checks. Either model SWAP in `_pin`, or mark the configuration `unmodeled` when SWAP, TXINV or RXINV is set.

No regressions: every earlier correct-alternative probe still passes, and every earlier wrong answer still fails. The exceptions are the intended changes listed above, plus the documented parser limitation for register read-back arithmetic, which is unchanged.

**Overall delta verdict:** items 1–8 are resolved. One medium issue is new (N1, the leniency of the I2C band at Fm), and two low ones remain (R1, R2). I recommend applying N1 (a) or (b) before C3-015/016/017 are used on the test split.


## Phản hồi của người thực hiện sau delta re-review (2026-10-22)
- N1 (dải I2C quá lỏng): chọn phương án (b) — thêm kiểm tối thiểu tLOW/tHIGH của Table 358 (spec `mode`, mã `wrong_i2c_timing`; ước lượng tLOW ≈ tSCLL + tSYNC1, tHIGH ≈ tSCLH + tSYNC2 với tSYNC = (2+DNF)·tI2CCLK). Giá trị mẫu Table 360 và 3 tham chiếu đạt; hai thiết kế của reviewer (Fm SCLL 14/SCLH 7 và 11/11, Sm SCLL 52/SCLH 38) nay trượt; hai biến thể mới trong C3-015/016/017 (`fast_mode_low_period_too_short`, `high_period_too_short`). Đề nêu rõ quy tắc.
- R1: `USART_PRESC` vào danh sách khoá ghi (RM p.1772). R2: `CR2.SWAP/TXINV/RXINV/LINEN/CLKEN` ⇒ `unmodeled`, grader trượt `unmodeled`. Nit p.1632 đã sửa.
- Kiểm tra lại: agent 913 test, eval 711 test pass; `verify_tasks --categories C3` 0 vấn đề (20 task, 72 biến thể); vendor `--check` không lệch. Không hệ nào được chạy trước khi các sửa này hoàn tất (baseline chạy sau).
