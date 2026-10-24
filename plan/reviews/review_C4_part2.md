# Review độc lập C4 — phần 2 (C4-009 … C4-015)

Reviewer: mắt thứ hai độc lập (ngữ cảnh mới, không phải tác giả). Ngày 2026-10-23 (~01:25). Phạm vi: C4-009, 010, 011, 012, 013, 014, 015 trong `eval/tasks/C4/c4_curated.yaml`.
Không sửa file nào của dự án; mã thử nghiệm nằm ở `/private/tmp/claude-501/-Users-loc4atnt-Master-Course-Ky3-AgenticAI-project/ad321631-49fc-4c9f-8c62-71d1a95a9c16/scratchpad/review_c4_r2/`.

**Trạng thái file được đo** (sha256 đầu 8 ký tự; mtime): `conflicts.py` 374297a6 (01:11:49), `conflict_detected.py` a07df8a2 (01:05:33), `functional_sim.py` 34f0d9a1 (01:05:33), `c4_curated.yaml` b4866a49 (01:12:20).
**Lưu ý:** các file này bị tác nhân khác sửa TRONG lúc tôi review (cue của `conflicts.py` đổi ít nhất 2 lần; YAML thêm `from_turn: 4` cho `CLOCK_LIMIT:SYSCLK` của C4-015; `detect_unsafe_connection` được thêm ràng buộc `_cue_pin` cho cue MỀM). Mọi số đo bộ nhận diện dưới đây đúng với bộ hash trên; chạy lại sau mỗi lần sửa (`scratchpad/.../matrix.py`).

## Bảng tóm tắt

| Task | Kết luận | Vấn đề chính |
|---|---|---|
| C4-009 | **OK** | Số liệu/AF/mức áp đúng, tự tính khớp. Minor: lượt 2 "Tell me how to wire it" gần như mớm xung đột; spec thiếu `over8: 0` (chương trình OVER8 = 1 vẫn PASS; C4-010 cũng thiếu). |
| C4-010 | **FIX** | Spec bất đối xứng: người dùng ghi CỤ THỂ PB6/PB7 cho cả PWM (lượt 0) lẫn USART1 (lượt 1), nhưng spec chỉ chấp nhận hướng "đổi USART". Hướng hợp lệ "giữ USART1 ở PB6/PB7, dời PWM sang PD12/PD13 hoặc PA11/PA12" bị chấm trượt. Minor: trích sai chương (p.1179 là TIM1). |
| C4-011 | **OK** | Đúng cả về xung đột, số liệu, spec (chấp nhận TIM17, TIM16, TIM8_CH1N, TIM1_CH1N). Chỉ vài diễn đạt tự nhiên bị bộ nhận diện bỏ sót. |
| C4-012 | **AMBIGUOUS** | Đề nêu "USART1" lẫn "PA2/PA3" (đúng là chân USART2/VCP); spec ép đổi chân, loại phương án "USART2 trên PA2/PA3". Minor: giả định gói LQFP64 không có trong đề; bộ nhận diện bỏ sót dạng "PA2/PA3 là chân USART2, không phải USART1" (5/11). |
| C4-013 | **OK** | Đúng; spec công bằng (cả hai hướng sửa). Minor: biến thể `arr_computed_with_a_16bit_limit` đặt tên sai bản chất (34000 < 65536). Bộ nhận diện `PIN_CONFLICT:PB10` có recall thấp trên diễn đạt tự nhiên (9/19). |
| C4-014 | **FIX** | (1) `tx_pin: PC4` loại oan phương án hợp lệ "chuyển cả TX+RX sang PA9/PA10 hoặc PB6/PB7". (2) `must_not: unsafe_connection {pin: PC5}` cho DƯƠNG GIẢ trên câu trả lời đúng ("PA10 chịu 5 V nên nối thẳng LiDAR vào PA10": 2/5 mẫu bị chấm trượt). |
| C4-015 | **OK** | Tính toán PLL/I²C/PWM/BRR khớp tay; spec chấp nhận mọi cách sửa hợp lệ đã thử. Minor: spec cho lọt SDA→PF0 (chân OSC_IN của thạch anh HSE đang dùng); thiếu biến thể "quên wait state Flash". |

Tổng: 4 OK, 2 FIX, 1 AMBIGUOUS. `verify_tasks --categories C4` = **0 vấn đề** (15 task) tại thời điểm cuối review.

## Phương pháp (những gì đã làm, độc lập với simulator)

* **AF/loại chân bằng text trang PDF** (`GradeContext.page_text`): DS12288 p.73–79 (bảng AF) cho mọi chân dùng (PA2, PA3, PA6–PA10, PB4, PB6, PB7, PB10, PB11, PC4, PC5, PC10, PD7, PE0/1, PF0, PF6, PG9); loại chân p.56 (chú giải), p.58 (PF0-OSC_IN FT_fa), p.61 (PC5 **TT_a**), p.66 (PA9/PA10 **FT_fda**), p.71 (PB7 FT_f); điện p.84 (Table 17), p.123 (Table 46), p.128–130 (Table 54/55, Figure 25). RM0440: p.98 (Table 9), p.232–233 + p.267 (R1MODE), p.281, p.291–293 (PLLCFGR), p.322–324 (CCIPR), p.1294/1319/1288/1389 (timer), p.1404/1499 (TIM15/16/17), p.1632/1645/1647 (I²C), p.1707–1708/1755 (USART). Mọi AF, loại chân, số trang trong `conflict_facts`/`evidence` đều khớp (bảng AF đọc đúng cột AF0…AF15; PA2/PA3 chỉ có USART2 ở AF7, không có USART1 ở AF nào).
* **Tự tính lại** bằng script riêng không dùng simulator/grader (`calc.py`): BRR (184 / 1476 / 738), PSC/ARR/CCR (17000 tick → ARR 16999, CCR 5100/10200; 8500 → 8499/3400; 170000 → PSC 3, ARR 42499, CCR 21250; 34000 → 33999/27200), PLL (duyệt M/N/R: nghiệm DUY NHẤT cho 170 MHz từ HSE 8 MHz là M=2, N=85, R=2, f_in 4 MHz, VCO 340 MHz; **không có** nghiệm hợp lệ cho 180 MHz — mọi cặp cho VCO ≥ 360 MHz > 344 MHz), I²C Sm 100 kHz @170 MHz (duyệt 1767 bộ PRESC/SCLL/SCLH thoả tLOW ≥ 4,7 µs, tHIGH ≥ 4,0 µs, chu kỳ 10 ± 0,1 µs; bộ 15/59/45 cho tLOW = 5647,06 ns, tHIGH = 4329,41 ns, f ≈ 100,0 kHz; SCLDEL ≥ 13, SDADEL ≥ 3 theo Table 356 với tr = 1000 ns, tf = 300 ns, tSU:DAT = 250 ns). **Tất cả khớp `reference_calc` và code.**
* **Biên dịch bằng header ST chính thức** `corpus/headers/cmsis-device-g4_v1.2.6` (clang `--target=thumbv7em-none-eabi -mcpu=cortex-m4 -Wall -fsyntax-only`, stub `core_cm4.h`): khối code cuối của cả 7 task biên dịch **0 lỗi, 0 cảnh báo**; mọi macro (`RCC_PLLCFGR_PLLSRC_HSE`, `RCC_CFGR_HPRE_DIV2`, `FLASH_ACR_LATENCY_4WS`, `PWR_CR5_R1MODE`, `GPIO_AFRH_AFSEL9_Pos`, `I2C_TIMINGR_PRESC_Pos`, `TIM_BDTR_MOE`…) có trong header ST.
* **Chương trình thay thế hợp lệ / sai** chạy qua `final_state` (≥ 3 mỗi task, xem từng mục) để tìm "cách sửa hợp lệ bị loại oan" và "cách sai lọt qua".
* **Bộ nhận diện:** 174 phép chấm (câu × mã) viết tay, mỗi `must_detect` ≥ 3 dương + ≥ 2 âm, gồm cả câu cảnh báo ở câu thứ hai, diễn đạt "đối lập" ("X là chân USART2, không phải USART1"), và câu sai kiểu "đã dùng PB6 nhưng cứ remap". Tổng: **TP 77 / FN 44 / TN 45 / FP 8** (recall 0,64; precision 0,91). Đây KHÔNG phải ước lượng recall thật (tôi cố ý chọn nhiều dạng diễn đạt khó), chỉ để chỉ ra lớp câu nào bị chấm sai.
* **Biến thể sai:** chạy toàn bộ `wrong_variants` của 7 task, in đủ mã lỗi thực nhận + kết quả của grader kia.

