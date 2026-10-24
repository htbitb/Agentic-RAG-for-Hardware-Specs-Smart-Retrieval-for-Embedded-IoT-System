# Hướng dẫn viết task C4 (P3) — thiết kế nhiều lượt có xung đột cài sẵn

Tham chiếu: `plan/P3_Handoff.md` §3 Bước 4–5, `plan/DECISIONS.md` D19–D21, D25; mẫu hoàn chỉnh: **`eval/tasks/C4/c4_curated.yaml` (C4-001)**.

## 1. Một task C4 là gì
Hội thoại 3–6 lượt giữa người dùng và một trợ lý thiết kế firmware STM32G474 (CMSIS, bare-metal C). Ở một lượt nào đó người dùng đưa ra yêu cầu mà **một xung đột
thiết kế có thật** (theo bảng AF / datasheet / RM) đã được cài sẵn — người dùng **không nhắc** tới xung đột. Hệ được chấm bởi hai grader (đều gate TSR):

* `final_state` — khối code C ở **lượt cuối** (lượt cuối luôn đòi "chương trình khởi tạo HOÀN CHỈNH trong một khối code C") chạy qua `analyze_c_code` →
  `simulate_register_writes` (bản hwmodel đóng băng) và phải thoả MỌI `expected.spec`, không vi phạm mô phỏng, không dùng chân bị cấm.
* `conflict_detected` — mỗi xung đột trong `expected.must_detect` ({code, turn}) phải được câu trả lời **NÊU Ở LƯỢT `turn` HOẶC SỚM HƠN** (chủ động). Nêu muộn hơn (sau khi
  người dùng hỏi) thì trượt `conflict_late`; không nêu thì `conflict_missed`; `must_not: unsafe_connection` trượt nếu trợ lý khuyên nối trực tiếp / "không cần level shifter".
* `compile` (không gate): khối code lượt cuối biên dịch được với clang.

## 2. Định dạng YAML (xem C4-001)
```yaml
- id: C4-0NN
  category: C4
  split: dev            # tạm; `assign_splits` sẽ ghi lại
  difficulty: medium|hard
  chips: [stm32g474]
  tags: [<họ xung đột chính>, ...]       # tag đầu = tầng chia dev/test: pin_conflict | no_such_af | non_ft | timer_shared | clock_limit | level_shift | multi_conflict
  turns: [{user: ...}, ...]               # 3–6 lượt; lượt 1 nêu quy ước D20; lượt cuối đòi chương trình hoàn chỉnh
  expected:
    chip: stm32g474
    initial: <preset>                     # reset | sysclk_170mhz_pll_hsi16_apb_div1 | ..._apb2_div2 | ..._apb1_div2 | sysclk_80mhz_pll_hsi16_apb_div1
    hse_hz: 8000000                       # (tuỳ chọn) nếu đề dùng thạch anh HSE
    spec: [...]                           # trạng thái CUỐI (chức năng), xem §4
    must_detect: [{code: "PIN_CONFLICT:PA8", turn: 1}, ...]   # turn = chỉ số 0-based của lượt NGƯỜI DÙNG gây ra xung đột; tuỳ chọn from_turn (≤ turn): chỉ tính phát hiện từ lượt đó
    must_not: [{code: unsafe_connection, rails: [1.8, 3.3]}]    # hoặc {code: unsafe_connection, pin: PA3}; bỏ nếu không có nguy cơ đó
  graders: [final_state, conflict_detected, compile]
  review_status: verified
  provenance:
    authored_by: "..."
    conflict_facts: [...]                 # đối chiếu DB P1: {type: af, pin, signal, af} | {type: no_af, pin, signal} | {type: ft, pin, tolerant} | {type: clock_limit, like, max}
    evidence: [{doc_id, page, contains: [snippet nguyên văn trên trang PDF]}]   # xác minh bằng text trang (`ctx.page_text`)
    reference_calc: >-                    # PHÉP TÍNH TAY có công thức và số trang; KHÔNG sinh từ simulator/DRC (D19)
    reference_solution: {turns: [ <câu trả lời tham chiếu của lượt 1>, ... ]}   # đúng bằng số lượt người dùng
    wrong_variants: [{name, grader: final_state|conflict_detected, edits: [{turn, find, replace}], expect: [mã lỗi]}]   # `expect` BẮT BUỘC, không rỗng
    valid_variants: [{name, note, edits: [{turn, find, replace}]}]   # cách sửa HỢP LỆ khác lời giải tham chiếu: verify_tasks bắt buộc PASS final_state (chống loại oan)
```

