# Agentic RAG for Hardware Specs (STM32G474 / ESP32 / nRF52840 / FreeRTOS)

Agent hỗ trợ thiết kế phần cứng nhúng cho môn CO5151 Agentic AI. Dự án đã chuyển từ v1, một vòng ReAct tra cứu trên dữ liệu chỉ đọc, sang **v3**. Bản v3 có:
- dữ liệu thật từ SVD và PDF;
- Board State và DRC;
- sandbox mô phỏng thanh ghi;
- runtime có kế hoạch, ngân sách, checkpoint và resume;
- Verification Gate G1–G5;
- human-in-the-loop qua interrupt và resume;
- harness đánh giá chung cho 5 hệ.

| Thư mục | Nội dung |
|---|---|
| `agent/` | Agent v3: runtime, Gate, MCP servers, `hwmodel/`, UI (xem `agent/README.md`) |
| `native-RAG/` | Baseline Native RAG (S1) |
| `eval/` | Harness đánh giá, task C1–C8, grader, kết quả (`eval/results/dev_baseline_v2/report.md`) |
| `corpus/` | Corpus chung: PDF, SVD, header |
| `snapshots/` | Các phiên bản agent đóng băng dùng để đánh giá |
| `plan/` | Kế hoạch, sổ quyết định, brief và ledger từng giai đoạn, review, demo |

Đọc theo thứ tự sau:
1. `plan/AgenticUpgradePlan.md`: kế hoạch tổng thể.
2. `plan/DECISIONS.md`: các quyết định.
3. `plan/HANDOFF_P6_P9.md`: trạng thái hiện tại và phần việc còn lại.

Khi chạy, tạo `agent/.env` từ `agent/.env.example.txt`. **Không commit `.env`.**