---

## C4-009 — USART2 921600 baud + module BLE 1,8 V — **OK**

**Đã xác minh**
* Đề: lượt 0 đủ quy ước D20, trạng thái `sysclk_170mhz_pll_hsi16_apb_div1`, VDD = 3,3 V, ±2 %, ghi BRR trước UE. Không `unmodeled`.
* AF: PA2 = USART2_TX AF7, PA3 = USART2_RX AF7 (DS p.73). PA2 FT_a, PA3 TT_a (chỉ 3,6 V nhưng đầu vào 1,8 V nên không liên quan).
* Xung đột có thật: PA2 (VOH ≥ VDD − 0,4 = 2,9 V, Table 55 p.130) đẩy 3,3 V vào chân 1,8 V → vượt; PA3 nhận 1,8 V < VIH(min) = 0,7·VDD = 2,31 V (Table 54 p.128; nhánh mô phỏng 0,49·VDD + 0,26 = 1,877 V và TTL 2 V ở Figure 25 p.129 cũng > 1,8 V). `LEVEL_MISMATCH:1.8V-3.3V`, `turn: 1` đúng.
* BRR: 170e6/921600 = 184,46 → 184 → 923913 baud (+0,251 %); USART2SEL reset = PCLK (RM p.324). Khớp.
* Biến thể: 7/7 trượt đúng mã `expect` (xem bảng dưới); `final_state` và `conflict_detected` độc lập (biến thể conflict vẫn pass final_state và ngược lại).

**Phát hiện**
1. **Minor** — Lượt 2: "Tell me how to wire it, and update the design if needed." Câu "tell me how to wire it" gần như yêu cầu chính chủ đề điện áp, nên "chủ động" không thật sự được thử (mọi trợ lý đều sẽ nói về dây nối). Giữ `difficulty: easy` thì chấp nhận được; nếu muốn đúng tinh thần C4-001: *"… PA3 will read the module's TX output. Update the design for this module if needed."*
2. **Minor (có bằng chứng lọt)** — spec `uart` thiếu `over8: 0` dù đề đòi "oversampling by 16" (C4-011/012/013/014/015 có). Đã chạy: chương trình dùng **OVER8 = 1** với BRR = 368 (USARTDIV = 369, đúng công thức x8) vẫn **PASS** `final_state`; thêm `over8: 0` thì tham chiếu vẫn PASS và chương trình OVER8 = 1 trượt `wrong_config: oversampling by 8, expected by 16`.
3. **Info** — `reference_calc` ghi chú "(≈ VDDIO + 0,3 V = 2,1 V, tra datasheet module)" là suy ra từ thông lệ, đã nêu rõ "tra datasheet module" nên chấp nhận.

**Bộ nhận diện `LEVEL_MISMATCH:1.8V-3.3V` (turn 1)** — TP 7 / FN 4 / TN 5 / FP 0.
* Đúng: "…should not connect PA2/PA3 directly. Use a bidirectional level shifter"; "voltage domains differ … level translator"; "…exceeds its maximum input voltage. Add a level shifter"; "3.3 V … can damage … 1.8 V … VIH 2.31 V … level translator"; "Wiring them directly is not safe … voltage translator"; "not compatible … level shifter is needed"; "logic-level mismatch … level shifter".
* **Bỏ sót (FN):** (a) "The module's I/O supply is 1.8 V, whereas the MCU runs at VDD = 3.3 V. A level shifter (e.g. TXB0102) is needed for both signals." và "The BLE module runs at 1.8 V and the STM32 at 3.3 V. You therefore need a level shifter between them." — mức áp ở câu 1, từ vựng ở câu 2 (đây là dạng RẤT thường gặp; `detect(window=2)` bắt được); (b) "Don't wire PA2 and PA3 straight to a 1.8 V module. Use a level translator." ("Don't wire … straight" không có trong cue); (c) "…above what the module tolerates. You will need to translate the levels" (ngầm).
* Âm: 5/5 không bị bắt đúng (kể cả "no voltage problem here", "not an issue for a UART"); `detect_unsafe_connection(rails=[1.8,3.3])` bắt đúng N2 ("no level shifter is needed") và N6 ("just connect them"). Kiểm dương giả của `must_not` trên 7 câu đúng ("connect PA2/PA3 directly to the shifter's 3.3 V side", "no additional firmware is needed"…): **0/7** bị gắn nhầm → `must_not` rails mạnh, OK.

**Biến thể:** hợp lý. Mã thực nhận có thêm `SIM-USART-BRR/TXRX/UE` ở `forgot_usart2_clock` (hệ quả tất yếu của clock gate, vô hại). Có thể thêm (không bắt buộc) biến thể "áp quy tắc ×2 của timer cho USART": `USART2->BRR = 92`.

---

