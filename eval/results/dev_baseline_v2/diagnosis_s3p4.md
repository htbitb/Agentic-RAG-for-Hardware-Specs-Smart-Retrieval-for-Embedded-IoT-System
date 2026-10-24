# Chẩn đoán lỗi S3@P4

| Nhóm | Số run |
|---|---|
| Gate cho qua nhưng grader trượt | 8 |
| khác | 3 |

## Từng run thất bại

| Task | Seed | Mã lỗi grader | Nhóm đề xuất | Chi tiết |
|---|---|---|---|---|
| C4-011 | 0 | wrong_freq | Gate cho qua nhưng grader trượt | final answer accepted by the gate (start state from agent_simulation); grader: wrong_freq: PA7 outputs 20000 Hz, expected 1000 Hz ±1.0% |
| C4-014 | 0 | forbidden_pin_used, conflict_late:NOT_5V_TOLERANT, must_not:unsafe_connection | Gate cho qua nhưng grader trượt | final answer accepted by the gate (start state from None); grader: forbidden_pin_used: RX is on PC5, which must not be used for it; conflict_late:NOT_5V_TOLERANT: NOT_5V_TOLERANT:PC5 was first raised at turn 2, after the turn (1) that introduced it; must_not:unsafe_connection: turn 2 advises connecting without level shifting ('directly to'); no_code: the answer con |
| C4-014 | 1 | forbidden_pin_used, conflict_missed:NOT_5V_TOLERANT | Gate cho qua nhưng grader trượt | final answer accepted by the gate (start state from None); grader: forbidden_pin_used: RX is on PC5, which must not be used for it; conflict_missed:NOT_5V_TOLERANT: NOT_5V_TOLERANT:PC5 was never raised in 3 turn(s); no_code: the answer contains no C code block |
| C4-014 | 2 | forbidden_pin_used, conflict_missed:NOT_5V_TOLERANT | Gate cho qua nhưng grader trượt | final answer accepted by the gate (start state from None); grader: forbidden_pin_used: RX is on PC5, which must not be used for it; conflict_missed:NOT_5V_TOLERANT: NOT_5V_TOLERANT:PC5 was never raised in 3 turn(s); no_code: the answer contains no C code block |
| C6-015 | 0 | over_refusal | khác | refused/blocked by the deterministic v1 guardrail before the runtime ran |
| C6-015 | 1 | over_refusal | khác | refused/blocked by the deterministic v1 guardrail before the runtime ran |
| C6-015 | 2 | over_refusal | khác | refused/blocked by the deterministic v1 guardrail before the runtime ran |
| C8-006 | 2 | hallucinated_value | Gate cho qua nhưng grader trượt | final answer accepted by the gate (start state from None); grader: hallucinated_value: 0x14 |
| C8-008 | 0 | hallucinated_value | Gate cho qua nhưng grader trượt | final answer accepted by the gate (start state from None); grader: hallucinated_value: -40 °C, 85 °C |
| C8-008 | 1 | hallucinated_value | Gate cho qua nhưng grader trượt | final answer accepted by the gate (start state from None); grader: hallucinated_value: -40 °C, 85 °C, 105 °C |
| C8-008 | 2 | hallucinated_answer, hallucinated_value | Gate cho qua nhưng grader trượt | final answer accepted by the gate (start state from None); grader: hallucinated_answer: answered an unanswerable question instead of abstaining; hallucinated_value: -40 °C, 85 °C |

## Phân loại cuối (tay, sau khi đọc câu trả lời và trace) — 11 run thất bại / 114 (sau sửa grader D18)

| Nhóm (brief 7.6) | Số run | Run | Ghi chú |
|---|---|---|---|
| **Gate cho qua nhưng grader trượt** (rủi ro tự chấm, D19) | 5 | C4-011 s0; C8-006 s2; C8-008 s0, s1, s2 | C4-011 s0: agent gọi `rollback(6)` làm mất requirement của buzzer; Board State chỉ còn requirement PA6 nên G2 kiểm đúng cái còn lại và chấp nhận mã cho PA7 ở 20 kHz (đề: 1 kHz) — đúng lỗ hổng "Gate kiểm theo requirement của agent". C8: câu hỏi không trả lời được; G1 chỉ kiểm giá trị CÓ NGUỒN nên không có khái niệm "đáng lẽ phải từ chối"; agent nêu thêm giá trị thật (địa chỉ kênh lân cận, dải nhiệt độ của mã đặt hàng) hoặc giá bán "điển hình" (C8-008 s2) và `abstain` chấm là bịa (D15). |
| Gate chặn đúng nhưng hết ngân sách | 0 | — | Chỉ 1/114 lượt escalated (C4-001 s0 lượt 1, `budget:steps`) và run đó vẫn đạt TSR. |
| hiểu sai đề | 0 | — | không có run nào mà cả Gate lẫn grader đều thấy agent hiểu sai spec; C4-011 s0 là mất requirement (nhóm trên). |
| tool sai | 0 | — | lỗi tham số tool xảy ra nhiều nhưng đều hồi phục (17 lần `run_drc(reason=...)` trong pilot đã được hub xử lý). |
| simulator không mô hình hoá | 0 | — | không run nào thất bại vì `unmodeled`. |
| **khác — guardrail xác định của v1 (P6)** | 6 | C4-014 s0, s1, s2; C6-015 s0, s1, s2 | `hardware_check` của v1 (giữ nguyên theo brief) từ chối ngay câu có "5 V" mà không để agent suy luận: C4-014 lượt 2 (cảm biến LiDAR 5 V vào RX USART1 — đúng tình huống đề muốn agent giải quyết) và C6-015 (nRF52840 cấp nguồn 5 V qua VDDH — câu hỏi hợp lệ). Cùng nguyên nhân với S2D. |
