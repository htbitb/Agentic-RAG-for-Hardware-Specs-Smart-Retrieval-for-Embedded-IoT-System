# Independent review: C5 (system-level goals, 12 tasks)

Reviewer: independent subagent (did not author the tasks or graders), 2026-10-23.
Scope: `eval/tasks/C5/c5_curated.yaml` (C5-001…012 and the derived `C5-xxx-O`), the graders `eval/graders/checklist.py` and `clarify.py`, `eval/sim_human.py`, `eval/schema.py::derive_oracle`, and `functional_sim`/`compile` on the tasks with code.
Method: I formed my view from the YAML, the corpus page cache (`corpus/.cache/pages/*.jsonl`) and the graders, then read `plan/drafts/C5_authoring_notes.md`.
Everything below was run with `eval/.venv/bin/python` against the real graders and is read-only. Scratch scripts are in
`/private/tmp/claude-501/-Users-loc4atnt-Master-Course-Ky3-AgenticAI-project/e2497821-b4ae-4a3f-9222-9ac5c1039b9f/scratchpad/review_c5/`
(`h.py` = harness, `fixes.py` = candidate replacement items, `test_fixes.py` = validation). There were no LLM or network calls.

**Where fixes go:** the installed YAML is byte-identical to `plan/drafts/C5_curated_draft.yaml` and is generated. Apply the fixes in `plan/drafts/c5_common.py`
(`LOW_POWER`, `sleep_total()`, `COMPAT_RX`, `LEVEL_SHIFTER_RX`, `no_direct*`) and in `c5_tasks_a.py` / `c5_tasks_b.py`, then rebuild.

## 0. Baseline: what passes today

- `python -m eval.tools.verify_tasks --categories C5` reports 12 tasks and 0 problems.
- All 12 reference answers pass `checklist`. The 6 reference answers with code also pass `functional_sim` and `compile` (status `ok`). Every CMSIS identifier they use is `#define`d in the vendored `cmsis-device-g4_v1.2.6` headers.
- All 27 wrong variants fail exactly their `must_fail` items.
- `verify_c5` does not run `functional_sim` on wrong variants, so I ran it myself:
  - The guessed-HSE, PLL-input and 8 MHz-PLL variants fail `functional_sim` (SIM-CLK-LIMIT / wrong_clock).
  - The 20 kHz variant fails it (wrong_freq) and the 115200 variant fails it (wrong_baud).
  - The level-shifter, sleep-mode and LDO variants pass `functional_sim`, which is expected because the simulator does not model those aspects.
- All 6 oracle variants derive correctly. Each prompt contains every hidden value, matched by its own `value_patterns`, and the reference answer passes each oracle checklist.

The machinery works on the authors' own strings. The problems are in what else passes and what else fails.

## 1. Per-task verdicts

Legend: **BLOCKER** = before any system run, a plausible answer gets the wrong TSR verdict (demonstrated below), or the task's purpose is not measured. **FIX** = should be fixed, lower impact. **OK** = no change needed.
Finding numbers like G2 refer to section 2. "Validated" means I ran the fix on a copy of the task: the reference still passes, wrong variants still fail their `must_fail` items (plus any new item), and the adversarial string flips.