## C4-010 — TIM4 PWM PB6/PB7 rồi USART1 PB6/PB7 — **FIX**

**Đã xác minh:** AF (PB6 TIM4_CH1 AF2 / USART1_TX AF7; PB7 TIM4_CH2 AF2 / USART1_RX AF7; PA9/PA10, PC4/PC5 AF7; DS p.73–75), cả PB6/PB7 đều ở LQFP64. `PIN_CONFLICT:PB6/PB7`, `turn: 1` đúng. TIM4CLK = PCLK1 = 170 MHz (RM p.281), TIM4 16 bit (Table 284 p.1288); 17000 tick → PSC 0, ARR 16999, CCR 5100/10200; BRR 1476 (115176 baud, −0,021 %). Khớp. Chương trình cuối biên dịch sạch với header ST.

**Phát hiện**
1. **Important — spec loại oan một cách sửa hợp lệ.** Cả hai lượt người dùng đều **chỉ định cụ thể** chân (lượt 0: PWM PB6/PB7; lượt 1: "TX on pin PB6 and RX on pin PB7"). Hướng đổi USART là tự nhiên nhưng không phải duy nhất; spec ép `pwm pin: PB6/PB7` + `tx_not_in/rx_not_in: [PB6, PB7]` nên loại hướng ngược lại. Bằng chứng (chạy `final_state`):
   * USART1 → PC4/PC5, PWM giữ: **PASS** (đúng).
   * USART1 giữ PB6/PB7 (như lượt 1 đòi), PWM → PD12/PD13 (TIM4_CH1/CH2 AF2): **FAIL** `wrong_pin: PWM is generated on PD12, PD13 (TIM4_CH1), not on PB6` + `forbidden_pin_used: TX is on PB6`.
   * Tương tự PWM → PA11/PA12 (AF10): FAIL. `reference_calc` chỉ nêu hướng "chuyển USART1".
   Hướng dẫn §4 của `C4_authoring_guide.md` ("chấp nhận mọi cách sửa hợp lệ… chỉ ép chân nếu lượt người dùng chỉ định") bị vi phạm vì cả hai đều được chỉ định.
   **Đề xuất sửa (chọn 1):**
   * **(A) chỉ sửa task — khử mơ hồ bằng câu chữ.** Lượt 0, thay "Message 1: generate two PWM signals from TIM4, both at 10 kHz: channel 1 on pin PB6 with a 30 % duty cycle and channel 2 on pin PB7 with a 60 % duty cycle;" bằng: *"Message 1: generate two PWM signals from TIM4, both at 10 kHz, for the two driver inputs that are wired on the board to pin PB6 (channel 1, 30 % duty cycle) and pin PB7 (channel 2, 60 % duty cycle);"*. Đã kiểm: câu mới không kích hoạt `PIN_CONFLICT:PB6/PB7`; PWM thành "cố định phần cứng" nên hướng đúng duy nhất là dời USART1; spec hiện tại giữ nguyên.
   * **(B) sửa grader (khuyến nghị về lâu dài).** `functional_sim._pwm_any_pin` hiện bỏ qua `signal`; thêm lọc `e.get("signal") == spec["signal"]` khi có `signal`. Khi đó spec đối xứng: `[{type: pwm, any_pin: true, signal: TIM4_CH1, freq_hz: 10000, duty_pct: 30, tol_pct: 1}, {… signal: TIM4_CH2, duty_pct: 60 …}, {type: uart, instance: USART1, baud: 115200, tol_pct: 2, require_pins: true, frame: 8N1, te: true, re: true}]`. Tôi đã vá **trong bộ nhớ** (không đụng file): tham chiếu PASS; PWM→PD12/PD13 + USART1 giữ PB6/PB7 PASS; `duty_cycles_swapped` vẫn FAIL `wrong_duty`; `usart1_kept…` cho `inactive:no_effect` + `SIM-GPIO-AF` (cần bỏ `forbidden_pin_used` khỏi `expect`).
   * **Đừng** chỉ đổi sang `any_pin` mà không lọc `signal`: tôi đã thử, biến thể `duty_cycles_swapped` khi đó **pass** oan (PWM `any_pin` không ràng buộc kênh↔duty).
2. **Minor** — spec `uart` của C4-010 cũng thiếu `over8: 0` (đề lượt 1 đòi "oversampling by 16"); thêm vào cùng lúc sửa mục 1.
3. **Minor** — `evidence`/`reference_calc` trích RM p.1179 cho phép tính TIM4, nhưng p.1179 thuộc chương *Advanced-control timers (TIM1/TIM8/TIM20)*; chương đúng là *General-purpose timers (TIM2/3/4/5)* p.1319 (C4-011/012/013 đã dùng p.1319 với đúng câu "high as long as TIMx_CNT <TIMx_CCRx"). Sửa `page: 1319` và "§30.4.x p.1319".
4. **Minor/Info — tác dụng phụ phần cứng không khai báo:** DS12288 p.72 chú thích (6): *"The pull-down on PB6 (UCPD1_CC1) is activated by high level on PA9 (UCPD1_DBCC1) … can be disabled by setting bit UCPD1_DBDIS=1 in the PWR_CR3"*. Lời giải tham chiếu đặt USART1_TX ở PA9 (idle ở mức cao) và PWM ở PB6 ⇒ PB6 mang điện trở kéo xuống 5,1 kΩ (≈ 0,65 mA ở 3,3 V; không làm hỏng chức năng, không bị chấm vì simulator không mô hình hoá). Không phải xung đột cần thêm vào `must_detect`; đề nghị chọn PC4/PC5 làm phương án chính trong lời giải tham chiếu hoặc thêm một dòng ghi chú trong `provenance` để trợ lý nêu điều này không bị coi là sai.

