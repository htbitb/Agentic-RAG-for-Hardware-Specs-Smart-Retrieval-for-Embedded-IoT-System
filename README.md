# Agentic RAG for Hardware Specs (STM32G474 / ESP32 / nRF52840 / FreeRTOS)

Agent hỗ trợ thiết kế phần cứng nhúng cho môn CO5151 Agentic AI. Dự án đã chuyển từ v1, một vòng ReAct tra cứu trên dữ liệu chỉ đọc, sang **v2**. Bản v2 có:
- dữ liệu thật từ SVD và PDF;
- Board State và DRC;
- sandbox mô phỏng thanh ghi;
- runtime có kế hoạch, ngân sách, checkpoint và resume;
- Verification Gate G1–G5;
- human-in-the-loop qua interrupt và resume;
- harness đánh giá chung cho 5 hệ.

| Thư mục | Nội dung |
|---|---|
| `agent/` | Agent v2: runtime, Gate, MCP servers, `hwmodel/`, UI (xem `agent/README.md`) |
| `native-RAG/` | Baseline Native RAG (S1) |
| `eval/` | Harness đánh giá, task C1–C8, grader, kết quả (`eval/results/dev_baseline_v2/report.md`) |
| `corpus/` | Corpus chung: PDF, SVD, header |
| `snapshots/` | Các phiên bản agent đóng băng dùng để đánh giá |
| `plan/` | Kế hoạch, sổ quyết định, brief và ledger từng giai đoạn, review, demo |

Đọc theo thứ tự sau:
1. `plan/AgenticUpgradePlan.md`: kế hoạch tổng thể.
2. `plan/DECISIONS.md`: các quyết định (D45–D49 là P6/P7).
3. `plan/HANDOFF_P6_P9.md`: bàn giao P6–P9; `plan/P6_progress.md`, `plan/P7_progress.md`: những gì đã làm sau bàn giao và những gì CHƯA đo.

**Trạng thái (2026-11-18):** P0–P5 đã đo trên dev. P6 (Policy Engine, guardrail biết rail/lớp chân, C7 v2 gián tiếp, cờ A7) và P7 (Lesson memory, C10, cờ A5) đã có mã và test offline nhưng **chưa đo bằng LLM thật**; P8 (UI) làm dở; P9 (đánh giá đầy đủ trên `test`) chưa bắt đầu.

Tái lập môi trường: `agent/requirements.lock.txt`, `eval/requirements.lock.txt`, `native-RAG/requirements.lock.txt` ghim phiên bản đã dùng (Python 3.11); `agent/.env.example` là file cấu hình mẫu. Chạy thử UI: `agent/start.sh --install`; chạy eval: `eval/README.md`.

Khi chạy, tạo `agent/.env` từ `agent/.env.example.txt`. **Không commit `.env`.**
