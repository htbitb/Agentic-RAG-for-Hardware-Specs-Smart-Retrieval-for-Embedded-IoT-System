# P4 — Independent review: Agent Runtime v3 + S3@P4 evaluation adapter

Reviewer: independent subagent (did not write this code). Date: 2026-10-23. Read-only on `agent/`, `eval/`, `snapshots/`, `plan/` (only this file was created).

**Verdict: Spec ✅ (all brief items present; the deviations are documented Rulings) · Quality: approved for the in-progress P4 evaluation (no Critical finding). Five Important items need a fix or a post-hoc audit before the S3@P4 numbers are reported, and before the P9 ablations.**

## Scope and method

- Code: `agent/agent/runtime/{state,checkpoint,loop,control_tools,flags,factory,intake,trace,summary,cli}.py`, `agent/agent/scripted.py`, `agent/agent/tools.py`, `eval/adapters/agent_v3{,_worker}.py`, `eval/graders/process.py`, `eval/score.py`, and the tests `agent/tests/test_runtime_*.py` and `test_tool_hub_p4.py`. I looked at the Gate only where it meets the runtime.
- Snapshot: `diff -r -x __pycache__ agent/agent snapshots/agent_p4/agent` reports the two trees as **identical**, so the line numbers below (under `agent/`) also hold for the frozen copy the evaluation runs.
- Scratch tests are in `/private/tmp/claude-501/-Users-loc4atnt-Master-Course-Ky3-AgenticAI-project/ff56cc68-8a5f-4c62-a87c-6c5ef9dd7c8d/scratchpad/review_runtime/test_review_findings.py`. There are 18 tests and all of them pass. A pass means the defect is present, except for the tests marked "control". Run them with `agent/.venv/bin/python -m pytest <dir> -q -p no:cacheprovider`. They use no network and no LLM.
- Mutation spot-check: `/private/tmp/claude-501/-Users-loc4atnt-Master-Course-Ky3-AgenticAI-project/ff56cc68-8a5f-4c62-a87c-6c5ef9dd7c8d/scratchpad/review_runtime/mutate.py` mutates a **copy** of `agent/`. Of 18 mutations, the suite caught 15 and 3 survived (see m7).
- Real traces were read only (read-only) from `eval/results/{pilot_p4,pilot_p4_full,pilot_p4_round1,ablation_smoke_p4}`. I did not open `dev_baseline_v2/` (that run is in progress) or `eval/.cache`.

## Findings

### Critical

None.

### Important

**I1. When a run escalates in the middle of a tool batch, the wrap-up LLM call is sent with unanswered `tool_calls` and the rest of the batch is silently dropped.**
- *Evidence:*
  - `_run_pending` appends the tool message only after `_exec_call` returns (`loop.py:247-248`).
  - `_exec_call` runs `_classify` inside itself (`loop.py:285-286`), and `_classify` can call `_escalate` (`loop.py:441-442`).
  - With no draft yet, `_escalate` goes to `_wrapup` (`loop.py:449`), which calls `self.llm.chat(state.messages, [])` (`loop.py:513`). At that moment the last assistant message still has tool calls with no answers. `_terminate` then empties `pending_calls`, so the other calls of the batch never get a tool message.
  - Scratch tests `test_F1_*` (a pairing checker inside the policy) confirm this. `test_F1c` and the `test_control_*` tests show that the budget, REPLAN-block, finish-in-batch, gate-fail and compaction paths keep the pairing correct.
  - **This happened in a real run:** `ablation_smoke_p4` C4-001 `-Reflection`, seed 0, turn 2. At seq 11 `simulate_register_writes` returned SIM-CLK-GATE, SIM-I2C-PE and SIM-I2C-TIMING. Seq 13 is the `llm_call wrapup=True`. Seq 14 is `escalated repeated_error SIM-CLK-GATE`. The wrap-up model wrote the turn's final answer without seeing the simulation result that caused the escalation.
  - The current gateway accepted the malformed request. A strict OpenAI-compatible endpoint returns 400, which becomes `error:BadRequestError` and therefore a system error.