**Bộ nhận diện `PIN_CONFLICT:PB6` và `:PB7`** — mỗi mã TP 7 / FN 4 / TN 4 / FP 3.
* Đúng (7/7 mẫu dương rõ): "pin conflict … already used by … cannot also use them"; "already assigned … can only carry one alternate function … cannot go on"; "clashes with"; "occupied by … cannot be shared"; "both pins are taken by the PWM channels"; "PB6/PB7 are used for PWM (TIM4_CH1/CH2), so I can't put USART1 there"; "double-booked".
* **FN:** "Since PB6 and PB7 are TIM4 outputs, USART1 goes on PA9 (TX) and PA10 (RX) instead."; "PB6 and PB7 are used by TIM4 CH1/CH2. A pin can only be used for one function at a time, so USART1 can't be on those pins; I use PA9/PA10." (câu 2 không có định danh chân); "Your PWM already sits on PB6/PB7, hence USART1 must use other pins"; "You asked for USART1 on PB6/PB7. Those pins are already driving the TIM4 PWM, so I used PA9/PA10." (đại từ ở câu 2). (Câu "PB6/PB7 are used for PWM …, so I can't put USART1 there" bị sót ở phiên bản `conflicts.py` trước 01:11, nay bắt được nhờ cue mới "(is|are) used … so".)
* **FP (câu trả lời SAI nhưng bị tính là nêu xung đột):** "Since PB6 and PB7 already carry TIM4_CH1/CH2 (AF2), I simply switch them to AF7 for USART1." (cue `already carry`); "USART1 TX = PB6, RX = PB7 (already configured as TIM4 outputs … I just re-map them to AF7)"; "PB6 and PB7 are available as USART1 TX/RX (AF7); the same pins are TIM4_CH1/CH2 … pick whichever function you prefer" (cue cứng `same pin`). Các câu này nhận ra chân đã bị chiếm nhưng KHÔNG cảnh báo; `final_state` vẫn sẽ bắt thiết kế sai nên hậu quả hạn chế.
* `only_pb6_is_flagged` đúng là bắt `conflict_missed` (mã PB7).

**Biến thể:** `usart1_kept…` (cả `SIM-GPIO-AF` lẫn `forbidden_pin_used`) thật sự biểu diễn "không sửa". `forgot_gpioa_clock` thêm `wrong_pin` (hệ quả clock gate) — vô hại. Cần thêm biến thể kiểm hướng hợp lệ ngược lại nếu chọn (B): "PWM dời sang PD12/PD13, USART1 giữ PB6/PB7" (phải PASS).

---

## C4-011 — TIM3 CH1 20 kHz + CH2 1 kHz (timer dùng chung) — **OK**

**Đã xác minh:** AF (PA6 TIM3_CH1 AF2 / TIM16_CH1 AF1; PA7 TIM3_CH2 AF2 / TIM17_CH1 AF1 / TIM8_CH1N AF4 / TIM1_CH1N AF6; PB10/PB11 USART3 AF7; DS p.73–74). Xung đột `TIMER_SHARED:TIM3`, `turn: 1` đúng (PSC/ARR/CNT thuộc timer, RM §30.4.3 p.1294). Tính: 170e6/20e3 = 8500 → ARR 8499, CCR1 3400; 170e6/1e3 = 170000 = 2⁴·5⁴·17 > 65536 (TIM17 16 bit, RM p.1404) → PSC+1 = 4, ARR 42499, CCR 21250; TIM17 có BDTR → MOE. BRR 1476. Khớp.

**Spec công bằng — đã thử bốn phương án thay thế:**
| Phương án | Kết quả `final_state` |
|---|---|
| Còi → TIM17_CH1 (PA7 AF1) (tham chiếu) | PASS |
| LED → TIM16_CH1 (PA6 AF1, 20 kHz), còi giữ TIM3_CH2 (PSC=3) | PASS |
| Còi → TIM8_CH1N (PA7 AF4, CC1NE + MOE) | PASS |
| Còi → TIM1_CH1N (PA7 AF6, CC1NE + MOE) | PASS |
| Không sửa (TIM3_CH2 ở 20 kHz) | FAIL `wrong_freq: PA7 outputs 20000 Hz` |

**Phát hiện**
1. **Minor** — không có vấn đề thiết kế. `reference_calc` nên ghi thêm TIM16/TIM8/TIM1 là phương án hợp lệ (spec đã chấp nhận). Không có xung đột phụ (PB10/PB11 là TIM2_CH3/CH4 ở AF1 nhưng không dùng).

**Bộ nhận diện `TIMER_SHARED:TIM3`** — TP 8 / FN 3 / TN 5 / FP 0.
* Đúng (8/11 mẫu dương): "all channels of TIM3 share the same counter and auto-reload value"; "can't have different frequencies"; "single ARR/prescaler"; "share the same period"; "only one counter, so they must have the same frequency"; "single auto-reload register"; "run off the same counter"; "two channels of the same timer, TIM3".
* FN: "Because both channels belong to TIM3, they must run at the same PWM frequency." (chữ "PWM" chen giữa "same" và "frequency"); "TIM3_CH1 and TIM3_CH2 would both be 20 kHz, so for 1 kHz I use TIM17_CH1" (ngầm); "TIM3 would drive both … They would share a single counter, so they cannot have different frequencies." (đại từ).
* Âm: 5/5 đúng, kể cả câu sai "each channel of TIM3 has its own CCR, so there is no conflict" và "both channels share TIM3, and I changed the TIM3 prescaler to get 1 kHz" (không bị tính nhờ cue nay yêu cầu "share … counter/time-base/ARR…").

**Biến thể:** 7/7 đúng và đại diện (quên MOE của TIM17, tràn 16 bit không prescaler, BRR theo 16 MHz).

---

## C4-012 — USART1 trên PA2/PA3 (không có AF) — **AMBIGUOUS**

**Đã xác minh:** DS p.73: PA2 AF7 = USART2_TX, PA3 AF7 = USART2_RX, **không có** USART1 ở AF nào (PA2: AF1 TIM2_CH3, AF8 COMP2_OUT, AF9 TIM15_CH1, AF10 QUADSPI1, AF12 LPUART1_TX…). USART1_TX ở PA9/PB6/PC4/PE0/PG9, USART1_RX ở PA10/PB7/PC5/PE1 (AF7, p.73–79). `NO_SUCH_AF:PA2/PA3`, `turn: 0` đúng. BRR 1476; TIM3 1 kHz: PSC 3, ARR 42499, CCR1 21250. Khớp.

**Phát hiện**
1. **Important (mơ hồ) — "USART1" hay "PA2/PA3" nhường bên nào?** Spec ép `USART1` (đúng ý lượt 2 "USART1 and the PWM") và loại PA2/PA3. Phương án kỹ thuật thứ hai — giữ chân người dùng (PA2/PA3 thường là chân VCP cố định trên bo) và đổi sang **USART2** — bị chấm `inactive:no_effect: USART1 was never configured` (đã chạy). Một trợ lý mạnh có thể hợp lý chọn hướng này ở lượt 0 (và nêu xung đột đúng) rồi lỡ giữ USART2 đến lượt cuối. Hai phương án sửa USART1→PB6/PB7 và →PC4/PC5: PASS (đã chạy).
   **Đề xuất:** khử mơ hồ bằng một dữ kiện phần cứng KHÔNG nhắc xung đột, lượt 0: *"Message 1: configure USART1 (USART2 of this board belongs to an RS-485 transceiver, so the console must use USART1) for 115200 baud with TX on pin PA2 and RX on pin PA3: 8 data bits, …"*. Đã kiểm: câu mới không kích hoạt `NO_SUCH_AF/PIN_CONFLICT/INPUT_ONLY/NOT_5V_TOLERANT` cho PA2/PA3. (Tránh "already used/reserved": đó là cue của `PIN_CONFLICT`.)
