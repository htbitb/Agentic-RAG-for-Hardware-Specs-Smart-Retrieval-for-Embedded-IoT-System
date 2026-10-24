# Probe 1 (không dùng làm demo chính) — ghi nhận trung thực
Mục tiêu D4 viết KHÔNG nêu nguồn clock. Agent tự chọn HSI16 (hợp lệ), không hỏi gì (0 interrupt), dùng hết ngân sách 40 bước (escalated `budget:steps`), 41 lời gọi LLM, ~$0,086.
Không có thông tin ẩn "bắt buộc" trong đề này nên việc không hỏi là đúng; demo D4 chính (thư mục `run*` kế bên) nêu rõ clock lấy từ thạch anh HSE của bo mà không cho tần số.
Không chỉnh prompt để ép hỏi.
