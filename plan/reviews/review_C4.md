# Review độc lập — benchmark C4 (15 task) và bộ chấm `final_state` / `conflict_detected`

Hai reviewer độc lập (ngữ cảnh mới, không phải tác giả; không sửa dự án; không đọc `agent/.env`): `review_C4_part1.md` (C4-001…008) và `review_C4_part2.md` (C4-009…015).
Mỗi reviewer: đọc text trang PDF (DS12288 Table 13/14/17/46/54, RM0440 Table 9/38…) để kiểm AF, loại chân, giới hạn clock, mức logic; tự tính lại PSC/ARR/CCR, BRR, TIMINGR, PLL, wait state bằng Python thuần (không qua simulator);
biên dịch code lượt cuối bằng **header ST chính thức** (`corpus/headers/cmsis-device-g4_v1.2.6`, `clang -fsyntax-only`: 15/15 sạch); chạy ~25 chương trình thay thế/biến thể mới qua `final_state`; viết ~320 câu trả lời dương/âm tự nhiên cho bộ nhận diện.
Ngoài ra `p3-code-reviewer` soát mã P3 (kết quả ở `plan/P3_progress.md` — mục "Review mã").

## Kết luận gốc của hai reviewer
| Task | Kết luận | Vấn đề chính |
|---|---|---|
| C4-001 | FIX | `kernel_clk_hz` loại oan I2C3SEL = HSI16; thiếu `require_pins`; câu lượt trước khớp cue |
| C4-002 | OK (sửa nhỏ) | `from_turn` cho PB7; lời giải chọn PB8 = BOOT0 |
| C4-003 | FIX (nhỏ) | `must_not` báo oan câu đúng ("PA15 is 5 V tolerant, so no level shifter is needed") |
| C4-004 | OK | `from_turn` (lượt 0 nói "ARR is shared by all TIM2 channels") |
| C4-005 | FIX | spec [150; 170] MHz để lọt lời giải lặng lẽ hạ xuống 150 MHz |
| C4-006 | OK | dữ kiện đúng; bộ nhận diện sót cách nói R1MODE |
| C4-007 | OK | bộ nhận diện sót "must not exceed 16 MHz" |
| C4-008 | OK | thiếu biến thể ghi đè GPIOA; "instead of PA9" im lặng bị tính là nêu |
| C4-009 | OK | lượt 2 "Tell me how to wire it" gần như mớm xung đột; spec thiếu `over8` |
| C4-010 | FIX | spec bất đối xứng loại oan hướng "giữ USART1 ở PB6/PB7, dời PWM"; trích sai chương |
| C4-011 | OK | chấp nhận TIM17/TIM16/TIM8_CH1N/TIM1_CH1N |
| C4-012 | AMBIGUOUS | "USART1" lẫn "PA2/PA3": hướng USART2 bị chấm trượt |
| C4-013 | OK | biến thể đặt tên sai bản chất; `any_pin` không ràng buộc TIM2 |
| C4-014 | FIX | `tx_pin: PC4` loại oan PA9/PA10; `must_not` báo oan câu đúng |
| C4-015 | OK | SDA→PF0 (OSC_IN) lọt; thiếu biến thể quên wait state |

Không có lỗi Critical về dữ kiện (AF, loại chân, giới hạn, phép tính, `turn` và mã `must_detect` đều đúng ở cả 15 task).

