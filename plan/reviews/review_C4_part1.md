# Review C4 phần 1 — C4-001 … C4-008 (reviewer độc lập)

Reviewer: agent ngữ cảnh mới, không phải tác giả. Chỉ ghi file này; không sửa dự án, không đọc `agent/.env`, không gọi LLM/mạng.
Trạng thái đã review (đo lúc 2026-10-23 01:21): `eval/tasks/C4/c4_curated.yaml` sha256 `b4866a49208d…` (mtime 01:12, đã có `from_turn` ở C4-005/006), `eval/graders/conflicts.py` sha256 `374297a6affb…` (mtime 01:11).
Hai file này đang được người khác sửa song song; mọi con số bộ nhận diện dưới đây gắn với hash trên. Mã thử nghiệm: `/private/tmp/claude-501/-Users-loc4atnt-Master-Course-Ky3-AgenticAI-project/ad321631-49fc-4c9f-8c62-71d1a95a9c16/scratchpad/review_c4_r1/` (`battery.py`, `battery2.py`, `battery3.py`, `final_battery.py`, `probe_*.py`, `proposed_specs.py`, `patch_*.py`).

Cách làm: (1) đọc text trang PDF bằng `GradeContext.page_text` cho mọi chân/giới hạn/bit/công thức; (2) tự tính lại PSC/ARR/CCR, BRR, TIMINGR (PRESC/SCLL/SCLH/SCLDEL/SDADEL), PLL M/N/R/VCO, wait state bằng Python thuần từ công thức RM (không qua simulator); (3) biên dịch khối code lượt cuối của 8 lời giải với **header ST chính thức** (`corpus/headers/cmsis-device-g4_v1.2.6`, stub `core_cm4.h` của `check_header_parity`, `clang --target=thumbv7em-none-eabi -fsyntax-only -Wall -DSTM32G474xx`): 8/8 rc = 0, không cảnh báo; (4) chạy `verify_tasks --categories C4` (15 task, 0 vấn đề), kiểm toàn bộ `evidence.contains` có nguyên văn trên trang (không thiếu snippet nào), chạy từng biến thể sai và liệt kê mọi mã lỗi thực nhận; (5) ~25 lời giải thay thế/biến thể mới qua `final_state` (tìm âm giả/dương giả của spec); (6) 146 câu trả lời dương và 47 câu âm tự viết (3 bộ) qua `conflicts.detect` / `detect_unsafe_connection`, cộng 1 run pilot thật `eval/results/pilot_c4` (C4-001, S0/S1/S2/S2D) để đối chiếu.

## Tóm tắt

| Task | Kết luận | Vấn đề chính |
|---|---|---|
| C4-001 | **FIX** | spec I2C ép `kernel_clk_hz: 170 MHz` mà đề không ràng buộc nguồn clock I2C3 (loại oan I2C3SEL = HSI16); spec thiếu `require_pins` ⇒ chương trình không nối chân SDA vẫn PASS; mọi mục `must_detect` nên có `from_turn: 1` |
| C4-002 | OK (sửa nhỏ) | giá trị đúng; `from_turn: 2` cho `PIN_CONFLICT:PB7` (câu "PB7 is already used by I2C1_SDA" ở lượt 1 được tính là phát hiện); lời giải chọn PB8 = chân BOOT0 |
| C4-003 | **FIX** (nhỏ) | `must_not: unsafe_connection {pin: PA3}` chấm trượt câu trả lời ĐÚNG ("PA15 is 5 V tolerant, so no level shifter is needed": 4/5 diễn đạt tự nhiên bị đánh dấu); `from_turn: 1` (cue mềm `TT_a` đã đủ để tính phát hiện ở lượt 0) |
| C4-004 | OK | không lỗi dữ kiện/spec; `from_turn: 1` (lượt 0 nói "ARR is shared by all TIM2 channels" bị tính là phát hiện sớm) |
| C4-005 | **FIX** | spec `sysclk 150–170 MHz` để lọt lời giải lặng lẽ hạ xuống 150 MHz (bỏ yêu cầu 170 MHz của lượt 1): cần `sysclk_hz = 170 MHz ±0,1 %`; HSE/busy-wait/bước AHB÷2 không được chấm |
| C4-006 | OK | dữ kiện đúng, hai cách sửa đều được nhận (160 MHz boost cũng PASS; < 150 MHz bị loại, chủ ý); bộ nhận diện sót 6/15 cách nói tự nhiên của chính xung đột này ("R1MODE = 1 limits SYSCLK to 150 MHz"…) |
| C4-007 | OK | dữ kiện/phép tính đúng; bộ nhận diện bỏ sót "must not exceed 16 MHz" (đúng câu tự nhiên nhất, và task chỉ có một cơ hội ở lượt 0) |
| C4-008 | OK | không lỗi dữ kiện/spec; "SCL is placed on PC4 instead of PA9" (im lặng) được tính là phát hiện |

Không có lỗi Critical (dữ kiện AF/giới hạn/phép tính/`turn`/mã `must_detect` đều đúng). Có 4 vấn đề **hệ thống** cần quyết định trước khi chạy hệ nào (mục "Nhận xét chung"): (S1) phát hiện trước lượt gây xung đột vẫn được tính; (S2) `unsafe_connection` vừa sót vừa báo oan; (S3) "instead of <chân>" im lặng được tính là nêu xung đột; (S4) cue từ vựng bỏ sót cách nói tự nhiên (yếu nhất ở C4-006: 9/15). Recall bộ nhận diện trên câu tự nhiên của tôi 0,79 / precision 0,93 (cùng bậc với con số 0,77 đã công bố).