- *Why it matters:* It breaks the message-pairing invariant. The final answer is written blind, and the stored transcript is malformed. Under A4 (`max_repairs=0`), every first agent-side simulator violation or structural board refusal takes this path, so the P9 `-Reflection` numbers would be measured on blind wrap-ups.
- *Can it affect the in-progress evaluation of the frozen snapshot?* **YES, rarely.** In the main configuration it needs the 4th occurrence of the same simulator-violation code, or of the same `CODE:pin` board refusal, before any draft exists. That happened 0 times in the 76 S3 runs of pilot_p4_full and pilot_p4_round1.
- *Fix:*
  1. In `_classify`, record a pending escalation instead of escalating on the spot.
  2. Escalate in `_run_pending` after appending the current tool message, plus a synthetic `{"error": "not executed: run escalated"}` tool message for each remaining call.
  3. Send `self._view(state.messages)` to the wrap-up call.
  4. Add a well-formedness assertion to `ScriptedPolicy.chat` so the whole suite guards this invariant.

**I2. Infrastructure waiting time is charged to the agent's `wall_s` budget, and a `budget:wall_s` escalation is scored as a system failure with no telemetry to separate the two.**
- *Evidence:*
  - `used["wall_s"]` adds the monotonic time between checkpoints (`loop.py:553-557`). That time includes the whole `llm.chat` call.
  - In the worker, that call goes through `LLMCache._with_retry` (`eval/llm_cache.py:138-162`). This includes the cross-process limiter, backoff of 2, 4, 8, 16 and 32 s (62 s for five retries), and server-hinted waits of up to 300 s.
  - The worker reports only the call count and flags (`agent_v3_worker.py:76-92`). Retries and wait times are not reported.
  - A `budget:wall_s` escalation skips the wrap-up (`loop.py:509`) and returns the fallback text with no code. The BUDGET NOTICE at 75 % of `wall_s` also changes the agent's behaviour.
  - Pilot `pilot_p4_round1` C4-012, seed 0, turn 0: one LLM step took **209.9 s** (the gap between the `run_drc` tool_call and the next `llm_call`), which was half of the 420 s budget in force then. The turn ended `escalated budget:wall_s` with 0 answer attempts. From the trace it is impossible to tell whether that time was model latency or retries.
- *Why it matters:* S3 is the only system with a wall-clock budget, so gateway slowness becomes S3 failures counted in TSR. This biases S3 downward: conservative for the claim, but noise that cannot be removed afterwards.
- *Can it affect the in-progress evaluation?* **YES.** Any `budget:wall_s` escalation in `dev_baseline_v2` may be partly infrastructure.
  - Audit now: for each such turn, sum the gaps before `llm_call` events and list the turns where a single gap exceeds about 60 s.
- *Fix:*
  1. Have `LLMCache` expose limiter and backoff seconds, and subtract them from `wall_s`.
  2. Record per-call latency and retry count in the `llm_call` event.
  3. Raise an `infra:slow_llm` flag when waits make up a large share of the budget.

**I3. Every S3@P4 prompt contains a run-unique project id, so LLM-cache keys never repeat and `--cache replay` cannot reproduce any S3@P4 run.**
- *Evidence:*
  - The adapter uses `session_id = f"{task.id}-s{seed}-{uuid4().hex[:6]}"` (`agent_v3.py:75`), and that value becomes the `project_id`.
  - `intake.project_context` writes `PROJECT CONTEXT (project <id>; ...` into a system message (`intake.py:72-80`, `loop.py:174-177`). It does this even for an empty board, because `get_board_state` returns version 0 rather than None.
  - Board tool results echo `project_id` (`board_state_server.py:117`).
  - The cache key is the sha256 of (model, messages, tools, temperature, seed) (`llm_cache.py:64-66`).
  - Scratch tests `test_F2`/`F2b`: the same task, seed and model give different first prompts, and therefore different keys.
  - `smoke_replay_p4` ran only S0 through S2D.
- *Why it matters:* README §2 and §10 say a replay reproduces answers and TSR, and the checklist requires "smoke replay 0 cache-miss". For S3@P4, every replayed call would be an `infra:cache_miss`. Results cannot be re-run without cost, and a `--resume` re-pays for every unfinished run.
- *Can it affect the in-progress evaluation?* **NO** for the numbers. **YES** for reproducibility.
- *Fix (either one):*
  - Use a deterministic project id per (task, seed); the per-run directory already isolates the database.
  - Or keep the id out of the prompt: remove it from `project_context`, and strip `project_id` from board tool results in the hub.

