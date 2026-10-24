# C5 — ghi chú tác giả (P5, subagent `c5-author`)

Bản nháp 12 task mục tiêu cấp hệ thống (`plan/drafts/C5_curated_draft.yaml`). Nguồn sự thật là các file Python bên cạnh; YAML được SINH ra:

| File | Vai trò |
|---|---|
| `c5_common.py` | quy ước đề D20, thư viện regex checklist dùng chung, mẫu code clock, bảng bằng chứng dùng chung |
| `c5_tasks_a.py` / `c5_tasks_b.py` | C5-001…006 (thiếu thông tin) / C5-007…012 (đủ thông tin): đề, policy, hidden_info, checklist, spec, lời giải tham chiếu, biến thể sai (dạng sửa find→replace) |
| `build_c5_draft.py` | sinh YAML (áp sửa để tạo `wrong_variants[].answer` nguyên văn), kiểm round-trip YAML |
| `check_c5_draft.py` | tự kiểm thuần `re` (không import repo): checklist trên lời giải và biến thể, bằng chứng nguyên văn, rò rỉ giá trị ẩn, từ khoá câu hỏi, 61 câu thăm dò diễn đạt |
| `c5_handcalc.py` | phép tính tay: liệt kê MỌI cấu hình PLL hợp lệ, BRR, ARR/CCR, mức logic, tổng dòng ngủ, tuổi thọ pin |

Chạy lại: `eval/.venv/bin/python plan/drafts/build_c5_draft.py && eval/.venv/bin/python plan/drafts/check_c5_draft.py` (cần PyYAML; `c5_handcalc.py` chạy bằng python3 bất kỳ).

## Bảng 12 task

| id | split | loại | chip | code | hidden_info (giá trị) | graders | độ khó |
|---|---|---|---|---|---|---|---|
| C5-001 | test | thiếu ×2 | stm32g474, esp32 | có | `hse_hz` (24 MHz), `pwm_hz` (16 kHz) | checklist, clarify, functional_sim, compile | hard |
| C5-002 | **dev** | thiếu ×2 | stm32g474, esp32 | có | `hse_hz` (12 MHz), `esp_baud` (921600) | checklist, clarify, functional_sim, compile | hard |
| C5-003 | test | thiếu ×1 | stm32g474, nrf52840 | không | `battery_mah` (400 mAh) | checklist, clarify | medium |
| C5-004 | test | thiếu ×1 | stm32g474, nrf52840 | có | `nrf_supply` (VDDH từ Li-ion, REGOUT0 chưa ghi ⇒ I/O 1,8 V) | checklist, clarify, functional_sim, compile | hard |
| C5-005 | **dev** | thiếu ×1 | stm32g474 | không | `sensor_io_v` (1,8 V) | checklist, clarify | medium |
| C5-006 | test | thiếu ×2 | stm32g474, esp32 | không | `hse_hz` (25 MHz), `sleep_budget` (5 µA) | checklist, clarify | medium |
| C5-007 | test | đủ | stm32g474, esp32 | có | — | checklist, functional_sim, compile | hard |
| C5-008 | **dev** | đủ | stm32g474, nrf52840 | có | — | checklist, functional_sim, compile | hard |
| C5-009 | test | đủ | stm32g474, nrf52840 | không | — | checklist | medium |
| C5-010 | test | đủ | stm32g474, nrf52840 | có | — | checklist, functional_sim, compile | hard |
| C5-011 | **dev** | đủ | stm32g474, esp32 | không | — | checklist | medium |
| C5-012 | test | đủ | stm32g474, nrf52840 | không | — | checklist | medium |

