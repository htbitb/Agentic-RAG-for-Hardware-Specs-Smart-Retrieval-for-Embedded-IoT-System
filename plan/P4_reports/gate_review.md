# P4 — Independent review of Gate v3

Reviewer: independent subagent (I did not write the gate). Scope: `agent/agent/gate/*.py`, `agent/tests/test_gate_*.py`, how `agent/agent/runtime/loop.py` and `flags.py` use the gate, against `plan/P4_interfaces.md` §2/§4 and `plan/P4_Handoff.md` "Bước 3". No file under `agent/`, `eval/`, `snapshots/` or `plan/` was modified except this report.
Every case below was run through `Gate(call).run(ctx)` with the real tool functions (Board State in a temporary DB, analyzer, simulator, clang, hw-knowledge). Nothing used the network or an LLM. The scripts are in `/private/tmp/claude-501/-Users-loc4atnt-Master-Course-Ky3-AgenticAI-project/ff56cc68-8a5f-4c62-a87c-6c5ef9dd7c8d/scratchpad/review_gate/` (`h.py` is the harness; `d1.py` re-runs the real D1 run from a copy of its checkpoint and Board State).
Baseline: `agent/.venv/bin/python -m pytest agent/tests/test_gate_*.py -q -p no:cacheprovider` → 159 passed in 3.8 s.

## Verdict

**Spec ❌ · Quality: not approved.**

- **Spec.** The gate follows P4_interfaces §2 closely, and the four deviations it declares are acceptable (see "Deviations" below). It misses three requirements, though.
  - **Start state.** Handoff Bước 3 says `simulate_register_writes(initial=<trạng thái từ Board State/đề>)`. The gate and the runtime instead take the start state from the agent's own last simulation (Critical 2).
  - **"Never counted as a pass".** The contract says this for `unmodeled`, tool errors and `skipped`. In practice all three end in an accepted answer (`passed=True`), and a waived requirement shows up as `G2: "pass"` (Critical 1, Important 7).
  - **G4 "do not advise above Absolute Maximum".** This is not met for Vietnamese answers, which is the language the agent actually answers in (Important 5).
- **Quality.** The code is clean, fast (0.06–0.20 s per `Gate.run` on the real D1 answer), deterministic, and does not mutate its inputs. It is not approved because of:
  - a fail-open path that ordinary agent output can trigger (`"tol_pct": null`);
  - several reproducible false passes in the dangerous direction;
  - false fails on correct Vietnamese, formatted-number and snippet answers, which use up the 3-round repair budget.

## Findings

### Critical

**C1. Fail-open: G2 internal errors and errors caused by the agent's own input become `skipped`, and the runtime accepts the answer as `passed`**
- **Evidence.** The code is PWM_C with `TIM1->PSC = 1` (10 kHz, wrong). Board State requirement R1: pwm, PA8, 20 kHz, 25 %, satisfied, plus one extra field. `initial` is the 170 MHz preset. Results:

  | What triggers it | Observed output |
  |---|---|
  | R1 recorded with `"tol_pct": null` (`set_requirements` accepts it) | `passed=True`, G2 `skipped`, `G2-INTERNAL-ERROR` (unknown): `TypeError: float() argument must be ... not 'NoneType'` |
  | Same with `"duty_tol_pp": null` | Same result |
  | Requirement `"initial": "170mhz"` (typo) | `passed=True`, `G2-TOOL-ERROR` (unknown): `unknown initial state '170mhz'` |
  | Agent's last `simulate_register_writes` failed on a typo preset, runtime `ctx.initial="reset"` | `passed=True`, G2 `skipped` |
  | Code with `for (int i = 0; i < 3000; i++) { TIM1->CCR2 = 1; }` | `passed=True`, `G2-TOOL-ERROR`: `too many ops (3011 > 2000)` |

- **Where in the code.**
  - `functional.py:212,213,327,343,357`: `float(r.get("tol_pct", …))` crashes on an explicit `null`.
  - `functional.py:120`: `resolve_start` takes the last simulation observation even when that simulation errored.
  - The analyzer unrolls up to `LOOP_CAP = 4096` iterations (`hwmodel/codeparse.py:32`), but the server refuses more than `MAX_OPS = 2000` ops (`mcp_servers/hw_sandbox_server.py:19`).
  - `__init__.py:130-135`: any exception sets the gate to `skipped` with an `unknown` finding.
  - `types.py:49-50`: `passed` ignores `skipped`.
  - `loop.py:338`: the runtime accepts on `passed`, so `_InternalFailure` (fail-closed) is never reached.