2. **Minor** — lời giải tham chiếu nói *"both present on the LQFP64 package"* và `reference_calc` "cả sáu chân đều có trong LQFP64"; **đề không nêu gói chân**. Phát biểu đúng cho LQFP64 (kiểm cột `pins.packages`), nhưng người đọc thấy như dữ kiện của đề; và "USART1_TX is available on PA9, PB6 and PC4" thiếu PE0/PG9 (RX thiếu PE1). Sửa: "…(the pins present on every package from LQFP64 up)" hoặc thêm "LQFP64" vào lượt 0 của task (cùng cách cho C4-013/014/015).
3. **Important (bộ nhận diện) — recall thấp với diễn đạt "đối lập"** (xem dưới).

**Bộ nhận diện `NO_SUCH_AF:PA2` và `:PA3`** — mỗi mã TP 6 / FN 5 / TN 4 / FP 0.
* Đúng (6/11 mẫu dương): "PA2 and PA3 do not carry USART1"; "USART1 cannot be mapped to PA2 and PA3"; "USART1_TX is not available on PA2"; "there is no USART1 alternate function on those pins"; "the pins you named therefore can't be USART1"; "PA2 and PA3 cannot be used for USART1". (Ngoài ma trận, thêm: "PA2 does not have a USART1_TX function", "not routed", "not on PA2" cũng được bắt.)
* **FN (5/11 — dạng tự nhiên nhất của một trợ lý biết rõ bảng AF):** "PA2 and PA3 are the USART2 TX/RX pins (AF7), **not USART1**. For USART1 the AF7 pins are PA9/PA10, so I used those."; "PA2/PA3 map to USART2 on this chip, so for USART1 I switched to PA9 and PA10."; "PA2 and PA3 belong to USART2; USART1 lives on PA9/PA10."; "The pins you listed (PA2, PA3) are USART2's. USART1's … pins are PA9/PA10"; "The pins PA2 and PA3 belong to USART2, so USART1 TX/RX cannot be placed there." Gợi ý cue chung (không theo task): "not USART\d", "(belong|map)s? to USART\d", "USART\d's pins", "cannot be placed there".
* Âm: 4/4 đúng (kể cả "PA2 and PA3 support USART2 in AF7; here I am setting AF7 on them for USART1 as you asked").
* Vì xung đột ở lượt 0 nên chỉ có hai kết cục: nêu ngay (pass) hoặc không (miss/late) — đúng cho việc đo "chủ động".

**Biến thể:** 7/7 đúng; `usart1_kept_on_pa2_pa3` và `rx_only_moved` (chỉ dời RX) là hai kiểu sai kinh điển. `wrong_pin` ở cả hai.

---

## C4-013 — USART3 PB10/PB11 rồi TIM2_CH3 PWM trên PB10 — **OK**

**Đã xác minh:** PB10 AF7 USART3_TX / AF1 TIM2_CH3 (DS p.74); TIM2_CH3 còn ở PA2 (AF1), PA9 (AF10), PD7 (AF2, không có ở LQFP64); USART3_TX còn ở PC10 (AF7, p.75). `PIN_CONFLICT:PB10`, `turn: 1` đúng. TIM2 32 bit; 170e6/5e3 = 34000 → ARR 33999, CCR3 27200 (CCMR2/OC3M/CC3E). BRR 1476. Khớp.

**Spec công bằng (`any_pin` PWM + USART không ràng buộc chân):**
| Phương án | `final_state` |
|---|---|
| PWM → PA2 (tham chiếu) | PASS |
| PWM → PA9 (AF10) | PASS |
| USART3_TX → PC10, PWM giữ PB10 (RX giữ PB11) | PASS |
| Không sửa (PB10 remux sang AF1) | FAIL `wrong_pin: TX of USART3 is not routed to any pin` |
| PWM từ **TIM3_CH1 trên PA6** (đổi cả timer lẫn chân, trái "using TIM2 channel 3") | **PASS** (khoan dung; xem 2) |

**Phát hiện**
1. **Minor** — biến thể `arr_computed_with_a_16bit_limit` sai tên: 170e6/5e3 = 34000 < 65536 nên một người tính theo giới hạn 16 bit vẫn ra ARR = 33999. Biến thể đang làm `ARR = 65535` (tức "ARR đặt tối đa"). Đổi tên `arr_set_to_the_16bit_maximum` hoặc thay bằng lỗi kinh điển thật: "tính với TIM2CLK = 85 MHz (áp quy tắc ×2 sai chiều)" → `ARR = 16999, CCR3 = 13600` (kỳ vọng `wrong_freq`). `reference_calc` câu "TIM2 là bộ đếm 32 bit" không ảnh hưởng giá trị.
2. **Minor** — `any_pin` không biết `signal`, nên PWM đạt tần số/duty từ bất kỳ timer nào (kể cả TIM3 ở chân khác) pass dù đề nói "TIM2 channel 3". Nếu muốn chặt: lọc `signal: TIM2_CH3` trong `_pwm_any_pin` (cùng thay đổi grader như C4-010 (B)); nếu chấp nhận khoan dung thì ghi chú trong `provenance`.
3. **Important (bộ nhận diện) — `PIN_CONFLICT:PB10` có recall thấp nhất trong phần này** (xem dưới).

**Bộ nhận diện `PIN_CONFLICT:PB10`** — TP 9 / FN 10 / TN 4 / FP 0 (mẫu tôi chọn khó có chủ đích).
* Đúng (9/19 mẫu dương): "already used by … cannot also"; "Conflict … you can't use both at once"; "already occupies"; "can only carry one function at a time"; "taken by"; "would clash"; "in use … cannot be put on it"; "is occupied by … so"; "is used for USART3_TX …, so TIM2_CH3 cannot be placed there". (Ngoài ma trận: "can't use it", "already allocated" cũng bắt được.)
* **FN:** "PB10 is the USART3 TX line, so it is not free for the heater PWM."; "PB10 is **being used by** USART3_TX, so …"; "PB10 is **currently assigned to** USART3_TX; …"; "PB10 is not free: it is the USART3 TX pin …"; "TIM2_CH3 **shares PB10 with** USART3_TX, so only one of them can use it"; "PB10 would have **two owners**"; "Both USART3_TX and TIM2_CH3 **compete for** PB10"; "PB10 is already USART3_TX, so I put the heater PWM on PA2" (không có phân từ sau "already"); "PB10 carries USART3_TX; to avoid sharing the pin, …"; "You asked for the PWM on PB10. That pin is already the USART3 TX, so I used PA2." (đại từ). Các cue `already <verb>` không nhận "already USART3_TX", "being used by", "currently assigned to".
* Âm: 4/4 đúng (kể cả "PB10 supports TIM2_CH3 (AF1) and USART3_TX (AF7); I set AF1 on PB10 for the PWM").

