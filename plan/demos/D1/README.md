# Demo D1 — PWM có tự sửa (P4)

Kịch bản (`plan/AgenticUpgradePlan.md` §6 D1, brief P4 bước 7.1): *"Trên STM32G474 chạy 170 MHz, tạo PWM 20 kHz, duty 25% ở PA8 để điều khiển driver động cơ. Sinh code CMSIS."*
Chạy bằng LLM thật (`ag/gemini-3.8-flash-medium`) qua `cd agent && .venv/bin/python -m agent.runtime.cli --goal "..." --out <thư mục>`; mỗi thư mục có `summary.md` (dòng thời gian dễ đọc), `trace.jsonl` (sự kiện chuẩn hoá, Phụ lục D), `answer_turn0.md`.
Không sửa prompt để ép agent mắc lỗi.

| Thư mục | Nội dung | Diễn biến thật |
|---|---|---|
| `run1/` | D1 gốc, Gate TRƯỚC fix round 1 | Gate từ chối bản nháp 1 (`SIM-FLASH-WS`), agent sửa, bản 2 qua. **Đừng dùng làm bằng chứng tự sửa:** review độc lập chứng minh đó là hiện vật của quy tắc trạng thái khởi đầu (xem `run1/NOTE.md`). |
| `run2/` | D1 gốc, Gate sau fix | **Đúng ngay lần đầu** (18 lời gọi LLM, 13 tool call): mô phỏng PASS 20 000 Hz / 25 % trên PA8, Gate G1–G5 pass. Có 2 lần `simulate_register_writes` lỗi định dạng `ops` (`KeyError: 'mask'`) do agent tự dựng sai rồi sửa — lỗi dùng tool, không phải lỗi vật lý. |
| `run3_apb2_div2/` | Biến thể: bộ chia APB2 = 2 | **Đúng ngay lần đầu** (31 lời gọi, 28 tool call); cũng có vài lần gọi tool lỗi tham số rồi sửa. |
| `run4_from_reset/` | Biến thể: từ reset, tự cấu hình PLL 170 MHz rồi PWM | Gate TỪ CHỐI lần 1 vì `G1-V3` (thiếu trích dẫn cho giá trị tra cứu), agent sửa, lần 2 qua — tự sửa kiểu **provenance**, không phải kiểu mô phỏng. |
| `example_from_dev_eval/` | Hai run THẬT của lượt đánh giá dev (S3@P4, task C3-001 seed 2 và C3-016 seed 0), không phải lời nhắc D1 | **Chuỗi "mô phỏng báo lỗi → agent sửa → mô phỏng qua → Gate chấp nhận"** (`SIM-GPIO-MODE`, `SIM-I2C-PE`...). Đây là bằng chứng vòng kín vật lý; D1 với lời nhắc gốc không tự mắc lỗi vật lý trước Gate. |

Ghi nhận trung thực: với lời nhắc D1 gốc agent làm đúng ngay; vòng kín được quan sát ở các task dev khó hơn (xem mục "Chỉ số quá trình" của `eval/results/dev_baseline_v2/report.md` và bảng phân rã trong `plan/P4_progress.md`).
