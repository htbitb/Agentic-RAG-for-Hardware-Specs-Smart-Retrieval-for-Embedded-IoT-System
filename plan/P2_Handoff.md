# P2 HANDOFF — Hardware model và Sandbox (W3) + task C3

> Tài liệu này là **brief độc lập** cho một Claude Code session mới. Đọc hết trước khi làm.
> Tham chiếu: `plan/AgenticUpgradePlan.md` §4 W3, §7.3 (C3), §7.5 (grader `functional_sim`, `compile`), §8 dòng P2;
> `plan/DECISIONS.md` (**D19, D20, D21, D22 là ràng buộc của P2**; D05 chống rò rỉ vẫn áp dụng);
> kết quả trước: `eval/results/dev_baseline/report.md`, `plan/P1_data_quality.md`, ledger `plan/P1_progress.md`, `eval/README.md`.
> Thư mục làm việc: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project` (gốc dự án). Không phải git repo.

---

## 1. Mục tiêu P2

Cho agent (từ P4) khả năng **chạy thử sản phẩm của chính mình**: mô phỏng chuỗi ghi thanh ghi và nhận lỗi vật lý cụ thể
("ghi TIM1_PSC khi clock TIM1 đang tắt", "BDTR.MOE = 0 nên OC1 bị khoá"). Đồng thời dựng **grader `functional_sim`** và **task C3**
để chấm code của **mọi hệ** theo cùng một tiêu chuẩn.

**Tiêu chí thoát P2:**
1. `agent/hwmodel/` + MCP server `hw-sandbox` với 4 tool: `solve_timer_config`, `simulate_register_writes`, `analyze_c_code`, `compile_check`.
2. Golden tests pass, bao gồm **mọi lỗi kinh điển** ở §3 Bước 3 bị bắt với đúng mã lỗi.
3. Grader `functional_sim` + `compile` trong `eval/`, dùng **bản đóng băng** `eval/vendor/hwmodel/` (D19).
4. 20 task C3 có **lời giải tham chiếu** đã kiểm bằng tính tay độc lập; split dev/test.
5. Baseline C3 trên `dev` (3 seed) cho S0, S1, S2, S2D trong `eval/results/dev_baseline/report.md`.

**Ngoài phạm vi (KHÔNG làm):** sửa vòng lặp ReAct, verifier, guardrail, prompt hệ thống của agent (P4); Board State (P3).
**Không đăng ký tool `hw-sandbox` vào agent dùng cho S2D** — S2D là snapshot đóng băng của P1; tool sandbox chỉ được agent dùng từ P4.
Vẫn chạy được server `hw-sandbox` độc lập (stdio + inproc) và có test.

---

## 2. Bối cảnh cần biết

- **Dữ liệu P1** (`agent/data/hw_specs.sqlite`): bảng `peripherals`, `registers` (offset, address, size, access, `reset_value`
  của SVD + giá trị manual khi khác, `reserved_mask`, `rw_mask`, `svd_only`), `fields`, `enum_values`, `pins`, `pin_functions`
  (chip, pin, af, signal, peripheral), `clock_limits`, `electrical_limits`. Truy vấn qua `agent/mcp_servers/hw_queries.py`.
  **SVD có lỗi đã biết** (P1 ledger): vd `FLASH_ACR` reset 0x600 (RM: 0x0004 0601), SPI2/3/4 CR1/CR2 đảo reset, `TIM4_DTR2` không
  tồn tại, `TIMx_ARR` SVD 16 bit trong khi RM mô tả 20 bit (dithering). Simulator phải dùng **giá trị manual khi có**, và test bao các ca này.
- **Toolchain:** có `clang` (Apple). Đã thử: `clang --target=thumbv7em-none-eabi -mcpu=cortex-m4 -ffreestanding -fsyntax-only -Wall
  -Werror=implicit` chạy được với header tự sinh có `#include <stdint.h>`; `clang -E` dùng được để tiền xử lý. **Không có**
  `arm-none-eabi-gcc` — không cần cài.
