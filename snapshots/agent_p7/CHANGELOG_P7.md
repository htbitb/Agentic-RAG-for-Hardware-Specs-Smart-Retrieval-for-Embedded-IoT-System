# CHANGELOG P7 — Lesson memory (bộ nhớ dài hạn) + C10 (đường cong học)

Quyết định: `plan/DECISIONS.md` D48–D49; ledger: `plan/P7_progress.md`.

## Mới
* `agent/lessons.py` — Lesson memory (SQLite) xác định: ghi sau khi simulator (G2) xác nhận một lần tự sửa (fix = dòng C thêm/bớt, trigger = mã lỗi G2); đọc ở INTAKE theo chip + họ ngoại vi (TIM1 ≡ TIM8 ≡ TIM20), tối đa 3, như gợi ý chưa kiểm chứng. Sự kiện `lesson_written` / `lesson_used`.
* Cờ ablation **A5 `-Lessons`**. Cấu hình `LESSONS_DB` (`config.py`); eval đặt kho trống riêng cho mỗi run; snapshot không mang kho lesson.
* Eval: category C10, `Task.fresh_sessions` (phiên mới mỗi lượt, chung Lesson memory), 2 chuỗi C10-001 (dev) / C10-002 (test), mục báo cáo "C10 — Đường cong học".

## Sau smoke thật (D51)
* Lesson cũng được rút từ tự sửa qua lần `simulate_register_writes` của chính agent (`lessons_from_sims`); `sanitize_observation` quét MỌI chuỗi của kết quả tool (trước chỉ 4 khoá); mỗi task C7 v2 bọc cả bốn tool tri thức.

## Test
`agent/tests/test_lessons.py`; `eval/tests/test_report_c10.py`, `test_adapter_agent_v3_p6p7.py`.