## 3. Mã xung đột (`must_detect[].code`) và cách bộ nhận diện hiểu
Bộ nhận diện (`eval/graders/conflicts.py`, tất định; ĐỌC file này để biết cách diễn đạt nào được tính) xét **từng câu** của câu trả lời: câu phải chứa **định danh** (tên chân / hai mức
áp / timer / khối clock) **và** một **từ vựng xung đột** của họ mã đó, không bị phủ định trong cùng câu. Vì vậy câu trả lời tham chiếu phải nêu xung đột **trong một câu có đủ định danh**
(ví dụ "PA8 is already used by TIM1_CH1, so I2C3_SCL cannot also be placed on PA8", "the 1.8 V sensor cannot be wired directly to the 3.3 V MCU: add a level shifter").

| Họ mã | Ví dụ | Định danh trong câu | Ý nghĩa |
|---|---|---|---|
| `PIN_CONFLICT:<pin>` | `PIN_CONFLICT:PA8` | tên chân | chân đã có chủ khác |
| `NO_SUCH_AF:<pin>` | `NO_SUCH_AF:PB6` | tên chân | chân không mang tín hiệu được yêu cầu |
| `NOT_5V_TOLERANT:<pin>` | `NOT_5V_TOLERANT:PA3` | tên chân | ngõ ra 5 V vào chân không FT |
| `LEVEL_MISMATCH:<a>V-<b>V` | `LEVEL_MISMATCH:1.8V-3.3V` | ít nhất một mức áp (từ vựng yếu như "exceed/damage" cần đủ hai) | lệch miền điện áp, cần level shifter |
| `TIMER_SHARED:<TIMx>` | `TIMER_SHARED:TIM2` | tên timer | các kênh của một timer dùng chung bộ đếm/ARR nên một tần số |
| `CLOCK_LIMIT:<SYSCLK\|VCO\|PLL_IN\|HSE\|FLASH_WS>` | `CLOCK_LIMIT:SYSCLK` | từ chỉ khối clock (SYSCLK/system clock/HCLK, VCO, "PLL input", HSE/crystal...) | vượt giới hạn datasheet/RM |
| `unsafe_connection` (must_not) | `{rails: [1.8, 3.3]}` hoặc `{pin: PA3}` | hai mức áp / tên chân | khuyên nối trực tiếp / "no level shifter is needed" |

**`from_turn`:** nếu các lượt TRƯỚC lượt gây xung đột tự nhiên đã nhắc cùng loại giới hạn (vd lượt 1 cấu hình PLL 170 MHz nên câu trả lời nói "170 MHz là tối đa"), đặt `from_turn: <turn>` để câu nhắc đó không bị tính là nêu xung đột trước khi yêu cầu vượt giới hạn xuất hiện. Mặc định 0 (nêu sớm vẫn tính, D25). **Sau review độc lập:** review chỉ ra các câu lượt trước rất tự nhiên khớp cue ("SDA stays on PB7, which is already used for I2C1_SDA", "PSC and ARR are shared by all channels of TIM2", "PA3 is a TT_a pin", "…add a level shifter between the 3.3 V MCU and the driver", "PA9 … is also I2C2_SCL"); vì vậy MỌI mục có `turn ≥ 1` đặt `from_turn = turn` (hiện: tất cả 18 mục của 15 task; lý do khoa học: hệ có công cụ DB (S2/S2D) hay in bảng AF/giới hạn ở lượt sớm, nếu tính câu đó là "nêu xung đột" thì thiên vị đúng hệ đang được so sánh). Đây thu hẹp "trước hoặc tại" của D25 thành "tại" ở mức DỮ LIỆU task (grader mặc định vẫn là D25); chấm lại offline không tốn LLM nên đảo ngược được bằng cách bỏ `from_turn`. Báo cáo C4 vẫn in song song ba cách đếm (đúng lượt gây xung đột / D25 / nới 2 câu) để đọc độ bất định.

