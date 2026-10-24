# P4 — Gate v3 report (subagent G)

Contract: `plan/P4_interfaces.md` §2 (types, entry point, G1–G5 rules, kind table). Brief: `plan/P4_Handoff.md` "Bước 3". Not a git repo: nothing committed.
Status: **DONE_WITH_CONCERNS** (all tests green; the concerns are contract points I had to narrow or interpret, listed under "Deviations" and "Limitations").

## 1. Files created (no pre-existing file was modified)

| File | Role |
|---|---|
| `agent/agent/gate/__init__.py` | `GateFlags`, `GateContext`, `Gate.run`; read-only/memoised/exception-proof tool bridge; waivers; final gate status |
| `agent/agent/gate/types.py` | `Finding`, `GateReport` (`passed`, `errors`, `failed_codes`, `to_dict`, `feedback`), `tool_error` helper |
| `agent/agent/gate/codeblocks.py` | C block extraction (`extract_c_blocks`, `extract_c_code`), `program` (joined code + line→block map, fragment wrapping), `prose` |
| `agent/agent/gate/provenance.py` | G1 (new rules) + strict v1 mode (`agent.verifier.verify`) |
| `agent/agent/gate/functional.py` | G2 (analyze → simulate → requirement matching; independent of `eval/`) + `resolve_start` |
| `agent/agent/gate/drc_gate.py` | G3 (`run_drc` → findings, kind table, `unknown_codes`) |
| `agent/agent/gate/safety.py` | G4 (VDD vs abs-max, 5 V into non-FT pins, simulated clock limits, unsafe prose advice) |
| `agent/agent/gate/compile_gate.py` | G5 (`compile_check`) |
| `agent/tests/test_gate_{types,codeblocks,provenance,functional,drc,safety,compile,entry}.py` | 159 tests |
| `agent/tests/test_gate_support.py` | shared test support (real-tool `Recorder` call with failure injection, `board` fixture on a temp `BOARD_STATE_DB`, C samples); no tests |

Other files under `agent/`, `eval/`, `plan/` that changed during this session (`tools.py`, `config.py`, `runtime/*`, `conftest.py`, `eval/*`…) were edited by the other engineers, not by me. The runtime already consumes this API (`runtime/loop.py::_finish`, `runtime/flags.py::gate_flags`) and its tests pass against it.

## 2. Finding codes

`kind`/`severity` as emitted; `waivable` is computed per finding as `code in GateFlags.waivable` (default `("G2-UNMODELED", "G5-SKIPPED")`).

| Code | Gate | Kind | Severity | Waivable (default) | Meaning |
|---|---|---|---|---|---|
| `G1-V1` | G1 | local | error | no | value with unit in prose has no source (and is not derivable) |
| `G1-V2` | G1 | local | error | no | hex: address not in a lookup/user message, or register value without source |
| `G1-V3` | G1 | local | error | no | citation not returned by a tool, or no citation although a value comes only from a lookup |
| `G1-V4` | G1 | local | error | no | operating question answered only from absolute-max facts |
| `G2-UNSUPPORTED` | G2 | local | error | no | `analyze_c_code` stopped (line + construct) |
| `G2-SIM-<sim code>` | G2 | local | error / warning | no | relevant simulator violation, e.g. `G2-SIM-TIM-MOE`, `G2-SIM-CLK-GATE`, `G2-SIM-GPIO-AF`, `G2-SIM-USART-BRR`, `G2-SIM-CLK-LIMIT`, `G2-SIM-FLASH-WS` (warning: `G2-SIM-CLK-PROC`, `G2-SIM-RO`…) |
| `G2-FREQ` / `G2-DUTY` | G2 | local | error | no | PWM frequency (±tol_pct %) / duty (±duty_tol_pp points) |
| `G2-BAUD` / `G2-SCL` / `G2-CLOCK` | G2 | local | error | no | UART baud, I2C SCL range, clock tree (exact / `_min_hz` / `_max_hz`) |
| `G2-PIN` | G2 | local | error | no | effect on another pin / pin carries another function / tx,rx,scl,sda mismatch |
| `G2-NO-EFFECT` | G2 | local | error | no | no effect at all for a pending requirement |
| `G2-INACTIVE` | G2 | local | error | no | effect exists but is not running, reason not already reported as a violation |
| `G2-UNMODELED` | G2 | local | error | **yes** | effect `modeled=false`, unmodeled requirement type (spi, adc, dac, can, gpio_out, gpio_in) with code, chip without simulator model, unmodeled kernel clock |
| `G2-NO-CODE` | G2 | local | warning | no | no code block but a modelable requirement exists (gate `na`) |
| `G2-NOT-IN-CODE` | G2 | local | warning | no | requirement already `satisfied` (with evidence) and not touched by this answer's code: not re-checked |
| `G2-TOOL-ERROR` | G2 | local | unknown | no | analyze/simulate/requirements read failed → gate `skipped` |
| `G2-SKIPPED` | G2 | local | unknown | no | chip without simulator model and nothing else to check → gate `skipped` |
| `DRC-PIN-01/02/03`, `DRC-CLK-01`, `DRC-ELEC-01`, `DRC-PWR-01` | G3 | structural | DRC severity (error / warning / unknown) | no | DRC rule; DRC sub-code (`PIN_CONFLICT:PA8`…) is in `actual` |
| `DRC-CLK-02`, `DRC-REQ-01` | G3 | local | DRC severity | no | missing RCC enable; requirement open / waived without reason |
| `G3-TOOL-ERROR` | G3 | local | unknown | no | `get_board_state`/`run_drc` failed → gate `skipped` |
| `G4-VDD-ABS-MAX` | G4 | structural | error | no | a target's VDD above its chip's absolute maximum |
| `G4-5V-NON-FT` | G4 | structural | error | no | ≥ 4.0 V driven into an MCU pin above its input maximum, when DRC is not shown to the agent |
| `G4-CLOCK-LIMIT` | G4 | structural | error | no | `SIM-CLK-LIMIT*` in G2's simulation |
| `G4-ABS-MAX` | G4 | structural | error (sure) / warning (uncertain) | no | prose advises a voltage above absolute maximum |
| `G4-OPERATING-RANGE` | G4 | structural | warning | no | prose advises a voltage above the recommended operating range (below abs max) |
| `G4-LIMIT-UNKNOWN` | G4 | local | unknown | no | no abs-max VDD row in the DB for a target chip |
| `G4-TOOL-ERROR` | G4 | local | unknown | no | `get_electrical_specs`/`run_drc` failed → gate `skipped` |
| `G5-COMPILE` | G5 | local | error | no | first clang diagnostic, located per block/line/col (+ count of the others) |
| `G5-SKIPPED` | G5 | local | unknown | **yes** | `compile_check` returned `skipped` (other chip / no toolchain) → gate `skipped` |
| `G5-TOOL-ERROR` | G5 | local | unknown | no | `compile_check` failed / unknown status → gate `skipped` |
| `G<n>-INTERNAL-ERROR` | any | local | unknown | no | bug inside one gate, contained; gate `skipped` |