- **Agent venv:** `agent/.venv` (Python 3.11). Thêm `pycparser` vào `agent/requirements.txt` nếu dùng.
- **Eval:** grader hiện có ở `eval/graders/`; `Task` schema ở `eval/schema.py` (thêm `functional_sim`, `compile` vào `GRADERS`;
  `functional_sim` là grader **gating**, `compile` là chỉ số báo cáo riêng). Lệnh chạy/giới hạn tốc độ: `eval/README.md`.
  Khoá Gemini miễn phí: 15 RPM, 500 request/ngày → dùng `--llm-rpm 12`, gặp `fatal:` quota thì hôm sau `--resume`.
- **Dữ kiện mẫu đã biết đúng** (dùng cho golden test): TIM1 ở 170 MHz, PWM 20 kHz → `PSC=0, ARR=8499 (0x2133)`, duty 25% →
  `CCR1=2125`. Quy tắc STM32: nếu prescaler APBx ≠ 1 thì TIMxCLK = 2 × PCLKx. TIM1 là advanced timer → cần `BDTR.MOE=1`.
  PA8 AF6 = TIM1_CH1 (datasheet Table 13). Phải tự kiểm lại trên PDF trước khi dùng làm golden.

---

## 3. Công việc

### Bước 0 — Chuẩn bị
1. Đọc `plan/DECISIONS.md` (đặc biệt D19–D22). Tạo ledger `plan/P2_progress.md` (Task / Ruling / chi phí nếu sai).
2. **D22:** thêm cơ chế tắt nạp `.env` khi chạy test agent (vd `AGENT_DOTENV=0` đặt trong `agent/tests/conftest.py`; `config.py`
   tôn trọng biến này) + test khẳng định `pytest agent/tests` không mở kết nối mạng (monkeypatch socket). Không đổi hành vi khi chạy thật.

### Bước 1 — Lớp thanh ghi chung `agent/hwmodel/regmap.py` (cả 3 chip)
- Nạp memory map từ `hw_specs.sqlite`: mỗi thanh ghi có địa chỉ, kích thước, reset (ưu tiên giá trị manual), `rw_mask`, `reserved_mask`,
  access của từng field (RO/WO/RW, **W1C**/`oneToClear`, read-to-clear nếu SVD có).
- Ghi: áp mặt nạ access; ghi vào bit reserved → vi phạm `SIM-RESERVED` (warning); ghi địa chỉ không tồn tại → `SIM-BADADDR` (error);
  ghi thanh ghi RO → `SIM-RO` (warning, không đổi giá trị). Hỗ trợ op `write`, `set_bits` (`|=`), `clear_bits` (`&= ~`), `modify`, `read`.
- Thanh ghi `svd_only=1` vẫn mô phỏng được nhưng kèm cảnh báo `SIM-SVDONLY`.

### Bước 2 — Lớp ngữ nghĩa STM32G474 (`agent/hwmodel/periph/{rcc,gpio,tim,usart,i2c}.py`, `clock_tree.py`)
- **RCC:** cổng clock `AHBxENR/APBxENR`; ghi vào thanh ghi của peripheral đang tắt clock → `SIM-CLK-GATE` (error, lệnh ghi **bị bỏ qua**
  như phần cứng thật). Cây clock: HSI16/HSE/PLL (PLLM/N/R, nguồn) → SYSCLK → AHB/APB1/APB2 prescaler → PCLK, TIMxCLK (quy tắc ×2).
  Kiểm giới hạn từ `clock_limits` (SYSCLK, dải VCO, PLL input) → `SIM-CLK-LIMIT`. Không mô phỏng thời gian chờ ready: coi `*RDY` lên
  ngay khi bật (ghi rõ là giả định).
- **GPIO:** `MODER`, `AFRL/AFRH`, `OTYPER`, `PUPDR`, `OSPEEDR` → chức năng thực tế của chân; AF tra bảng `pin_functions` của P1.
  Chân ở AF mode nhưng AF không thuộc tín hiệu mong muốn → effect phản ánh đúng tín hiệu thực tế (grader sẽ bắt).