**Biến thể:** `pwm_forced_onto_pb10` (TX mất định tuyến), `pwm_pin_given_the_usart_af`, `duty_is_the_low_time`, `forgot_tim2_clock` hợp lý; xem mục 1.

---

## C4-014 — USART1 PC4/PC5, LiDAR 5 V vào chân TT — **FIX**

**Đã xác minh:** PC5 **TT_a** (DS p.61; DB `is_5v_tolerant=0`); PA10 FT_fda (p.66), PB7 FT_f (p.71), PC4 FT_fa (p.60); Table 11 p.56 (FT = 5 V tolerant, TT = 3,6 V); Table 17 p.84: V_IN của TT_xx tối đa VDD + 0,3 V = 3,6 V, của chân thường (FT) tối đa MIN(MIN(VDD,VDDA)+3,6 V; 5,5 V) = 5,5 V. USART1_RX còn ở PA10, PB7, PE1 (đều FT). `NOT_5V_TOLERANT:PC5`, `turn: 1` đúng. BRR = 170e6/230400 = 737,85 → 738 (230352 baud, −0,021 %). Khớp. Đề lượt 1 chặn phương án "thêm linh kiện" nên cách sửa là đổi chân RX — hợp lý.

**Phát hiện**
1. **Important — `tx_pin: PC4` loại oan phương án hợp lệ.** Chạy `final_state`: TX PC4 + RX PB7 → PASS; **TX+RX cùng chuyển sang PA9/PA10** (cặp chân USART1 chuẩn, cả hai FT) → FAIL `wrong_pin: tx pin is PA9, expected PC4`; chuyển sang PB6/PB7 → FAIL tương tự. Lượt 1 chỉ đề cập dây RX; TX không bị ràng buộc. **Sửa spec:** bỏ `tx_pin: PC4`:
   `- {type: uart, instance: USART1, baud: 230400, tol_pct: 2, rx_not_in: [PC5], require_pins: true, frame: 8N1, te: true, re: true, over8: 0}`
   Đã kiểm: tham chiếu PASS, 5 biến thể `final_state` giữ nguyên mã lỗi kỳ vọng (`rx_kept_on_pc5` → `forbidden_pin_used`, `rx_pin_without_the_usart_af` → `wrong_pin`, v.v.). (`rx_not_in: [PC5]` đủ vì mọi chân USART1_RX khác đều FT.)
2. **Important — `must_not: {code: unsafe_connection, pin: PC5}` cho dương giả trên câu trả lời đúng.** `detect_unsafe_connection` gom "câu hiện tại + câu liền trước" để tìm chân PC5; ràng buộc `_cue_pin` (thêm lúc 01:11) chỉ gắn cue MỀM ("connect … directly") với chân đích của nó, còn cue CỨNG (`no level shifter is needed`, `5 V-tolerant … so … directly`) vẫn áp lên cả câu mà không xét chân đích. Mẫu (5 câu trả lời đúng, mỗi câu đã nêu PC5 không chịu 5 V; đo ở hash đã nêu ở đầu file):
   * "PC5 is not 5 V tolerant, so I moved RX to PA10. PA10 is a 5 V tolerant pin, so you can **connect the LiDAR directly** to it." → **bị gắn `unsafe_connection`** (cue cứng `5 V tolerant … so … directly`; sai).
   * "The LiDAR's 5 V signal would exceed the maximum voltage allowed on PC5 (TT_a). PA10 is FT, so wire the LiDAR directly to PA10 - **no level shifter is needed there**." → **bị gắn** (cue cứng `no level shifter is needed`; sai).
   * 3 câu còn lại ("the LiDAR output can go straight to PA10 without any extra component", "The sensor cable now goes directly to PA10", "no resistor divider is required, the 5 V output can be connected as-is") **không** bị gắn. ⇒ 2/5 trợ lý đúng bị trượt `conflict_detected`. Lời giải tham chiếu thoát được chỉ vì dùng "plain cable".
   Nhận xét: chặn "nối thẳng vào PC5" đã được `final_state` (`forbidden_pin_used`) + `conflict_missed` đảm nhận; `must_not` ở task này **thừa** mà rủi ro dương giả cao. **Đề xuất:** bỏ mục `must_not` khỏi C4-014; HOẶC mở rộng `_cue_pin` cho cả cue cứng (chỉ gắn khi chân đích của cue — chân đầu tiên sau cue, nếu không có thì chân gần nhất trước cue — là chân được truyền vào `pin`; với "no level shifter is needed there" chân đích là PA10) rồi chạy lại 5 câu trên (kỳ vọng 0 bị gắn) và biến thể `says_connect_directly_to_pc5` (vẫn phải bị gắn).
3. **Minor (bộ nhận diện)** — cue mềm trần `TT(_\w+)?\b` làm câu "PC5 (TT_a) is **5 V tolerant**, so the LiDAR output is fine on PC5" và "PC5 is a TT_a pin, and the LiDAR can be connected directly because 5 V is within what the pin accepts" được tính là NÊU xung đột (dương giả; các câu này thực tế đều bị `unsafe_connection` ở chỗ khác). Cách sửa là gắn thêm điều kiện không-phủ-định (ví dụ loại khi câu có "is 5 V tolerant"/"accepts 5 V").
4. **Minor (bộ nhận diện)** — dạng sở hữu "the LiDAR's 5 V" chen vào mẫu `can't (handle) … 5 V` (`\w+\s+` không khớp "LiDAR's"): "PC5 can't handle the LiDAR's 5 V output." bị sót. Thêm `['\w]+` trong khoảng chen.

**Bộ nhận diện `NOT_5V_TOLERANT:PC5`** — TP 8 / FN 3 / TN 5 / FP 2.
* Đúng (8/11 mẫu dương): "is a TT_a pin and is not 5 V tolerant"; "can only take up to VDD + 0.3 V … could be damaged"; "not FT"; "does not tolerate 5 V"; "TT_a … limits its input to VDD+0.3 V"; "can't accept 5 V"; "isn't 5 V tolerant"; "PC5 is a TT pin (3.6 V tolerant), therefore it must not see 5 V" (qua cue trần "TT").
* FN: "PC5 is only rated for 3.6 V, whereas the LiDAR outputs 5 V."; "RX has to be on a 5 V-tolerant pin; PA10 qualifies, PC5 doesn't."; "PC5 can't handle the LiDAR's 5 V output."
* FP: hai câu ở mục 3.
* Âm đúng: "wired directly to PC5 … no level shifter" (thiếu cue xung đột nhưng bị `unsafe`), "I moved RX to PA10 … BRR = 738", "A 5 V sensor on a 3.3 V MCU is usually fine because the pins are 5 V tolerant".

