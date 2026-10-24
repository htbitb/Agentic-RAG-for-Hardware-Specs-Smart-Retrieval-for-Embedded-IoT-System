# CHANGELOG P5 — Human-in-the-loop v2 + sửa tồn đọng P4 (hệ S3@P5)

Brief: `plan/P5_Handoff.md`; quyết định: `plan/DECISIONS.md` D33–D40; ledger + Ruling: `plan/P5_progress.md`; hợp đồng giao diện: `plan/P5_interfaces.md`.

## Sửa runtime theo review P4 (D37) — `agent/runtime/loop.py`
* I1 leo thang giữa lô tool call trả lời nốt mọi call (`tool_skipped`) trước khi wrap-up; wrap-up dùng bản nén; `ScriptedPolicy` kiểm cặp tool_call/tool.
* I3 prompt tất định theo (task, seed) (adapter dùng `session_id` không uuid; không còn đường dẫn tuyệt đối trong kết quả tool).
* I4 chân trang ESCALATED không còn mã lỗi thô; I5 bản nháp/wrap-up lỗi G4 không được trả (`Gate.safety_only`).
* m1 tham số tool không phải object; m2 `args_sha`; m4 `sandboxed-exec` chạy lại khi resume; m5 ảnh chụp Board State ở INTAKE là bằng chứng cho G1; m6 `CLOCK_LIMIT:FLASH_WS` là lỗi cục bộ; I2 trừ thời gian chờ hạ tầng khỏi `wall_s` (`llm.infra_wait_s`).

## G2: trạng thái khởi đầu không do agent chọn (D36) — `runtime/start_state.py`, `gate/functional.py`
Preset/HSE do INTAKE trích từ lời người dùng (hoặc clock có sẵn trong Board State); lệch ⇒ `G2-START-MISMATCH`; `gate_result.start.source` ∈ user_text | board_clock | code_configures_clock | default | context.

## HITL v2 (W7) — `runtime/hitl.py`, `runtime/loop.py`, `runtime/run_api.py`, `ui/server.py`
* `ask_human(kind=choice|clarify, question, options?, why_needed)`; `write_config_file` ⇒ interrupt `approval` (diff, Approve/Reject + góp ý).
* Trạng thái `INTERRUPTED`; `resume(run_id, interrupt_id, decision, payload)` từ checkpoint (kill tiến trình rồi resume ở tiến trình khác); `ResumeError` khi sai/đã dùng; giới hạn `AGENT_BUDGETS={"ask_human": 3}`; mời hỏi khi leo thang `repeated_error`.
* Cờ ablation **A6 `-HITL`** (`AGENT_ABLATIONS=A6`): ẩn `ask_human`, approval tự duyệt.
* Run API: `POST /api/runs`, `POST /api/runs/{id}/resume`, `GET /api/runs/{id}`, `GET /api/runs/{id}/events` (JSON hoặc SSE); lớp Python `RunService` dùng chung cho UI và eval.
* CLI: `python -m agent.runtime.cli --goal ... [--answers JSON | --interactive | --stop-on-interrupt]`, `--resume RUN --interrupt ID --decision ...`.
* Prompt v2: quy tắc 4 (trạng thái khởi đầu), 6 (giả định chỉ cho chi tiết nhỏ), 9 (approval), 11 (khi nào được hỏi) — xem `PROMPT_DEVLOG.md` VÒNG 3.

## Test
`agent/tests`: `test_runtime_p5_fixes`, `test_runtime_start_state`, `test_runtime_hitl`, `test_run_api` (+ cập nhật các test cũ theo D36/I4). Test helper `build(...)` mặc định bật A6 (hành vi P4); test HITL truyền `hitl=True`.
