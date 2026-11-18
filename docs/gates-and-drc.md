# Ghi chú: 5 cổng Gate (G1–G5) và 8 luật DRC (G3)

Ghi chú nội bộ để chuẩn bị báo cáo/slide. Nguồn: `agent/agent/gate/*.py`, `agent/hwmodel/drc.py`, `docs/architecture.md` §4.4–4.5.

> **Tình trạng trong báo cáo:** `interim-report.pdf` (trang 4) mới chỉ nhắc 5 gate mỗi gate một cụm từ và "8 luật DRC", không liệt kê luật nào.
> Slide cũng chỉ ghi "Gate G1–G5". Nội dung chi tiết hiện chỉ có trong `architecture.md` và file này.
> Đề bài giới hạn 10 trang nội dung (phụ lục không tính), nên chi tiết nên đưa vào phụ lục (xem §4).

---

## 1. Gate là gì

Gate là **cổng kiểm cuối** chạy khi agent gọi `finish`: `Gate.run(ctx) -> GateReport`. Agent không được tự tuyên bố xong. Một câu trả lời chỉ được chấp nhận khi qua cả 5 cổng.

Tính chất thiết kế:

- **Xác định, không dùng LLM.** Gate không đọc prompt, không đọc env, không ghi file. Cùng đầu vào thì cùng kết quả.
- **Chỉ gọi tool read-only:** `get_board_state`, `run_drc`, `analyze_c_code`, `simulate_register_writes`, `compile_check`, `get_electrical_specs`, `get_clock_limits`. Lời gọi khác bị từ chối.
- **Fail closed.** Tool lỗi hoặc ném ngoại lệ thì thành finding `unknown` và cổng ở trạng thái `skipped`. `skipped` **không bao giờ được tính là pass**.
- **Phản hồi có kiểu.** Mỗi lỗi là một `Finding {gate, code, where, expected, actual, hint_source, severity, kind, waivable}`, nên agent biết sửa ở đâu và tra nguồn nào.

| Thuộc tính | Giá trị | Ý nghĩa |
|---|---|---|
| `severity` | `error` | Chặn `finish` |
| | `warning` | Báo, không chặn |
| | `unknown` | Không kiểm được. Không chặn nhưng không bao giờ tính là pass |
| `kind` | `local` | Agent tự sửa tại chỗ rồi `finish` lại |
| | `structural` | Sai chân, xung đột tài nguyên, vượt trần clock. Runtime bật `REPLAN_REQUIRED` và agent phải `update_plan` |

Trạng thái mỗi cổng: `pass | fail | skipped | na`. Nếu cùng một mã lỗi lặp quá `max_repairs` (3) lần thì runtime chuyển sang `ESCALATED` và trả câu trả lời tốt nhất kèm các requirement chưa đạt.

**Miễn trừ (waive):** chỉ `G2-UNMODELED` và `G5-SKIPPED` được miễn, qua `finish(waived_requirements=[{id, reason}])` với lý do không rỗng.

---

## 2. Năm cổng

| Cổng | Câu hỏi nó trả lời | Kiểm cái gì |
|---|---|---|
| **G1 Provenance** | "Số liệu này lấy từ đâu?" | Mọi số, địa chỉ hex và trích dẫn `[doc p.N]` trong câu trả lời phải truy được về kết quả tool, lời người dùng hoặc câu trả lời trước. Số tự tính chỉ hợp lệ khi solver, simulator hoặc clock tool xác nhận. |
| **G2 Functional** | "Code này có làm đúng việc không?" | Mô phỏng chuỗi ghi thanh ghi trong code C trong câu trả lời. So kết quả (chân, tần số, duty, baud, SCL…) với requirement agent đã ghi, xuất phát từ trạng thái khởi đầu lấy từ lời người dùng. |
| **G3 Board DRC** | "Thiết kế có vi phạm luật phần cứng nào không?" | Chạy `run_drc` trên Board State: 8 luật (xem §3). |
| **G4 Safety** | "Có gợi ý nào làm hỏng chip không?" | (i) VDD của target vượt Absolute Maximum, hoặc nguồn ≥ 4 V đẩy vào chân MCU không chịu được; (ii) vi phạm giới hạn clock do simulator báo; (iii) văn xuôi khuyên áp điện áp vượt Absolute Maximum (luật tiếng Anh và tiếng Việt, chỉ là lỗi khi câu là lời khuyên). Khi leo thang, đây là cổng duy nhất áp cho văn bản wrap-up. |
| **G5 Compile** | "Code có biên dịch được không?" | `clang -fsyntax-only` trên khối code C. `skipped` (không có trình biên dịch) không bao giờ là pass. |

Ví dụ thật (S3@P5, C3-020, PLL 168 MHz từ HSE 8 MHz): lần `finish` đầu bị `G1 = fail` vì thiếu trích dẫn trang tài liệu cho dải PLL, G2–G5 pass. Agent bổ sung `[STM32G474_Datasheet p.123]`, lần sau cả 5 cổng pass.

**Liên hệ với ablation:** A2 (`-BoardState`) tắt G3 và G2 không còn requirement để so. A3 (`-Sandbox`) chuyển G1 về `verifier.py` của v1 (`strict_v1_provenance`).

---

## 3. Tám luật DRC (cổng G3)

`run_drc` đọc Board State, không đọc câu trả lời. Mỗi vi phạm có `rule`, `code` (kèm đối tượng, ví dụ `PIN_CONFLICT:PA8`), `severity`, `message`, và `alternatives` hoặc `evidence` (doc + trang) khi có.
Chưa `set_target` thì G3 trả `na`. Nhận lỗi trực tiếp từ `allocate_pin` là cơ chế chặn sớm, còn DRC là lưới kiểm lại toàn bộ trạng thái.

