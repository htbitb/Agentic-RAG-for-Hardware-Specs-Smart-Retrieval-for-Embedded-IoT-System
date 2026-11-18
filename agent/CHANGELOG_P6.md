# CHANGELOG P6 — Guardrail v2: Action Policy Engine + guardrail biết rail/lớp chân (hệ S3@P7)

Quyết định: `plan/DECISIONS.md` D45–D47; ledger: `plan/P6_progress.md`.

## Mới
* `agent/policy.py` — Policy Engine xác định, chạy trước mọi tool call của agent: SUPPLY_ABS_MAX (set_target vượt Absolute Maximum của rail VDD, kèm trích dẫn, ⇒ REPLAN_REQUIRED), WRITE_QUOTA, TAINTED_CONTENT, TAINTED_NO_APPROVER, ARG_TOO_LARGE. Từ chối ⇒ lời gọi KHÔNG chạy; sự kiện `policy_denied` (trace + audit).
* Taint tracking: `guardrail.sanitize_*(collect=)` + `ToolHub.drain_removed()`; trạng thái `AgentState.policy` nằm trong checkpoint; thẻ approval mang `payload.tainted`.
* Ngân sách `Budgets.files` (3 file ghi mỗi run). Cờ ablation **A7 `-Guardrail`** (`AGENT_ABLATIONS=A7`).

## Đổi hành vi
* `guardrail.parse_hardware_requests/evaluate_hw`: biết rail (VDD, VDDH, VBUS...) và lớp chân (FT_c, TT...); rail nRF52840 VDDH/VBUS được xét (trước P6 bị bỏ qua); yêu cầu không nêu phạm vi chỉ bị từ chối ở INTAKE khi không rail/lớp nào chịu được. Sửa over-refusal C6-015 và "5 V vào chân FT". G4 dùng `strict=True` (không nới).
* INTAKE: A7 bỏ qua lọc injection trực tiếp và hardware_check.

## Eval
* `eval/adapters/interceptor.py` (injection gián tiếp / lỗi công cụ ở tầng kết quả tool), `Task.tool_rules`, 14 task C7-016…029, `attack.details.exposed`, mục báo cáo "C7 theo loại tấn công", đăng ký `S3@P7` và A7.

## Test
`test_guardrail_rails`, `test_policy`, `test_runtime_policy`, `test_c7_indirect_tasks`; `eval/tests/test_interceptor`.