- **Why it matters.** Wrong code is delivered as verified. The trace records `gate_result.passed=true` and `finish.accepted=true`, so these runs also count as gate passes in the process metrics. The independent grader calls the vendored simulator with no 2000-op cap and would fail the code: a "Gate cho qua – grader trượt" case. LLMs often emit `null` for optional JSON fields.
- **Suggested fix.**
  - Treat missing values as defaults: `float(r.get("tol_pct") or default)`.
  - Errors caused by the answer or the requirements (bad `initial`, too many ops, `ValueError` from the simulator) should be `G2-…` **error** findings with kind local. Only real infrastructure failures (timeouts, missing toolchain) should be `unknown`.
  - `resolve_start` should skip observations whose result has an `error`.
  - An internal exception in G2 should fail closed (error) when the answer has code and a modelable requirement.
  - The runtime, or the contract, should not accept an answer when G2 is `skipped` but code and modelable requirements exist. At minimum, record `verified=false` so metrics do not count it as a pass.

**C2. The start state comes from the agent's own last simulation, not from Board State or the task. This produces both a false fail (the D1 demo's only "self-correction") and false passes**
- **Evidence, false fail (the real D1 run).**
  - Reproduced with `d1.py`, using the real observations and Board State.
  - The agent simulated only `TIM1_PA8_PWM_Init` with `initial="sysclk_170mhz_pll_hsi16_apb_div1"` (trace seq 37–39).
  - The runtime copies that preset into `ctx.initial` (`loop.py:378, 322`).
  - The gate then simulated the **full** draft#1, including `SystemClock_Config`, starting from a chip already running at 170 MHz. `FLASH->ACR &= ~FLASH_ACR_LATENCY;` therefore produced `G2-SIM-FLASH-WS @ code block 1, line 9, op 0`.
  - Starting from `reset` (how the chip actually boots), the same draft#1 gives `passed=True` (only a `G2-SIM-CLK-PROC` warning).
  - So the "sim fail → fix → pass" shown in `plan/demos/D1/summary.md` is an artifact of the start-state rule, not an agent error.
- **Evidence, false pass.**
  - The agent's simulation used `initial={"preset": CLK170, "ops": [set RCC_APB2ENR.TIM1EN, set TIM1_BDTR.MOE]}`. The inproc hub passes the dict through.
  - The answer's code has **neither** the TIM1 clock enable **nor** MOE.
  - Result: `passed=True`, all five gates `pass` (scratch `adv_g2b.py`, case A2).
  - The same mechanism without a dict: code with no clock configuration passes a 20 kHz requirement after the agent simulated a timer snippet on the 170 MHz preset. This is already pinned by `test_the_last_agent_simulation_sets_the_start_state_when_the_runtime_gives_none`. If the task's `initial` is `reset` (10 of the 35 `initial:` entries in `eval/tasks/C3,C4`), the grader then sees 1.88 kHz.
- **Where in the code.** `functional.py:106-127`, `loop.py:322, 378`. P4_interfaces §2.3 narrowed the Handoff's "from Board State/task" to "requirement > agent's last simulation > reset".
- **Suggested fix.**
  - Take the start state from Board State or the task: the clock config recorded by `set_clock_config`, or a required `initial` on the requirement.
  - Never inherit `initial.ops` from the agent.
  - If the answer's own code configures the clock (writes `RCC_CFGR.SW` or `RCC_PLLCFGR`), simulate from `reset`.
  - Put the start state and its source in the `gate_result` event.
  - Re-label the D1 demo.

**C3. G1 does not see values the agent writes in LaTeX, inline code, non-C fences or unit-less table cells, so invented numbers pass**
- **Evidence.** Each answer below was checked with `get_electrical_specs("stm32g474","supply voltage")` in the observations (the true Absolute Maximum is 4.0 V). Every one gives `passed=True`, G1 `pass` (scratch `g1.py`, `g1f.py`):
  - `The absolute maximum VDD is $V_{DD,max} = 4.6\,\text{V}$ [STM32G474_Datasheet p.82].`
  - `… is $4.6\text{ V}$ …`
  - `` … is `4.6 V` … ``
  - ```` ```text\nVDD absolute maximum: 4.6 V\n``` ````
  - An untagged fence with the same line
  - `| VDD absolute maximum | 4.6 | V |`
  - `` TIM1 base address is `0x40013C00` `` (an invented address)
- **For comparison.** The plain-text forms are caught: `4.6 V` gives `G1-V1`, and `0x40013C00` gives `G1-V2`.
- **The real D1 answer.** G1 checked only 6 claims. `$170\text{ MHz}$`, `$20\text{ kHz}$`, `$20.000\text{ kHz}$`, `$50\ \mu\text{s}$` and `170\,000\,000` were never checked.
- **Where in the code.** `codeblocks.py:98-100` strips *every* fence and all inline code from the prose. `_QTY_RX` (`ingestion/unit_normalizer.py:42`) needs the number and the unit side by side.
- **Why it matters.** G1 is the system's grounding claim, and the production model (gemini, see D1) writes LaTeX by habit.
- **Suggested fix.**
  - Normalise LaTeX before extracting claims: `\text{…}`, `\mathrm{…}`, `\,`, `\ `, `~`, `$`.
  - Check quantities and hex inside inline code and inside non-C fences; strip only fences that G2 actually analyses.
  - For tables, carry a "unit" column header over to its cells.

