# P4 — báo cáo phần eval (subagent `eval-implementer`; nội dung do subagent gửi qua tin nhắn, controller lưu lại nguyên văn tóm tắt)

Status: DONE_WITH_CONCERNS · `eval/.venv/bin/python -m pytest eval/tests -q -p no:cacheprovider` → 955 passed, 1 skipped (baseline 826). Không file nào dưới `agent/` hoặc `snapshots/` bị chạm.

## Files
Mã mới: `eval/graders/process.py`, `eval/adapters/agent_v3.py` (chứa `ABLATION_VARIANTS`), `eval/adapters/agent_v3_worker.py`.
Test mới: `test_grader_process.py`, `test_score_process.py`, `test_report_process.py`, `test_run_s3p4.py` (gồm chạy run → score → report có ablation), `test_adapter_agent_v3.py`, `test_worker_agent_v3.py` (chạy worker thật trên snapshot giả), `trace_builder.py`.
Sửa: `score.py`, `report.py`, `run.py`, `system_prompts.py`, `tools/freeze_snapshot.py`, `README.md` (§10), `test_freeze_snapshot.py`, `test_system_prompts.py`; hai assertion cũ đổi: `SYSTEM_ORDER` (test_report.py), `SYSTEMS_ALL` (test_run.py).

## Hành vi
* `score.py` gắn `graders.process` chỉ khi trace có `run_started`, SAU khi `tsr_pass` đã chốt ⇒ không ảnh hưởng TSR; chấm lại bản sao `dev_baseline`/`dev_baseline_v2` cho `scores.jsonl` giống hệt.
* `report.py`: `SYSTEM_ORDER` = S0,S1,S2,S2D,S3@P4,S3; `PAIRS` thêm (S3@P4,S2D), (S3@P4,S0); mục "Chỉ số quá trình (S3)" sau mục C4 (Self-Correction + tỷ lệ cuối cũng đạt grader độc lập, Mean Repair Iterations, replan + Replan Effectiveness 2 cách, Premature-Finish Rate, Step Efficiency + gọi trùng, phủ `plan_updated` C3/C4, số lượt escalated, phân bố mã gate fail); ablation hiển thị `S3@P4 [-Planner]`…, không gộp vào hệ chính.
* `run.py`: `S3@P4` đăng ký (không nằm trong `--systems` mặc định); `--ablations A1..A4` (chỉ với S3@P4, THAY cho lượt chạy chính; chạy hai lần vào cùng `--out` để có cả hai); Runner giữ một adapter cho mỗi (hệ, biến thể); manifest ghim `snapshot_agent_p4_sha256` + `snapshot_agent_p4_data_sha256`.
* Adapter/worker theo mẫu agent_v1: tiến trình riêng `python -I -B`, quét env (`AGENT_*`, `TEXT_INDEX_*`, `HW_SPECS_DB`, `BOARD_STATE_*`, `HWMODEL_DATA_DIR`, `MEMORY_DB`, `AUDIT_LOG`, `SANDBOX_DIR`), `escalated`→`answered`, trace phẳng, `board_state` của lượt cuối, `bad_run_dir`/`build_runtime_failed` dừng cả lượt chạy.
* `freeze_snapshot` loại thêm `data/board_state.sqlite`, `data/checkpoints.sqlite` (kể cả -wal/-shm/-journal) và `data/traces/`.

## Ruling của subagent (nơi hợp đồng im lặng)
1. Chuỗi kiểm tra = `gate_result` + `sim_result` của agent có `artifact`; bỏ `sim_result` source="gate" (đếm hai lần làm phồng Mean Repair Iterations). 2. `plan_updated` "sau trigger" chỉ tính sau `replan_required` hoặc `gate_result` fail cùng lượt. 3. Replan Effectiveness quyết định theo lượt (kết thúc bằng `finish` accepted sau replan, không `escalated` sau đó); cách 2 theo `tsr_pass`. 4. Step Efficiency = mọi tool call của agent / số run `tsr_pass`. 5. Gom lượt theo `(turn, run_id)`. 6. `--ablations` THAY cho lượt chạy chính. 7. `DEFAULT_SYSTEMS` giữ S0..S2D. 8. Timeout lượt S3@P4 = max(--timeout, 600) (controller đã nâng lên 900 s sau pilot). 9. Gắn nhãn biến thể ở `build_report`. 10. Mục quá trình chỉ hiện khi có hệ có trace v3. 11. Quét cả họ tiền tố `AGENT_*` (một `AGENT_ABLATIONS` lạc sẽ âm thầm biến hệ chính thành ablation). 12. `variant` suy từ ablations. 13. `usd` tính từ giá cấu hình, bỏ `usage.usd` của runtime. 14. `errors` runtime không có tiền tố thành `error:<msg>`. 15. Worker thoát 5 khi build_runtime lỗi thay vì sinh 12 dòng lỗi hạ tầng; giữ cờ hạ tầng khi `ask()` ném. 16. `system_prompts.py` nạp `snapshots/agent_p4/agent/prompts/system_v3.md` cho grader `attack`.

## Lưu ý (concerns) và việc controller đã làm
* Worker chỉ thử trên snapshot giả → controller đã chạy thật: pilot `eval/results/pilot_p4*`, `ablation_smoke_p4`, và lượt dev đầy đủ.
* Chỉ số quá trình dựa trên tên trường §4 (`pass`, `passed`, `accepted`, `internal`, `artifact`): runtime phát đúng các trường đó; mô phỏng thăm dò của agent luôn mang `artifact` (`sim#N`).
* `ASSUMPTIONS["S3@P4"]` ban đầu là giá trị tạm → controller hiệu chỉnh từ pilot (13,7 lời gọi/lượt, 21 600 token vào, 240 ra).
* Self-Correction đo theo Gate của chính agent; report in kèm tỷ lệ cuối cũng đạt grader độc lập.