Every finding fills `{code, where, expected, actual, hint_source}` with concrete text, e.g.
`G2-FREQ | requirement R1 (PA8 PWM) | 20000 Hz ±1% | 20238.1 Hz on PA8 (TIM1_CH1: TIMxCLK 170000000 Hz, PSC = 0, ARR = 8399; error +1.19%) | solve_timer_config / formula f_TIM/((PSC+1)(ARR+1))`;
`G2-SIM-CLK-GATE | code block 1, line 6, op 3 (TIM1->PSC = 0) | TIM1 clock enabled in RCC before its first register access | write to TIM1_PSC while RCC_APB2ENR.TIM1EN = 0 … | get_register_bitfields(RCC, <bus>ENR) for the TIM1EN bit; RM0440 p.285`;
`G1-V3 | answer | at least one [doc p.N] citation when a value comes only from a documentation lookup | no citation; documentation-only values: 4.0 V | cite the source returned by the lookup: [STM32G474_Datasheet p.82]`.

## 3. Rulings (where the contract was silent or had to be interpreted)

**G1 provenance**
- Ruling: derivation = ONE step, `quantity × or ÷ divider`, where the quantity has the claim's unit and the divider is a register/divider field (PSC+1, ARR+1, USARTDIV, PLL M/N/R, AHB/APB dividers, I2C PRESC/SCLL/SCLH+1) or an integer the user wrote; both operands from the same tool result, or one of them from the user/prior answers; claims accepted earlier in the same answer can feed the next step (16 MHz / 4 = 4 MHz → 4 MHz × 85 = 340 MHz). — The literal "a*b or a/b of any two evidence numbers within 0.5 %" accepts 95–98 % of random 3-significant-digit claims on a realistic D1 evidence set (67 numbers; measured, §5), i.e. G1 would no longer reject anything. The implemented rule accepts 0.5–4 % (v1: 0.8–3 %) and still accepts every legitimate pattern in the tests (170 MHz / 8500 = 20 kHz, 16 MHz / 9600 → BRR 0x683, SYSCLK / APB prescaler, VCO_in × N, rounded simulator values). — Cost if wrong: a correct value computed across two unrelated tool results (clock from tool A × divider from tool B, neither from the user) is rejected; the agent must simulate or cite (one repair round).
- Ruling: rounding tolerance 0.5 % only against STRUCTURED computed values and user quantities of the same unit; lookups and free text must match exactly (v1). — Lookups/manual chunks hold hundreds of numbers; rounding there re-opens the coverage problem. — Cost: an agent paraphrasing a datasheet value with rounding ("about 15.9 MHz" for 15.88) is rejected until it quotes it.
- Ruling: matching is unit-aware for computed outputs (keys `*_hz`, `vdd`, `*_ua`…, `unit` columns); unit-blind matching (v1 style) is kept only for numbers in lookup text/table cells and in user messages; user-message numbers that belong to a quantity or a percentage are not bare numbers ("25 %" no longer supports "25 mA"). — v1 accepted any claim whose number appeared anywhere (e.g. "6 V" because of `af: 6`); tested both directions. — Cost: a user writing "VDD = 3.3" without unit still supports "3.3 V" (kept on purpose).
- Ruling: `±1` applies to hex register values (and to N−1 encoded divider operands), not to physical quantities; hex derivations use a ±1-count tolerance instead of 0.5 %. — "4.0 V + 1 = 5 V" would otherwise bless an invented "5 V"; a 0.5 % window on ARR = 8499 would accept 8458. — Cost: none known.
- Ruling: addresses (≥ 0x2000_0000) need a lookup result or the user's message; analyzer `addr` fields do not count; a 32-bit register VALUE ≥ 0x2000_0000 equal to a structured simulator/solver/board value (e.g. `GPIOA_MODER = 0xABFEFFFF` from `final_registers`) is a value, not an address. — Contract rule (2) would otherwise reject legitimate final register values; analyzer addresses would launder invented addresses written into code. — Cost: a user-supplied wrong address passes G1 (the user's responsibility).
- Ruling: not evidence — control tools (`update_plan`, `finish`, `record_decision`…; only an explicit allow-list of lookup/computed tools counts), results with `{"error": "..."}`, and agent-authored free text stored in Board State (`decisions`, `rationale`, `question`, `options`, `waiver_reason`, `artifacts`). Requirement values written by the agent DO count (contract lists `get_board_state` as type (b)). — Cost: see limitation "laundering through Board State".
- Ruling: citation sources = every dict with `doc` in tool results (page, page_start–page_end, alt_pages) plus page references embedded in tool text (`RM0440 Table 282 p.1261`, `DS12288 … p.82`); citations may list pages (`[doc p.82, p.84]`, `p.1707-1708`). svd_only: `[STM32G474_SVD]`, `[STM32G474_SVD SVD]`, `[STM32G474 SVD]` are valid iff a tool returned that doc with `page: null`. — Cost: none known.
- Ruling: the "missing citation" V3 is raised only when the answer has no citation attempt at all; each invalid citation is its own V3. — Avoids two findings for one fix.
- Ruling: abstention = an ABSTAIN phrase of v1 within the first 200 characters of the prose (v1 searched the whole answer). — A design answer ending with "I cannot verify the start-up time" would otherwise switch G1 off entirely (tested). — Cost: a refusal that starts with a long preamble is checked like any answer.
- Ruling: V4 uses the last user message (the current goal); strict mode passes `"\n".join(user_texts)` exactly as the contract says. — Earlier turns should not trigger field-type confusion for the current one.

