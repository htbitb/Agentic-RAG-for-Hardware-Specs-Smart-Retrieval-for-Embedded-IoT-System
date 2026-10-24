# Ghi chú (đọc trước khi dùng run này)

Run 1 của demo D1 (LLM thật `ag/gemini-3.8-flash-medium`, Gate thật **trước fix round 1**). Diễn biến: Gate từ chối bản nháp 1 với `G2-SIM-FLASH-WS`, agent sửa, bản 2 được chấp nhận.

**Không dùng làm bằng chứng "tự sửa".** Review độc lập của Gate (`plan/P4_reports/gate_review.md`, finding C2) chứng minh lần từ chối đó là hiện vật của quy tắc trạng thái khởi đầu:
agent mô phỏng thử một hàm khởi tạo timer bằng preset `sysclk_170mhz_pll_hsi16_apb_div1`; Gate mô phỏng CẢ chương trình (gồm `SystemClock_Config`) bắt đầu từ chính preset đó,
nên `FLASH->ACR &= ~FLASH_ACR_LATENCY` bị coi là hạ wait state ở 170 MHz. Bắt đầu từ `reset` (cách chip thật khởi động) thì bản nháp 1 qua Gate.
Quy tắc đã sửa (fix round 1). Giữ lại run này vì trung thực: nó cho thấy cả vòng Gate → phản hồi có kiểu → sửa → chấp nhận chạy được với LLM thật.
Demo chính thức sẽ nằm ở `plan/demos/D1/` (các run sau fix).