## Xử lý (thực hiện TRƯỚC khi chạy bất kỳ hệ nào trên C4)
| Phát hiện | Xử lý |
|---|---|
| C4-001 `kernel_clk_hz` | **Đã sửa**: bỏ khoá khỏi spec I2C3 (biến thể "TIMINGR tính cho 16 MHz" vẫn trượt `wrong_scl`); thêm `require_pins: true` |
| C4-001 thiếu biến thể | **Đã thêm** `sda_pin_never_configured`, `second_init_overwrites_gpioa` (`SIM-GPIO-MODE`), `timing_computed_for_16mhz` |
| C4-001 ghi chú 1,88 V | **Đã thêm** vào `reference_calc` (0,49·VDD + 0,26 = 1,877 V > 1,8 V) |
| "available on the LQFP64" (C4-001/002/012/013/015) | **Đã bỏ** khỏi lời giải tham chiếu (đề không nêu gói chân); quy tắc ghi vào `C4_authoring_guide.md` §9 |
| C4-002 PB8 = BOOT0 | **Đã thêm** cảnh báo BOOT0/nSWBOOT0 và PA15 làm phương án vào lời giải; spec giữ nguyên |
| C4-003, C4-014 `must_not` báo oan | **Đã sửa bộ nhận diện** (lời khuyên nối thẳng phải nói về CHÂN bị cấm: cue gắn với chân gần nhất, câu nêu chân khác bị bỏ qua, "away from PA3") + 8 test hồi quy; `must_not` được giữ |
| C4-005 spec | **Đã sửa**: `sysclk/hclk/pclk1/pclk2 = 170 MHz ±0,1 %`; thêm biến thể `silently_lowered_to_150mhz` (`wrong_clock`) |
| C4-009 | **Đã sửa**: bỏ "Tell me how to wire it" (lượt 2 chỉ còn "Update the design for this module if needed"), thêm `over8: 0` |
| C4-010 spec bất đối xứng | **Đã sửa ở grader + spec**: PWM `any_pin` nay lọc theo `signal` (và nhận `forbid_pins`) ⇒ spec đối xứng (TIM4_CH1 = 30 %, TIM4_CH2 = 60 %, USART1 không ràng buộc chân); `valid_variants` mới (verify_tasks bắt buộc PASS) có "PWM sang PD12/PD13, USART1 giữ PB6/PB7"; sửa trích dẫn p.1179 → p.1319 (§30.4.x); biến thể `usart1_kept…` expect `inactive:no_effect` |
| C4-012 mơ hồ | **Đã sửa đề**: lượt 0 nêu "USART2 of this board belongs to an RS-485 transceiver, so this console must use USART1" (không kích hoạt cue nào) |
| C4-013 | **Đã sửa**: đổi tên biến thể `arr_set_to_the_16bit_maximum`, thêm `timer_clock_taken_as_85_mhz`; spec `signal: TIM2_CH3`; `valid_variants` "USART3_TX→PC10, PWM giữ PB10" |
| C4-014 `tx_pin` | **Đã sửa**: bỏ `tx_pin: PC4`; `valid_variants` "TX+RX sang PA9/PA10" |
| C4-015 | **Đã thêm** `sda_pin: PA8` (SDA→PF0/OSC_IN trượt `wrong_pin`) và biến thể `sda_on_the_hse_oscillator_pin`, `forgot_flash_latency` (`SIM-FLASH-WS`) |
| C4-008 | **Đã thêm** biến thể `i2c_init_overwrites_gpioa` |
| S1: câu lượt TRƯỚC khớp cue | **Đã áp dụng**: `must_detect[].from_turn = turn` cho cả 18 mục có `turn ≥ 1`. Thu hẹp "trước hoặc tại" của D25 thành "tại" ở mức dữ liệu (grader mặc định vẫn D25; đảo được bằng chấm lại offline). Báo cáo in thêm cột D25 nguyên văn |
| S2: `unsafe_connection` sót/oan | **Đã sửa** (cue "don't need…", "isn't strictly necessary", "is optional", "without … shifter" (có bộ lọc điều kiện), mức áp lạ kèm "5 V tolerant", "not recommended/wrong/bad idea"; "shifter's port" không còn bị báo) |
| S3: "instead of PA9" im lặng được tính là nêu | **Đã sửa**: dạng "instead of/rather than/not <chân|MHz>" chỉ tính khi cùng câu có mệnh đề lý do (because/since/which is…); "avoid/never/stay away from" vẫn tính |
| S4: từ vựng sót | **Đã sửa tổng quát** (must not exceed, limits, tops out at, only allows up to, 150 MHz or lower, being used by, currently assigned to, shares X with, compete for, belong to USARTn, lacks, isn't connected to, "level converter", "different domains", …); số đo ở `plan/P3_progress.md` |
| LaTeX `$170\text{ MHz}$` (từ `p3-code-reviewer`, dữ liệu pilot thật) | **Đã sửa** `conflicts.normalize()` trước khi tách câu (cũng dấu nháy cong, khoảng trắng đặc biệt) |
| ReDoS (3 regex bậc hai) | **Đã sửa** (quét chú thích tuyến tính, `^[ \t]*`, cận chữ số, cắt 200 000 ký tự/1 500 ký tự mỗi câu) + test thời gian |
| Recall thấp ở diễn đạt "đối lập"/tách câu | **Chấp nhận có công bố**: giữ D25 "cùng câu" làm cách chấm; báo cáo in cột nới 2 câu để đọc độ bất định (recall thật < 1; dương ngầm chưa được nhận diện theo thiết kế) |
| S5 / simulator không mô hình hoá (nguồn PLL, busy-wait RDY, bước AHB÷2, PUPDR, UCPD dead-battery, chiếm chân OSC) | **Ghi nhận hạn chế** (báo cáo cuối + P4: ứng viên cho DRC/sandbox) |
| Biến thể không có `expect` / khoá spec gõ nhầm / `must_not` lạ | **Đã sửa**: `verify_tasks` đòi `expect` không rỗng; `Task.__post_init__` kiểm `SPEC_KEYS`, `CONFLICT_FAMILIES`, `MUST_NOT_KEYS` |
| Khối code rời cạnh chương trình đầy đủ làm trượt oan (`extract_c_code`) | **Đã sửa**: khối chỉ có lệnh ghi thanh ghi, không có định nghĩa hàm, bị bỏ khi đã có khối chứa `main()` |

## Còn lại có chủ đích
* `PIN_CONFLICT:PA8` ở C4-001 chỉ tồn tại nếu trợ lý nghĩ tới PA8 ("choose the pins yourself"): đây là thiết kế của task (đo việc NÊU), công bố trong báo cáo.
* Spec clock của C4-006/015 là dải (cả hai cách sửa hợp lệ), nên 160 MHz boost vẫn PASS ở C4-006; C4-015 cho lọt 169,33 MHz — không biểu diễn được "170 ±0,1 % HOẶC ≥ 150" bằng `functional_sim`.
* Hiệu ứng mà simulator không chấm (ghi để P4): nguồn PLL (HSE vs HSI16), chờ RDY, bước chia AHB/2, `PUPDR` cho chân 5 V, kéo xuống UCPD dead-battery của PB6/PB4, chiếm chân dao động HSE.
* Recall của bộ nhận diện trên diễn đạt tự nhiên: xem `plan/P3_progress.md` (hợp nhất 6 tập: precision ≈ 0,99, recall dương rõ ≈ 0,97, dương ngầm ≈ 0,41).
