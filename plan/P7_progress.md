# P7 ledger — Memory v2: Lesson memory + task chuỗi C10 (hệ S3@P7 sẽ là bản đóng băng kế tiếp). Quyết định: plan/DECISIONS.md D48–D49
(Cùng nhánh feat/p6-policy-engine; chưa commit. Định dạng: `Ruling: … — lý do — chi phí nếu sai`.)

## Ruling
- Ruling: **Lesson memory tất định** — `agent/agent/lessons.py`: `LessonStore` (SQLite; id = băm (chip, họ ngoại vi, mã lỗi, fix) nên cùng bài học không ghi hai lần), `lessons_from_run` (chính sách ghi), `render` (gợi ý đưa vào ngữ cảnh). Tích hợp `loop.py`: `_learn` sau khi Gate chấp nhận (trước `_terminate`), `_lesson_context` ở INTAKE; sự kiện `lesson_written` / `lesson_used` trong trace và audit (đúng danh sách W8 mục 5); lỗi kho lesson (đĩa đầy...) KHÔNG bao giờ làm hỏng một run (audit `lesson_store_error`). — Lý do: W6 yêu cầu bộ nhớ dài hạn có chính sách ghi/đọc; làm tất định để tái lập và không tốn lời gọi. — Chi phí nếu sai: lesson kém chất lượng bị đưa vào như gợi ý (không phải sự thật); mọi đáp án vẫn qua Gate.
- Ruling: **chỉ ghi khi simulator xác nhận** — bản cuối phải có G2 = pass; mã lỗi hạ tầng/không sửa được bằng code bị loại; không ghi khi không có thay đổi mã, không rõ chip/ngoại vi, bị bộ lọc injection gắn cờ, hoặc run từng nhận observation bị gắn cờ (lesson là đường bền vững vào ngữ cảnh: chống đầu độc bộ nhớ, rủi ro R6).
- Ruling: **họ ngoại vi** — TIM1/TIM8/TIM20 ≡ TIM-ADV (RM0440: BDTR, MOE); các ngoại vi khác bỏ chữ số cuối. Đây là tri thức phần cứng, không phải luật theo task; không có bảng cho họ nào khác ngoài timer vì chưa có bằng chứng cần.
- Ruling: **cô lập (D05)** — worker đặt `LESSONS_DB=<thư mục run>/lessons.sqlite` (trống); `_SCRUB` chặn `LESSONS_DB` từ shell; `freeze_snapshot` loại `data/lessons.sqlite*`; `.gitignore` thêm `agent/data/lessons.sqlite*`. Test bắt cả hai (test_lessons).
- Ruling: **A5 `-Lessons`** — không ghi, không đọc; biến thể `-Lessons` đăng ký trong adapter S3 (`ABLATION_VARIANTS["A5"]`).
- Ruling: **C10 + fresh_sessions (D49)** — lý do và thiết kế ở D49. Kiểm trước khi tin task: mã chuẩn TIM20 CH2 PC2 5 kHz 60 % qua `final_state` (pass), cùng mã bỏ `BDTR.MOE` bị bắt `SIM-TIM-MOE`. Báo cáo: mục "C10 — Đường cong học" (số lần Gate không qua mỗi lượt; dùng/ghi lesson; chấp nhận). Chain test (C10-002) viết bởi cùng phiên thiết kế bộ nhớ — cần người khác duyệt.
- Ruling: **không** thêm hint lesson theo mã lỗi lúc Gate fail (chỉ INTAKE) — giữ P7 nhỏ; nếu đường cong dev không giảm, đó là lượt chỉnh kế tiếp (ghi PROMPT_DEVLOG/D-mới, báo số vòng chỉnh).
- `system_v3.md` KHÔNG đổi (lesson đến qua system message riêng, không sửa prompt gốc) ⇒ không có vòng PROMPT_DEVLOG.

## Test (offline, không LLM thật)
- `agent/tests/test_lessons.py` (12): họ ngoại vi, diff mã, kho (dedupe/tìm/đếm), chính sách ghi (G2 skipped, không đổi mã, mã hạ tầng, còn lỗi ở bản cuối, văn bản có injection), ghi + dùng lại qua hai runtime, A5, run bị gắn cờ, kho hỏng, và **Gate thật**: thiếu MOE ở TIM1 ⇒ `G2-SIM-TIM-MOE` ⇒ sửa ⇒ lesson "+TIM1->BDTR |= TIM_BDTR_MOE;" ⇒ phiên mới cho TIM8 thấy lesson.
- `eval/tests/test_report_c10.py` (3), `test_adapter_agent_v3_p6p7.py` (2).

## Chưa làm / cần người dùng
1. Đo thật: S3@P7 trên chuỗi C10-001 (dev) với và không có A5, nhiều seed — đây mới là bằng chứng R3/H4; chi phí nhỏ (một chuỗi 3 lượt ≈ 3 task C3), cần duyệt mô hình + ngân sách.
2. Demo D5 (UI): kịch bản ghi sẵn cho lesson TIM1 → TIM8 cần một run LLM thật (chưa có) rồi thêm vào `demo_scenarios.json`; P8 chưa làm.
3. Người khác duyệt/viết lại C10-002 và C7-023…029 trước khi khoá P9.