Cân bằng split (gán cố định theo brief, trước khi chạy hệ nào): dev = 2 thiếu + 2 đủ, 2 có code + 2 không, 2 hard + 2 medium; test = 4 + 4, 4 + 4, 4 + 4.
Số mục ẩn trung bình: dev 1,5 (002: 2, 005: 1), test 1,5 (001: 2, 003: 1, 004: 1, 006: 2). Mỗi task thiếu thông tin có một task "đủ" đối chứng gần
như cùng cấu trúc (001↔007, 002/005↔008, 003↔009, 004↔010/012, 006↔011) để hệ không đoán được "có thiếu hay không" từ hình thức đề.
Giá trị HSE thay đổi: 24, 12, 25 MHz (ẩn ở 001, 002, 006); 12, 16, 8, 16, 25, 12, 8 MHz (cho sẵn ở 004, 005, 007, 008, 010, 011, 012). Ở 004/005 HSE được CHO SẴN
dù task thiếu thông tin khác — chống phản xạ "lúc nào cũng hỏi HSE" (hỏi HSE ở đó là câu hỏi thừa).

## Quy ước checklist (áp cho mọi task)
* `steps` (bullets_min 5), `pll` (dung sai 0,1 %), `flash_ws` (4 WS), `boost_mode` (khi SYSCLK > 150 MHz), `low_power_mode` (Standby/Shutdown vì Stop 1 = 80,5 µA typ).
* `sleep_total` (quantity, match any, đơn vị µA): lấy KẾT QUẢ trên dòng có "total/sum/overall/…", bỏ qua số hạng của tổng (`10 µA (ESP32) + …`, `8 mA x 2 s`)
  nhờ lookahead `_SKIP`; dạng "11.7 µA in total" cũng được nhận; không bắt qua dòng.
* `level_shifter` (mentions) không tính câu phủ định ("no level shifter is needed", "does not need a level shifter", "level shifter isn't required").
  `no_direct*` (forbids) bắt các khẳng định nguy hiểm ("no level shifter is needed", "directly compatible", "can be wired directly"); ở task có MỘT link
  lệch áp và MỘT link tương thích (008, 011) thì forbids chỉ xét câu có tên thiết bị lệch áp (`no_direct_near`).
* `compat` cho link 3,3 V ↔ 3,3 V: phải nói tương thích/nối thẳng (không gate việc thêm level shifter là "sai nguy hiểm").
* Câu trả lời tham chiếu là câu trả lời SAU khi người dùng đã trả lời câu hỏi (nêu lại giá trị ẩn).

## Từng task

**C5-001 (test, thiếu HSE + tần số PWM, có code).** Node điều khiển động cơ kiểu D4: TIM1_CH1/PA8 → driver, USART1 PA9/PA10 115200 → ESP32, SYSCLK 170 MHz
từ PLL/HSE, ngân sách ngủ < 50 µA. Ẩn: thạch anh HSE của bo (24 MHz) và tần số PWM mà module driver cần (16 kHz) — cả hai là sự kiện về bo/module không
tên của người dùng, không tool nào tra được. Đoán 8 MHz ⇒ M = 2, N = 85 ⇒ với 24 MHz thật SYSCLK = 510 MHz (trượt `pll` và spec clock); đoán 25 MHz ⇒
163,2 MHz (−4 %); đoán 20 kHz ⇒ trượt `pwm_freq` và spec pwm. Phép tính: 24/6 = 4 MHz × 85 = 340 MHz / 2 = 170 MHz (cấu hình duy nhất); ARR 10624,
CCR1 4250; BRR 1476; Stop 1 80,5 µA > 50 ⇒ Standby + RTC LSE 0,655 µA + ESP32 Deep-sleep 10 µA + driver 1 µA = 11,7 µA.

**C5-002 (dev, thiếu HSE + baud, có code).** Node thu dữ liệu: cảm biến I2C1 100 kHz (3,3 V), USART2 → ESP32 chạy firmware bridge của đồng nghiệp, LDO 250 mA.
Ẩn: HSE 12 MHz, baud 921600 (firmware của người khác — không tra được). Đoán 8/16/24 MHz đều trượt `pll` (255 / 127,5 MHz / PLL-in 2 MHz); đoán 115200 ⇒ trượt
`baud` và spec uart. Phép tính: 12/3 × 85 / 2 = 170 MHz (duy nhất); BRR = 184 ⇒ 923913 baud (+0,25 %); I2C TIMINGR như C4-001; dòng đỉnh 240 + 29,5 + 1 = 270,5 mA
> 250 mA và ESP32 DS Table 5-2 đòi nguồn ≥ 0,5 A ⇒ LDO không đủ (mục `supply_rating`, `peak_current`).