- **TIM (TIM1/8/20 advanced, TIM2–5 general, TIM15–17):** `PSC`, `ARR`, `CCRx`, `CCMRx.OCxM` (PWM mode 1/2), `CCER.CCxE/CCxP`,
  `BDTR.MOE` (advanced), `CR1.CEN`, `EGR.UG`, preload (`ARPE`, `OCxPE`) → effect `{pin, signal, pwm_hz, duty_pct, active, reason}`.
  Khi không có xung: `active=false` + lý do cụ thể (`SIM-TIM-MOE`, `SIM-TIM-CEN`, `SIM-TIM-CCE`, `SIM-TIM-OCM`, `SIM-GPIO-AF`, ...).
- **USART:** `BRR`, `OVER8`, `CR1.UE/TE/RE`, nguồn clock (`RCC_CCIPR.USARTxSEL`) → `baud`, sai số %.
- **I2C:** `TIMINGR` (PRESC, SCLL, SCLH, SDADEL, SCLDEL) + nguồn clock → f_SCL xấp xỉ (công thức RM, ghi rõ bỏ qua thời gian sườn/
  bộ lọc nếu có) → effect `{instance, scl_hz}`.
- Mọi thứ khác → liệt kê trong `unmodeled` (D21). **Nguyên tắc: `unmodeled` không bao giờ được tính là pass.**

### Bước 3 — Golden tests (`agent/tests/test_hwmodel_*.py`) — viết TRƯỚC khi cài đặt ngữ nghĩa
- Chuỗi khởi tạo PWM TIM1_CH1 trên PA8 đúng chuẩn (theo trình tự trong RM0440, ghi trang) → effect 20 kHz / 25%.
- Mỗi lỗi kinh điển phải bị bắt với **đúng mã**: quên bật clock TIM1 (`SIM-CLK-GATE`); quên bật clock GPIOA; quên `MOE`; quên `CEN`;
  quên `CC1E`; sai AF (vd AF2 thay vì AF6 trên PA8); MODER không phải AF; sai thứ tự dịch bit (`<< 4` thay vì `<< 0` cho AFRH chân 8);
  PSC lệch 1 (`PSC=1` → 10 kHz); quên quy tắc ×2 khi APB2 prescaler ≠ 1; ghi bit reserved; ghi vào địa chỉ không tồn tại.
- USART: BRR cho 115200 ở 170 MHz (OVER8=0) — tính tay, ghi lại phép tính. I2C: một giá trị TIMINGR có trong RM (bảng ví dụ) → f_SCL.
- Clock tree: cấu hình PLL HSI16 → 170 MHz (Range 1 boost) và một cấu hình vượt giới hạn → `SIM-CLK-LIMIT`.
- **Mọi giá trị kỳ vọng tính tay hoặc lấy từ RM có trang**, không lấy từ chính simulator.

### Bước 4 — Solver và phân tích code
- `solve_timer_config(chip, timer, target_hz, duty_pct, channel, clock_state?)`: liệt kê (PSC, ARR), chọn sai số nhỏ nhất rồi độ phân giải
  duty lớn nhất; trả `CCR`, sai số, độ phân giải; tôn trọng ARR 16/32 bit theo timer.
- `ingestion/header_gen.py`: sinh header CMSIS-style từ SVD/DB (struct theo peripheral với padding đúng offset, macro instance
  `TIM1`, `*_Pos`/`*_Msk`/tên bit như `RCC_APB2ENR_TIM1EN`). Test: `offsetof` khớp offset DB trên mẫu thanh ghi; một đoạn code CMSIS
  chuẩn biên dịch được bằng `compile_check`.