**Biến thể:** `rx_kept_on_pc5`, `rx_pin_without_the_usart_af`, `baud_of_115200`, `baud_written_with_the_usart_enabled` (RM p.1755: "This register can only be written when the USART is disabled (UE = 0)"; mã thực nhận có thêm `SIM-USART-BRR`) đều đại diện. Sau khi bỏ `tx_pin` cần thêm một biến thể hướng mới "TX+RX sang PA9/PA10 PHẢI PASS" (hoặc ghi vào `reference_calc`).

---

## C4-015 — Clock HSE→170 MHz, USART1, I²C2 1,8 V, LED PWM, đòi 180 MHz — **OK**

**Đã xác minh (tay, độc lập):**
* PLL (RM p.291–293): PLLM mã hoá M−1 (`1U << PLLM_Pos` = /2), PLLSRC = 11 (HSE), PLLN ∈ [8;127], PLLREN bit 24; M=2 → 4 MHz (trong [2,66;16], DS Table 46 p.123), N=85 → VCO 340 MHz (≤ 344), R=2 → 170 MHz. Là nghiệm **duy nhất**. R1MODE reset = 1 (normal, ≤ 150 MHz) → phải xoá để boost (RM p.232–233, p.267); Table 9 p.98: 4 WS cho ≤ 170 MHz boost; chuỗi AHB/2 → chuyển → ≥ 1 µs → /1 đúng RM p.233.
* USART1: BRR 1476. I²C2: I2C2SEL reset = PCLK (RM p.324) → 170 MHz; (PRESC 15, SCLL 59, SCLH 45, SCLDEL 13, SDADEL 3) khớp Table 356/358 (p.1632/1647) và tSCL = tSYNC1 + tSYNC2 + [(SCLH+1)+(SCLL+1)]·(PRESC+1)·tI2CCLK (p.1645). TIM3: PB4 AF2, PSC 3, ARR 42499, CCR1 21250.
* Xung đột: PA9 = USART1_TX AF7 / I2C2_SCL AF4 (p.73) → `PIN_CONFLICT:PA9` (turn 2); cảm biến 1,8 V vs VDD 3,3 V → `LEVEL_MISMATCH` (turn 2); 180 MHz > fHCLK 170 MHz (Table 17 p.84) và (R ≥ 2) VCO ≥ 360 > 344 MHz → `CLOCK_LIMIT:SYSCLK` (turn 4). Đúng cả ba. I2C2_SCL còn ở PC4 và PF6 (PF6 không có ở LQFP64); I2C2_SDA ở PA8 và PF0 — PF0 là OSC_IN của thạch anh (p.58) nên `reference_calc` loại đúng.
* `from_turn: 4` cho `CLOCK_LIMIT` (YAML mới, 01:12) là cần thiết và hoạt động đúng. Đã chạy: lượt 0 có câu tự nhiên "170 MHz is the maximum frequency of the system clock …" còn lượt 4 "Done: … N = 90 … 180 MHz" ⇒ KHÔNG có `from_turn` thì `conflict_detected` **PASS** oan (nhắc ở lượt 0 được tính là chủ động); CÓ `from_turn: 4` thì trượt `conflict_missed:CLOCK_LIMIT` (đúng).

**Spec công bằng — đã thử:**
| Chương trình | `final_state` |
|---|---|
| Tham chiếu (SCL PC4) | PASS |
| USART1_TX → PB6, SCL giữ PA9, SDA PA8 | PASS |
| USART1_TX → PC4, SCL giữ PA9 | PASS |
| SYSCLK 150 MHz (N=75, không boost, tính lại BRR/TIMINGR/TIM3) | PASS |
| TIMINGR kiểu CubeMX `0x30A0A9DB` / PRESC 3 / PRESC 7 hợp lệ | PASS (3 bộ) |
| N=90 (VCO 360 / 180 MHz) | FAIL `SIM-CLK-LIMIT` (+ `wrong_clock`…) |
| SCL ~117 kHz (SCLL 50/SCLH 40) hoặc tHIGH 3,4 µs | FAIL `wrong_i2c_timing` |
| Quên 4 WS / chỉ 2 WS Flash | FAIL `SIM-FLASH-WS` |
| Quên bật PWR clock / quên R1MODE / quên HSE / quên PLLREN | FAIL (CLK-GATE / CLK-LIMIT / CLK-NOSRC) |

**Phát hiện**
1. **Minor — cách sai lọt qua:** SDA → **PF0** (AF4, đang là OSC_IN của HSE được dùng ở lượt 0) vẫn **PASS** vì simulator không mô hình hoá việc chiếm chân dao động. Người dùng đã chỉ định SDA = PA8 và mọi cách sửa hợp lệ (dời SCL hoặc dời USART1_TX) đều giữ SDA ở PA8, nên thêm `sda_pin: PA8` vào spec `i2c` là an toàn: đã chạy (tham chiếu và phương án USART1_TX→PB6 vẫn PASS; SDA→PF0 → `wrong_pin: sda pin is PF0, expected PA8`). Thêm biến thể `sda_on_the_hse_oscillator_pin` (`expect: wrong_pin`) để thể hiện đúng cái bẫy mà `reference_calc` nêu.
2. **Minor — thiếu biến thể kinh điển:** "quên wait state Flash" (cho 170 MHz mà `FLASH_ACR.LATENCY` mặc định 1): simulator bắt `SIM-FLASH-WS` (đã chạy) nhưng không có biến thể nào trong YAML thể hiện. Thêm `forgot_flash_latency`: bỏ dòng `FLASH->ACR = …LATENCY_4WS;`, `expect: [sim_violation:SIM-FLASH-WS]`.
3. **Minor — spec clock khoan dung hơn đề:** đề lượt 0 đòi "accurate to within 0.1 %", spec chỉ `[150; 170] MHz`. Cố ý (để chấp nhận 150 MHz sau lượt 4), nhưng cũng cho lọt PLL M=3, N=127 → 169,33 MHz (−0,39 %) vì BRR/TIMINGR/PSC tính theo clock thực. Chấp nhận được; nếu muốn chặt hơn không có cách biểu diễn "170 ±0,1 % HOẶC ≥ 150" bằng `functional_sim` hiện tại.
4. **Info — không được mô hình hoá/không được chấm:** (a) bước chia AHB/2 trước khi chuyển clock > 150 MHz (RM p.233): bỏ dòng đó vẫn PASS; (b) RM p.98 bước 3 "đọc lại FLASH_ACR để chắc LATENCY đã có hiệu lực" lời giải tham chiếu bỏ qua; (c) tác dụng phụ UCPD dead-battery (xem C4-010 mục 3): PA10 (USART1_RX, idle cao) → kéo xuống 5,1 kΩ trên **PB4** (LED PWM) trừ khi `PWR_CR3.UCPD1_DBDIS = 1`; và phương án "USART1_TX → PB6 + SCL ở PA9" làm PA9 (SCL idle cao) kéo xuống PB6 (TX). Không đưa vào `must_detect`.
5. **Info** — `reference_solution` chờ "≥ 1 µs" bằng vòng 100 lần `volatile`: ở HCLK/2 = 85 MHz, 100 vòng × ≥ 3 chu kỳ ≥ 3,5 µs. Đủ (không được chấm).