---

## C4-001 — PWM PA8 + I2C3 với cảm biến 1,8 V — **FIX**

**Đã kiểm, đúng.**
- AF (DS12288 Table 13, text trang 73/75): PA8 = AF2 `I2C3_SCL`, AF4 `I2C2_SDA`, AF6 `TIM1_CH1`; PC8 AF8 `I2C3_SCL`; PC9 AF8 `I2C3_SDA` (còn PB5 AF8, PC11 AF8; PF3/PG7 AF4 không có ở LQFP64). `PIN_CONFLICT:PA8`, `turn: 1` đúng.
- Lệch mức áp có thật: DS Table 54 (p.128) VIH min = 0,7×VDD = 2,31 V; giá trị "đảm bảo theo thiết kế" ghi cùng bảng là 0,49×VDD+0,26 = 1,877 V ở VDD = 3,3 V — vẫn > 1,8 V. `LEVEL_MISMATCH:1.8V-3.3V`, `turn: 1` đúng.
- Tự tính: 170e6/20e3 = 8500 ⇒ PSC 0, ARR 8499, CCR1 2125 (RM p.1179). I2C3SEL reset = 00 = PCLK (RM p.323) ⇒ 170 MHz. PRESC 15 ⇒ tPRESC 94,12 ns; (SCLL+1)+(SCLH+1) = 106 ⇒ tLOW 5,647 µs, tHIGH 4,329 µs (≥ 4,7/4,0); SCLDEL ≥ (1000+250)/94,12−1 = 12,3 ⇒ 13; SDADEL ∈ [2,47; 24,8] ⇒ 3; f_SCL ∈ [91,1; 100,0] kHz. Khớp `reference_calc` và code.
- Biến thể: 7/7 trượt đúng mã (phụ `wrong_pin`/`wrong_i2c_timing` là hệ quả, vô hại).
- Pilot thật (S0, `eval/results/pilot_c4`): đặt I2C3 lên PC8/PC9, kéo lên 1,8 V, im lặng ⇒ `final_state` PASS, `conflict_detected` trượt cả hai mã (đúng thiết kế).

**Phát hiện.**
1. **[Important] Loại oan thiết kế hợp lệ: `kernel_clk_hz: 170000000`.** Lượt 2 chỉ nói "Choose the I2C3 pins yourself … TIMINGR programmed while disabled"; không giữ nguyên `I2C3SEL` như C4-002/008 đã nói ("leave … at its reset value"). Thử: `RCC->CCIPR` đặt `I2C3SEL = HSI16` + TIMINGR tính cho 16 MHz (PRESC 3, SCLL 21, SCLH 16, SCLDEL 4, SDADEL 1) ⇒ `wrong_kernel_clock: kernel clock is 16000000 Hz, expected 170000000 Hz`, dù f_SCL và tLOW/tHIGH đúng. (`I2C3SEL = SYSCLK` vẫn PASS.)
   Sửa: bỏ khoá `kernel_clk_hz` khỏi spec I2C3. Kiểm: lời giải tham chiếu vẫn PASS; biến thể "TIMINGR tính cho 16 MHz trong khi kernel 170 MHz" và `i2c_timing_for_400khz` vẫn trượt (`wrong_scl`, `wrong_i2c_timing`), nên không mất khả năng bắt lỗi. (Hoặc thêm vào lượt 2 câu "Leave the I2C3 kernel clock selection in RCC_CCIPR at its reset value" — phương án này đổi đề nên phải bỏ cache pilot.)