**G2 functional**
- Ruling: without checkable requirements (`board=False`, empty list, or only `power`/`other`) G2 checks analysis + op-level and global violations + violations of channels/serial peripherals that ARE routed to a pin ("intended use"). — Contract says "violation cấp lệnh" only; that would let the canonical "forgot MOE on TIM1_CH1/PA8" pass under A2. — Cost: a deliberately routed-but-disabled channel fails.
- Ruling: end-of-program violations of a peripheral whose writes were ignored because its clock was off (op-level `SIM-CLK-GATE`) are not repeated (`details.G2.suppressed`). — Root cause first; the other codes are consequences. — Cost: if the agent fixes the clock and the rest is also wrong, the next round reports it.
- Ruling: a requirement with `status: satisfied` and non-empty `evidence` that this answer's code does not touch → `G2-NOT-IN-CODE` warning, not re-checked; pending requirements are always checked. — Multi-turn tasks (C4) produce partial code in intermediate turns; requiring the full program every turn would force repeats/escalations. — Cost: an agent can mark a requirement satisfied without implementing it in this answer (visible in the warning and the trace; the independent grader still checks the final code).
- Ruling: requirement without `pin`/`pins` (pwm) = any pin carrying the requested signal; uart/i2c without `instance` = any instance of that kind. — Agents record "PWM 20 kHz" without a pin. — Cost: none known.
- Ruling: start state priority implemented inside the Gate: requirement `initial`/`hse_hz` > `ctx.initial` if not "reset" (resp. `ctx.hse_hz`) > args of the agent's last `simulate_register_writes` in `observations` > "reset". — The contract lists the priority but `ctx.initial` cannot express "unset" separately from "reset". — Cost: an explicit "reset" from the runtime is overridden by the agent's last simulation.
- Ruling: UART kernel clock LSE / I2C reserved kernel selection, and analysis of a chip other than stm32g474, map to `G2-UNMODELED`; `analyze_c_code` "no_toolchain" maps to `G2-TOOL-ERROR` (infrastructure, not the agent's code). — Cost: none known.
- Ruling: fragment-only answers (no function definition in any C block) are wrapped as `#include "stm32g4xx.h"` + `void gate_snippet(void) { … }` for G2/G5, with locations mapped back to the original block/line. — Q&A answers often show snippets; they are still simulated and compiled rather than failing as "no entry point". — Cost: a snippet that relies on surrounding code the agent did not show may fail.
- Ruling: `SIM-CLK-LIMIT` is reported both as `G2-SIM-CLK-LIMIT` (local) and `G4-CLOCK-LIMIT` (structural), as the contract states literally. — Cost: two findings for one cause in the feedback (the runtime treats the run as structural anyway).

**G3 / G4 / G5**
- Ruling: `*-TOOL-ERROR`, `*-INTERNAL-ERROR` and `G4-LIMIT-UNKNOWN` have `kind="local"` even in G3/G4 (contract: every G3 finding except two, and every `G4-*`, is structural). — They are `unknown` (never blocking) and an infrastructure hiccup must not make a runtime that keys on `kind` insert REPLAN_REQUIRED. The runtime currently uses `report.errors()` only, so this is defensive. — Cost: none.
- Ruling: `G4-5V-NON-FT` is computed from `run_drc`'s per-net evaluations (FAIL on "VOH_max <= input max", source ≥ 4.0 V, destination is a target MCU pin) and emitted only when G3 is not showing DRC to the agent (G3 off or skipped); otherwise the net is listed in `details.G4.five_volt_reported_by_drc`. — "Do not double DRC-ELEC-01"; pin FT data is not reachable with the Gate's allowed tools. — Cost: a 5 V device that is declared but never `connect`-ed is not checked.
- Ruling: G4 clock check reuses G2's simulation only (no own simulation when G2 is off). — Under A3 the sandbox server is hidden anyway. — Cost: with `g2=False, g4=True` and the sandbox available, code clock limits are not checked (`details.G4.clock_checked = false`).
- Ruling: G4 prose: a finding only for a sentence without negation/caution words (not, never, avoid, exceed, above, damage, limit, up to, tolerant…) where `guardrail.parse_hardware_requests` finds an applied voltage; severity error only if the clause is advice (imperative or "you can/should…") about an MCU supply (VDD/VBAT/VREF/MCU/chip name) and `evaluate_hw` says refuse; pins (FT unknown) or other devices → warning; `warn` verdict → `G4-OPERATING-RANGE` warning. Limits come from `get_electrical_specs` rows already in observations, else one call per parameter. — Conservative per contract. — Cost: unsafe advice phrased indirectly is a warning only.
- Ruling: each Board State target is compared with its OWN chip's absolute maximum (STM32G474 4.0 V, ESP32 3.6 V…). — Multi-MCU boards (tested). — Cost: none.
- Ruling: G3 reads `get_board_state()` (full state, also used for G4 and the chip fallback) while G2 reads `get_board_state(section="requirements")` as the contract states; both memoised. — Cost: two read-only calls instead of one.

**Entry point**
- Ruling: waivers match a finding by requirement id (`where` starts with `requirement <id>`) or by finding code (`{"id": "G5-SKIPPED", ...}`); only codes in `GateFlags.waivable`; reason must be non-empty (else `details.waivers_rejected`); a waiver for a non-waivable code keeps the error and appends "[waiver for R1 not applied: G2-FREQ cannot be waived]" to `actual`. — Contract only defines requirement-id waivers but lists `G5-SKIPPED` (not tied to a requirement) as waivable. — Cost: none known.
- Ruling: the Gate refuses any tool outside `READ_ONLY_TOOLS` (returns `{"error": ...}` to the gate module), memoises identical calls within a run, converts exceptions/non-dict results to errors, and logs every call in `details.calls` (`{tool, args (shortened), ok, error}`) for the trace's internal `tool_call` events. Each gate runs in an exception guard. — Determinism + "never raises". — Cost: none.
- Ruling: gate status is derived after waivers: `fail` iff an error finding remains; otherwise the module's base status (`pass` / `skipped` / `na`); `off` from flags. `passed` follows the contract (no error, no `fail`), so a run whose tools all failed has `passed=True` with gates `skipped` — the caller must look at `gates` if it wants stricter behaviour. `to_dict()` also carries `failed_codes`.

## 4. Deviations from the contract (stated, not silent)

1. G1 derivation is narrower than the literal text (one step, unit-aware, same source or user operand) — the literal rule is not implementable without making G1 accept ~all numbers (measured 95–98 %).
2. G2 without requirements also checks routed channels/peripherals (stronger than "op-level only").
3. `kind="local"` for unknown-severity infrastructure findings in G3/G4.
4. Abstention restricted to the beginning of the prose.
Everything else follows §2 verbatim (names, shapes, defaults: pwm tol 1 % / duty_tol_pp = tol, uart 2 %, i2c 5 %, clock 0.1 %).

## 5. Known limitations

- Provenance is value-level, not semantic: a real number of another parameter (e.g. FT_c 5.5 V quoted as VDD max) passes, as in v1. Residual acceptance of random invented values on a realistic D1 evidence set: MHz 4.0 %, kHz 2.8 %, V 1.0 %, mA 0.5 % (v1: 3.0 / 1.5 / 0.8 / 2.5 %), measured with 400 random 3-significant-digit claims per unit (scratch script, not a test).
- Laundering through Board State: values the agent writes into requirements/devices (`add_device(i_typ_ua=…)`) become type (b) evidence, per contract.
- G2 relevance without the AF table: the requirement's signals are its `signal` plus the signals the simulation shows on its pins; an unrouted channel without `signal` in the requirement is reported as `G2-NO-EFFECT` (with the unrouted channels' reasons) rather than as the simulator code.
- G2 inherits the simulator's honesty limits (PLL ready timing, AHB÷2 procedure only a warning, PUPDR on 5 V pins are not judged) — they are never counted as checked.
- `DRC-REQ-01` (open requirement) blocks finishing until the agent marks requirements `satisfied`/`waived` in Board State; G2 never reads `status` except for the out-of-scope rule above.
- G5 `skipped`/tool errors and sandbox timeouts are non-blocking per contract (`passed` stays True, gate `skipped`).
- The waiver id convention for code-level waivers (`{"id": "G5-SKIPPED"}`) must be known to the agent (the feedback hint says so).