**I4. The escalation footer generated by the runtime is credited by the gating conflict detector (PIN_CONFLICT family).**
- *Evidence:*
  - The footer is built at `loop.py:452-461`. It contains `why` (for `repeated_error`, this includes the code, e.g. `(CONFLICT:PA8)`).
  - It also contains `_tried`'s "recurring problems: CONFLICT:PA8 x1" (`loop.py:501-502`), taken from counters keyed `CODE:pin` (`loop.py:428`).
  - With the eval venv, `eval.graders.conflicts.detect(text, "PIN_CONFLICT:PA8")` gives:
    - body alone: **None**;
    - body plus the repeated-error footer: **match**;
    - body plus a budget footer containing "CONFLICT:PA8 x1": **match** (the evidence sentence is the "What was tried" line).
  - TIMER_SHARED, NO_SUCH_AF, NOT_5V_TOLERANT and LEVEL_MISMATCH footers do not match.
  - No pilot evidence sentence came from a footer so far.
- *Why it matters:* `conflict_detected` gates TSR, and Proactive Detection Rate is a headline metric. Under D28, silently choosing another pin does not count. The footer can turn exactly that silent re-route into a credited "proactive detection" on an escalated turn. The D29 blind labelling was calibrated on prose, not on this machine-generated text.
- *Can it affect the in-progress evaluation?* **YES, narrowly:** escalated C4 turns at or after the cause turn whose counters contain `CONFLICT:<pin>`.
  - Audit: re-grade with the footer removed (`answer.split("\n---\n**Not fully verified")[0]`) and publish the change.
- *Fix:*
  - Keep raw codes out of the user-visible text: unmet and tried items already go into `escalation` and the trace.
  - Or have the adapter strip the footer before grading.
  - Include S3 footers in the D29 re-check.

**I5. Escalation can hand the user a draft that failed the safety gate (G4), and the wrap-up answer never passes through any gate.**
- *Evidence:*
  - `_best_artifact` (`loop.py:466-471`) picks the draft with the fewest failing codes, whichever gates failed.
  - `_wrapup` text is returned without running the Gate (`loop.py:449`, `507-521`).
  - Scratch `test_F8`: a draft rejected with `G4-5V-NON-FT` (1 code) beats a later draft with 3 codes. The escalated answer starts with "Connect the 5 V sensor output directly to PC5; it is fine."
  - Scratch `test_F8b`: a wrap-up saying "Apply 6 V to VDD, it is fine." is returned, and the Gate is never called.
  - This contradicts the Ruling "every product that reaches the user has passed the Gate".
- *Why it matters:* This is a safety regression against v1. v1 abstained ("Insufficient evidence") when its check failed; v3 emits content its own safety gate rejected, marked only by a code in the footer.
- *Can it affect the in-progress evaluation?* **YES in principle, not observed.** There were no G4 failures across the pilot and ablation-smoke traces.
- *Fix:*
  1. Exclude artifacts with any G4 error from `_best_artifact`.
  2. Run at least G4 (better, the whole Gate) on the wrap-up text.
  3. If nothing safe remains, return the fallback text with the safety finding stated in words.

### Minor

- **m1. Tool arguments that are not a JSON object escape `ask()`.**
  - `OpenAICompatLLM` keeps whatever `json.loads` returns, so `"null"` becomes None, `"[]"` a list and `'"abc"'` a string.
  - Each then fails outside any handler: `"__malformed__" in args` (`loop.py:268`), `args.items()` (`tools.py:155-157`), or `{**args, ...}` (`tools.py:159`). The result is TypeError or AttributeError (scratch `test_F3`).
  - The worker turns this into an `error:` turn, which is correct labelling. But the run is never finalized, so the next user turn is numbered 0 again and loses the failed turn from its context (scratch `test_F6`).
  - Fix: `if not isinstance(args, dict): args = {"__malformed__": json.dumps(args)}`.
- **m2. The duplicate-call metric uses args clipped to 400 characters.**
  - `_emit_call` stores `args=clip(args)` (`loop.py:292`, `trace.py:8-10`), and `process._call_key` hashes that string (`process.py:81-82`).
  - Two `analyze_c_code` calls whose code differs after 400 characters count as a duplicate (scratch `test_F4`).
  - In the pilots, 3 of 23 duplicates had clipped args, so they cannot be confirmed.
  - Fix: emit `args_sha` (sha256 of the canonical JSON of the full args) in the event and key on it.