**Người dùng KHÔNG được nhắc xung đột:** `verify_tasks` chạy bộ nhận diện trên từng lượt người dùng và báo lỗi nếu nó "nêu" xung đột. Người dùng có thể nêu **sự kiện** (cảm biến 1.8 V, ngõ ra 5 V, tên chân,
tần số) nhưng không dùng từ vựng xung đột (conflict, level shifter, exceed, not 5 V tolerant, already used...).

## 4. `expected.spec` — chức năng, không phải giá trị thanh ghi
Mục của `functional_sim` (xem docstring đầu `eval/graders/functional_sim.py`): `pwm` (pin|`any_pin`, freq_hz, duty_pct, tol_pct, duty_tol_pp, `timer_not_in`, `forbid_pins`), `uart` (instance, baud, tol_pct,
tx_pin|rx_pin, `tx_not_in`, `rx_not_in`, frame, te, re, over8, `require_pins`), `i2c` (instance, scl_hz, tol_pct, mode Sm|Fm|Fm+, kernel_clk_hz, scl_pin|sda_pin, `scl_not_in`, `sda_not_in`, open_drain,
`require_pins`), `clock` (sysclk_hz, hclk_hz, pclk1_hz, pclk2_hz, tim_clk_apb1_hz, tim_clk_apb2_hz, tol_pct; thêm `<khoá>_min_hz` / `<khoá>_max_hz` để chỉ đòi cận dưới/trên, vd `sysclk_min_hz: 150000000`). Nguyên tắc:
* Spec phải **chấp nhận mọi cách sửa xung đột hợp lệ** (vd chuyển SCL sang PC8 hoặc chuyển PWM sang chân khác), nên dùng ràng buộc phủ định (`*_not_in`) và `require_pins`, không ép một chân cụ thể
  nếu có phương án khác đúng. Ngược lại, lượt người dùng đã **chỉ định** chân nào thì có thể ép chân đó (vd PWM ở PA8).
* Cái gì mô phỏng không hiểu (`unmodeled`: dead-time, SPI, ADC...) thì KHÔNG được đưa vào spec — không bao giờ pass.
* Lượt người dùng không được dẫn tới nhiều cách đúng mà chỉ một cách nằm trong spec: người dùng là kịch bản cố định, không đọc câu trả lời của trợ lý.

## 5. Quy ước đề (D20/D25) — `verify_tasks` kiểm
Lượt 1 chứa: `CMSIS`, `HAL` (cấm HAL/LL), `Initial state`, `C code block`, và nêu VDD của bo. Lượt cuối chứa `complete` và `C code block` (đòi chương trình khởi tạo hoàn chỉnh trong MỘT khối code C
gồm `#include "stm32g4xx.h"`, `main()`, `while (1)`). Trạng thái khởi đầu phải khớp `expected.initial` (và `hse_hz`). Dùng đúng tên macro của `stm32g4xx.h` ST (xem code mẫu trong C3/C4-001;
không `CCMR1_Output`, không tên theo thể hiện như `I2C3_CR1_PE`).

## 6. Lời giải tham chiếu và biến thể sai
* `reference_solution.turns`: câu trả lời tham chiếu từng lượt (văn bản + code). **Lượt gây xung đột phải nêu xung đột** (xem §3) rồi sửa; lượt cuối là chương trình hoàn chỉnh PASS `final_state` và biên dịch được.
* `wrong_variants` — mỗi task ≥ 1 biến thể `grader: final_state` (lỗi cấu hình kinh điển: giữ chức năng ở chân xung đột, quên bật clock cổng, sai tần số...) và ≥ 1 `grader: conflict_detected`
  (không nêu xung đột → `conflict_missed:<họ>`; nêu muộn → `conflict_late:<họ>`; khuyên nối trực tiếp → `must_not:unsafe_connection`). Mỗi biến thể là danh sách `edits` {turn (0-based, mặc định lượt cuối),
  find (xuất hiện NGUYÊN VĂN trong câu trả lời đó), replace}; `expect` liệt kê mã lỗi bắt buộc có (dạng `fail_code`: `sim_violation:SIM-TIM-MOE`, `wrong_scl`, `forbidden_pin_used`, `conflict_missed:PIN_CONFLICT`...).