## 6. Tests

TDD: every module's tests were written first and seen failing (module missing / assertion), then implemented; mutation checks were run on provenance (tolerance, unit-blind scope, control-tool exclusion, ±1, address threshold, chaining, same-source pairing, percentage exclusion), functional (tolerance default, relevance without requirements, root-cause suppression, I2C range, start-state priority, satisfied/untouched), drc_gate (kind table, severity mapping, na, requirement location), safety (5 V threshold, skip words, certainty rule, DRC dedup, abs-max comparison, observation reuse) and the entry point (read-only guard, waivable from flags, waiver reason, board flag, exception containment); each mutation made at least one test fail (two weak tests found this way were strengthened).

```
$ agent/.venv/bin/python -m pytest agent/tests/test_gate_*.py -q -p no:cacheprovider
159 passed in 3.9s
$ agent/.venv/bin/python -m pytest agent/tests -q -p no:cacheprovider
1507 passed in 79.6s          # baseline 1212 + 159 gate tests + tests added concurrently by the runtime engineer
```

Coverage by area: types 13 (passed/failed_codes/feedback cap+order+hints, tool_error); codeblocks 12 (tags, untagged C detection, JSON/pin maps/prose skipped, duplicates, fragment dropping next to `main`, unterminated fence, prose stripping, line→block mapping, fragment wrapping); G1 41 (correct answers in both directions vs v1: PWM 20 kHz/PA8/170 MHz, USART2 9600 baud BRR 0x683 at 16 MHz, APB prescaler, PLL chain, I2C rounding at ±0.5 %; hallucinations: invented abs-max, invented address, analyzer-only address, 10 plausible fabrications against a full D1 session, uncited lookup values, unreturned citations, svd_only citations, control-tool echoes, late disclaimer, V4, strict-mode mapping); G2 32 (all requirement types, tolerance borders, each code, waiver-relevant flags, unmodeled cases, no-code, no-requirement modes, tool errors incl. missing toolchain, start-state priority, compact sim summary); G3 10; G4 21; G5 7; entry 23 (D1 end-to-end with real Board State/analyzer/simulator/clang, determinism, no Board State mutation, read-only guard, every ablation flag, strict v1 difference, waivers, all tools raising, internal bug containment, defaults).

---

## Fix round 1 (review `plan/P4_reports/gate_review.md`, rulings from the team lead)

Status: **DONE_WITH_CONCERNS** (every ruling implemented; residual limits listed at the end). Scope unchanged: only `agent/agent/gate/*.py` and `agent/tests/test_gate_*.py` were edited.
The reviewer's scratch scripts (`scratchpad/review_gate/*.py`, unchanged) were re-run against the fixed gate and their cases were turned into regression tests where they are deterministic.

### What changed, per finding