- `analyze_c_code(code, chip)`: `clang -E` với header sinh → `pycparser` (hoặc parser tự viết cho tập con) → danh sách `ops`
  (`write/set_bits/clear_bits/modify`) theo thứ tự. Hỗ trợ: gán, `|=`, `&= ~`, biểu thức hằng với macro/dịch bit, `AFR[1]`,
  read-modify-write nhiều dòng, hàm `main`/init gọi nhau tuyến tính. Cấu trúc không hỗ trợ (vòng lặp phụ thuộc dữ liệu, HAL/LL, con trỏ
  động) → lỗi có kiểu `unsupported_construct` kèm dòng — **không đoán**. Vòng chờ `while(!(RCC->CR & RCC_CR_PLLRDY));` được bỏ qua
  hợp lệ (ghi rõ).
- `compile_check(code, chip)`: clang ARM như §2; trả `ok | errors[] | skipped` (`skipped` không bao giờ là pass).

### Bước 5 — MCP server `agent/mcp_servers/hw_sandbox_server.py`
4 tool trên, quyền `sandboxed-exec` (thêm vào `PERMISSIONS`), giới hạn kích thước code/ops, timeout. Chạy được inproc và stdio.
**Chưa** đưa vào danh sách server của agent dùng cho eval (xem §1).

### Bước 6 — Grader và task C3 (eval)
1. Đóng băng: copy `agent/hwmodel/` (+ header_gen, dữ liệu cần thiết hoặc đường dẫn tới `snapshots/agent_p1/data` với hash) →
   `eval/vendor/hwmodel/` + `VENDOR.md` (nguồn, ngày, sha256). Manifest eval ghi `hwmodel_vendor_sha256`. Grader **chỉ** import bản vendor.
2. `eval/graders/functional_sim.py`: trích khối code C từ câu trả lời (code fence; nhiều khối → nối theo thứ tự) → `analyze_c_code` →
   `simulate_register_writes(initial=<preset của task>)` → so `effects` với `expected.spec` (dung sai `tol_pct`). Lý do trượt có mã:
   `no_code`, `unsupported_construct`, `sim_violation:<code>`, `wrong_freq`, `wrong_duty`, `wrong_pin`, `inactive:<reason>`, `unmodeled`.
   `eval/graders/compile.py`: báo cáo riêng (`ok/fail/skipped`), không gate TSR.
3. **Task C3** (`eval/tasks/C3/c3_curated.yaml`, 20 task, ~30% dev): PWM (nhiều timer/chân/tần số, có ca cần ×2 APB, có ca advanced
   timer), UART baud, I2C f_SCL, PLL/SYSCLK (cấu hình cây clock tới tần số đích trong giới hạn), kết hợp (PWM + đổi chân theo AF).
   - **D20:** mỗi đề nêu rõ "bare-metal C, CMSIS register access (vd `TIM1->PSC = ...`), không HAL/LL", nêu trạng thái khởi đầu
     (`initial` preset, vd `sysclk_170mhz_pll_hsi16_apb_div1`) và yêu cầu "trả lời kèm một khối code C hoàn chỉnh".
   - `expected.spec`: chức năng (pin/signal/Hz/duty/baud/scl_hz + `tol_pct`), **không** giá trị thanh ghi.
   - `provenance.reference_solution`: code tham chiếu + **phép tính tay** (công thức, trang RM) chứng minh nó đạt spec, độc lập với simulator.
   - Test: mọi lời giải tham chiếu pass `functional_sim`; với mỗi task có ≥ 1 biến thể sai kinh điển bị trượt đúng mã.
4. **Review độc lập** (subagent khác, ngữ cảnh mới): kiểm từng task C3 — đề rõ ràng, spec khả thi, phép tính tay đúng, lời giải tham chiếu
   đúng theo RM. Lưu `plan/reviews/review_C3.md`; áp dụng sửa trước khi chạy hệ nào.
5. `verify_tasks` mở rộng cho C3 (lời giải tham chiếu pass, có phép tính tay); cập nhật `INDEX.md` (`make_index`).