| # | Luật | Quy định | Mã lỗi tiêu biểu | Loại sửa |
|---|---|---|---|---|
| 1 | `DRC-PIN-01` | Mỗi chân một chủ. Chỉ bus khai báo rõ (I2C/SPI/CAN/1-Wire) mới được chia sẻ. Tính cả chân mà requirement đã chiếm. | `PIN_CONFLICT:<pin>` | structural |
| 2 | `DRC-PIN-02` | Tín hiệu phải có trong bảng AF của chân, và chân phải có trong package. | `NO_SUCH_PIN`, `PIN_NOT_IN_PACKAGE`, `NO_SUCH_AF:<pin>`, `TARGET_NOT_SET` (unknown) | structural |
| 3 | `DRC-PIN-03` | Không gán chức năng output cho chân input-only. | `INPUT_ONLY:<pin>`, `INPUT_ONLY_UNVERIFIED` (unknown) | structural |
| 4 | `DRC-CLK-01` | Các tần số dẫn xuất (SYSCLK, HCLK, PCLK, PLL…) không vượt `clock_limits`. Lấy kết quả từ cây clock/simulator. | `CLOCK_LIMIT:<SYSCLK/HCLK/PCLK…>`, `CLOCK_LIMIT:FLASH_WS`, `CLOCK_CONFIG:NO_SOURCE`, `CLOCK_NOT_CONFIGURED` (unknown) | structural |
| 5 | `DRC-CLK-02` | Ngoại vi được dùng phải được bật clock RCC (bit `*ENR`). | `CLOCK_GATE:<periph>`, `CLOCK_ENABLE_UNKNOWN` (unknown) | local |
| 6 | `DRC-ELEC-01` | Nối giữa hai miền điện áp phải qua kiểm mức logic (VOH/VIH, VOL/VIL). Chân không 5 V-tolerant không được nhận 5 V. Kiểm cả giới hạn ADC (VDDA/VREF+). | `LEVEL_MISMATCH:1.8V-3.3V`, `NOT_5V_TOLERANT:<pin>`, `ADC_RANGE:<pin>` | structural |
| 7 | `DRC-PWR-01` | Tổng dòng theo chế độ (run, sleep…) không vượt ngân sách (`budget_ua`) của requirement công suất. Thiết bị thiếu số dòng thì `unknown`, không đoán. | `POWER_BUDGET:<mode>`, `POWER_UNKNOWN`, `POWER_BUDGET_MISSING` (unknown) | structural |
| 8 | `DRC-REQ-01` | Mọi requirement phải `satisfied` (kèm bằng chứng, ví dụ id mô phỏng) hoặc `waived` (có lý do) trước khi `finish`. | `REQ_OPEN`, `REQ_WAIVER_REASON`, `REQ_STATUS_INVALID` (error); `REQ_NO_EVIDENCE` (warning) | local |

Ghi chú:

- Chỉ `DRC-CLK-02` và `DRC-REQ-01` là **local** (`LOCAL_RULES` trong `drc_gate.py`). Sáu luật còn lại là **structural** và buộc agent lập lại kế hoạch.
- `unknown` (thiếu số liệu: chưa có clock, thiếu dòng của thiết bị, thiếu VDDA…) **không chặn nhưng không tính pass**.
- Lỗi chạy `run_drc` hoặc `get_board_state` sinh `G3-TOOL-ERROR` (unknown) và G3 thành `skipped`.
- Không phải mọi xung đột đều do G3 bắt. Hai cơ chế báo sớm nằm ở server `board-state`: `set_requirements` trả `contradictions` (`PIN_CONFLICT:<pin>`, `TIMER_SHARED:<timer>` khi các kênh PWM của một timer có tần số khác nhau), và `allocate_pin` từ chối chân sai/đã có chủ hoặc cảnh báo `PERIPHERAL_SHARED`. Kịch bản demo C4 (`c4_timer_conflict`) là ví dụ: còi 1 kHz đặt cùng TIM3 đang chạy 20 kHz bị báo `TIMER_SHARED:TIM3`, agent chuyển còi sang TIM17. G3 chạy sau cùng như lưới an toàn trước `finish`.

---

## 4. Gợi ý đưa vào báo cáo (giữ trong giới hạn 10 trang)

Phương án nhẹ nhất là thêm **một bảng nén** vào mục 2 (Kiến trúc) và để chi tiết trong phụ lục:

```
G1 Provenance : số/địa chỉ/trích dẫn phải truy về tool hoặc lời người dùng
G2 Functional : mô phỏng code C so với requirement (chân, tần số, duty, baud)
G3 Board DRC  : 8 luật trên Board State: PIN-01/02/03 (chân), CLK-01/02 (clock),
                ELEC-01 (mức logic, 5 V), PWR-01 (ngân sách dòng), REQ-01 (requirement)
G4 Safety     : vượt Absolute Maximum, vi phạm giới hạn clock, lời khuyên áp quá áp
G5 Compile    : clang -fsyntax-only
```

Ba ý nên giữ trong phần văn xuôi:

1. Gate là xác định và read-only. Tool lỗi thì `skipped` và không bao giờ tính là pass.
2. Phản hồi lỗi có kiểu (`code, where, expected, actual, hint_source`) và phân `local` / `structural` để runtime quyết định tự sửa hay lập lại kế hoạch.
3. Chỉ hai trường hợp được miễn (`G2-UNMODELED`, `G5-SKIPPED`) và phải kèm lý do.