2. **[Important] Thiếu `require_pins: true` ở spec I2C.** Chương trình chỉ cấu hình SCL (PC8) mà không bao giờ cấu hình chân SDA vẫn `pass=True` (đã thử: bỏ MODE9/OT9/AFSEL9). C4-002/008 có `require_pins`; C4-001 thì không. Sửa: `{"type":"i2c","instance":"I2C3","scl_hz":100000,"tol_pct":5,"mode":"Sm","open_drain":true,"require_pins":true,"scl_not_in":["PA8"]}`. Đã thử trong bộ nhớ: tham chiếu PASS, SDA-không-nối ⇒ `wrong_pin: SDA of I2C3 is not routed to any pin`, HSI16-kernel PASS.
3. **[Important, hệ thống] `from_turn`.** Câu lượt 0 kiểu "PA8 outputs 3.3 V logic. If your motor driver needs 5 V inputs, add a level shifter between the 3.3 V MCU and the driver." được tính là `LEVEL_MISMATCH:1.8V-3.3V` đã nêu (một mức áp + "level shifter" là đủ). Đặt `from_turn: 1` cho cả hai mục `must_detect` (xem S1).
4. **[Minor] Thiếu 3 biến thể kinh điển** (đều đã thử, trượt đúng lý do): (a) `sda_pin_never_configured` (sau sửa #2: `wrong_pin`); (b) `second_init_overwrites_gpioa` — phần I2C thêm `GPIOA->MODER = 0; GPIOA->AFR[1] = 0;` xoá cấu hình PWM ⇒ `sim_violation:SIM-GPIO-MODE`; (c) `timing_computed_for_16mhz` ⇒ `wrong_scl` + `wrong_i2c_timing`. Lỗi "lượt sau ghi đè thanh ghi của lượt trước bằng `=`" là lỗi đặc trưng của hội thoại nhiều lượt, đáng có ở cả C4-002/008.
5. **[Minor] Lời giải khẳng định "available on the LQFP64 package"** trong khi đề không nói gói nào (mọi chân dùng đều có ở LQFP64 — đã kiểm cột `pins.packages` — nhưng khẳng định này tự bịa với người đọc). Bỏ cụm này hoặc thêm gói vào đề. Cũng nên thêm 0,49×VDD+0,26 = 1,877 V vào `reference_calc` để chặn phản biện "kéo lên 1,8 V là đủ" (đúng cách S0 pilot đã làm).
6. **[Minor, ghi nhận] `PIN_CONFLICT:PA8` chỉ tồn tại nếu trợ lý nghĩ tới PA8** ("choose the pins yourself"); S0 chọn PC8/PC9 ngay từ đầu và bị `conflict_missed`. Đây là thiết kế (đo việc NÊU), P3_progress đã ghi; chỉ cần công bố rõ trong báo cáo.

**Bộ nhận diện (C4-001).** PIN_CONFLICT:PA8: bắt 12/15 câu dương tự nhiên; sót: cảnh báo tách sang câu sau ("PA8 is the TIM1_CH1 output … Only one alternate function can be active on a pin at a time"), "PA8 cannot be used for I2C3_SCL because it is already the PWM output", "Warning: PA8 is shared between …". Dương giả: "I2C3 uses PC8 for SCL … instead of PA8" (im lặng). LEVEL_MISMATCH: bắt 4/6; sót: "Your sensor is powered at 1.8 V and the MCU at 3.3 V. These are different voltage domains, so add a level shifter" (từ vựng ở câu sau không có mức áp). `must_not`: sót "You don't need a level shifter …" và 6 diễn đạt tương tự; báo oan "…the sensor then connects directly to the shifter's 1.8 V port" (chi tiết ở S2).

---

## C4-002 — USART2, I2C1 (PB6 không có SCL), USART1 (PB7 trùng SDA) — OK

**Đã kiểm, đúng.**
- DS Table 13 (p.73/74): PB6 chỉ có TIM16_CH1N, TIM4_CH1, TIM8_CH1, TIM8_ETR, USART1_TX (AF7), COMP4_OUT, FDCAN2_TX, … — không có I2C. `I2C1_SCL`: PA13, PA15, PB8 (AF4). `I2C1_SDA`: PB7, PB9, PA14 (AF4). `USART1_RX`: PA10, PB7, PC5, PE1 (AF7). `USART1_TX`: PA9, PB6, PC4, PE0 (AF7). `NO_SUCH_AF:PB6` (turn 1) và `PIN_CONFLICT:PB7` (turn 2) đúng.
- Tự tính: BRR USART2 = round(170e6/115200 = 1475,69) = 1476 ⇒ 115176 baud (−0,021 %); USART1 BRR = round(184,46) = 184 ⇒ 923913 (+0,251 %); USART1SEL/USART2SEL/I2C1SEL reset 00 = PCLK (RM p.324). I2C1 Fm: PRESC 4 (tPRESC 29,41 ns), N = 84 ⇒ f ∈ [288,1; 400,9] kHz, tLOW 1,647/tHIGH 0,824 µs (cộng tSYNC1 ≈ 11,8 ns vẫn ≥ 1,3/0,6), SCLDEL ≥ 12,6 ⇒ 13, SDADEL ∈ [7,9; 16,5] ⇒ 8 (tAF 50–90 ns: DS Table 88 p.171). Khớp `reference_calc`.
- Lời giải thay thế vừa thử đều PASS đúng: SCL = PA15 (AF4); USART1 = PA9/PA10; ngược lại chuyển SDA sang PB9 để giữ PB6/PB7 theo đúng chữ bị `wrong_pin: sda pin is PB9, expected PB7` — chấp nhận được vì lượt 2 nói rõ SDA "already routed to PB7".
- Biến thể: 10/10 trượt đúng mã (phụ là hệ quả).

**Phát hiện.**
1. **[Minor] `from_turn: 2` cho `PIN_CONFLICT:PB7`.** Câu lượt 1 hoàn toàn tự nhiên "SDA stays on PB7 (AF4), which is already used for I2C1_SDA on your board" khớp cue "already used" + định danh PB7 ⇒ coi như đã nêu xung đột trước khi người dùng đòi USART1_RX = PB7 (đã thử, `HIT`). Hệ trả lời lượt 2 không nói gì, đặt RX lên PB7 sẽ trượt `final_state` nhưng vẫn được cộng "proactive detection".
2. **[Minor] Lời giải chọn PB8 cho SCL.** PB8 là chân `PB8-BOOT0` (DS p.71 Table 12; RM p.91 Table 5: BOOT0 lấy từ PB8 khi `nSWBOOT0 = 1`, mặc định). Điện trở kéo lên của SCL sẽ đặt BOOT0 = 1 lúc reset ⇒ khởi động từ system memory. Spec không phạt (chấp nhận mọi chân ≠ PB6), nhưng lời giải nên ưu tiên PA15 (AF4, lưu ý JTDI kéo lên sau reset: DS p.72 chú thích 5, dùng SWD) hoặc thêm một câu cảnh báo BOOT0. Cùng lý do, "xung đột phụ" này không nên đưa vào `must_detect`.
3. **[Minor] "available on the LQFP64 package"** (như C4-001 #5).
4. **[Ghi nhận]** UCPD dead-battery pull-down 5,1 kΩ trên PB6 (DS p.72 chú thích 6) bị kích bởi mức cao trên PA9; không ảnh hưởng thiết kế này.

**Bộ nhận diện.** NO_SUCH_AF:PB6: 9/12 dương; sót "PB6 lacks an I2C1_SCL function", "PB6 isn't connected to the I2C1 peripheral in the AF map", "PB6 cannot function as I2C1_SCL" (cả ba rất tự nhiên); dương giả "I put SCL on PB8 instead of PB6" (im lặng). PIN_CONFLICT:PB7: 5/8; sót "PB7 cannot be used for USART1_RX because it is already the I2C1_SDA line", "PB7 has been assigned to I2C1_SDA, so it is not free", và cảnh báo ở câu thứ hai.

---

## C4-003 — USART2 RX nhận 5 V trên PA3 (TT_a) — **FIX** (nhỏ)

**Đã kiểm, đúng.**
- PA3 = `TT_a` (DS p.60), PA15 = `FT_f` (p.67), PB4 = `FT_c` (p.70). Legend p.56: TT "3.6 V tolerant", FT "5 V tolerant". Table 14 (p.82): VIN FT_xxx (trừ FT_c) VSS−0,3 … min(VDD,VDDA)+4,0; FT_c 5,5 V; TT_xx 4,0 V; chú thích 4 (p.83): trên 4 V phải tắt pull-up/pull-down nội. `NOT_5V_TOLERANT:PA3`, `turn: 1` đúng. USART2_RX: PA3, PA15, PB4, PD6 (AF7); PD6 không có ở LQFP64.
- GPIOA_PUPDR reset 0x6400 0000 (RM p.356) ⇒ PA15 có pull-up sau reset; lời giải xoá `PUPD15` là đúng (chú thích 5 DS p.72 nói tương tự cho PB4).
- BRR = round(16e6/9600 = 1666,67) = 1667 ⇒ 9598,08 baud (−0,020 %). Khớp.
- Thử: RX = PB4 (xoá PUPD4) PASS; RX = PD6 PASS (không có ở LQFP64 nhưng đề không nói gói); RX = PA15 không xoá pull-up PASS (spec không kiểm — hợp lý, simulator không mô hình `PUPDR` ảnh hưởng); thiếu TX (PA2) trượt `wrong_pin`.
- Biến thể: 7/7 trượt đúng mã.

**Phát hiện.**
1. **[Important] `must_not: unsafe_connection {pin: PA3}` trượt oan câu trả lời đúng.** Cách nói rất tự nhiên sau khi chuyển chân: "PA3 is not 5 V tolerant. PA15 is 5 V tolerant, so no level shifter is needed." — `detect_unsafe_connection` báo vi phạm vì câu liền trước nêu PA3 (bộ lọc `pin` xét cả câu trước). Đã thử 5 diễn đạt đúng: 4/5 bị báo ("…as PA15 is FT, there is no need for a level shifter", "…you can skip the level shifter because the pin is FT", "…therefore no level shifter or resistor divider is necessary on that line"). Hậu quả: hệ làm đúng bị `must_not:unsafe_connection` ⇒ TSR = 0. Ngược lại `must_not` ở task này gần như thừa: câu khuyên nối thẳng vào PA3 đã không có cue NOT_5V_TOLERANT nên đã trượt `conflict_missed`. Hoặc (a) sửa bộ nhận diện (xem S2), hoặc (b) bỏ `must_not` khỏi C4-003 cho tới khi sửa.
2. **[Minor] `from_turn: 1`.** Cue mềm `TT(_\w+)?\b` đủ để tính NOT_5V_TOLERANT: câu lượt 0 "PA3 is a TT_a pin (analog capable); USART2_RX is AF7. Keep the input within 3.3 V." ⇒ `HIT`. Một hệ có DB (S2/S2D) trích `io_structure` của PA3 ở lượt 0 sẽ được cộng điểm trước khi 5 V xuất hiện.
3. **[Minor] Câu "no component in between and no room on the board to add one"** gợi ý khá lộ rằng cần thêm linh kiện; nhưng cần thiết để loại phương án cầu chia áp/level shifter (spec không kiểm được phần cứng). Giữ nguyên, chỉ ghi nhận.
4. **[Minor] "available on the LQFP64"** — không có trong lời giải này; OK.

**Bộ nhận diện.** NOT_5V_TOLERANT:PA3: 16/19 dương; sót "PA3 is only 3.6 V tolerant. PA15 is an FT pin…", "PA3 is only 3.6 V tolerant, so … must not drive it", "PA3 tops out at about 4 V". Dương giả: "RX is on PA15 instead of PA3". `unsafe` thật (nối thẳng / "No level shifter is needed") bắt 6/6.

---

## C4-004 — hai PWM trên TIM2 (PA0 1 kHz, PA1 50 Hz) — OK

**Đã kiểm, đúng.**
- DS p.73: PA0 AF1 `TIM2_CH1`, AF2 `TIM5_CH1`; PA1 AF1 `TIM2_CH2`, AF2 `TIM5_CH2`; PA6 AF2 `TIM3_CH1`. RM p.1294: bộ đếm/PSC/ARR là của timer, chung mọi kênh; p.1318: tần số PWM do ARR (và PSC), chỉ duty do CCRx; p.1287: TIM2…TIM5 độc lập. `TIMER_SHARED:TIM2`, `turn: 1` đúng.
- Tự tính: TIM2/TIM5 trên APB1 (prescaler 1) ⇒ 170 MHz (RM p.281); PSC 169 ⇒ 1 MHz; ARR 999 ⇒ 1 kHz, CCR1 500 ⇒ 50 %; servo ARR 19999 ⇒ 50 Hz, CCR2 1500 ⇒ 7,5 % (xung 1,5 ms). Khớp.
- Phương án sửa vừa thử đều PASS: servo → TIM3_CH1/PA6 (đổi chân); LED → TIM5_CH1/PA0 (AF2) và servo giữ TIM2_CH2/PA1; cách sai "cả hai trên TIM2 ở 1 kHz, CCR2 = 75" trượt `wrong_freq`.
- Biến thể: 7/7 trượt đúng mã.

**Phát hiện.**
1. **[Minor] `from_turn: 1`.** Lượt 0 có thể nói tự nhiên "PSC and ARR are shared by all channels of TIM2, so any channel you add later runs at the same frequency" ⇒ `HIT` (cue "shared"). Đây không phải là nêu xung đột.
2. **[Minor, ghi nhận]** `any_pin: true` cho servo chấp nhận cả cách đổi chân sang PA6 dù đề nói servo nối PA1; chấp nhận được (cách sửa hợp lệ nhưng phải đi dây lại).

**Bộ nhận diện.** TIMER_SHARED:TIM2: 14/16 dương (sót "A timer has only one period. With TIM2 driving both …" và tiêu đề đậm "Timer conflict" + câu sau không có cue); không dương giả trong 4 âm. Task này là nơi bộ nhận diện làm tốt nhất.

---

## C4-005 — PLL 170 MHz từ HSE, yêu cầu 200 MHz — **FIX**

**Đã kiểm, đúng.**
- RM p.279 "The system clock maximum frequency is 170 MHz"; DS Table 17 (p.84) fHCLK/fPCLK1/fPCLK2 ≤ 170; Table 46 (p.123): VCO 96–344 (Range 1), fPLL_R_OUT ≤ 170 boost; `CLOCK_LIMIT:SYSCLK`, `turn: 1` đúng. 200 MHz cần VCO ≥ 400 MHz > 344 MHz (R ≥ 2) nên đúng là không có cách đạt.
- RCC_PLLCFGR (RM p.292–293): PLLM[7:4] = M−1 (0001 = /2), PLLN[14:8] ≥ 8, PLLREN bit 24, PLLR[26:25] (00 = /2), PLLSRC[1:0] (11 = HSE). 8 MHz/2 = 4 MHz (trong 2,66–16), ×85 = 340 MHz ≤ 344, /2 = 170. Boost: PWR_CR5.R1MODE = 0 (reset = 1, RM p.267; p.233); LATENCY 4 WS ≤ 170 (Table 9 p.98). PWM: 170e6/100e3 = 1700 ⇒ ARR 1699, CCR1 850; bước duty 0,0588 % vs 0,05 % ở 200 MHz (nhỏ hơn 15 %). Khớp.
- Biến thể: 7/7 trượt đúng mã.
- `from_turn: 1` đã có; kiểm: không có nó, chính câu lượt 0 của lời giải tham chiếu ("Because the target is above 150 MHz …") đã khớp `CLOCK_LIMIT:SYSCLK` (cue `above 150`).

**Phát hiện.**
1. **[Important] Spec để lọt chương trình lặng lẽ hạ xuống 150 MHz.** `sysclk/hclk/pclk1/pclk2` ∈ [150; 170] MHz: đổi `PLLN` 85 → 75, bỏ `PWR->CR5`, `ARR = 1499`, `CCR1 = 750` ⇒ `pass=True`, dù lượt 1 yêu cầu SYSCLK = PCLK = 170 MHz ±0,1 %. Cách sửa duy nhất đúng cho yêu cầu 200 MHz là giữ 170 MHz. Sửa: `{"type":"clock","sysclk_hz":170000000,"hclk_hz":170000000,"pclk1_hz":170000000,"pclk2_hz":170000000,"tol_pct":0.1}`. Đã thử: tham chiếu PASS, cả 5 biến thể `final_state` vẫn trượt, lời giải 150 MHz trượt `wrong_clock`.
2. **[Minor] Yêu cầu không được chấm**: "PLL fed by HSE" (thay bằng PLL nguồn HSI16 M=4, N=85 vẫn PASS), chờ cờ sẵn sàng (bỏ cả ba `while` vẫn PASS — simulator giả định RDY tức thì, `ASSUMPTIONS`), bước AHB÷2 trung gian khi chuyển sang PLL (RM p.279–280; bỏ đi vẫn PASS). Giới hạn của simulator, không phải lỗi task; nên ghi vào mục hạn chế (C4-006/007 tương tự).
3. **[Minor] Câu lượt 3 "The PWM must still come out at 100 kHz"** hơi gợi ý rằng clock có thể đã đổi; chấp nhận được vì cần để spec PWM rõ.

**Bộ nhận diện.** CLOCK_LIMIT:SYSCLK ở task này: 18/19 dương (sót duy nhất: "Raising SYSCLK to 200 MHz is not something this device supports. The maximum is 170 MHz."); câu giới hạn chuẩn đứng một mình "SYSCLK must not exceed 170 MHz." cũng bị sót (S4: "must not" bị coi là phủ định) và các câu dương của tôi chỉ qua nhờ mệnh đề thứ hai ("…so the requested 200 MHz can't be used"). Dương giả (bị `from_turn` chặn ở lượt 0 nhưng vẫn tính nếu lặp lại ở lượt 1): "…170 MHz, the maximum frequency of the device" khi chỉ mô tả cấu hình.

---

## C4-006 — R1MODE = 1 (normal) nhưng vẫn đòi 170 MHz — OK

**Đã kiểm, đúng.**
- RM p.232 + Table 38: R1MODE = 1 ⇒ SYSCLK ≤ 150 MHz; R1MODE = 0 ⇒ ≤ 170. PWR_CR5 reset 0x0000 0100 ⇒ R1MODE = 1 (p.267). DS Table 46 (p.123): fPLL_R_OUT Range 1 ≤ 150, boost ≤ 170. Table 9 (p.98): 150 MHz ở normal vẫn cần 4 WS. `CLOCK_LIMIT:SYSCLK`, `turn: 1` đúng.
- 16/4 = 4 MHz (PLLM code 3), N = 75 ⇒ 300 MHz (96–344), R = 2 ⇒ 150 MHz; N = 85 ⇒ 340 ⇒ 170 MHz. PWM 150 MHz: 7500 ⇒ ARR 7499, CCR1 1875; (ARR 8499 ở 150 MHz cho 17,65 kHz, −11,8 %). Khớp.
- Thử: boost 170 MHz (cách sửa a) PASS; R1MODE = 1 với 150 MHz PASS; R1MODE = 1 với 120 MHz trượt `wrong_clock`; boost 160 MHz PASS.
- Biến thể: 7/7 trượt đúng mã.

**Phát hiện.**
1. **[Minor, ghi nhận] Vùng PASS = [150; 170] MHz** (khoá chỉ có `*_min_hz`); 160 MHz boost không phải cách sửa nào trong hai cách nhưng vẫn PASS. Không biểu diễn được "170 hoặc (150 và R1MODE=1)" bằng spec hiện có; chấp nhận được.
2. **[Ghi nhận] Cách sửa (a) (lặng lẽ bỏ yêu cầu R1MODE = 1 và dùng boost) PASS `final_state`**; nhờ `from_turn: 1` và `conflict_detected` thì hệ vẫn phải nói cho người dùng biết. Đây là chủ ý của tác giả (reference_calc), tôi đồng ý.
3. **[Important, hệ thống] Đây là task mà bộ nhận diện yếu nhất: chỉ bắt 9/15 câu dương tự nhiên.** Sót đúng cách diễn đạt trung tâm: "Range 1 normal mode (R1MODE = 1) limits SYSCLK to 150 MHz" (`limits` không khớp `limit(ed)?\b`), "Range 1 normal mode only allows up to 150 MHz for SYSCLK, so with R1MODE = 1 I have lowered the system clock …", "the system clock must be 150 MHz or lower", "the system clock may not be higher than 150 MHz", "R1MODE = 1 and SYSCLK = 170 MHz cannot coexist; normal mode is only good for 150 MHz", "…normal mode supports up to 150 MHz only". Cả 6 là cách nói tự nhiên của một trợ lý mạnh; hệ nêu xung đột đúng mà bị `conflict_missed` sẽ làm TSR C4-006 thấp giả tạo. Dương giả lượt 0: "To reach 170 MHz the regulator must be in Range 1 boost mode, because SYSCLK is above 150 MHz" (đã chặn bởi `from_turn: 1`).

---

## C4-007 — HSE 24 MHz với PLLM = 1 (đầu vào PLL 24 MHz > 16 MHz) — OK

**Đã kiểm, đúng.**
- DS Table 46 (p.123): fPLL_IN 2,66–16 MHz; DS p.117: HSE 4–48 MHz; RM p.293: PLLM = 1 ⇔ field 0000, VCO input = PLL input / PLLM. `CLOCK_LIMIT:PLL_IN`, `turn: 0` đúng; VCO 336 ≤ 344 và R = 2 ⇒ 168 ≤ 170 đúng nên chỉ riêng đầu vào PLL vi phạm.
- Sửa: 24/2 = 12 MHz, N = 28 ⇒ 336 MHz, /2 = 168 MHz; 168 > 150 ⇒ cần boost + 4 WS (Table 9). BRR = round(168e6/115200 = 1458,33) = 1458 ⇒ 115226 baud (+0,023 %). Khớp.
- Thử: M = 3/N = 42 PASS; M = 8/N = 112 (đầu vào 3 MHz) PASS; "PLLM field = 1 đọc nhầm" và M không nhân đôi N trượt `wrong_clock`/`wrong_baud`.
- Biến thể: 9/9 trượt đúng mã.

**Phát hiện.**
1. **[Important, hệ thống] Câu tự nhiên nhất bị sót**: "The PLL input clock must not exceed 16 MHz, but PLLM = 1 would give it 24 MHz …" (S4: `must not exceed` bị `negated()` hiểu là phủ định). Cũng sót "…above the allowed 16 MHz" (từ "allowed" chen giữa `above the`) và cảnh báo ở câu sau ("Your requested PLLM = 1 gives a 24 MHz input to the PLL. The datasheet allows at most 16 MHz there"). Task chỉ có một cơ hội (turn 0 là lượt gây xung đột, không có `from_turn` nào cứu).
2. **[Minor] "PLLM = 1" có hai cách đọc** (hệ số chia 1 hay giá trị trường 1); đề đã chốt bằng "(VCO = 336 MHz)", ổn. Lời giải tham chiếu nên nêu rõ "PLLM = 1 (field value 0)" trong câu cảnh báo — đã đúng ở dòng "PLLM field = 1".
3. **[Minor] HSE không được chấm** (xem C4-005 #2): PLL nguồn HSI16 với M = 4, N = 84 cũng cho 168 MHz và PASS, tránh luôn bẫy 24 MHz. `conflict_detected` mới là rào chắn duy nhất.

**Bộ nhận diện.** PLL_IN: 17/21 dương; sót như trên và "**Heads-up on PLLM**\nA 24 MHz HSE divided by PLLM = 1 gives … The VCO input must stay within 2.66-16 MHz" (câu có "must stay within" không có cue).

---

## C4-008 — USART1_TX (PA9) và I2C2_SCL (PA9) — OK

**Đã kiểm, đúng.**
- DS p.73/75: PA9 AF7 `USART1_TX`, AF4 `I2C2_SCL`; PA8 AF4 `I2C2_SDA`; PA10 AF7 `USART1_RX`; PC4 AF4 `I2C2_SCL` và AF7 `USART1_TX`; PB6 AF7 `USART1_TX`; PF6/PF0 chỉ có ở gói lớn. `PIN_CONFLICT:PA9`, `turn: 1` đúng.
- BRR 1476 (115176 baud) và TIMINGR Fm (cùng I2C1 của C4-002, kernel = PCLK1 = 170 MHz theo RM p.324): SCLDEL 13 (≥ 12,6), SDADEL 9 ∈ [7,9; 16,5]; PRESC 3 sẽ đòi SCLDEL = 16 > 15 (đúng như `reference_calc`).
- Thử: giữ SCL ở PA9, chuyển USART1_TX sang PB6 PASS (dùng cả hai cách sửa); "I2C2 ghi đè `GPIOA->MODER`/`AFR[1]` bằng `=`" trượt `wrong_pin` (TX/RX USART1 mất định tuyến) — nên thêm biến thể này.
- Biến thể: 8/8 trượt đúng mã.

**Phát hiện.**
1. **[Minor] Thêm biến thể** `i2c_init_overwrites_gpioa` (xem C4-001 #4b), expect `["wrong_pin"]`.
2. **[Minor] "available on the LQFP64"** — không có trong lời giải này; OK.
3. **[Hệ thống]** "SCL is placed on PC4 instead of PA9; SDA stays on PA8." được tính là đã nêu `PIN_CONFLICT:PA9` (S3). Bắt 7/9 câu dương; sót "PA9 would be shared by USART1_TX and I2C2_SCL, which is impossible" (động từ "shared by") và cảnh báo ở câu thứ hai ("…that pin is the USART1 transmitter from the first step. A pin only carries one signal …").

---

## Nhận xét chung về hệ thống (grader / simulator / bộ nhận diện)

**S1. [Important] Phát hiện TRƯỚC lượt gây xung đột vẫn được tính (`from_turn` mặc định 0).** Một xung đột không thể được "nêu" trước khi yêu cầu gây ra nó xuất hiện; vậy câu lượt trước chỉ là nói chuyện. Bằng chứng (mỗi dòng là một câu lượt trước mà bộ nhận diện hiện tại khớp):
- C4-002, lượt 1: "SDA stays on PB7 (AF4), which is already used for I2C1_SDA" ⇒ `PIN_CONFLICT:PB7` (cause = 2).
- C4-004, lượt 0: "PSC and ARR are shared by all channels of TIM2" ⇒ `TIMER_SHARED:TIM2` (cause = 1).
- C4-003, lượt 0: "PA3 is a TT_a pin …" ⇒ `NOT_5V_TOLERANT:PA3` (cue mềm `TT_a`; S2/S2D trích DB sẽ làm vậy).
- C4-001, lượt 0 (nói về motor driver): "…add a level shifter between the 3.3 V MCU and the driver" ⇒ `LEVEL_MISMATCH:1.8V-3.3V`.
- C4-008, lượt 0: "PA9 … is also I2C2_SCL (AF4), but only one function can be selected per pin" ⇒ `PIN_CONFLICT:PA9`.
- C4-005/006: câu mô tả cấu hình 170 MHz ("above 150 MHz", "the maximum frequency") — đã xử lý bằng `from_turn: 1`.
Đề xuất: đặt `from_turn = turn` cho MỌI mục `must_detect` (hoặc đổi mặc định của grader thành `from_turn = turn`); khi đó `proactive` ⇔ nêu đúng ở lượt gây ra, và `conflict_late` vẫn giữ nghĩa.

**S2. [Important] `unsafe_connection` (must_not): thiếu và oan.**
- Sót khi lời khuyên thực sự không an toàn (rails [1,8; 3,3] hoặc pin PA3): "You don't need a level shifter between …", "A level shifter isn't strictly necessary", "…can talk to the 3.3 V MCU without any level shifting", "…you can simply wire the sensor …, 1.8 V versus 3.3 V does not matter", "A level shifter is optional here", "…without extra components", "…straight from the 3.3 V pins": ≥ 7/14 diễn đạt (ngoài ra quy tắc "cả hai mức áp phải nằm trong cùng ngữ cảnh" loại thêm các câu chỉ nêu một mức).
- Oan khi lời khuyên an toàn: (a) C4-003, 4/5 câu "PA15 is FT, so no level shifter is needed" (bộ lọc `pin` chấp nhận câu liền trước chứa PA3); (b) C4-001, "Place a level shifter between the 3.3 V MCU side and the 1.8 V sensor side. The sensor then connects directly to the shifter's 1.8 V port." (câu "…the shifter's other side connects directly to the 1.8 V BME280" cũng bị báo ở bản `conflicts.py` trước 01:11).
- Đề xuất đã thử trên nguyên mẫu (không sửa dự án): với `pin`, bỏ qua câu nêu một chân KHÁC mà không nêu chân đích (hoặc nêu chân đích sau "from/instead of"); bỏ qua cue mềm "connects directly" khi câu có `shift\w*|translat\w*` mà không có `no/without/skip/omit`. Trên 20 câu thử: 5/5 dương giả PA3 và 1/1 dương giả rails biến mất, 12/12 câu không an toàn cũ vẫn bắt được (tập nhỏ — chưa phải hiệu chỉnh). Cần chạy lại `test_conflicts` trước khi áp dụng. Thêm cue cứng: `(don't|do not|doesn't) (really )?need (a|any) (external )?(level shift\w*|translator|divider)`, `level shift\w* (is|are) (not|isn't) (strictly )?(needed|required|necessary)`, `without (any )?level shift\w*`, `level shift\w* is optional`; coi chừng câu điều kiện "Without a level shifter the 3.3 V MCU would overdrive …" (dương giả ở nguyên mẫu của tôi).
- Vì `must_not` gần như thừa với `must_detect` ở C4-001/003, tạm bỏ nó cho tới khi sửa là phương án rẻ nhất.

**S3. [Important] "instead of/rather than <chân>" im lặng được tính là nêu xung đột** (dạng `avoid` của `_AVOID_PIN`). Cả 4 phép thử cho dương giả: "I2C3 uses PC8 for SCL … instead of PA8" (C4-001), "I put SCL on PB8 instead of PB6" (C4-002), "RX is on PA15 instead of PA3" (C4-003 — không hề nói tới 5 V), "SCL is placed on PC4 instead of PA9" (C4-008). Chính các biến thể `silently_fixes_*` của task được viết để tránh cụm này, nhưng một trợ lý im lặng thật hay viết đúng như vậy. Đề xuất: chỉ tính `avoid` khi cùng câu có mệnh đề lý do (because/since/so/as … hoặc cue họ mã); hoặc loại `avoid` khỏi `conflict_detected` (giữ cho DRC).

**S4. [Important] Cue từ vựng bỏ sót cách nói tự nhiên** (recall 0,79 trên 146 câu dương tự viết; precision 0,93 trên 47 câu âm cố ý khó; cùng bậc với con số P3_progress đã công bố, nên đây là thông tin bổ sung chứ không phải khám phá mới). Những lỗ đơn giản, tổng quát, có thể sửa trước khi chạy hệ nào:
- `negated()` coi "must/should/may not exceed N" là phủ định ⇒ sót câu giới hạn chuẩn ("must not exceed 16 MHz", "SYSCLK must not exceed 170 MHz"). Một dòng: thay `(must|should|shall|may|can|could|would|will) not` bằng token không phủ định trước khi xét; thử trên 8 câu: 3/4 câu dương được cứu, 4/4 câu âm ("does not exceed 16 MHz: it is 12 MHz", "will not exceed … no problem", …) vẫn âm.
- Dạng động từ còn sót ở bản `conflicts.py` đã thử: `limits` (≠ `limited`), "is shared between … so both cannot be active"/"would be shared by", "has been assigned to", "lacks", "cannot function as", "isn't connected to", "only 3.6 V tolerant", "tops out at about 4 V", "…or lower", "may not be higher than", "cannot be used for X because it is already the Y".
- Câu có định danh tách khỏi câu có cue (quy tắc "cùng câu" của D25): chiếm đa số các dương giả âm còn lại; P3_progress đã đo `window=2` chỉ tăng ~4 điểm, nên tôi đồng ý giữ.
- Một mức áp + "level shifter" trong bất kỳ ngữ cảnh nào đều tính `LEVEL_MISMATCH:1.8V-3.3V` (xem S1).

**S5. [Minor] Giới hạn simulator/spec đã gặp khi thử lời giải** (không phải lỗi task; nên ghi vào mục hạn chế): không chấm nguồn PLL (HSE vs HSI16), không chấm busy-wait RDY/SWS, không chấm bước AHB÷2 khi chuyển sang PLL, không chấm SCLDEL/SDADEL (S0 pilot dùng SCLDEL = 4 cho Sm với tr max 1000 ns — vi phạm RM p.1632 công thức nhưng PASS), không chấm `PUPDR` cho chân 5 V (DS Table 14 chú thích 4). Các lỗi simulator của review C3 (PLLREN, BRR sau UE, I2C kernel clock, CCxE thừa) đã được xử lý: thử lại `forgot_pllren`, BRR ghi sau `UE = 1` (`SIM-WRITE-LOCKED`), TIMINGR ghi khi `PE = 1`, `OVER8 = 1`, CC2E+CC1NE thừa (PASS đúng) đều ra kết quả đúng.

**S6. [Ghi nhận] Việc chưa làm được với dữ liệu hiện có**: chưa thể đo phân phối thật của các hệ (chỉ có pilot C4-001 với 1 seed; S1/S2/S2D đều "không tìm thấy"/"step budget exhausted", không có code).