- **m3. `process.turns` is always one higher than the real number of turns.**
  - The adapter adds `{"type": "worker"}` with no turn or run_id (`agent_v3.py:89`), and `_turns` groups it as a turn of its own.
  - pilot_p4_round1: (actual, reported) = (1, 2) ×33, (3, 4) ×4, (4, 5) ×1.
  - It is not used in `aggregate`, and `ended_escalated` is unaffected. Drop events without `run_id` in `_turns`.
- **m4. Resume treats `sandboxed-exec` tools as at-most-once,** while the Ruling (P4_progress) says they are re-run. Every non-read-only permission sets `in_flight` (`loop.py:275-278`); see scratch `test_F5`. No impact on the evaluation, which never resumes. Align the code or the Ruling.
- **m5. What the model is shown is not what G1 can cite.**
  - The PROJECT CONTEXT board summary (derived clocks, pins, requirement values) and the intake `get_electrical_specs` results are never added to `state.observations` (`loop.py:174-177`, `intake.py:20`). G1 sees only this turn's tool calls, user texts and *accepted* earlier answers (`loop.py:334-335`).
  - So in a later turn, a value shown in the context whose source turn escalated causes a G1 failure until the agent calls the tool again. That costs extra repair rounds.
  - Fix: pass the intake board snapshot as an internal observation.
- **m6. `CLOCK_LIMIT:FLASH_WS` is classed as structural.** The model can fix it locally by setting `flash_latency`, yet it forces REPLAN_REQUIRED and an extra LLM call (`loop.py:425-430`).
- **m7. Gaps in the test suite.**
  - Three mutations survived:
    - re-append history on every `_finalize` (`loop.py:570`);
    - feed escalated earlier answers to G1 as evidence (`loop.py:335`);
    - treat an empty reply as a final answer (`loop.py:234`).
  - `ScriptedPolicy` never checks that messages are well-formed, which is why I1 went unnoticed.
  - `test_with_the_sandbox_ablated...` asserts nothing about the outcome.
  - The killed mutations, by contrast, show the core guarantees are well pinned down: read-only-only retry, REPLAN blocking, `in_flight`, per-call checkpoint, the repair budget, the step and wall budgets, the notice, the fail-closed Gate, the footer, and `sim_context`.
- **m8. Cosmetic issues.**
  - `state.status` never takes the values OBSERVE or CHECK, and it stays ACT after REPLAN instead of returning to PLAN.
  - For an explicit `finish`, the agent's `tool_call` event comes after `done`.
  - The wrap-up uses the full uncompacted message list, which makes it the largest prompt of the run (fold this into the I1 fix).

## Checked and fine

- **State machine and contract.**
  - INTAKE runs the guardrail input check, then v1's hardware check, word for word (`intake.py` vs `react_agent.py:156-185`), then the board and plan context. Then PLAN, then ACT/OBSERVE (`_classify`), then FINISH_GATE (explicit `finish` or implicit text), ending in DONE, REFUSED or ESCALATED.
  - The `ask`/`resume` return shape matches P4_interfaces §3.
  - Every exit from `_drive` is terminal except an escaped exception (m1).
- **Checkpointing.**
  - The state is saved after intake, after every tool call, after every LLM text step (via feedback or terminate), and when tool calls become pending. The in-flight marker is set before every non-read-only call.
  - Resume equivalence is covered by in-process kills at 0–3 and real `os._exit(137)` kills at 1 and 3.
  - Wall time is not counted while the process is dead.
- **Message pairing.** Pairing holds for budget escalation, REPLAN-blocked calls, `finish` refused inside a batch, Gate-fail feedback, compaction (`_view` only shortens content) and `_interrupt_in_flight` (scratch control tests).
- **REPLAN.**
  - It cannot deadlock: `finish` stays allowed, a failed `update_plan` leaves REPLAN pending, and every round costs a step.
  - A1 hides `update_plan` and never sets REPLAN.
  - A REPLAN raised by a Gate failure is announced once, after the batch or in the feedback message.