**C5-003 (test, thiếu dung lượng pin, không code).** Logger độ ẩm đất STM32 + nRF52840 (3,0 V), chu kỳ 15 phút, 2 s × 8 mA, mục tiêu 3 năm. Ẩn: dung lượng "pin vừa
vỏ hộp" (400 mAh, dùng hết). Không tra được (không nêu loại pin). Phép tính: ngủ 0,655 + 0,40 + 1 = 2,06 µA; trung bình 19,8 µA; 400 mAh ⇒ 20170 h = 2,3 năm < 3
năm ⇒ phải đưa ≥ 2 phương án (pin ≥ 521 mAh, chu kỳ ≥ 1215 s, pha hoạt động ≤ 1,48 s). Đoán 2000 mAh ⇒ 11,5 năm "đạt" ⇒ trượt `lifetime`, `trade_offs`,
`no_false_claim`; đoán 225 mAh ⇒ 1,3 năm (ngoài [2,0; 2,6]).

**C5-004 (test, thiếu cách cấp nguồn nRF52840, có code).** STM32 (HSE 12 MHz cho sẵn → 170 MHz, M3/N85/R2) ↔ nRF52840 aQFN73 qua USART3 1 Mbaud. Ẩn: nRF cấp từ Li-ion vào VDDH, REGOUT0
chưa ghi. Đây là sự kiện của bo; hệ phải TRA tiếp PS để suy ra I/O = 1,8 V (REGOUT0 mặc định, PS p.63/p.82). Đoán "nRF 3,3 V" ⇒ kết luận nối thẳng ⇒ trượt `regout0`,
`level_shifter`, `no_direct`. Phép tính: 3,3 V > VDD + 0,3 = 2,1 V (PS p.972); 1,8 V < VIH 2,31 V (DS p.128); REGOUT0 = 3,3 V cần VDDH ≥ 3,6 V (PS p.155) — Li-ion
xuống 3,0 V ⇒ translator. BRR = 170.

**C5-005 (dev, thiếu mức I/O của breakout, không code).** Node rung: breakout gia tốc kế mua ngoài (không sơ đồ) trên I2C1 400 kHz + ngắt đánh thức; HSE 16 MHz (cho sẵn) → 150 MHz
(normal mode, 4 WS). Ẩn: breakout chạy I/O 1,8 V. Đoán 3,3 V ⇒ nối thẳng ⇒ trượt `level_shifter`, `no_direct`. Phép tính: 1,8 V < 0,7 × 3,3 = 2,31 V (và < 1,88 V
giá trị thiết kế) ⇒ level shifter hoặc cấp MCU 1,8 V (VDD ≥ 1,71 V, DS p.84); 16/4 × 75 / 2 = 150 MHz (duy nhất). Policy `choice: level shifter` (demo `choice`).

**C5-006 (test, thiếu HSE + ngân sách ngủ, không code).** Bộ điều khiển van tưới: HSE (25 MHz ẩn) → 150 MHz normal mode, ESP32 báo mỗi giờ, ngân sách ngủ (5 µA ẩn,
do người thiết kế hệ thống đặt). Đoán ngân sách 50 µA ⇒ giữ ESP32 Deep-sleep ⇒ tổng 12,3 µA ⇒ trượt `esp32_off`, `sleep_total`; Hibernation ⇒ 7,3 µA vẫn > 5.
Phép tính: Standby + RTC LSE 0,655 + ESP32 power-off (CHIP_PU thấp) 1 + cảm biến 0,6 + buck 1 = 3,26 µA. HSE 25 MHz có 8 cấu hình hợp lệ (M = 2…9); đoán
8/16/12/24 MHz ⇒ 468,8 / 234,4 / 312,5 / 156,25 MHz ⇒ trượt `pll`.