### Bước 7 — Baseline C3
1. `eval.run --resume eval/results/dev_baseline --systems S0,S1,S2,S2D --split dev --categories C3 --seeds 3 --cache record`
   (thử `--limit 2` trước). Ước tính chi phí < 0.1 USD; hỏi người dùng nếu > 2 USD.
2. `eval.score` + `eval.report`; report có cột C3, mục `compile` riêng, và phân loại lỗi C3 theo mã.
3. Dự đoán (để kiểm, **không** để vá): S2D có thể trượt C3 vì verifier V1 từ chối giá trị dẫn xuất (đã biết từ trước P0). Nếu đúng như vậy,
   ghi bằng chứng từ trace — đó là động lực cho P4, **không** sửa verifier ở P2.

---

## 4. Quy tắc làm việc

- **D05 chống rò rỉ:** không đọc task split `test` của C1/C2/C6–C8; không vá agent theo task. Task C3 do chính session này viết nên được đọc,
  nhưng **không** dùng task C3 test để chỉnh simulator — golden test lấy từ RM và tính tay.
- **D19:** giá trị kỳ vọng của golden test và của task C3 **không** được sinh bằng chính simulator.
- **Không sửa:** `snapshots/agent_v1/`, `snapshots/agent_p1/`, run cũ trong `eval/results/dev_baseline/runs.jsonl`, ground truth
  C1/C2/C6–C8. Không sinh lại C1 từ generator.
- **Bảo mật:** không in/ghi key; `.env` không vào snapshot/kết quả/vendor. Code trong câu trả lời của hệ là **dữ liệu không tin cậy**:
  chỉ tiền xử lý/parse/compile `-fsyntax-only`, **không bao giờ chạy**; `clang -E` chỉ với include path là header tự sinh (chặn
  `#include` tuyệt đối/ra ngoài thư mục tạm).
- **TDD**; mọi quyết định có ảnh hưởng ghi vào `plan/P2_progress.md` dạng "Ruling" (kèm chi phí nếu sai).
- **Hỏi người dùng khi:** chi phí ước tính > 2 USD; cần cài phần mềm hệ thống; mâu thuẫn với `AgenticUpgradePlan.md`/`DECISIONS.md`;
  định thay đổi vòng lặp/verifier/guardrail/prompt của agent.

---

## 5. Checklist nghiệm thu P2

- [ ] D22: test agent không gọi mạng; `pytest agent/tests` xanh
- [ ] `hwmodel` lớp chung (3 chip) + ngữ nghĩa STM32G474 (RCC, clock tree, GPIO, TIM, USART, I2C); `unmodeled` trung thực
- [ ] Golden tests: chuỗi PWM chuẩn + toàn bộ lỗi kinh điển ở Bước 3 bắt đúng mã; giá trị kỳ vọng có nguồn (trang RM / tính tay)
- [ ] `solve_timer_config`, `header_gen`, `analyze_c_code`, `compile_check` + server `hw-sandbox` (inproc + stdio)
- [ ] `eval/vendor/hwmodel/` + `VENDOR.md` + hash trong manifest; grader `functional_sim`, `compile` + test
- [ ] 20 task C3 có lời giải tham chiếu + tính tay; `plan/reviews/review_C3.md` đã áp dụng; `verify_tasks` 0 vấn đề
- [ ] Baseline C3 dev × {S0, S1, S2, S2D} × 3 seed trong report
- [ ] `pytest eval/tests` xanh; smoke replay vẫn chạy, 0 cache-miss
- [ ] `plan/P2_progress.md` đầy đủ Ruling

## 6. Báo cáo khi kết thúc session

Tóm tắt: đã làm gì; phạm vi mô hình hoá (cái gì modeled / unmodeled); kết quả golden test; tỷ lệ code của các hệ phân tích được
(`analyze_c_code` thành công / tổng); bảng TSR C3 (+ compile) cho S0/S1/S2/S2D với phân loại lỗi; chi phí thực tế; điểm lệch khỏi brief;
các Ruling (kèm chi phí nếu sai); vấn đề mở cho P3 (Board State) và P4 (runtime, verifier).