- **Budgets and accounting.** Steps, tokens, usd and wall are checked before each LLM call (the wrap-up can exceed the step budget by one call, as documented). `llm_calls`, tokens and usd are counted once per successful call, wrap-up included. The worker's `llm_calls` (which counts cache hits) matches the `llm_call` events.
- **Escalation output.** Escalation never returns an empty "step budget exhausted"; the text always carries a body, the unmet requirements (or failed codes) and what was tried. `_finalize` writes the session history exactly once per run.
- **ToolHub.**
  - Only read-only tools are retried; TypeError, ValueError and KeyError are never retried.
  - `project_id` is injected for every board tool and hidden from the schema. A `project_id` sent by the model is dropped, because `_props` excludes it, and then overwritten.
  - Unknown arguments are dropped and reported back.
  - Internal calls are not counted as agent tool calls.
  - `write_config_file` still goes through `approval.request` and is only queued (`pending_approval`).
  - No MCP tool takes a filesystem path from the model.
- **Isolation between runs.** I found no leakage across runs, tasks or seeds.
  - There is one worker process per task, with its own directory for memory, audit, sandbox, board state, checkpoints and traces.
  - The adapter scrubs the `AGENT_*` and `TEXT_INDEX_*` prefixes and the database variables; `BOARD_STATE_PROJECT` is removed.
  - The snapshot contains no `.env`.
  - Module-level caches live for one process, i.e. one task. The session persists across the turns of a task (same `rt`, same checkpoint DB).
  - Because the project id is unique (I3), the shared LLM cache cannot carry anything from one S3 run to another.
- **Status mapping.**
  - `escalated` maps to `answered`.
  - Runtime LLM errors get the `error:` prefix, but the infrastructure flag (`infra:`) is kept, so these runs are excluded as infrastructure.
  - An exception that escapes the runtime gives `error:`, a system error, which is correct.
  - `fatal:` aborts the whole run.
  - No realistic BaseException path exists in the runtime that would kill a worker and be mislabelled as `infra:adapter_crash`.
  - Graders never read `RunResult.board_state` (D25).
- **Process grader against real events.** A scripted run (agent sim fail, sim pass, structural Gate fail, update_plan, pass) gives checks `FPFP`, self-corrected, 2 repair iterations, 1 replan with 1 plan update after the trigger, replan accepted, and 1 rejected `finish` out of 2.
  - The Gate's own `sim_result` is correctly left out of the check chain.
  - Every agent sim carries an artifact tag, so the docstring's "untagged exploratory sims are excluded" clause never applies. In practice only 1 of 33 pilot self-corrections came from simulations alone.
- **Ablation flags.**
  - A1 hides `update_plan` and removes REPLAN.
  - A2 hides the board-state server and sets G3 off with `board=False`.
  - A3 hides the sandbox and sets G2 and G5 off with strict v1 provenance.
  - A4 sets `max_repairs` to 0.
  - All four are wired through the factory and through the worker's environment and arguments.
- **No hard-coded routing in the main path.** `route()` is gone; `parse_entities` is used only for the hardware check and for the chip remembered in history.
- **ScriptedPolicy cannot reach real runs.** Both the runtime and the factory refuse a simulated LLM, and the worker exits with `simulated_llm`.

## Residual risks (not defects of this code)

- **Any text-only reply is a final answer, and G2-NO-CODE is only a warning.** So a design turn can end without any code.
  - The prompt says a short factual lookup "may be answered in plain text", but does not say that any text reply ends the turn.
  - Pilot round1 C4-014 turn 2: the model repeated the previous turn's guardrail refusal, the Gate accepted it, and `final_state` failed.
- **The v1 hardware check is kept as the brief asks, but S3 resolves the chip from any earlier goal, while v1 used only verified turns.**
  - In C4 this refuses legitimate design statements, e.g. C4-014 turn 1 "RX driven by a LiDAR powered at 5 V", probably more often than S2D. This affects the S3 vs S2D comparison on C4 (fix in P6).
- **Under A4, the first agent-side simulator violation or board refusal escalates.** This is by Ruling, and it goes through I1.
- **The current gateway tolerates two kinds of request a strict endpoint could reject with 400:**
  - an assistant message with empty content and no tool calls (the "Your reply was empty" path);
  - a tool-call history sent with `tools=[]` (the wrap-up).