**C5-007 (test, đủ, có code).** Đối chứng của 001 với mọi số cho sẵn (HSE 8 MHz, 20 kHz/25 %, driver 2 µA, RTC trên LSI vì không có LSE). Thêm bẫy: Shutdown
tắt LSI (DS p.25) ⇒ phải Standby (0,885 µA) ⇒ tổng 12,9 µA. Biến thể: Stop 1 (93,5 µA), PLLM = 4 (PLL-in 2 MHz < 2,66).

**C5-008 (dev, đủ, có code).** HSE 16 MHz → 170 MHz, cảm biến độ ẩm 1,8 V trên I2C3 (PC8/PC9) ⇒ level shifter; nRF52840 QFN48 (VDD/VDDH nối tắt, PS p.970) ở 3,3 V ⇒
nối thẳng; USART2 1 Mbaud (BRR 170); ngủ 2,06 µA ≤ 10 µA. Biến thể: nối thẳng cảm biến, Stop 1, PLLM = 2 (VCO 680 MHz).

**C5-009 (test, đủ, không code).** Đối chứng của 003: 2600 mAh cho sẵn, chu kỳ 10 phút, 1,5 s × 10 mA, LDO 2 µA, mục tiêu 12 năm ⇒ 28,05 µA ⇒ 10,6 năm < 12 ⇒ phương án
(≥ 2948 mAh, chu kỳ ≥ 692 s, pha hoạt động ≤ 1,3 s). Biến thể: không đưa phương án; Stop 1 (111,7 µA, 2,7 năm).

**C5-010 (test, đủ, có code).** HSE 25 MHz → 150 MHz normal mode (không cần R1MODE/AHB-2), buzzer 4 kHz/50 % TIM3_CH1 PA6 (ARR 37499), USART3 460800 (BRR 326, −0,15 %);
nRF52840 VDDH = 4,0 V với REGOUT0 = 3,3 V do script sản xuất ghi ⇒ headroom 0,7 V ≥ 0,3 V ⇒ I/O 3,3 V ⇒ nối thẳng. Biến thể: PLL cho 8 MHz; bỏ qua REGOUT0 đã ghi.

**C5-011 (dev, đủ, không code).** HSE 12 MHz → 160 MHz (boost, 4 WS; M3/N80/R2 duy nhất), cảm biến khí 1,8 V ⇒ level shifter, ESP32 3,3 V ⇒ nối thẳng, ngân sách 8 µA ⇒ ESP32
phải tắt hẳn (Deep-sleep 13,2 µA, Hibernation 8,2 µA đều vượt) ⇒ 4,16 µA. Biến thể: ESP32 Deep-sleep; cảm biến nối thẳng.

**C5-012 (test, đủ, không code).** Đối chứng của 004 với mọi thông tin cho sẵn (VDDH Li-ion, REGOUT0 xoá ⇒ 1,8 V): 5 tín hiệu USART1+RTS/CTS+wake qua translator; STM32
nghỉ Standby + SRAM2 (RRS) không RTC = 0,13 + 0,305 = 0,44 µA ≤ 2 µA, đánh thức bằng WKUP1/PA0. Biến thể: giả định nRF 3,3 V; Stop 1.

## Kiểm đã chạy (2026-10-23)
* `check_c5_draft.py`: 12 task, 94 mục checklist trên lời giải tham chiếu đều PASS; 27 biến thể sai trượt ĐÚNG tập `must_fail` (với `pll` kiểm cả ngữ nghĩa
  "mọi bộ M/N/R" lẫn "một bộ"); 339 snippet bằng chứng có nguyên văn trên trang (bỏ khoảng trắng, không phân biệt hoa/thường); 61 câu thăm dò diễn đạt
  đúng kỳ vọng; đề không chứa giá trị ẩn; câu hỏi mẫu khớp đúng mục hidden_info, câu hỏi không liên quan không khớp.