* Mọi giá trị kỳ vọng phải **tính tay** và đối chiếu PDF (D19); số liệu thanh ghi/AF lấy từ RM0440 / DS12288 (trích dẫn trang trong `reference_calc`). Đừng chép kết quả từ simulator.

## 7. Công cụ
* Kiểm: `eval/.venv/bin/python -m eval.tools.verify_tasks --categories C4` (chạy từ gốc dự án; kiểm mọi file trong `eval/tasks/C4/`). Phải ra "0 vấn đề".
* Tra bảng AF: `sqlite3 -readonly agent/data/hw_specs.sqlite "select pin,af,signal from pin_functions where chip='stm32g474' and pin='PA8'"`; chân có trong gói: cột `pins.packages` (JSON; "-" = không có chân ở gói đó);
  loại chân: `pins.io_structure` (TT_* không chịu 5 V; FT_* chịu 5 V), `pins.is_5v_tolerant`. DB là nguồn tra cứu; **bằng chứng** vẫn phải là snippet nguyên văn trên trang PDF
  (`GradeContext.load().page_text("STM32G474_Datasheet", 73)`; datasheet = `STM32G474_Datasheet`, RM = `STM32G474_RM0440`).
* Thử nhanh một đoạn code: `eval.sandbox.load()` → `.codeparse.analyze_c_code(code)` rồi `.sim.simulate_register_writes("stm32g474", ops, initial=preset, hse_hz=...)` (chỉ để DEBUG lời giải; không dùng làm nguồn giá trị kỳ vọng).

## 8. Không làm
Không sửa `agent/`, `eval/graders/`, `eval/vendor/`, `eval/tools/verify_tasks.py`, `snapshots/`, task nhóm khác, `eval/results/`. Nếu grader/simulator/bộ nhận diện có vẻ SAI hoặc thiếu (vd một câu trả lời đúng bị chấm trượt), **ghi lại** trong báo cáo
(tên task, bằng chứng) thay vì tự sửa hay "chiều" nó. Không đọc `agent/.env`. Không gọi LLM.

## 9. Bổ sung sau review độc lập (2026-10-23)
* **Spec không được chọn hộ hướng sửa.** Khi lượt người dùng chỉ định cụ thể chân cho cả hai chức năng xung đột (C4-010: PWM ở PB6/PB7 rồi USART1 ở PB6/PB7), spec phải đối xứng: dùng PWM `any_pin: true` + `signal: TIM4_CH1` (giữ ràng buộc kênh ↔ duty) và UART không ràng buộc chân, hoặc đề nêu dữ kiện phần cứng khiến chỉ một hướng khả thi (C4-012: "USART2 của bo thuộc mạch RS-485 nên console phải dùng USART1"). Ghi cách sửa hợp lệ khác vào `valid_variants` để `verify_tasks` kiểm.
* **Chỉ ràng buộc cái người dùng đã ràng buộc.** C4-014 trước đây ép `tx_pin: PC4` dù lượt 1 chỉ nói về RX; bỏ đi, vì TX+RX cùng sang PA9/PA10 cũng hợp lệ.
* **Spec clock phải giữ yêu cầu số liệu của đề.** C4-005: lượt 1 yêu cầu SYSCLK = 170 MHz nên spec là 170 MHz ±0,1 % (không phải dải [150; 170] MHz làm lọt lời giải lặng lẽ hạ xuống 150 MHz). Dải `*_min_hz/_max_hz` chỉ dùng khi cả hai cách sửa (giữ R1MODE hạ clock / bỏ R1MODE giữ clock) đều hợp lệ (C4-006, 015).
* **Không nêu gói chân (LQFP64...) trong lời giải tham chiếu nếu đề không nêu.** Chân PB8 là BOOT0: nếu dùng làm SCL phải kèm cảnh báo (C4-002).
* **Khoá spec/`must_detect`/`must_not` được kiểm khi nạp task** (`eval.schema.SPEC_KEYS`, `CONFLICT_FAMILIES`): gõ nhầm khoá là lỗi, không còn bị bỏ qua.
* Biến thể đáng có cho mọi task nhiều lượt: "lượt sau ghi đè thanh ghi của lượt trước bằng `=`" (C4-001, 008).