### Important

**I1. Once a requirement is marked `satisfied` (DRC-REQ-01 forces this before every finish), code on the wrong pin or instance, or no code at all, passes with only a warning**
- **Evidence.** R1 (PA8, TIM1_CH1, 20 kHz) is `satisfied` with evidence `sim#1`.
  - Code generating PWM on **PA9**/TIM1_CH2 gives `passed=True`, G2 `pass`, warning `G2-NOT-IN-CODE`. Same result with PA9 at 170 kHz.
  - R-UART (USART2) satisfied, answer configures **USART1** → `passed=True` (scratch `fp2.py`, case C2b).
  - Code in a ```` ```text ```` fence, or no code at all → `passed=True` with warning `G2-NO-CODE`.
  - With R1 `pending`, the same inputs fail correctly (`G2-PIN` / `DRC-REQ-01`).
- **Where in the code.** `functional.py:379-394` (`_touched`), `functional.py:462`, `functional.py:412-417`.
- **Why it matters.** D1 shows the agent marks requirements satisfied *before* finishing (trace seq 42). A rewrite between that agent simulation and the final answer is therefore never re-checked. The grader fails all of these cases.
- **Suggested fix.**
  - Apply the "not re-checked" rule only to requirements satisfied in an *earlier turn* (not in this turn's observations), and only when the code has no effect of that requirement's kind (no PWM, no USART at all).
  - Make `G2-NO-CODE` an error when this turn set or satisfied a modelable requirement.

**I2. G1 derivation still accepts the typical wrong values (×2 / ÷2 errors), and the 4 % residual in the implementer's report understates this**
- **Evidence.** With the real D1 observations and goal (`g1c.py`), these claims all pass:
  - "TIM1 clock is 85 MHz" (`1.7e+08 / 2`)
  - "PWM is 10 kHz" (`20000 / 2`)
  - "PWM is 40 kHz" (`1.7e+08 / 4249`)
  - "PCLK1 42.5 MHz" (`/4`)
  - "HSE 8 MHz" (`4e+06 x 2`)
  - "TIM1 clock 340 MHz" (the VCO value, accepted directly)
  - Only "VCO 320 MHz", "21.25 kHz" and "VDD max 3.6 V" fail.
- **Where in the code.** `provenance.py:297-303`: any divider (PLL `r=2`, `m=4`, candidate ARRs) from the same tool result divides any quantity.
- **Why it matters.** Real errors are not random 3-digit numbers. They are exactly the factor-of-2 mistakes (forgetting the APB ×2, PSC off by one) that this rule blesses.
- **Suggested fix.** Verify only arithmetic the answer itself shows (operands in the same expression, e.g. `170 MHz / 8500`). Alternatively, pair a quantity only with the dividers of the same record that belong to it (the timer clock with PSC/ARR of the same solver or effect entry).

**I3. Agent-authored text is counted as evidence, contradicting the implementer's own rulings**
- **Evidence.**
  - (a) *Prior answers are parsed unit-blind, including their code blocks.* With the D1 answer as `prior_answers`, these turn-2 claims pass as "user": "The absolute maximum VDD is 13 V" (from "13 bit"), "Each GPIO can sink at most 25 mA" (from `$25\%$`), "USART2 kernel clock is 98 MHz" (from "trang 98"), "8499 mV".
  - (b) *Requirement free text.* `set_requirements([{id:"R9", type:"other", evidence:"datasheet: VDD absolute maximum 4.6 V", description:"supply rated 4.6 V"}])`. Answer "The absolute maximum VDD is 4.6 V." → G1 `pass`, supported by "computed", **no citation needed**.
- **Where in the code.** `provenance.py:117` calls `_text(..., "c", user=False)` on the whole prior answer. `provenance.py:286` makes every class-c bare number unit-blind. `AGENT_TEXT_KEYS` (`provenance.py:31`) lacks `evidence` and `description`.
- **Why it matters.** Multi-turn C4 tasks lose most of G1's protection from turn 2 onward, and a hallucinating agent writes its belief into `evidence`.
- **Suggested fix.**
  - For prior answers, use only quantities with units and hex values, from the prose only, and not unit-blind.
  - Treat every free-text string field of Board State as agent text (`evidence`, `description`, `notes`, `name`, `title`, `summary`); take only typed numeric fields.

**I4. False fails on correct answers caused by number and citation formatting**
- **Evidence.** All of these are correct values (`fp.py`, `g1.py`, `g1b.py`):
  - `= 20,000 Hz` → `G1-V1 … 000 Hz has no source`
  - `170,000,000 Hz` → same
  - Vietnamese `20.000 Hz` → `20.000 Hz has no source; closest … 20000 Hz`
  - Vietnamese decimal comma, `… là 4,0 V …; từ 1,71 V đến 3,6 V` → three `G1-V1` errors: `0 V`, `71 V`, `6 V`
  - Citation `[STM32G474_RM0440, p. 1267]` or `[RM0440 §28.6.20, p.1267]` → `G1-V3 no citation`
  - A safety refusal ending in "use a 3.3 V regulator" → `G1-V1 3.3 V has no source`
- **Why it matters.** Each false fail costs a repair round. Repeated `G1-V1` counts toward the 3-repair limit and can end in ESCALATED. The feedback ("000 Hz", "71 V") does not tell the agent what to change.
- **Suggested fix.**
  - Normalise digit grouping (`\d{1,3}([,.  ]\d{3})+`) and the Vietnamese decimal comma before matching.
  - When a match is directly preceded by `\d[,.]`, emit `unknown` rather than `error`.
  - Parse `[doc, p. N]` and `[doc §x, p.N]`.

**I5. G4's prose check does not detect unsafe advice in Vietnamese**
- **Evidence** (`g4.py`):
  - `You can power the STM32G474 VDD directly from 5 V.` → `G4-ABS-MAX` error ✓.
  - `Bạn có thể cấp trực tiếp 5 V vào chân VDD của STM32G474.` → `passed=True`.
  - `Hãy nối VDD của STM32G474 với nguồn 5 V từ USB.` → `passed=True`.
- **Where in the code.** `safety.py:21-26` (English-only regexes) and the guardrail's English parser.
- **Why it matters.** The users and the agent's answers are Vietnamese (D1), so this G4 check is effectively off.
- **Suggested fix.**
  - Add Vietnamese advice verbs and negation words: cấp, nối, đưa, dùng / không, tránh, vượt, tối đa.
  - Alternatively, use a language-independent rule: a voltage above the Absolute Maximum next to a VDD/VBAT/chip token, with no negation in the clause → warning.

**I6. False fails on correct Q&A snippets that have no requirements (C1/C2-type answers, the S2D strength the brief says must be kept)**
- **Evidence** (`snip.py`, no Board State):
  - "Just the GPIO part" snippet (GPIOA clock + MODER8 + AFSEL8 = 6) → G2 fail with `G2-SIM-TIM-CEN`, `-OCM`, `-CCE`, `-MOE` (end of program).
  - "Show the CMSIS line" answer `TIM1->BDTR |= TIM_BDTR_MOE;` → `G2-SIM-CLK-GATE`.
- **Where in the code.** Declared deviation #2 (`functional.py:173-178`) combined with op-level CLK-GATE on wrapped fragments.
- **Suggested fix.** For wrapped fragments (no function definition) with no requirements, either downgrade end-of-program violations and `SIM-CLK-GATE` to warnings, or simulate with the clocks of the touched peripherals enabled. Keep deviation #2 for complete programs (with `main`).

**I7. A requirement that was waived or not re-checked is reported as G2 `pass`**
- **Evidence** (`waive.py`):
  - Centre-aligned PWM (`TIM_CR1_CMS_0`), which really gives 10 kHz. Without a waiver: `G2-UNMODELED` error ✓.
  - With `waived=[{"id":"R1",…}]`, or with the code-level `{"id":"G2-UNMODELED",…}`: `passed=True` and **`gates.G2 = "pass"`**.
  - NOT-IN-CODE (I1) also yields G2 `pass`.
- **Where in the code.** `__init__.py:188-196`.
- **Why it matters.** The contract says unmodeled is "never pass", but the trace's `gate_result.gates` reports a verified pass. The code-level id also waives *every* unmodeled requirement at once.
- **Suggested fix.** Set G2 to `skipped` (or a new `waived` status) whenever a requirement was waived or not checked, and accept only requirement-id waivers for `G2-UNMODELED`.

**I8. Words in v1's abstain list disable G1 for the whole answer**
- **Evidence.**
  - `The outputs are blocked until MOE is set. The absolute maximum VDD is 4.6 V [STM32G474_Datasheet p.82].` → `passed=True` (abstained).
  - The same happens with "The board refused PA8 at first, …".
- **Where in the code.** `provenance.py:429-432` with `verifier.ABSTAIN = ("insufficient evidence","refuse","cannot verify","not found in the documentation","blocked")`.
- **Suggested fix.** Treat the answer as an abstention only when it has no numeric or hex claims, or when an explicit abstain phrase (e.g. "Insufficient evidence") starts the answer. Otherwise check the claims anyway.

### Minor

- **Citation doc names are matched by substring.** `[S p.82]` and `[Datasheet p.82]` are accepted whenever p.82 was returned for any doc whose name contains the text (`provenance.py:383-384`).
- **A base address derived as address − offset is rejected.** "TIM1 base address 0x40012C00" (BDTR is at 0x40012C44, offset 0x44) → `G1-V2`, although only derivable from the lookup.
- **Requirement ids containing spaces break waiver matching.** `_REQ_REF = ^requirement (\S+)` (`__init__.py:91`) and `loop.py::_unmet_requirements` take only the first word, so a valid waiver for "PWM PA8" is never applied. `set_requirements` accepts such ids.
- **Lookup-only answers show an `unknown` `DRC-CLK-01` (CLOCK_NOT_CONFIGURED) in the feedback** whenever a target exists without a clock config. This is noise for the agent.
- **Fence info strings like ```` ```c:main.c ```` are not recognised as C.** This matches the grader, so it is consistent, but the answer then passes with `G2-NO-CODE`.
- **Runtime: `count_error` treats `G1-V1` as one code.** Fixing claim A and then failing on claim B still counts as a repeat, which leads to early ESCALATED.