* DEBUG (C4 guide §7, KHÔNG làm nguồn giá trị): grader `functional_sim` + `compile` đóng băng trên 6 task có code: cả 6 lời giải PASS; biến thể đoán HSE/PWM/baud trượt
  `functional_sim` (SIM-CLK-LIMIT / wrong_freq / wrong_baud) — khớp với checklist.
* Chạy schema `eval.schema.Task` + grader `eval/graders/checklist.py` THẬT của c5-eval (chỉ đọc, sau khi c5-eval bổ sung đơn vị h/day/month/year): 12 task nạp
  hợp lệ, 12 lời giải PASS, 27 biến thể trượt ĐÚNG `must_fail` — 0 sai khác với bản cài lại của tôi.
* `eval/sim_human.SimulatedHuman` (c5-eval): câu hỏi mẫu hợp lý khớp đúng mục ẩn, câu hỏi không liên quan nhận "Không biết…"; `derive_oracle` sinh đúng
  `C5-00x-O` (lượt đầu + "Additional information from the user: …").

## Điểm mở / nghi ngờ cho reviewer độc lập
1. **Đã giải quyết với c5-eval:** (a) grader `pll` ban đầu chỉ nhận nguồn HSE ⇒ tôi chuyển C5-004/005/011 từ HSI16 sang bo có thạch anh HSE (12/16/12 MHz,
   tính tay lại, mỗi cái một cấu hình duy nhất); c5-eval sau đó cũng thêm khoá tuỳ chọn `pll.source` (bản nháp KHÔNG dùng). (b) Mục `lifetime` (003, 009) dùng
   `unit_out: year` — c5-eval đã thêm h/day/month/year vào `QTY_UNITS` (năm = 365,25 ngày).
2. **Phụ thuộc phiên bản grader:** bản nháp hợp lệ với `eval/schema.py` + `eval/textnorm.py` HIỆN TẠI (có đơn vị thời gian); nếu c5-eval hoàn tác thay đổi đó,
   hai mục `lifetime` sẽ bị schema từ chối.
3. **Trả lời rào đón ("nếu nRF chạy 3,3 V thì không cần level shifter"):** ở 004/005/012 câu đó chạm `no_direct` (forbids) ⇒ trượt. Tôi cho là đúng ý đồ (đoán/rào đón
   thay vì hỏi), nhưng reviewer nên xét có quá nghiêm không.
4. **Dòng ngủ nRF52840 trong System OFF đánh thức bằng GPIO:** PS chỉ liệt kê "wake on reset" 0,40 µA (và LPCOMP 0,86 µA); tôi dùng 0,40 µA và để khoảng
   `sleep_total` rộng ([1,8; 3,2] µA ở 003, [2,8; 4,2] µA ở 009, [1,5; 10] µA ở 008) để hệ chọn dòng khác vẫn đạt.
5. **Bảng dòng STM32 theo VDD:** DS chỉ có hàng 1,8/2,4/3,0/3,6 V; task 3,3 V dùng hàng 3 V. Khoảng `sleep_total` chấp nhận cả hàng 3,6 V và giá trị max 25 °C.
6. **Hidden keyword rộng:** `nrf_supply`/`sensor_io_v` có "powered", "supply voltage"; `pwm_hz` có "kHz", "motor driver". Câu hỏi không liên quan vẫn có thể bị tính
   là "cần thiết" (ảnh hưởng Precision, không gate).
7. D05: chỉ đọc C3 dev (001, 012, 020) và C4 dev (001) làm mẫu văn phong; không mở task `split: test` nào của C1–C4/C6–C8.