| Task | Split | Verdict | Findings and exact fix |
|---|---|---|---|
| C5-001 | test | **BLOCKER** | (a) **A wrong design passes the full TSR gate** (checklist + functional_sim). Take the authors' `stop1_over_budget` variant (95.5 µA > 50 µA) and add *"Standby would lose the clock configuration, so Stop 1 is kept; the total must stay below 50 µA."* The restated budget (50) falls inside `sleep_total` [11, 50], and the word "Standby" satisfies `low_power_mode` (G1). **Fix:** `sleep_total` max 50 → **20** (real totals are 11.6–11.9 µA for Standby or Shutdown at 3.0–3.6 V). Validated. (b) `esp_link_compat` is keyword-stuffable and rejects correct phrasings (G2) → use the new `COMPAT_RX`. (c) `pwm_freq` rejects "16,000 Hz", "16 000 Hz" and "16-kHz" (G9) → number group `\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?\|\d+(?:\.\d+)?` and `\s*-?\s*` before the unit. Validated. (d) `pwm_hz` keyword `kHz` is too generic: *"What load capacitance does the 32.768 kHz LSE crystal need?"* matches **both** hidden items, discloses both answers, and gives precision = recall = 1.0 (G12). → drop `kHz` from `pwm_hz`; see G12 for HSE keywords. |
| C5-002 | dev | FIX | (a) `ldo_judged_adequate` plus a quote of the datasheet passes the whole checklist: *"The ESP32 datasheet recommends at least 500 mA, but the worst-case peak of 270.5 mA lasts only microseconds, so the 250 mA LDO is adequate."* **Fix:** add a forbids item `no_ldo_ok_claim` with patterns `(?<!not )(?<!n't )(?:250\s*mA\s+)?(?:LDO\|regulator)\s+(?:is\|will\s+be\|should\s+be\|remains\|stays)\s+(?:still\s+)?(?:adequate\|sufficient\|enough\|fine\|ok(?:ay)?)\b` and `\bfits\s+(?:within\s+)?the\s+250\s*mA\b`, and add it to the `must_fail` of `ldo_judged_adequate`. Validated. (b) `peak_current` [260, 330] mA rejects correct answers that use other credible peak figures, e.g. *"…the worst-case total is about 410 mA"* using the ESP32-WROOM module figure. The engineering conclusion only needs > 250 mA. → min 251, max 700, and allow "at peak" (`(?:in[ \t]+\|at[ \t]+)?` in pattern 2). Validated. (c) `esp_baud` keywords miss *"How fast is the serial link to the ESP32?"*, *"What speed does the bridge firmware's UART run at?"* and *"Which data rate does the UART-to-Wi-Fi bridge expect?"* → add `serial link`, `data rate`, `how fast`, `UART run`, `speed does`. |
| C5-003 | test | **BLOCKER** | (a) **Shutdown passes** even though the prompt requires "a brown-out reset active". RM0440 p.234: "The BOR is active in all power modes except Shutdown mode"; p.251: "The BOR is not available in Shutdown mode". Shutdown + RTC 0.565 µA gives 1.97 µA, which is inside [1.8, 3.2]. Demonstrated. **Fix:** `low_power_mode.any_of` → `["\\bstandby\\b"]` and add forbids `not_shutdown` (G1). Validated. (b) **Correct remedies fail `trade_offs`**: *"use a 650 mAh cell instead of the 400 mAh one; wake up every 21 minutes instead of every 15 minutes; keep each active phase under 1.48 s"* (G7). → add the three groups in G7. Validated. (c) **A correct remedy fails `no_false_claim`**: *"a 650 mAh cell meets the 3-year target with a 20 % margin"*. → use the subject-restricted patterns in G7. Validated; `guessed_2000mah` still fails it. (d) A hedge over capacities passes `lifetime` because of `match: any` (G13). Document this. |
| C5-004 | test | **BLOCKER** | (a) **A correct answer fails `no_direct`**: *"The 3.3 V STM32 and the 1.8 V nRF52840 are not directly compatible, so a translator is required."* is a natural sentence for this exact answer (G3). → add `(?<!not )(?<!n't )(?<!never )(?<!be )` before `(?:directly\|fully)\s+compatible`. Validated. (b) `level_shifter` passes *"The link does not require a level shifter."*, *"Instead of a level shifter, a 1 kOhm series resistor on TX is enough."* (the authors' own `series_resistor` mistake, rephrased) and *"We can skip the level translator."*. It also fails correct *"Fit an NTS0104 (dual-supply translating transceiver)…"* (G4). → new `LEVEL_SHIFTER_RX`. Validated. (c) **Safe default:** a non-asking answer ("supply mode unknown, so fit a translator anyway") passes checklist and functional_sim. Demonstrated (G13). (d) The prompt presupposes the answer: *"what has to be fitted or configured on the board for the link to be safe"* → change to *"whether anything has to be fitted or configured on the board for the link to be safe and reliable"*, and make the same change in C5-012 to keep the pair symmetric. (e) `nrf_supply` keywords: `powered` and `supply voltage` match unrelated questions (*"Is the board powered from USB?"*, *"What supply voltage does the STM32 use?"*). They miss *"What is the nRF52840's VDD?"* and *"Is the nRF52840 on the same 3.3 V rail as the STM32?"*. → replace `powered` with `nRF52840 powered`, `nRF powered`, `powers the nRF`; replace `supply voltage` with `supply voltage of the nRF`; add `rail`, `nRF52840 s VDD`, `high voltage mode`, `normal voltage mode`. |
| C5-005 | dev | **BLOCKER** | (a) Same `no_direct` false fail: *"The breakout is not fully compatible with 3.3 V logic."* (G3). (b) Same `level_shifter` gaps (G4); also fails correct *"Fit a level-translating I2C buffer such as the TCA9406."*. (c) **Safe default:** "I/O voltage unknown, always fit a translator" passes the whole checklist without asking. Demonstrated. Fix it or document it (G13). (d) `sensor_io_v` keywords miss *"Does the breakout include a level translator?"*, *"What is the VDD of the accelerometer breakout?"* and *"Is the breakout 3.3 V compatible?"*. `powered` matches *"Is the debug UART powered from the ST-Link?"*. → add `level translator`, `level shifter`, `VDD of the`, `breakout VDD`, `breakout voltage`, `3.3 V compatible`; drop bare `powered` and `supply voltage` in favour of breakout- or sensor-qualified forms. |
| C5-006 | test | **BLOCKER** | (a) **A valid alternative fails.** `esp32_off` explicitly accepts a load switch or P-MOSFET, but then the ESP32 contributes about 0 µA and the total is 0.655 + 0.01 + 0.6 + 1 = 2.27 µA, below the `sleep_total` min of 2.5. Demonstrated. (b) max 5.0 = the hidden budget, so a restated budget passes (G1). **Fix:** `sleep_total` [2.5, 5.0] → **[2.0, 4.5]**. The irreducible total is 0.565 (Shutdown) + 0 + 0.6 + 1 = 2.165. Validated. (c) `sleep_budget` keywords `µA`/`uA` match *"Is the soil sensor's 0.6 µA idle current measured at 3.3 V?"* and `budget` matches *"What is the power budget of the Wi-Fi transmit phase?"*. They miss *"What is the target standby current for the whole node?"* → drop `µA`/`uA`; add `standby current`, `night current`, `target current`, `consumption allowed`. (d) `sleep_budget` can be defaulted by minimising current; `hse_hz` still carries the need to ask (G13). |
| C5-007 | test | **BLOCKER** | (a) **A wrong design passes the full TSR gate:** Shutdown with the RTC on the LSI (0.565 + 10 + 2 = 12.6 µA). RM0440 p.251 says "The PLL, the HSI16, the LSI and the HSE oscillators are also switched off" in Shutdown, and there is no LSE. The authors call this a trap in their notes, but the checklist accepts `shutdown`. Demonstrated: checklist PASS and fsim PASS. **Fix:** Standby-only `low_power_mode` + `not_shutdown` forbids (G1). (b) `sleep_total` [12, 50] → **[12, 20]** (budget restatement, G1). Validated. (c) B1. |
| C5-008 | dev | **BLOCKER** | (a) **A correct answer fails `no_direct_sensor`.** The task has one 1.8 V link and one 3.3 V link, so a correct answer naturally contrasts them: *"Unlike the humidity sensor, the nRF52840 can be connected directly because both run at 3.3 V."* or *"The nRF52840 UART is directly compatible, while the humidity sensor needs a PCA9306."*. Both are forbidden because `[^\n.]{0,80}` crosses clause boundaries (G5). → `[^\n.,;:]{0,60}` plus the negated claim. Validated; `sensor_wired_directly` still fails. (b) `sleep_total` max 10 = budget → 6 (G1). (c) B1. |
| C5-009 | test | **BLOCKER** | Same as C5-003 (a), (b), (c). Shutdown violates the BOR requirement; natural remedies fail `trade_offs`; remedy phrasing fails `no_false_claim` (use `(?:12\|twelve)`). Validated with the same new items. Also B1. |
| C5-010 | test | **BLOCKER** (only via B1; otherwise FIX) | (a) `headroom` is satisfied by any "0.3 V" or "0.7 V", including the wrong argument *"…the 3.3 V STM32 output exceeds VDD + 0.3 V"*. → `(?:VDDH\|4(?:\.0)?\s*V\s+(?:rail\|supply))[^\n]{0,80}(?:0\.[37]\s*V\|headroom\|dropout)`, `(?:headroom\|dropout)[^\n]{0,80}(?:VDDH\|4(?:\.0)?\s*V\|0\.[37]\s*V)`, `VDDH\s*(?:>=\|≥\|-\|−)`. Validated. (b) The reference answer says *"no AHB /2 step is needed"*, which contradicts RM0440 p.279 ("recommended to use a transition state … Switching from HSE or HSI16 to PLL with AHB frequency (HCLK) higher than 80 MHz"). The project's own simulator flags it (`SIM-CLK-PROC` warning on the reference). → add the HPRE /2 → switch → ≥ 1 µs → /1 step to the reference code and reword the text. (c) Optional: REG0 output error is −10 % (PS p.155), so worst-case nRF VDD = 2.97 V and VI/O max = 3.27 V, just under a 3.3 V STM32 high. The reference could mention this; grading is unaffected. (d) B1. |
| C5-011 | dev | **BLOCKER** | (a) **A wrong design passes the checklist.** Take `esp32_left_in_deep_sleep` (13.16 µA > 8 µA), add *"its EN pin keeps the usual 10 kΩ / 1 µF RC delay"* (the standard ESP32 reset circuit, which satisfies `esp32_off` via `\bEN\s+pin`) and *"slightly above the total budget of 8 µA"* (8 is inside [3.5, 8.0]). Demonstrated. (b) A valid load-switch design fails (3.17 µA < 3.5). **Fix:** `sleep_total` → **[3.0, 7.0]**; remove `\bEN\s+pin` from `esp32_off` and put `(?<!not )(?<!n't )(?<!no )` before `power[- ]?(?:gate…)`. Validated. (c) `no_direct_sensor` false fail: *"The ESP32 link is directly compatible; the gas sensor on I2C1 needs a level shifter."* (G5). (d) Plan-only and 160 MHz, so `boost_mode` is mention-only and *"boost mode is not required"* passes. → add forbids `no_boost_claim` (G10). Validated. (e) B1. |
| C5-012 | test | **BLOCKER** | (a) **A correct answer fails `sleep_total`.** The prompt asks for "the STM32 idle current", but the item needs the word *total*: *"STM32 idle current = 0.13 + 0.305 = 0.44 µA"* fails. Demonstrated. → add pattern `\bidle\s+current\b[^\n]{0,120}?` + number + unit + `_SKIP` and narrow to [0.3, 1.5]. Validated. (b) Same `no_direct` false fail as C5-004 (*"Only if REGOUT0 were programmed to 3.3 V … would the two chips be fully compatible."*). (c) `no_boost_claim` as in C5-011. (d) Prompt wording as in C5-004 (d). (e) B1. |

**B1 (BLOCKER, all of C5-007…012): the complete-info half does not measure what it is for.**
- The six complete-info tasks list `graders: [checklist, (functional_sim, compile)]` without `clarify`.
- `hitl.clarify_aggregate()` and `report.hitl_section()` build the complete-info column ("Câu hỏi thừa / run (đủ thông tin)") and the per-task table only from `clarify` details with `required == 0`.
- Demonstrated: scoring a C5-008 run that asked one unnecessary question gives graders `['checklist','compile','functional_sim','hitl']`, and `clarify_aggregate(...)['complete']['runs'] == 0`.
- **Fix:** add `clarify` to `graders` of C5-007…012 (it is not gating). Validated:
  - `verify_c5` still returns no problems.
  - The complete half then counts every run, including runs with no question: 2 runs, 1 unnecessary, 0.5 per run.
- Also make `verify_c5` require `clarify` for every C5 task, not only those with `hidden_info`.

## 2. Grader / DSL weaknesses (ranked; every string below was run through the real grader)

**G1 (HIGH): `quantity` with `match: any`, and `max` equal to the budget.** Any in-range number on a line containing *total/sum/overall* passes, including a restatement of the budget or a subtotal.
- Failing strings:
  - C5-001: *"Node total = 95.5 µA, above the total budget of 50 µA."* → PASS.
  - The Stop-1 and Deep-sleep full answers above pass for the same reason.
- Fix: move every `max` clearly below the budget (C5-001 20, C5-006 4.5, C5-007 20, C5-008 6, C5-011 7.0, C5-012 1.5).
- Residual risk: a subtotal in range ("STM32-side total 2.9 µA, node total 12.9 µA") still passes `match: any`. I did not switch to `match: all` because correct answers often mention a rejected alternative's total.

**G1b (HIGH): `low_power_mode` accepts `shutdown` where Shutdown is illegal.**
- C5-003 and C5-009 require an active BOR (RM0440 p.234, p.251). C5-007 has only the LSI, which is off in Shutdown (p.251).
- The item is mention-only, so *"Standby would lose the clock config, so Stop 1 is used"* also passes it.
- Fix for 003/007/009: `any_of: ["\\bstandby\\b"]` plus forbids `not_shutdown` with patterns:
  - `(?:uses?|enters?|selects?|chooses?|goes\s+(?:in)?to|put\s+(?:\w+\s+){0,2}in(?:to)?|sleeps?\s+in|waits?\s+in)\s+(?:the\s+)?Shutdown\b`
  - `\bShutdown\s+(?:mode\s+)?(?:is\s+)?(?:selected|chosen|used)\b`
  - `STM32\w*,?\s+Shutdown\b`
- Validated: the references, which say "Shutdown is not an option…", still pass.

**G2 (HIGH): `COMPAT_RX` (`esp_link_compat` / `nrf_link_compat`) is keyword-based.**
- False passes:
  - *"The STM32 and the ESP32 are not directly compatible, so add a level shifter."*
  - *"PA9 is compatible with USART1_TX (AF7)."*
  - *"Connect the 24 MHz crystal directly to PF0/PF1."*
  - *"Use a direct connection from PA8 to the driver PWM input."*
- False fails:
  - *"There is no need for level shifting between the two 3.3 V chips."*
  - *"No translator is required: TX and RX can be tied straight to each other."*
- Fix (validated on all 9 tasks that use it):
  - Drop the bare `\b(?:are|is)\s+…compatible\b`, `(?:connect|wire)\w*…directly` and `direct\s+connection`.
  - Negation-guard `(?:directly|fully|electrically)\s+compatible`.
  - Add `\bno\s+(?:need\s+for\s+(?:a\s+|any\s+)?)?level[- ]?…` and `\bno\s+(?:level\s+)?(?:translator|shifter)s?\s+(?:is\s+|are\s+)?(?:needed|required|necessary)`.
  - Add a link-anchored direct-wiring pattern: `\b(?:TX|RX|UART|USART\d?|lines?|signals?|links?|chips|both)\b[^\n.]{0,40}(?:connected|wired|tied|joined)\s+(?:directly|straight|together)`.

**G3 (HIGH): the `no_direct` forbids ignore negation.**
- *"… are not directly compatible, so a translator is required."* is forbidden (C5-004/005/012).
- Fix: prefix `(?<!not )(?<!n't )(?<!never )(?<!be )` on the compatibility pattern.
- Add `can\s+(?:be\s+)?(?:connected|wired|tied)\s+(?:directly|together|straight)` and `(?<!not )(?:tie|tied|join|joined)\s+(?:\w+\s+){0,3}(?:together|directly|straight)`. Today *"No problem: the pins can simply be tied together."* passes.
- The authors' note 3 accepts failing hedges; the failure demonstrated here is not a hedge.

**G4 (HIGH): `LEVEL_SHIFTER_RX` has negation and vocabulary gaps.** Demonstrated false passes and false fails are in C5-004 (b).
- Fix: extend the negative lookbehinds with `require a `, `requires a `, `instead of a `/`the `, `skip the `/`a `, `avoid a `/`the `, `omit the `, `drop the `.
- Extend the lookahead with `would be|…overkill|unnecessary`.
- Add `translating` and `(?:dual[- ]supply|bidirectional|I2C)\s+(?:\w+\s+)?(?:voltage\s+)?(?:translator|transceiver|translating)`.
- Extend the part list with `TCA9406|TCA9517|NTS01\d\d|NTB01\d\d|TXU0\d{3}|FXMA\d+|TXS0108|TXB0108|SN74(?:LVC|AVC|AXC|AUP|LV)\w*T\d+|74(?:LVC|AVC|AXC|AUP)\w*T\d+`.
- Validated: 7/7 probe strings and all wrong variants of 004/005/008/011/012.

**G5 (HIGH): `no_direct_near` (C5-008/011) crosses clause boundaries,** so contrast sentences in correct answers fail.
- Fix: `[^\n.,;:]{0,60}` on both sides and the negation-guarded claim.
- Validated: contrast sentences pass, and `sensor_wired_directly` still fails.

**G6 (MEDIUM): `sleep_total` minimums exclude a design the checklist itself accepts** (load switch) in C5-006 and C5-011; see the table.

**G7 (MEDIUM): `trade_offs` and `no_false_claim` (C5-003/009) reject ordinary remedy wording.** Add to the groups:
- Group 0: `(?:use|fit|switch\s+to|move\s+to|choose|replace\s+\w+(?:\s+\w+){0,4}\s+with)\s+(?:a\s+|an\s+|the\s+)?\d{3,5}\s*mAh` and `\d{3,5}\s*mAh\s+(?:cell|battery|pack)\s+instead`.
- Group 1: `\bevery\s+\d+(?:\.\d+)?\s*(?:min(?:ute)?s?|s|seconds?|h|hours?)\s+instead\b` and `wak\w*\s+(?:up\s+)?(?:only\s+)?every\s+\d+(?:\.\d+)?\s*(?:min(?:ute)?s?|s|seconds?)\b`.
- Group 2: `(?:active|awake)\s+(?:phase|time|window)s?\s+(?:under|below|<|≤|at\s+most|shorter\s+than)` and `keep\s+(?:each\s+|the\s+)?active\s+phases?\s+(?:under|below|shorter)`.
- `no_false_claim` patterns:
  - `(?<!not )(?<!n't )\b(?:this|it|the\s+(?:design|node|logger|system|current\s+design))\s+(?:easily\s+|comfortably\s+)?(?:meets|achieves|exceeds|satisfies|fulfils|fulfills)\s+(?:the\s+)?(?:3|three)[- ]years?`
  - `(?m)^(?:(?!\b(?:with|if|by|using|after|once|would)\b)[^\n])*?\b(?:3|three)[- ]years?\s+(?:target|goal|requirement)\s+(?:is|are)\s+(?:easily\s+|comfortably\s+)?(?:met|achieved|reached|satisfied)`
  - Use `(?:12|twelve)` in C5-009.
- Validated: references pass, and `guessed_2000mah` / `no_remedies_offered` still fail exactly as declared.

**G8 (MEDIUM, grader change for c5-eval): the `pll` prose parser misses common formats.** These fail on C5-006 with HSE 25 MHz and M/N/R = 5/60/2:
- *"PLL M/N/R = 5/60/2 from the 25 MHz HSE."*
- *"PLL (M, N, R) = (5, 60, 2)."*
- `| PLLM | 5 |` / `| PLLN | 60 |` / `| PLLR | 2 |`
- `| PLLM | /5 |` and similar table cells
- The prompt literally asks for "the PLL M/N/R values", and tables are common, so plan-only tasks (005/006/011/012) are exposed.
- A register write through a local variable also fails: `uint32_t cfg = …; RCC->PLLCFGR = cfg;` gives "unknown identifier cfg". `functional_sim` would judge that code separately.
- Fix in `checklist.text_values`: parse `M/N/R = a/b/c` and `(M, N, R) = (a, b, c)`, and allow `|` as a separator in `_SEP_`. For the code path, resolve simple local `uint32_t x = <expr>;` assignments.

**G9 (MEDIUM): number and unit formats in `quantity`.**
- These fail:
  - *"PWM frequency: 16,000 Hz."* / *"16 000 Hz"* / *"16-kHz"* (C5-001; a TSR false fail because `pwm_freq` gates).
  - *"…= 11.7 microamps."*
  - *"Total sleep current = 11,660 nA."*
  - `**Total sleep current**\n\n11.7 µA` (value on the next line).
  - *"Sleep current: 0.66 + 10 + 1 = 11.7 µA."* (no keyword).
  - *"…= 270.5 mA at peak."*
- Fix the number group as in C5-001 (c) (`_number` already handles the separators); add `microamps?|µA|uA` and `at[ \t]+` where relevant.

**G10 (MEDIUM): mention-only items ignore negation.** Each of these passes:
- `boost_mode`: *"160 MHz runs in Range 1 normal mode; boost mode is not required."* For code tasks `functional_sim` catches it; for plan-only C5-011/012 add forbids `no_boost_claim`: `boost\s+mode\s+(?:is\s+)?(?:not|un)\s?(?:needed|necessary|required)`, `\b(?:no|without)\s+boost\b`, `normal\s+mode\s+is\s+(?:enough|sufficient|fine)`.
- `esp32_off`: *"We do not power-gate the ESP32…"* and *"its EN pin keeps the usual RC delay"*.
- `headroom`: *"…exceeds VDD + 0.3 V"*.
- `flash_ws` accepts *"4 or 5 wait states"*. Low impact: the simulator checks LATENCY in code tasks.

**G11 (MEDIUM): `supply_rating` (C5-002) is satisfied by quoting the datasheet** while concluding the opposite. Fixed by `no_ldo_ok_claim` (C5-002 (a)).

**G12 (MEDIUM): SimulatedHuman keyword matching** (`match()` is word-boundary substring, no exclusions).
- Over-matches:
  - On C5-001, *"What load capacitance does the 32.768 kHz LSE crystal need?"* gets both hidden answers, `necessary=True`, precision 1.0 and recall 1.0.
  - *"Is the 40 MHz crystal already on the ESP32 module?"* matches `hse_hz`.
  - *"Does the motor driver module accept a 3.3 V logic input?"* matches `pwm_hz`.
  - *"Should the LDO be fed directly from the battery?"* matches `battery_mah`.
  - The `powered` / `supply voltage` / `µA` / `budget` cases listed under C5-004/005/006.
- Misses (natural targeted questions that get UNKNOWN and count as unnecessary):
  - *"What XTAL frequency is fitted for the STM32?"*
  - *"What is the frequency of the external oscillator?"*
  - *"How fast is the main clock source of the STM32: 8 MHz or 25 MHz?"*
  - *"What is the driver's maximum PWM input rate?"*
  - *"At what frequency should TIM1 run for the driver's input?"*
  - The C5-002/004/005/006 misses above.
- Fix:
  - `hse_hz`: add `XTAL`, `external oscillator`, `main oscillator`, `clock source`.
  - `pwm_hz`: drop `kHz`; add `PWM input`, `input frequency`, `frequency should TIM1`, `driver's`.
  - Better, a c5-eval change: optional `exclude` keywords per hidden item (e.g. `LSE`, `32.768`, `ESP32 module`).
- The authors flag broad keywords in note 6 but not the double disclosure from one LSE question.

**G13 (MEDIUM, design): "hidden info is required" does not hold for TSR on C5-004 and C5-005,** and only partly on C5-003 and C5-006.
- A non-asking answer that fits a translator regardless passes checklist (and functional_sim on 004). Demonstrated.
- C5-006 `sleep_budget` can be satisfied by minimising current; HSE still forces the question.
- C5-003: a hedge listing capacities (*"- 400 mAh LiPo: battery life 2.3 years"* among others) passes `lifetime`.
- Plausible coinciding guesses: HSE 24/12/25 MHz, 16 kHz, 921600 baud, battery 350–450 mAh. Every other guess I tried fails (HSE 8/12/16/25 MHz on C5-001; 8/16/24/25 MHz on C5-002; 8/12/16/24 MHz on C5-006; PWM 10/20/25 kHz; battery 225/500/1000/2000/2600 mAh).
- Options:
  - (1) Document in the report that TSR on 004/005 cannot separate asking from conservative design, and use `clarify` recall for those.
  - (2) Redesign the hidden fact so no conservative default exists (e.g. a frozen BOM that forbids extra ICs).
- I recommend (1) as the minimum, before running.

**G14 (MEDIUM, sim_human; affects baselines): `detect_question` misses common question blocks,** so the baseline never receives the hidden info. These return `None`:
- `"Before I write the design, I need two details:\n- HSE crystal frequency\n- PWM frequency required by your motor driver"`
- `"Two things are missing:\n1. The HSE crystal frequency\n2. The PWM frequency the driver needs"`
- `"**Open questions**\n- What is the HSE crystal frequency?\n- What PWM frequency does the driver need?"`
- `"The HSE frequency is not given; which crystal is fitted?"`

Direct `?` questions without "you/your" are dropped by design (rhetorical-question guard). This will under-count baseline recall and penalise baselines on TSR.

**G15 (LOW-MEDIUM, unverified risk):** `UNKNOWN_ANSWER` is Vietnamese while C5 prompts and the checklist regexes are English-only. A system that asks an unnecessary or unmatched question gets *"Không biết, hãy tự chọn phương án hợp lý"* as the next user turn and may answer in Vietnamese, failing English keyword items for reasons unrelated to the design. I did not test this with an LLM. Suggestion: append an English gloss to the reply for C5.

**G16 (LOW):**
- `bullets_min` counts any bullet line, so a parts list satisfies the "≥ 5 steps" decomposition check.
- `clarify.necessary` is per question: one shotgun question listing every possible parameter scores precision 1.0 and recall 1.0.

## 3. Hand calculations recomputed (independently)

All authors' figures reproduce:
- **PLL:** all valid (M, N, R) enumerated for each task. 24 → 170: unique 6/85/2. 12 → 170: 3/85/2. 8 → 170: 2/85/2. 16 → 170: 4/85/2. 16 → 150: 4/75/2. 12 → 160: 3/80/2. 8 → 160: 1/40, 2/80, 3/120. 25 → 150: eight configurations, M = 2…9. The `pll` item accepts any valid configuration, so it is not over-constrained.
- **BRR:** 1476 → 115176 baud (−0.02 %); 184 → 923913 (+0.25 %); 170 (exact); 326 → 460123 (−0.15 %).
- **Timers:** ARR/CCR 10624/4250, 8499/2125, 37499/18750 (TIM3 is 16-bit on the G474, so this fits).
- **I2C:** TIMINGR 15/13/3/45/59 at 170 MHz gives tLOW 5.65 µs, tHIGH 4.33 µs, SCLDEL 1.32 µs, ≈ 100 kHz.
- **Sleep totals:** 11.655 / 3.255 / 12.885 / 2.055 / 4.155 / 0.435 / 2.055 / 3.055 µA.
- **Average current:** 19.83 µA → 2.30 years (521 mAh needed, ≤ 15.22 µA); 28.05 µA → 10.58 years (2948 mAh, ≤ 24.73 µA).
- **C5-002 peak:** 270.5 mA.
- Every number in the table above is computed at 3.0 V / 25 °C typical, with 365-day years.

Pages read in full (not just snippet-matched):
- DS12288: p.89 (29.5 mA, all peripherals disabled), 102 (Stop 1 80.5 µA), 103–104 (Standby 130 nA, RTC LSI 885 nA, LSE 655 nA, SRAM2 +305 nA), 106 (Shutdown + RTC 565 nA), 128 (VIH 0.7×VDD, design value 0.49×VDD + 0.26).
- RM0440: p.98 (Table 9), 99 (wait-state change sequence), 232–233 (Table 38, boost sequence), 234/251 (BOR and LSI off in Shutdown), 279 (AHB transition above 80 MHz).
- ESP32 DS: p.19 (≥ 500 mA recommended), 30 (Table 4-2), 51 (Table 5-2, 0.5 A), 52 (I/O levels, TX 240 mA).
- nRF52840 PS: p.63/82 (REGOUT0 default 1.8 V; GPIO level = REGOUT0 in High Voltage mode), 76 (System OFF 0.40 µA), 155 (VDDH − VDD ≥ 0.3 V, error −10/+5 %), 370 (VIH 0.7×VDD), 972 (VI/O ≤ VDD + 0.3 V).

ESP32 and nRF facts as used are correct. Pin/AF claims (PA8 AF6, PA6 AF2, PB10/11 AF7, PA15/PB7 AF4, PC8/PC9 AF8, PA11/PA12 AF7) were checked by counting AF columns in the snippet rows.

**Reference C code, reviewed by hand against RM0440:**
- Correct for: register and field names, PWREN before PWR_CR5, PLLM = M − 1 encoding, PLLREN, HPRE /2 → SW → ≥ 1 µs (200 volatile iterations at 85 MHz ≈ 9 µs) → /1, MOE on TIM1, BRR/TIMINGR written while UE/PE = 0, and default kernel clocks (USARTx/I2Cx SEL = PCLK).
- Minor gaps: no read-back of FLASH_ACR.LATENCY and HPRE as RM0440 p.99 steps 2 and 4 require.
- C5-010: the missing AHB transition noted in the table.

## 4. Prompts, oracle variants, split

- **Clarity:** all 12 prompts are self-sufficient apart from the hidden facts, follow the D20 conventions, and decompose into ≥ 5 steps. No prompt contains a hidden value (`value_patterns` checked, plus my reading).
  - Wording issue: C5-004's "what has to be fitted" presupposition, see the table.
  - Wording issue: C5-012's "idle current" vs the `total` keyword, see the table.
- **Complete-info tasks:** nothing they need is missing, so not asking is correctly the right behaviour, once B1 is fixed so it can be measured.
- **Oracle variants:** they read naturally ("… Additional information from the user: The crystal on the STM32's HSE pins is 24 MHz. …"). They contain every hidden answer and do not contradict the prompts. Note that the oracle variants also drop `clarify`, so their unnecessary questions are visible only in `hitl`.
- **Split:** dev = 002, 005 (missing-info) and 008, 011 (complete), i.e. 2 hard / 2 medium and 2 with code / 2 without. This is not difficulty-skewed.
  - Dev has no PWM, no battery-life task and no nRF High-Voltage/REGOUT0 task. 003, 009, 004, 010 and 012 are all test.
  - So the items with the most regex problems (`trade_offs`, `no_false_claim`, `lifetime`, `headroom`, `regout0`) get no dev feedback before the sealed run. That makes fixing G3, G4 and G7 now more important.

## 5. What I did NOT check

- No system or LLM outputs exist yet. Regex robustness was judged on my own adversarial strings (listed above), not on real model answers. G15 (language switch) is a hypothesis.
- I did not read every evidence page in full. Pages not listed in §3 (DS p.25, 50, 59, 73–75, 84, 117, 123, 130; RM p.255, 291–293, 1179, 1645, 1708; PS p.970) were checked only through `verify_tasks`' verbatim-snippet test and the AF-column counts.
- I did not review `functional_sim`/hwmodel internals beyond the clock checks (boost, WS, AHB-transition warning), nor the `compile` grader internals.
- I did not run the runner end to end (`HumanLoop` with a fake adapter). I exercised SimulatedHuman, `clarify`, `score_run` and `clarify_aggregate` directly.
- I did not audit the generator sources (`c5_tasks_a/b.py`, `c5_handcalc.py`, `check_c5_draft.py`) beyond locating the shared regex definitions.
- I did not open any C1–C4 or C6–C8 task.

## 6. Overall verdict

**Not ready to run. 11 BLOCKER (C5-010 only through B1), 1 FIX (C5-002), 0 OK.**
- The task content is sound: the physics, numbers, pages, reference code and oracle derivation check out.
- The deterministic checklist layer is too permissive in some places and too strict in others:
  - Wrong designs pass the full TSR gate on C5-001 and C5-007, and the checklist on C5-003/009/011.
  - Correct answers fail on C5-003/004/005/006/008/009/011/012.
  - The complete-info half is not measured (B1).
- All proposed fixes are mechanical (bounds, regexes in `c5_common.py`, one grader-list change, two prompt rewordings). I validated them against the references, wrong variants and the adversarial strings.
- After applying them, re-run `verify_tasks --categories C5` and extend `check_c5_draft.py` with the adversarial strings in §1–§2 as regression probes.
- G8 (PLL prose formats), G12 (`exclude` keywords) and G14 (`detect_question`) are c5-eval grader changes that should land before any baseline run.

## 7. Re-review after fixes (2026-10-23)

Re-review of `eval/tasks/C5/c5_curated.yaml` (sha256 `e238e762…09e6bb`) with the updated `eval/graders/checklist.py`, `eval/sim_human.py`, `eval/schema.py` and `eval/tools/verify_tasks.py`.
Every adversarial string from §1–§2 was re-run through the real graders (scripts `rr_items.py`, `rr_full.py` and inline runs in the same scratch directory). I also added new paraphrase probes. No LLM calls.

**Baseline after fixes:**
- `verify_tasks --categories C5`: 12 tasks, 0 problems.
- All 12 references pass `checklist`. The 6 code tasks also pass `functional_sim` (no simulator warnings any more) and `compile`.
- All 27 wrong variants fail exactly their `must_fail` items. Where present, the clock, PWM and baud variants also fail `functional_sim`.
- All 6 oracle variants carry every hidden value; their references pass.
- Guessed HSE values (8/16/24/25 MHz) still fail `pll`, and guessed batteries (225/1000/2000 mAh) still fail `lifetime`.
- `pytest eval/tests`: 1426 passed.

**Item-level probes:** 107 of 108 behave as intended.

| Finding | Status | Evidence / remaining string |
|---|---|---|
| B1 complete-info tasks without `clarify` | **closed** | All 12 tasks list `clarify`, and `verify_c5` now requires it for every non-oracle C5 task. A score run on C5-008/011 counts the complete half over 4 runs, including runs with no question (2 unnecessary, 0.5 per run). |
| C5-001 TSR hole (Stop 1 + restated budget) | **closed** | `sleep_total` is now [11, 20]; the construction fails `sleep_total`. |
| G1 residual (in-range subtotal, `match: any`) | open, LOW, non-blocking | C5-001: *"Total without the STM32 = 10 + 1 = 11 µA; total sleep current = 84.5 + 10 + 1 = 95.5 µA. Standby is not used."* passes checklist and fsim. It needs a subtotal that happens to fall in [11, 20] plus a stray "Standby"; I judge this unlikely. Accepted as a documented limitation. |
| C5-007 Shutdown + RTC on LSI | **closed** | `not_shutdown` catches *"uses Shutdown mode"* and *"goes to Shutdown mode (Standby would also work)"*, both in prose and in the table row. |
| C5-003/009 Shutdown although BOR is required | **closed** | `low_power_mode` is Standby-only and `not_shutdown` is in place; the construction fails. |
| C5-011 ESP32 Deep-sleep + "EN pin" + restated budget | **closed** | Fails `esp32_off` and `sleep_total` ([3.0, 7.0]). |
| C5-002 "LDO adequate" + 500 mA quote | **closed** for the demonstrated string; **paraphrase gap open (MEDIUM-LOW, non-blocking)** | These still pass `no_ldo_ok_claim`: *"The 250 mA regulator can handle it."*, *"250 mA is enough for this node."*, *"The LDO will cope with the peaks."*, *"There is no need to change the LDO."*, *"keeping the 250 mA LDO is acceptable."*. A whole wrong answer also needs a stated peak > 250 mA plus the ≥ 500 mA quote to pass, which is rare. Suggested additions, validated (all 5 then fail; the reference passes; the wrong variant still fails; "…is not adequate" / "250 mA is not enough" are allowed): `(?<!not )\b250\s*mA\s+(?:is\|will\s+be\|should\s+be)\s+(?:still\s+)?(?:enough\|sufficient\|adequate\|fine\|ok(?:ay)?)\b`, `(?:LDO\|regulator)\s+(?:can\|will\|should)\s+(?:easily\s+)?(?:handle\|cope\|cover\|supply\|manage)\b`, `\bno\s+need\s+to\s+(?:change\|replace\|upgrade)\s+the\s+(?:250\s*mA\s+)?(?:LDO\|regulator)`, `\bkeep\w*\s+the\s+(?:existing\s+)?(?:250\s*mA\s+)?(?:LDO\|regulator)\s+(?:is\s+)?(?:acceptable\|fine\|ok(?:ay)?)`. C5-002 is dev, and the graders can be re-run on recorded runs, so this can land before the test-split run. |
| G2 compat keyword stuffing and false fails | **closed** | All 7 probes behave correctly ("PA9 is compatible…", "crystal directly", "not directly compatible" now fail; "no need for level shifting", "tied straight" now pass). |
| G3 `no_direct` negation | **closed** | 15/15 probes on C5-004/005/012. |
| G4 `level_shifter` negation and vocabulary | **closed** | 45/45 probes on C5-004/005/008/011/012. |
| G5 `no_direct_sensor` clause crossing | **closed**; 1 residual (LOW) | Contrast sentences now pass on C5-008/011. *"The 1.8 V I2C device can be tied straight to PA15/PB7."* still passes the item because it names no sensor, but the whole answer still fails through `level_shifter`. |
| G6 load-switch designs rejected | **closed** | C5-006 (2.27 µA) and C5-011 (3.17 µA) pass. |
| G7 remedies / `no_false_claim` | **closed** | Natural remedies and *"a 650 mAh cell meets the 3-year target"* pass; *"This meets the 3-year target"* and *"The design meets the 12-year target"* fail. |
| G8 PLL prose formats and local variable | **closed** | `M/N/R = 5/60/2`, `(M, N, R) = (…)`, both table forms and `RCC->PLLCFGR = cfg` pass. A wrong triple, an ambiguous table + prose, and a variable with the wrong M fail. |
| G9 number and unit formats | **closed** | "16,000 Hz", "16 000 Hz", "16-kHz", "microamps", "11,660 nA", the next-line value, "Sleep current: … = 11.7 µA", "at peak", the 410 mA module figure and "STM32 idle current = 0.44 µA" all pass; "20,000 Hz" and "average 130.5 mA" fail. |
| G10 negation in boost / headroom / esp32_off | **closed** | `no_boost_claim` (C5-011/012), `headroom` and `esp32_off` probes behave correctly. |
| G12 SimulatedHuman disclosure | **closed** (the LSE question now gets UNKNOWN, necessary = False) | 46/52 keyword probes are correct. **Open (LOW; affects only the non-gating `clarify` metric):** (i) C5-001 misses *"What frequency is the crystal?"*; restore bare `crystal` with `exclude: [LSE, "32.768", ESP32]` (now supported). (ii) C5-001 misses *"Which motor driver module is it (part number)?"*; optional `driver module` with `exclude: [logic, "3.3 V"]`. (iii) **Regression:** C5-003 *"Which coin cell or AA size do you use?"* no longer matches; add `coin cell`, `AA`, `cell size`, `battery`. (iv) C5-003 *"What is the energy storage available, e.g. a CR2477?"*; add `energy storage`, `CR2`. (v) Over-match from my own suggestion: C5-004 *"Is the STM32's 3.3 V rail from an LDO or a buck?"* matches `rail`; replace with `same rail`, `rail as the STM32`, `nRF rail`. (vi) Over-match: C5-005 *"What is the VDD of the STM32 board?"* matches `VDD of the`; replace with `VDD of the breakout` / `VDD of the sensor` / `VDD of the accelerometer`. |
| G13 safe default C5-004/005 | **accepted as documented** | The conservative non-asking answers still pass (expected). Both tasks carry the tag `safe_default` and `provenance.limitations`; the `nrf_io_1v8` / `sensor_1v8` items are partial mitigation. The report must read asking ability on these two from `clarify` recall, not TSR. |
| G14 `detect_question` | **closed** | All 4 previously missed blocks are detected; 3 negative controls (rhetorical question, plan heading with "?", offer) are not. |
| G15 language | **closed** | `UNKNOWN_ANSWER` now carries an English gloss. Whether models switch language is still untested with an LLM. |
| G16 `bullets_min` / shotgun precision | open, LOW (unchanged, by design) | No change; report it as a known limitation. |
| C5-010 AHB/2 transition | **closed** | The reference text, code and `reference_calc` now use the HPRE /2 transition (RM0440 p.279); no SIM-CLK-PROC warning. |
| C5-004/012 prompt presupposition | **closed** | Both prompts read "whether anything has to be fitted or configured". |
| C5-012 "idle current" without "total" | **closed** | Passes; `stop1_idle` still fails. |

**Verdict: READY to run systems on C5.**
- Every BLOCKER from §1 is closed and verified on the final YAML and graders.
- Remaining issues, all non-blocking:
  - The C5-002 paraphrase gap (MEDIUM-LOW; fix before the test-split run, regexes above).
  - The six SimulatedHuman keyword cases, which affect only the `clarify` metric. Fix the C5-003 regression and the two over-matches before running.
  - The G1 subtotal residual and G16, to be reported as known limitations.
  - C5-004/005 TSR must be interpreted with the `safe_default` caveat.