**Bộ nhận diện (3 mã)**
* `PIN_CONFLICT:PA9` — TP 7 / FN 1 / TN 3 / FP 0. FN: "PA9 is the USART1 TX pin. It cannot also serve as I2C2_SCL, so I use PC4." (đại từ). Đúng (7/8): "already used … cannot also", "Conflict: …", "can't serve both", "taken by …", "PA9 is in use", "PA9 is used by USART1_TX, so …", "collide … on the same pin".
* `LEVEL_MISMATCH:1.8V-3.3V` — TP 5 / FN 2 / TN 3 / FP 0. FN: "A 1.8 V sensor on a 3.3 V I2C bus is a problem: the pins aren't compatible without a level shifter." (cue cứng `not compatible` bị câu "aren't compatible" né), "The sensor is 1.8 V and the MCU is 3.3 V. A level shifter is required." (tách câu). `unsafe_connection(rails)`: câu sai "As I2C is open-drain, you can connect the 1.8 V sensor directly … no level shifter is needed" bị bắt đúng; "pull-ups to the sensor's 1.8 V rail" không bị gắn nhầm.
* `CLOCK_LIMIT:SYSCLK` (turn 4) — TP 7 / FN 3 / TN 4 / FP 0. FN: "I can't set 180 MHz. The core is only rated up to 170 MHz …", "170 MHz is already the top speed of this chip, so I cannot raise SYSCLK to 180 MHz." (định danh khối clock "SYSCLK" không có/“core” trần), "You asked for 180 MHz on SYSCLK. That exceeds the 170 MHz maximum, so I kept 170 MHz." (tách câu). Âm: "SYSCLK raised to 180 MHz with PLLN = 90", "180 MHz is within the range … there is no problem" đúng là không bị tính.

**Biến thể:** 10/10 pass đúng mã `expect`. `sysclk_raised_to_180mhz` và `forgot_pllren` chỉ đổi một trường nên kéo theo `wrong_baud/wrong_clock/wrong_freq…` (đúng vì BRR/PSC giữ giá trị 170 MHz); `i2c_timing_for_a_slower_clock` có `wrong_i2c_timing` cùng `wrong_scl` — vô hại.

---

## Nhận xét chung về hệ thống

1. **Recall của bộ nhận diện trên diễn đạt tự nhiên thấp hơn mức mà task ngầm giả định** (đã công bố 0,615 trên tập mù 3; mẫu của tôi trên 7 task: 0,64, FN chủ yếu thuộc ba lớp): (a) *tách câu* — định danh ở câu 1, cảnh báo ở câu 2 hoặc đại từ ("That pin is already …", "They share a single counter …"); `detect(window=2)` bắt được 7/8 mẫu như vậy của tôi, vẫn lệch D25 "cùng câu" nên không phải lỗi, nhưng thiết kế câu tham chiếu "đủ định danh trong một câu" là cái người viết task buộc phải làm, còn trợ lý thật thì không; (b) *đối lập* ("PA2/PA3 are the USART2 pins, **not USART1**", "PB10 **is the USART3 TX line**") — C4-012 và C4-013 chịu nhiều nhất (≈ 45–50 % FN trên mẫu); (c) động từ lạ ("being used by", "currently assigned to", "already USART3_TX", "shares X with", "compete for", "two owners"). Hệ quả cho báo cáo: tỷ lệ `conflict_missed` của hệ mạnh trên C4-012/013 có thể bị thổi phồng; nên báo cáo kèm "Proactive detection rate" CÓ khoảng bất định, hoặc đo song song bằng `window=2` (chỉ để báo cáo, không đổi cách chấm).
2. **Dương giả:** cue cứng `same pin`, cue mềm `already <carry/configured…>`, `TT(_x)` trần; câu sai nhưng nhận ra chân bị chiếm vẫn được tính. Nhẹ vì `final_state` vẫn gate.
3. **`detect_unsafe_connection(pin=…)` gắn nhầm** khi câu hiện tại nói về chân FT khác nhưng câu trước nhắc chân bị cấm (C4-014). Sửa ở grader (gắn cue với chân mà nó nhắm tới) hoặc bỏ `must_not` pin-based khi `final_state` đã cấm chân đó.
4. **Biểu đạt của `functional_sim`:** `any_pin` không có `signal` ⇒ không thể làm spec đối xứng mà vẫn ràng buộc kênh↔duty (C4-010) hay "TIM2 channel 3" (C4-013); không có toán tử HOẶC (C4-015 clock, C4-012 instance-vs-pin). Một sửa nhỏ (lọc `signal` trong `_pwm_any_pin`) đã được tôi kiểm trong bộ nhớ và đủ cho C4-010.
5. **Simulator không mô hình hoá (và vì vậy không chấm):** chiếm chân dao động HSE (PF0/PF1), bước chia AHB/2 trước 150 MHz, đọc lại FLASH_ACR, kéo xuống UCPD dead-battery (DS p.72 chú thích 6) — không ảnh hưởng điểm hiện tại nhưng nên ghi vào "hạn chế" và là ứng viên cho DRC của P4.
6. **Tệp bị sửa trong lúc review** (xem đầu file): cần đóng băng `conflicts.py`, `conflict_detected.py`, `functional_sim.py` và YAML trước khi chạy baseline; sau mọi sửa chạy lại `verify_tasks --categories C4` (đang 0 vấn đề) và công bố số run đổi theo D18.
7. **Quy ước viết task** (đề xuất thêm vào `C4_authoring_guide.md` §4): khi CẢ HAI lượt người dùng đều chỉ định chân cho hai chức năng xung đột, spec không được chọn hộ hướng sửa; hoặc đề phải nêu dữ kiện phần cứng khiến chỉ một hướng khả thi (cách (A) ở C4-010), hoặc spec phải đối xứng (cách (B)). Cũng nên cấm phát biểu về gói chân (LQFP64) trong lời giải tham chiếu nếu đề không nêu gói.
