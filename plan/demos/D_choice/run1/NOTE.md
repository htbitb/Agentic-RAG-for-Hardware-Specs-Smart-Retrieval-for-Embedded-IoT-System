# Demo `choice` (LLM thật) — LEVEL_MISMATCH 1,8 V (không đụng kịch bản 5 V của `hardware_check` v1)
1. Tiến trình A: `cli --goal ... --stop-on-interrupt` → agent đọc thông số, gọi `ask_human(kind=choice)` với 2 phương án có ưu/nhược do agent viết (A: giữ cảm biến 1,8 V + level shifter; B: đổi cảm biến 3,3 V) → thoát mã 3 (checkpoint SQLite trong thư mục này).
2. Tiến trình B (mới): `cli --resume <run_id> --interrupt i_1332aa2b --decision choose --payload {"option":"A", ...}` → runtime ghi `record_decision(by=human)` = D1 vào Board State, agent làm tiếp theo phương án A (level shifter), Gate lần 1 từ chối (G1 provenance), sửa, lần 2 qua. 36 lời gọi LLM, ~$0,05.
`summary.md` chỉ liệt kê chặng sau resume; `trace.jsonl` có đủ hai chặng (interrupt_raised → resumed → human_decision → done).