## Deviations declared by the implementer: judgement

| # | Deviation | Judgement |
|---|---|---|
| 1 | G1 derivation narrower (one step, unit-aware, same source) | Acceptable and necessary. The residual risk is larger than reported (I2). |
| 2 | G2 checks routed channels without requirements | Acceptable for complete programs. It causes false fails on snippets (I6). |
| 3 | `kind="local"` for unknown infrastructure findings | Acceptable; harmless. |
| 4 | Abstention only in the first 200 characters | An improvement on v1, but still bypassable with common words (I8). |

Not declared: the start-state rule (C2, deviates from Handoff Bước 3, inherited from P4_interfaces); `G2: pass` after a waiver (I7); the code-level waiver ids extension; prior answers and requirement text counted as evidence (I3, contradicting the report's own rulings).

## Cases that behaved correctly

| Case | Result |
|---|---|
| D1 final answer (real observations) | pass, 0.06 s (0.20 s for the first run including clang) |
| Correct PWM PA8 with English derivation prose (C1) | pass |
| USART2 115200 baud, BRR 0x5C4 cited as hex (C2) | pass |
| I2C1 400 kHz, TIMINGR 0x10320309 from HSI16, cited (C3) | pass |
| Clock tree HSE 8 MHz → 170 MHz with derivation chain (C4); Vietnamese + LaTeX version | pass (the English version needs a citation for "150 MHz", correctly) |
| PWM + UART in one program (C5) | pass |
| Lookup answer in English; in Vietnamese with decimal point; as a markdown table | pass |
| Register address from a lookup (`0x40012C44`, also as `0x4001_2C44`), `[doc page N]` | pass |
| Missing TIM1 clock enable | `G2-SIM-CLK-GATE` ✓ |
| Wrong AF (AF2) | `G2-SIM-GPIO-AF` + `G2-PIN` ✓ |
| PSC off by one | `G2-FREQ` ✓ |
| Duty 50 % | `G2-DUTY` ✓ |
| Wrong pin while the requirement is pending | `G2-PIN` ✓ |
| MOE inside `if (0)` / `#if 0` / a comment / an uncalled function / after `while(1)` / after `return` / only in an IRQ handler | `G2-SIM-TIM-MOE` ✓ (the analyzer handles these well) |
| Nested 256×256 loop | `G2-UNSUPPORTED` (execution budget) ✓, 0.35 s |
| Waiver of a non-waivable code (`G2-FREQ` with a waiver for R1) | stays an error, with the note ✓ |
| Invented Absolute Maximum / current / °C / address in plain prose | `G1-V1` / `G1-V2` ✓ |
| Citation of a page that was not returned (p.83) | `G1-V3` ✓ |
| English unsafe 5 V advice | `G4-ABS-MAX` ✓ |
| Board target VDD 5 V | `G4-VDD-ABS-MAX` ✓ |
| Determinism and no mutation of inputs or Board State | ✓; a new memo per run, no state carried across runs |

## Residual risks (contract-level, not defects of this implementation)

- **G2 only checks the requirements the agent recorded.**
  - A requirement written to match wrong code (user asked 20 kHz, agent recorded 10 kHz, code makes 10 kHz) → `passed=True`.
  - A requirement typed `other` → `passed=True`.
  - No requirement at all, with wrong PSC → `passed=True`.
  - G1 does not compare prose claims with the gate's own simulation, so "PWM 20 kHz" in the prose passes even when the simulated effect is 10 kHz.
  - Suggestion: cross-check each requirement's numeric target against `user_texts`, and the prose's Hz claims against `sim.effects`.
- **Waivable `G2-UNMODELED` can hide real errors.** For example, centre-aligned mode halves the frequency. Report waived runs separately from verified ones (I7).
- **G1 unit coverage is `find_quantities` only.** Time (s/ms/µs/ns), %, baud, MSPS, LSB, dB and bit are never checked; invented "PLL lock 40 µs" and "4 MSPS, 80 dB" pass.
- **Value-level provenance.** A real number of another parameter passes (known, as in v1).
- **G2 inherits the simulator's honesty limits.** PLL ready timing, the AHB÷2 procedure (warning only) and PUPDR are not checked. Tool errors such as a sandbox timeout are non-blocking by contract (see C1 for when they should not be).

---

## Re-review of fix round 1

Scope: only the fix diff described in "Fix round 1" of `plan/P4_reports/gate_report.md`.
- **What I re-ran.** Every round-0 scratch script (outputs in `scratchpad/review_gate/r1/*.txt`) and the D1 re-run (`d1.py`).
- **New probes.** `r1_g4.py`, `r1_wit.py`, `r1_wit2.py`, `r1_inline.py`, `r1_real.py`, `r1_perf.py`, `r1_c2.py`, `r1_c4.py`, `r1_misc.py`, all in the same scratch directory.
- **Gate tests.** `pytest agent/tests/test_gate_*.py`: 267 passed in 5.2 s.

**Verdict, round 1: Spec ✅ for the rulings as given (C2 and I1 are PARTIAL by ruling) · Quality: not approved yet.**
- 8 of the 11 findings are fully addressed.
- The fixes introduced 4 new Important defects:
  - three false fails on correct answers (each would use up repair rounds; the G4 one also forces REPLAN);
  - one false pass that reopens I2.
- No Critical issue remains.

### Verdict per finding

| Finding | Verdict | Observed with the fixed gate |
|---|---|---|
| C1 fail-open | **ADDRESSED** | All of these now **fail closed**: requirement `"tol_pct": null`, `"duty_tol_pp": null` → `G2-FREQ` (no internal error); requirement `initial: "170mhz"` → `G2-INITIAL` error; last agent simulation errored → that simulation is skipped and the gate simulates from reset (`G2-FREQ … 941.176 Hz`); 3000-iteration loop → `G2-UNSUPPORTED … unrolls to 3011 register operations (> 2000)`. G1/G3/G4/G5 internal errors still fail open (see new minor m4). |
| C2 start state | **PARTIAL** (by ruling) | Fixed: D1 draft#1 with the runtime context now gives `passed=True`, `start.source = "code_configures_clock"`, no `G2-SIM-FLASH-WS`. A dict `initial.ops` that hid a missing TIM1EN and MOE now gives `G2-SIM-CLK-GATE`. Remaining: when the code does not configure the clock, the start state is still the agent's own preset (`r1_c2.py`). A task stated "from reset", code with no clock config and an agent simulation on `sysclk_170mhz_…` gives `passed=True`, `start = {"initial": "sysclk_170mhz_pll_hsi16_apb_div1", "source": "agent_simulation"}`. The same code from `reset` (what the grader uses for a reset task) gives `G2-FREQ … 1882.35 Hz`. Board State's recorded clock config is still not used as the start state. |
| C3 G1 blind spots | **ADDRESSED** | All seven forms of the invented `4.6 V` now give `G1-V1`: LaTeX `\,\text{V}`, `\text{ V}`, inline code, ```` ```text ````, untagged fence, table cell, unit in another column. An invented address in inline code gives `G1-V2`. The real D1 answer now has 9 claims checked (was 6), all supported. The new LaTeX parsing introduced a false fail (new I-3). |
| I1 satisfied requirement not re-checked | **PARTIAL** (by ruling) | PA9 instead of PA8 → `G2-PIN`; USART1 instead of USART2 → `G2-NO-EFFECT`. Still accepted with only a `G2-NO-CODE` warning: no code, or code only in a ```` ```text ```` fence, with the requirement satisfied (`passed=True`); the ruling keeps NO-CODE a warning. The new "set this turn ⇒ always check" rule introduced a false fail (new I-4). |
| I2 derivation | **ADDRESSED** for the five review claims | 85 MHz, 10 kHz, 40 kHz, 42.5 MHz and 8 MHz no longer pass against the D1 evidence. The replacement "witnessed arithmetic" rule lets the same ×2 / ÷2 errors through again when they are written next to their operands (new I-1). |
| I3 agent text as evidence | **ADDRESSED** | Turn-2 claims 13 V, 25 mA, 8499 mV fail; requirement `evidence`/`description` text "4.6 V" fails. Typed device fields (`add_device(i_typ_ua=4600000)` supporting "4.6 A") are still accepted, by ruling. |
| I4 number/citation formatting | **ADDRESSED** | `20,000 Hz`, `20.000 Hz`, `170.000.000 / 8500 = 20.000 Hz`, `170,000,000 Hz`, `4,0 V`, `1,71 V … 3,6 V` all pass. `[STM32G474_RM0440, p. 1267]` and `[RM0440 §28.6.20, p.1267]` pass. "use a 3.3 V regulator" is now a `G1-V1` warning only. Parenthesised citations `(RM0440, trang 1267)` still fail (out of scope). |
| I5 G4 in Vietnamese | **ADDRESSED** for the review's sentences | `Bạn có thể cấp trực tiếp 5 V vào chân VDD của STM32G474.` and `Hãy nối VDD … nguồn 5 V từ USB.` → `G4-ABS-MAX` error. The new language-independent rule flags correct power-chain and FT-pin sentences (new I-2). |
| I6 snippets | **ADDRESSED** | The GPIO-only snippet and the one-line MOE snippet now pass, with warnings tagged "[register snippet, not a complete program: warning only]". A complete program missing MOE still fails. |
| I7 waiver shown as pass | **ADDRESSED** | With a waiver for R1: `passed=True`, `gates.G2 = "skipped"`. A code-level `{"id": "G2-UNMODELED"}` waiver is rejected (`G2-UNMODELED` stays an error). |
| I8 abstain shortcut | **ADDRESSED** | "…blocked…" and "…refused…" answers with an invented 4.6 V now give `G1-V1`. |

**Performance and determinism.** `Gate.run` on the real D1 final answer takes 0.068–0.203 s (10 runs, first run includes clang), and the 10 outputs are identical. G1 worst cases: a 300-row table takes 0.54 s; 300 sentences with 6 operands each take 0.91 s; one sentence with 2000 numbers and 199 claims takes 0.26 s. No regression.

### New findings (introduced by the fix diff)

#### Important

**I-1. Witnessed arithmetic accepts wrong results whenever small integers appear earlier in the sentence (reopens I2)**
- **Evidence.** Against the real D1 observations (`r1_wit.py`), every one of these passes G1 as `derived`:
  - `f = 170 MHz / (0+1) / (8499+1) = 10 kHz.` (correct: 20 kHz), witnessed as `1.7e+08, 8498, 2`
  - `f = 170 MHz / (1 × 8500) = 10 kHz.`
  - `With PSC = 1, ARR = 8499 we get 170 MHz / 8500 = 40 kHz.`
  - `PLL: 16 MHz / 4 × 85 = 340 MHz, then / 2 = 160 MHz` (160 MHz witnessed as `1.6e+07, 5, 2`)
- **How often scaled errors pass** (`r1_wit2.py`; result written as factor × the correct value; P = passes, - = rejected):

  | Sentence | ×0.25 | ×0.5 | ×0.9 | ×1 | ×1.1 | ×1.5 | ×2 | ×4 |
  |---|---|---|---|---|---|---|---|---|
  | PWM with `PSC = 0` written | - | P | - | P | - | - | P | - |
  | PLL chain `16 MHz / 4 × 85 = 340 MHz, rồi chia R = 2 được … MHz` | P | P | - | P | - | P | P | P |

  Sentences without small integers ("170 MHz / 8500 = …", the UART baud sentence) reject every wrong factor, and random values are almost never accepted (1/400). So the hole is specifically the ×2 / ÷2 class, the most common LLM error.
- **Cause.** `provenance.py:316` adds ±1 to *every* integer operand, so 0 → 1, 1 → 2, 4 → 5 and 8499 → 8498. `provenance.py:322-336` then tries any 1–3 of the 6 preceding numbers, in any order, with × and ÷.
- **Fix.**
  - Apply ±1 only to values that are written as `X+1` / `X-1`, or to large register fields (e.g. ≥ 16); never to 0–4.
  - Better: evaluate the expression the answer actually writes (the operators and parentheses between the operands, after the LaTeX normalisation that already exists), rather than searching all combinations.

**I-2. G4 flags correct power-chain and 5 V-tolerant-pin sentences as `G4-ABS-MAX` error (structural, so REPLAN_REQUIRED)**
- **Evidence** (`r1_g4.py`; question "Thiết kế nguồn cho STM32G474 từ cổng USB 5 V."):
  - `Cấp nguồn 5 V từ USB qua LDO AMS1117 để tạo 3,3 V cho VDD của STM32G474.` → `G4-ABS-MAX` error, "5 V stated next to a supply/VDD/chip mention"
  - `Dùng nguồn USB 5 V, hạ xuống 3.3 V bằng LDO rồi cấp cho STM32G474.` → error
  - `Nối ngõ ra 5 V của cảm biến vào chân PA9 (chân FT) của STM32G474.` → error, although FT pins accept up to VDD + 4.0 V
  - English, already present in round 0 through the guardrail parser: `Use the 5 V USB rail and an AMS1117 LDO to supply 3.3 V to VDD of the STM32G474.` and `Power the board from a 12 V adapter and use a buck converter to make 3.3 V for the STM32G474.` → error
- **Cause.** `safety.py::_any_language` flags any voltage above the Absolute Maximum anywhere in a sentence that also mentions VDD, supply, nguồn or the chip name. It also runs after the English rule has already judged the sentence acceptable (a pin target within the FT limit).
- **Why it matters.** Power-tree sentences are exactly what design answers contain. `kind = structural` forces an `update_plan` round, and repeats lead to ESCALATED.
- **Fix.**
  - Do not apply the rule to a sentence containing a conversion word (LDO, regulator, buck, converter, hạ áp, ổn áp, level shifter, divider), or to one the English rule already evaluated.
  - Compare only the voltage nearest the VDD/chip token.
  - Treat "FT" or "5 V tolerant" as a pin target (limit VDD + 4.0 V).

**I-3. LaTeX scientific notation becomes a bogus claim and a `G1-V1` error**
- **Evidence** (`r1_real.py`, `r1_misc.py`; all are correct statements):
  - `$f = \frac{170 \times 10^{6}\,\text{Hz}}{8500} = 20\,\text{kHz}$` → `G1-V1 … "6 Hz" has no source`
  - `The timer clock is $1.7 \times 10^{8}$ Hz …` → `G1-V1 … "8  Hz"`
  - `$2.5 \times 10^{-3}$ A` → `G1-V1 … "-3  A"`
- **Cause.** `normalize_text` keeps `10^6`, and the `_QTY` lookbehind (`codeblocks.py:143`) does not exclude `^`, so the exponent is read as the number in front of the unit. Before round 1, LaTeX was not parsed at all, so this is new.
- **Why it matters.** The feedback ("6 Hz has no source") gives the agent no usable fix, so the round is wasted.
- **Fix.** Fold `a × 10^{n}` and `a·10^n` into one number (`a`e`n`) before extracting claims, and add `^` to the lookbehind.

**I-4. A correct partial answer in an intermediate C4 turn fails when the agent re-sends its full requirement list**
- **Evidence** (`r1_c4.py`).
  - Setup: R1 (PWM PA8) was satisfied in turn 1. In turn 2 the user asks to "add a BME280 on I2C3 … only the I2C3 initialisation is needed". The answer is I2C3-only code (correct, SCL 91–100 kHz).
  - If the agent re-sends only R2 with `set_requirements`: `passed=True` (R1 not re-checked).
  - If the agent re-sends **R1 + R2** (common: D1's agent re-sent its whole list): `G2-NO-EFFECT @ requirement R1 (PA8 PWM) … no PWM output was found on PA8` → fail.
  - C4 tasks grade only the *last* turn's complete program (`eval/tasks/C4/c4_curated.yaml` header), so intermediate partial code is legitimate.
- **Cause.** `functional._set_this_turn` counts every id present in a successful `set_requirements` call this turn, even when only `status`/`evidence` are re-sent unchanged.
- **Fix.** Count a requirement as "set this turn" only if it is new or one of its specification fields changed (compare with the Board State version at the start of the turn). Alternatively, ignore re-sends that only touch `status`/`evidence`.

#### Minor

- **m1. "Code configures the clock ⇒ reset" fires on any `RCC_PLLCFGR` write.** On a task already running at 170 MHz, adding `RCC->PLLCFGR |= RCC_PLLCFGR_PLLQEN;` (PLLQ for FDCAN) makes the gate simulate from reset and report `G2-FREQ … 1882.35 Hz`. The agent's own simulation on the preset showed 20 kHz (`r1_c2.py`). Fix: require writes to `SW` or to PLLSRC/PLLM/PLLN/PLLR, not to the PLLxEN bits.
- **m2. Hex masks are now checked, including in inline code.** Correct Q&A answers such as `(mask 0x8000)`, `TIM_BDTR_MOE = 0x00008000` and `(bit 11, 0x800)` give `G1-V2 … has no source` unless the agent simulated (`r1_inline.py`, M1–M3). This was already true in plain prose; checking inline code makes it more frequent. Fix: accept `1 << bit_offset` and field masks derived from `get_register_bitfields` fields.
- **m3. A table column unit is applied to every row.** Header `Value (MHz)` with rows PRESC 1, SDADEL 2, SCLDEL 3, t_SCLL 1.25 (µs) gives four `G1-V1` errors ("1 MHz", "2 MHz", …) (`r1_real.py`, R3b). Fix: skip rows whose label names a divider/count field, or rows that carry a unit of their own.
- **m4. G1 still fails open on an internal error.** The number parser raises `OverflowError` on `1e309 Hz`, so G1 is `skipped` and `passed=True`, and an invented `4.6 V` in the same answer passes (`r1_perf.py`). The trigger is exotic, but G1/G3/G4/G5 internal errors should fail closed like G2 now does.
- **m5. Unsafe advice escapes G4 if the sentence contains "max".** `Bạn có thể cấp trực tiếp 5 V vào VDD của STM32G474 (max 3,6 V khi hoạt động).` → G4 `pass`, because "max" is a negation word. This is the documented cost of the "max" ruling. With a citation, the answer passes every gate.