| Finding | Change (code) | Regression tests |
|---|---|---|
| **C1 fail-open** | (a) `functional._opt()` reads every optional numeric field (`tol_pct`, `duty_tol_pp`, `freq_hz`, `duty_pct`, `baud`, `scl_hz`, clock keys, `hse_hz`, sim args) with "absent / null / wrong type / non-finite → default"; effects with `pwm_hz=None` are handled. (b) `resolve_start` skips simulations whose result has `error` and never inherits a dict `initial` (only a preset NAME + `hse_hz`; `ops` never). (c) **fail closed**: with analysable code AND a pwm/uart/i2c/clock requirement, a G2 that cannot complete gives an **error**: `G2-INITIAL` (unknown preset; hint names the requirement and `set_requirements`), `G2-UNSUPPORTED` for > 2000 unrolled ops (checked before calling the simulator; hint "shorten or remove register-writing loops"), `G2-TOOL-ERROR` error for analyzer/simulator errors, timeouts and missing clang, `G2-INTERNAL-ERROR` error for an exception inside G2. `unknown` + `skipped` remains only when nothing had to be checked (no code, no modelable requirement, unreadable requirements, unmodelled chip). | `test_c1_*` (functional), `test_a_tool_error_fails_closed_*`, `test_a_tool_error_is_unknown_when_there_is_no_modelable_requirement`, `test_an_internal_bug_*_fails_closed_*` / `*_is_unknown` (entry) |
| **C2 start state** | New priority, reported in `report.details["start"] = {"initial", "hse_hz", "source"}`: requirement `initial` (name or `{"preset","hse_hz"}`, ops dropped) → `"requirement"`; the answer's ops write `RCC_PLLCFGR` or `RCC_CFGR.SW` (write / set / clear / modify with mask&3 / rmw / field SW) → `"reset"`, `"code_configures_clock"`; last SUCCESSFUL agent simulation with a preset name → `"agent_simulation"`; `ctx.initial` (string, not "reset") → `"context"`; else `"reset"`, `"default"`. `hse_hz`: requirement > agent's last successful simulation > `ctx.hse_hz`. | `test_start_state_priority_*`, `test_writes_to_the_clock_switch_*`, `test_c2_*` (functional, entry: the real D1 draft#1 now passes, no `G2-SIM-FLASH-WS`) |
| **C3 G1 blind spots** | `codeblocks.normalize_text` (`$`, `\text{}`, `\mathrm{}`, `_{}`/`^{}`, `\frac{a}{b}` → `(a) / (b)`, `\,` `\ ` `~` → space, `\mu` → µ, `\times`/`\cdot` → ×, other commands dropped). `codeblocks.prose` now keeps inline code and every fence that G2 does not analyse as C (```` ```text ````, untagged non-C). Markdown tables: a cell holding only a number gets the column's unit from a header like `Value (V)` / `Max [mA]` or from the single `Unit`/`Đơn vị` column of the same row; if no unit or units conflict, the cell is left unchecked. | `test_c3_*` (7 forms of the invented 4.6 V, invented address in inline code, correct VN table, unchecked unit-less table, the real D1 LaTeX claims) |
| **I1** | `G2-NOT-IN-CODE` only for a requirement with status `satisfied` that was NOT in a successful `set_requirements` call of this turn AND whose kind has no effect at all in this answer's code (no PWM / no USART / no I2C / no clock-register write / instance name absent). Everything else is checked. `G2-NO-CODE` stays a warning. | `test_i1_*` (PA9 instead of PA8 → `G2-PIN`; USART1 instead of USART2 → `G2-NO-EFFECT`; requirement set this turn → checked) |
| **I2** | Removed the "divider of the same tool result" derivation (and the operand-source machinery). A value is now derived only by **rounding (≤ 0.5 %) against a structured numeric field of a solver/simulator/set_clock_config/Board State result of the same unit**, or by **arithmetic written in the same sentence**: 1–3 numbers that appear BEFORE the value in that sentence (integers also tried ±1, e.g. `ARR+1`), combined by ×/÷, within 0.5 % (hex: ±1 count). | `test_i2_*`: the five factor-of-2 claims of the review now fail; `16 MHz / 4 × 85 = 340 MHz`, `f = 170e6/((1+1)(8499+1)) = 10 kHz`, `TIM1 at 170 MHz with PSC = 1 and ARR = 8499 gives 10 kHz` pass; a value cannot witness itself (`25 MHz / 1 = 25 MHz` → the first `25 MHz` fails). |
| **I3** | Prior answers: only quantities WITH units and hex values from their prose (`codeblocks.prior_prose`: every fence and inline code removed, LaTeX normalised); no bare numbers. Board State tools (`get_board_state`, `set_requirements`, `set_target`, `add_device`, `allocate_pin`, `connect`, `run_drc`, `set_clock_config`, ...): every string field is ignored (numbers, hex, text page references); only typed numeric fields count. | `test_i3_*` (13 V / 25 mA / 98 MHz / 8499 mV no longer supported by a prior answer; requirement `evidence`/`description` text no longer evidence; prior bare `ARR = 8499` no longer supports `0x2134`) |
| **I4** | Numbers are read in every valid way before matching (`20,000` → 20000 or 20.0; `20.000` → 20.0 or 20000; `170,000,000` / `170.000.000` / `170 000 000` → 170e6; `4,0` → 4.0; `1,234.5` / `1.234,5` → 1234.5; `1.7e8`); a claim is supported if any reading is. A unit glued to a number that cannot be read (`1,2,3 V`) gives `G1-V1` with severity **unknown**. Citations `[doc, p. N]`, `[doc §x.y, p.N]`, `[doc p.N–M]` (overlap with a returned range is enough), `[doc page N]`. An unsupported standard rail (1.8 / 2.5 / 3.3 / 5 V) in an advice sentence (EN or VI) is a `G1-V1` **warning**; the same value stated as a fact stays an error. | `test_i4_*` (both reviewer refusals pass with one warning; "The board supply is 3.3 V." without source fails) |
| **I5** | G4 prose: negation/warning words in English and Vietnamese (`codeblocks.has_negation`), advice detection in both languages (`codeblocks.is_advice`: imperative verbs / "you can…" / hãy, nên, có thể, cấp, nối, đưa, dùng, sử dụng…). After the English rule, a language-independent rule applies to sentences the English rule did not flag: a voltage above the chip's absolute-maximum VDD, in the same sentence as VDD/VBAT/VREF/supply/rail/nguồn/MCU/chip name, gives `G4-ABS-MAX`. | `test_i5_*` (both VI sentences of the review → error; `4,5 V` → error; "Yes: VDD = 5 V works …" and "Cấp nguồn 5 V cho cảm biến." → warning; VI negations and 3,3 V → nothing; LaTeX/inline code read) |
| **I6** | Fragment answers (no function definition, wrapped by the gate) with no checkable requirement: end-of-program violations and op-level `SIM-CLK-GATE` become **warnings** (text "[register snippet, not a complete program: warning only]"). Complete programs keep errors. | `test_i6_*` (GPIO-only snippet and one-line MOE snippet pass with warnings); `test_without_requirements_only_op_level_and_routed_channel_violations_count` still fails a complete program missing MOE |
| **I7** | Any gate with a waived finding, and G2 with a requirement not re-checked, ends `skipped` (never `pass`); `details["waived"]`, `details["not_rechecked"]`. A finding attached to a requirement can only be waived by the requirement id; a code-level id such as `{"id": "G2-UNMODELED"}` is rejected and recorded in `details["waivers_rejected"]` with the reason. `G5-SKIPPED` code-level waivers still work. `passed` semantics unchanged. | `test_i7_*` (entry), adapted `test_a_waivable_finding_with_a_reason_becomes_a_warning` |
| **I8** | Abstention (G1 skipped) only if an ABSTAIN phrase is in the first 200 characters AND the prose has no numeric/hex claim. | `test_i8_*` ("blocked" / "refused" no longer disable G1) |
| **Small** | G1 `where` names the claim: `answer: "4.0 V"`, `answer: "0x40013C00"`, `answer: citation [doc p.83]` (context moved to `actual`). Requirement references: `requirement R1 (...)` for ids without whitespace or `"`; otherwise `requirement "PWM PA8" (...)` with a JSON-quoted id. `agent.gate.types.requirement_ref(rid)` / `requirement_id(where)` build and parse it; waiver matching and G3's `DRC-REQ-01` location use them. | `test_findings_name_the_claim_*`, `test_requirement_reference_*` (types), `test_requirement_ids_with_spaces_*` (functional, drc, entry) |

**Format chosen for ids with spaces (for `loop.py::_unmet_requirements`):** `requirement "<id>" (<label>)`, id JSON-encoded (`"` and `\` escaped). `where.split()[1]` returns `"PWM` for such ids. The runtime should parse it with `from agent.gate.types import requirement_id; requirement_id(f.where)`, which handles both forms and returns `None` for non-requirement findings.

**New / changed codes:** `G2-INITIAL` (new; G2, local, error, or unknown when nothing had to be verified; not waivable). `G1-V1` can now be `warning` (standard rail in advice) or `unknown` (unreadable number). `G2-TOOL-ERROR` and `G2-INTERNAL-ERROR` are `error` when code meets a modelable requirement (fail closed), `unknown` otherwise. `G2-SIM-*` are warnings for register snippets without requirements (I6). The `G2-NOT-IN-CODE` condition changed (I1).

**Tests adapted because they encoded removed behaviour** (all others unchanged):
- `test_gate_codeblocks::test_prose_drops_analysed_c_fences_but_keeps_inline_code_text` (was `..._drops_fenced_blocks_and_inline_code_...`, C3).
- `test_gate_provenance`:
  - `test_values_inside_the_c_code_g2_analyses_are_left_to_g2` (inline code is now checked, C3).
  - `test_a_period_register_value_is_accepted_when_its_ratio_is_written_out` (was a ratio of two user numbers, I2).
  - `test_a_division_written_out_in_the_sentence_is_accepted_but_the_same_value_without_it_is_not` (was user-operand pairing, I2).
  - `where` assertion of `test_invented_absolute_maximum_*`.
- `test_gate_functional`:
  - the NOT-IN-CODE test (now `skipped` + `not_rechecked`, I1/I7);
  - the tool-error test (now fails closed, C1);
  - the missing-toolchain test (C1);
  - the start-state priority test (C2).
- `test_gate_entry`: the waiver test (`G2 skipped`, I7) and the internal-bug test (fails closed, C1).

### Rulings (where the lead's rulings left room)

- **Ruling: witnessed arithmetic.**
  - What: operands must appear before the value in the same sentence (split at `. ! ? ;` and line breaks). Up to the 6 nearest numbers are used, 1–3 operands, × and ÷, integers also ±1. Unit-less operands (`8500`, `170e6`) are not provenance-checked; quantities with units are checked as claims of their own.
  - Why: a value must not witness itself ("25 MHz / 1 = 25 MHz"), and the leftmost value of a chain must have a source.
  - Cost if wrong: a computation written after its result ("20 kHz, i.e. 170 MHz / 8500") is not recognised, so a `G1-V1` costs one rewrite. An invented unit-less operand inside a correct-looking formula passes.
- **Ruling: rounding only against structured outputs.**
  - What: rounding is allowed only against structured fields of the solver, the simulator, `set_clock_config` or Board State, never against user or lookup numbers (those must match exactly).
  - Why: this follows the I2 text.
  - Cost if wrong: "20.0 kHz" for a user's "20 kHz" is still exact; "≈ 20.1 kHz" needs the arithmetic written out.
- **Ruling: dropped "don't do this" C fragments are G1-checked.**
  - What: C fragments dropped next to a full program are now checked by G1 as prose.
  - Why: the literal reading of "only fences G2 actually analyses are excluded".
  - Cost if wrong: an invented register value inside a negative example triggers `G1-V2`.
- **Ruling: G4 language-independent error condition.**
  - What: an error requires advice wording AND an MCU-specific token (VDD/VBAT/VREF/MCU/vi điều khiển/chip name). Supply/rail/nguồn alone gives a warning.
  - Why: "error only when advice" is read as a necessary condition. "Cấp nguồn 5 V cho cảm biến" (power the sensor) is not about the MCU, and the contract asks G4 prose to be conservative.
  - Cost if wrong: VI advice about the MCU's "nguồn" that never names VDD or the chip is only a warning.
- **Ruling: negation words.**
  - What: the English negation list now also contains "max"/"maximum". With the VI words, a sentence such as "VDD max 5 V" is never flagged.
  - Cost if wrong: unsafe advice phrased with "max" is missed.
- **Ruling: dict `ctx.initial` is ignored.**
  - What: a dict-valued `ctx.initial` is ignored like the agent's dict, because the runtime copies the agent's simulation start into `ctx`.
  - Cost if wrong: a runtime that deliberately passes a `{"preset": ...}` dict falls back to "reset" unless the requirement or the agent's simulation names the preset.
- **Ruling: missing clang fails closed.**
  - What: missing clang (`no_toolchain`) fails closed for G2 when code meets a modelable requirement.
  - Why: it is "any reason that comes from the tool" in C1.
  - Cost if wrong: on a machine without clang every design answer with code fails G2 and escalates. That is honest (the requirement cannot be verified) but costly.
- **Ruling: unreadable requirements stay unknown.**
  - What: when `get_board_state` fails, G2 does not know whether a modelable requirement exists, so the result is `unknown` + `skipped` (op-level checks still run).
  - Cost if wrong: a Board State outage lets requirement mismatches through, visible as G2 `skipped`.
- **Ruling: a waived finding makes any gate `skipped`.**
  - What: a waived finding makes its gate `skipped` in general, not only G2 (e.g. a waived `G5-SKIPPED`).
  - Cost: none known.
- **Ruling: typed Board State fields remain evidence.**
  - What: typed numeric Board State fields remain type (b) evidence (`add_device(i_typ_ua=4600000)` still supports "4.6 A").
  - Why: the I3 ruling says "only typed numeric fields count".
  - Cost if wrong: laundering through typed device fields stays possible.

### Re-run of the reviewer's cases (their scripts, unchanged)

`crash.py`, `crash2.py`, `adv_g2b.py` (A2 laundering via `initial.ops`, A9 3000-iteration loop), `d1.py` (real D1 drafts), `fp.py`, `fp2.py`, `g1.py`, `g1b.py`, `g1c.py`, `g1d.py`, `g1e.py`, `g1f.py`, `g4.py`, `snip.py`, `waive.py`. Every case marked as a defect now behaves as ruled. In particular, D1 draft#1 with the runtime's context passes (start `code_configures_clock`), and all C1 triggers fail closed.

Still accepted, value-level, documented below:
- "TIM1 kernel clock is 340 MHz" (340 MHz really is in the evidence, as the VCO);
- `[S p.82]` / `[Datasheet p.82]` (substring doc names, skipped by ruling);
- invented times, MSPS and dB (units not covered).

Still rejected, out of scope of the rulings:
- "TIM1 base address 0x40012C00" (address − offset);
- citations in parentheses or "(RM0440, trang 1267)" (only bracketed citations are recognised).

`fp2.py` C3 fails, correctly: its TIMINGR `0x00310309` gives 533–889 kHz, and PB8's AF row is on p.74, not p.73. With `0x10320309`, G2 passes.

Residual G1 acceptance of random invented values on the realistic D1 evidence set (same measurement as round 0, 400 random 3-significant-digit claims per unit):

| Unit | Round 0 | Round 1 | v1 |
|---|---|---|---|
| MHz | 4.0 % | 2.2 % | 3.0 % |
| kHz | 2.8 % | 1.0 % | 1.5 % |
| V | 1.0 % | 1.0 % | 0.8 % |
| mA | 0.5 % | 0.5 % | 2.5 % |

### Could not do / not done (by ruling or out of scope)

- Skipped by ruling, kept as known limits:
  - the `DRC-CLK-01` unknown noise;
  - substring doc-name matching in citations;
  - ```` ```c:main.c ```` info strings (not recognised as C, consistent with the grader).
- Runtime side, which is the controller's code:
  - copying `details["start"]` into the `gate_result` event;
  - parsing requirement ids with `requirement_id()` in `_unmet_requirements`;
  - `count_error` treating `G1-V1` as one code (G1 `where` now names the claim, so per-claim counting is possible).
- Units still unchecked by G1: s/ms/µs/ns, %, baud, MSPS, LSB, dB, bit.

### Tests

```
$ agent/.venv/bin/python -m pytest agent/tests/test_gate_*.py -q -p no:cacheprovider
267 passed in 5.2s      # codeblocks 42, compile 7, drc 11, entry 30, functional 52, provenance 79, safety 32, types 14 (was 159)
$ agent/.venv/bin/python -m pytest agent/tests -q -p no:cacheprovider
1626 passed in 87.3s
```

Mutation check (round 1): 21 mutations of the new rules were tried, and each one makes at least one test fail. Four survived the first pass; tests were added for them:
- prior bare numbers feeding hex ±1;
- user-number rounding;
- the citation-range overlap;
- the > 2000-op pre-check (no simulator call).

---

## Fix round 2 (re-review "Re-review of fix round 1" in `gate_review.md`)

Status: **DONE_WITH_CONCERNS**. Every item ruled on is implemented (I-1, I-2, I-3, I-4, m1–m4; m5 skipped by ruling). Scope unchanged: only `agent/agent/gate/*.py` and `agent/tests/test_gate_*.py` were edited. The reviewer's round-1 probes (`review_gate/r1_*.py`, unchanged) were re-run; their deterministic cases are regression tests.

### What changed, per item

| Item | Change | Tests |
|---|---|---|
| **I-1 witnessed arithmetic** | The round-1 combination search (any 1–3 earlier numbers with blanket ±1) is removed. `provenance._Sentence` tokenises the normalised sentence (numbers with units, hex, `e` notation, `+ - × · * / ÷ x ( ) %`, relation markers `= ≈ → ⇒ i.e. gives is là được …`). For a claim right after a relation marker, the arithmetic written just before that marker is parsed by `_Parser`, a recursive descent parser (no `eval`; whitelisted tokens; ≤ 40 tokens; ≤ 16 reading combinations). It accepts implicit `)(`, same-sentence assignments `NAME = number` (e.g. `PSC = 0 … ((PSC+1)(ARR+1))`), and a continuation from the previous result (`340 MHz, then / 2 = …`). The expression is evaluated, and the claim passes iff the result matches (≤ 0.5 %; hex: \|Δ\| < 1) **and every operand is supported**: tool, lookup or user value; an earlier claim or witnessed step (recursive, leftwards only); or a value already established in the answer. A literal `1` counts only in an explicit `X+1` / `X-1`. Unparseable → unsupported (no guessing). Hex ±1 now only means the N−1 encoding of PSC/ARR/PRESC/SCLL/SCLH (`ARR + 1`), never `value − 1`. A claim repeated with the same value later in the answer counts as "stated earlier". | `test_i1_*`: the reviewer's six wrong-factor sentences fail; continuation `/ 2 = 170 MHz` passes and `= 160 MHz` fails; an unsourced operand fails; an expression with undefined variables fails; the UART chain `= 1475.7 ≈ 0x5C4` passes and `0x5C8` fails. `test_i2_arithmetic_written_*` (adapted: operands now need a source). `test_hex_plus_one_*` (`0x2132` = ARR−1 fails). |
| **I-2 G4 false positives** | Language-independent rule: never applied to a sentence with a conversion word (LDO, regulator, buck, boost, converter, DC-DC, step-down, level shifter, divider, hạ áp, ổn áp, chuyển đổi, bộ chia, mạch hạ, hạ xuống) or to a sentence the English rule already judged. Only the voltage nearest a VDD/VBAT/VREF/supply/nguồn/MCU/chip token is compared. A pin described as FT / "5 V tolerant" / "chịu 5 V" uses the DB's FT input limit (VDD + 4.0 V) instead of the supply limit, in both rules. English rule in conversion sentences: judged only when every voltage in the sentence is above the limit. | `test_i2_correct_power_chains_and_ft_pins_are_not_flagged` (the reviewer's N1–N3, N5–N8 plus a nearest-voltage case); "Use a 5 V LDO to power VDD" still an error; a 5 V signal to PA4 (no FT) still reported. |
| **I-3 LaTeX scientific notation** | `normalize_text` folds `a \times 10^{n}`, `a × 10^n`, `a·10^n`, `a \cdot 10^{n}`, `a\,10^{n}` and `10^{n}` into one number `aen`; parentheses around the whole value are kept. `^` and `{` are excluded from the number lookbehind, so an exponent is never read as the number before a unit. Also added: `\texttt{}` unwrap and `\Rightarrow`/`\implies`/`\to` → `⇒` (a relation marker). | `test_i3_*` (codeblocks, provenance): `170 \times 10^{6}\,\text{Hz} / 8500 = 20 kHz` passes; `2.5 \times 10^{-3} A` is one claim, `answer: "2.5e-3 A"`. |
| **I-4 intermediate C4 turn** | A requirement counts as set this turn only if it is NEW or a specification field (everything except `status`, `evidence`, `waiver_reason`) differs from the start of the turn. The start-of-turn list is read with a read-only `get_board_state(section="requirements", version=v−1)`, where v is the version returned by this turn's first successful `set_requirements`. Fallback: a `get_board_state` read earlier in the turn. If neither is available, every re-sent id is checked (conservative). | `test_i4_*` (real versioned Board State): unchanged re-send with new evidence → not re-checked (`not_rechecked = ["R1"]`, no error); `freq_hz` changed → checked (`G2-NO-EFFECT`); no version known → checked. |
| **m1** | "Code configures the clock ⇒ reset" now needs a write touching `RCC_CFGR.SW` or `RCC_PLLCFGR` PLLSRC/PLLM/PLLN/PLLREN/PLLR. PLLPEN, PLLQEN, PLLP, PLLQ and PLLPDIV no longer count. | `test_m1_*` (5 op shapes). |
| **m2** | Hex values below `0x2000_0000` that are a contiguous run of 1-bits (`0x8000`, `0x800`, `0xF0`, `0x0000_8000`, `1 << k`) are field masks, not claims. Addresses (≥ `0x2000_0000`, even power-of-two ones such as `0x40000000`) and other hex stay checked. | `test_m2_*` (the reviewer's M1–M3 pass; `0x40000000` and `0x2135` still fail). |
| **m3** | A header unit (`Value (MHz)`) is not carried to a row whose label is a divider/count field (PRESC, SCLDEL, SDADEL, SCLL, SCLH, ARR, PSC, N/M/R/P/Q, PLLx, BRR, CCRx, USARTDIV, div…, prescaler…, count…, bits, steps, ticks, WS, latency, OVER8), nor to a row that has its own unit in another cell (`µs`, `%`, `bit`, `baud`, any SI unit…). | `test_m3_*` (the reviewer's R3b table: only `16 MHz` is checked). |
| **m4** | `number_values` never overflows (`1e309` → unreadable → `G1-V1` unknown). `Gate.run` makes every gate fail closed with an error `Gn-INTERNAL-ERROR` (kind local) when it had something to check: G1 if the prose has claims or citations; G3 if the Board State has a target; G4 if there is a target, code or a voltage in the prose; G5 if there is code (G2 as in round 1). Otherwise the finding stays `unknown`. If deciding whether there is something to check itself raises, the gate fails closed. | `test_m4_*` (codeblocks, provenance, entry: G1/G3/G4/G5 closed; nothing to check → unknown). |

Removed as dead code: `codeblocks.numbers()` (replaced by the sentence tokenizer).

**Tests adapted because they encoded removed behaviour:**
- `test_gate_provenance::test_i2_arithmetic_written_in_the_sentence_is_accepted`. Its round-1 cases relied on operands without a source (`(1+1)` with PSC only stated later, and `PSC = 1 … gives 10 kHz` with no written expression). Now the user text supplies the operands, and the cases are `(0+1)(8499+1)`, `((PSC+1)(ARR+1))`, `16 MHz / 4 × 85` and `170 MHz / 8500`.

All other round-0/1 tests are unchanged and pass.

### Re-run of the reviewer's round-1 probes (scripts unchanged)

| Probe | Result now |
|---|---|
| `r1_wit.py` | The six wrong-factor sentences fail on the wrong value. Random kHz values in a D1-style sentence: 0/400 accepted (round 1: the ×2/÷2 class passed). Random V values in a lookup-style sentence: 0/400. |
| `r1_wit2.py` | PWM (both phrasings): only ×1 passes. SYSCLK: ×1 and ×2 pass. ×2 = 340 MHz is accepted as a direct value (the VCO really is 340 MHz in the evidence; value-level limit). UART ×1 now fails: its operand `1476` has no source in the D1 evidence (operand rule). |
| `r1_g4.py` | N1–N8 pass G4. N7/N8 fail **G1** for "12 V", which is not in the evidence (correct provenance behaviour; "3.3 V" in the imperative N8 is a rail warning). |
| `r1_real.py` | R0–R4 pass, including the LaTeX `10^{6}` forms and the `Value (MHz)` table. |
| `r1_c4.py` | Both turn-2 variants pass (G2 `skipped`, R1 not re-checked). |
| `r1_c2.py` | The PLLQEN case keeps the agent's preset (`agent_simulation`). The "task from reset, no clock code" residual is unchanged (C2 partial by ruling). |
| `r1_inline.py` | M1–M3 pass. M4 (base = address − offset) still fails, out of scope. M5–M7 fail on `0x0855`, which really is wrong: CCR1 = 2125 = `0x084D`, and `0x0855` = 2133. M7 also fails on "3.3 V" in a ```` ```json ```` fence (non-C fences are checked, C3 ruling). |
| `r1_misc.py` | X1 (m5, skipped by ruling) still passes G4. X2 is now one claim `2.5e-3 A`. |
| `r1_perf.py` | `1e309` probes: no internal error. Timings: 300-row table 0.12 s (round 1: 0.54 s); 300 sentences × 6 operands 0.07 s (0.91 s); 2000 numbers + 199 claims 0.07 s; D1 final answer 0.069–0.210 s, 1 distinct output over 10 runs. |

Residual acceptance of random invented claims on the D1 evidence (same 400-claim measurement as before): MHz 2.2 %, kHz 1.0 %, V 1.0 %, mA 0.5 % (unchanged; these are direct value coincidences, not arithmetic).

### Rulings (round 2)

- **Ruling: only the arithmetic right before the result counts.**
  - What: an expression counts only if it is the run of arithmetic tokens immediately before the relation marker that precedes the claim, read leftwards (skipping trailing `,;:`) until the first non-arithmetic token.
  - Why: this is "the expression the answer actually writes"; anything further away is a guess.
  - Cost if wrong: formulas split by words ("170 MHz divided by 8500 gives 20 kHz") or symbolic forms with unassigned names ("chia R = 2 được 170 MHz") are not recognised and cost a rewrite.
- **Ruling: assignments are taken from the same sentence.**
  - What: only `NAME = number` written earlier in the same sentence is substituted. Names assigned in another sentence are unknown.
  - Cost if wrong: `PSC = 0.` in one bullet and `f = …/(PSC+1)…` in the next is rejected.
- **Ruling: any matching value supports a bare operand.**
  - What: a bare operand counts as supported if the same value exists anywhere in the evidence (typed tool field, lookup number, user number).
  - Why: this is the "structured/lookup/user value" rule.
  - Cost if wrong: a coincidental small number lets a correctly computed but semantically wrong expression pass. Example: "prescaler 2 … 170 MHz / 2 = 85 MHz" is accepted against D1 because PLLR = 2.
- **Ruling: hex `+1` is tied to N−1 fields.**
  - What: `+1` for hex is accepted only from fields encoded N−1 (`psc`, `arr`, `presc`, `scll`, `sclh`); `value − 1` is never accepted.
  - Why: off-by-one is the classic PSC/ARR error.
  - Cost if wrong: a register value written as `field − 1` without the formula needs the formula written out.
- **Ruling: the English rule only judges conversion sentences when every voltage is too high.**
  - What: in a sentence with a conversion word, the English rule judges only if every voltage is above the limit. The language-independent rule never judges such a sentence (per ruling).
  - Why: power-chain sentences contain an input above the limit and an output below it.
  - Cost if wrong: an unsafe sentence that also mentions a safe voltage and a regulator ("connect VDD to 5 V, the LDO gives 3.3 V") is missed.
- **Ruling: the FT limit comes from the DB.**
  - What: the FT limit is the largest absolute-maximum `input_voltage` row whose `applies_to` starts with `FT` (VDD + 4.0 V for STM32G474). In the English rule's pin check the FT rows replace the TT rows.
  - Cost if wrong: a pin labelled FT that is actually FT_c (5.5 V) is checked against 7.3 V in the language-independent rule.
- **Ruling: unknown start state ⇒ check every re-sent requirement.**
  - What: when the start-of-turn requirement list cannot be read (no version in the `set_requirements` result, and no earlier read), every re-sent id is checked.
  - Why: fail closed.
  - Cost if wrong: an intermediate C4 turn fails `G2-NO-EFFECT`, but only with a Board State server that does not return versions (ours does).
- **Ruling: deciding whether a gate had something to check is itself fail-closed.**
  - What: "had something to check" is computed with the same extraction functions; if that computation raises, the gate fails closed.
  - Cost: none known.

### Limits (round 2)

- Value-level provenance still accepts a real number of another quantity: "TIM1 clock 340 MHz" (the VCO value), "SYSCLK ×2 = 340 MHz", "prescaler 2" matched by PLLR = 2.
- Written-out arithmetic requires the formula immediately before the result. Prose arithmetic ("divided by"), symbolic forms with names assigned elsewhere, and results written before their formula are not recognised.
- C2 residual (by ruling): when the code does not configure the clock, the agent's last successful simulation preset is still the start state, even if the task said "from reset".
- I1 residual (by ruling): with no code at all, `G2-NO-CODE` is a warning.
- Skipped by ruling: m5 ("max" as a negation word), DRC-CLK-01 noise, substring doc names, `c:main.c`. Base address = address − offset and parenthesised citations remain out of scope.

### Tests

```
$ agent/.venv/bin/python -m pytest agent/tests/test_gate_*.py -q -p no:cacheprovider
321 passed in 5.4s      # codeblocks 52, compile 7, drc 11, entry 35, functional 60, provenance 100, safety 42, types 14 (round 1: 267)
$ agent/.venv/bin/python -m pytest agent/tests -q -p no:cacheprovider
1680 passed in 83.5s
```

Mutation check (round 2): 24 mutations of the new rules were tried.
- 22 make at least one test fail.
- The one real survivor was the continuation step. Its test was satisfied by a direct value, so it was rewritten to make 170 MHz reachable only through `340 MHz, then / 2`, and the mutation is now caught.
- One mutation is equivalent (`before or {}` behaves like the conservative branch).
- One was a no-op (typo in the sed pattern).