## Sau review độc lập (`plan/reviews/review_C5.md`, 2026-10-23)
Áp dụng mọi sửa phía task (nguồn: `c5_common.py`, `c5_tasks_a.py`, `c5_tasks_b.py`; sinh lại YAML; KHÔNG đổi split):
* **B1:** `clarify` có trong `graders` của MỌI task (007–012 thêm vào) ⇒ nửa đủ thông tin được `hitl.clarify_aggregate` đếm (đã kiểm: 2 run, 1 câu hỏi thừa ⇒ 0,5/run).
* **G1/G6 (cận `sleep_total`, max rõ dưới ngân sách):** 001 [11; 20], 006 [2,0; 4,5], 007 [12; 20], 008 [1,5; 6], 011 [3,0; 7,0], 012 [0,3; 1,5] (+ mẫu "idle current").
  Mẫu thêm: số có phân cách hàng nghìn, "microamps", giá trị ở dòng kế tiếp, "Sleep current: … = X µA".
* **G1b:** 003/007/009 dùng `low_power_mode` chỉ-Standby + forbids `not_shutdown` (BOR không có / LSI tắt trong Shutdown, RM0440 p.234, p.251); 012 thêm `not_shutdown`.
* **G2–G5:** `COMPAT_RX`, `NO_SHIFTER_CLAIM_RX`, `LEVEL_SHIFTER_RX`, `no_direct_near` thay bằng bản có chặn phủ định của reviewer; thêm mẫu hẹp "levels are compatible".
* **G7:** `trade_offs`/`no_false_claim` (003, 009) dùng hàm chung với nhóm diễn đạt của reviewer và mẫu giới hạn chủ ngữ.
* **G9–G11:** `pwm_freq` (16,000 / 16 000 / 16-kHz), `peak_current` [251; 700] mA + "at peak", forbids `no_ldo_ok_claim` (002, thêm vào must_fail của `ldo_judged_adequate`),
  `esp32_off` bỏ `\bEN\s+pin` + chặn phủ định, `headroom` (010) neo vào VDDH/4,0 V, forbids `no_boost_claim` (011, 012). Không sửa: `flash_ws` nhận "4 or 5 wait states" (G10, tác động thấp).
* **G12 (từ khoá SimulatedHuman):** `hse_hz` bỏ "crystal" trần (thêm XTAL, external/main oscillator, clock source, các cụm "crystal …" có định tính); `pwm_hz` bỏ
  "kHz", "motor driver", "driver module"; `esp_baud`, `battery_mah`, `nrf_supply`, `sensor_io_v`, `sleep_budget` theo bảng review (không dùng "how fast"/"speed does"
  trần vì sẽ khớp cả câu hỏi HSE ở 002). Mọi câu hỏi mẫu/khớp nhầm của review được kiểm bằng `SimulatedHuman.match` thật.
* **G13 (mặc định an toàn):** 004/005 ghi `provenance.limitations` + tag `safe_default`; giảm nhẹ bằng mục `nrf_io_1v8` / `sensor_1v8` (phải nêu mức 1,8 V).
  003 (rào nhiều dung lượng qua `match: any`) và 006 (ngân sách có thể "đoán" bằng cách tối thiểu dòng) giữ nguyên, ghi ở đây.
* **Đề:** 004 và 012 "what has to be fitted" ⇒ "whether anything has to be fitted" (bỏ tiền giả định).
* **C5-010:** code + lời giải đi qua trạng thái AHB/2 ≥ 1 µs khi chuyển sang PLL (HCLK > 80 MHz, RM0440 p.279–280; mô phỏng hết cảnh báo); thêm ghi chú dung sai
  REG0 −10/+5 % (PS p.155). `clock_code_normal` dùng chung đã sửa.
* **Không thuộc phía task (để c5-eval):** G8 (định dạng PLL dạng "M/N/R = a/b/c", bảng), G14 (`detect_question`), G15 (câu UNKNOWN tiếng Việt), G16, khoá `exclude`.
* Hồi quy: `check_c5_draft.py` thêm 40 chuỗi đối kháng của review (mục) + 7 câu trả lời đầy đủ; cũng chạy qua harness `h.py`/`test_fixes.py` của reviewer trên YAML đã cài.
