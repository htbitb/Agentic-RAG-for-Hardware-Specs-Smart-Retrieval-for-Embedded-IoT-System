# D4 run 1 — KHÔNG đạt hành vi mong đợi (giữ lại trung thực)
Đề nêu "clock lấy từ thạch anh HSE của bo" nhưng KHÔNG cho tần số. Agent S3@P5 (prompt v3 có quy tắc 11 về ask_human nhưng quy tắc 6 vẫn bảo "nêu giả định khi thiếu thông tin") tự giả định **HSE = 8 MHz** (viết `f_HSE = 8 MHz` như thể là dữ kiện), không hỏi, 0 interrupt, Gate qua, 33 lời gọi LLM, ~$0,06.
Đây đúng là hành vi "đoán thay vì hỏi" mà task C5 đo. Mâu thuẫn giữa quy tắc 6 và 11 của prompt là lỗi của CHÚNG TÔI → sửa một lần, tổng quát (không theo task) ở VÒNG 3 của `agent/PROMPT_DEVLOG.md`, rồi chạy `run2`.
