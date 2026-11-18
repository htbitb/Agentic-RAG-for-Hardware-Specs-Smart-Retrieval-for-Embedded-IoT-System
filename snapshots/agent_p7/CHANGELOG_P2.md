# CHANGELOG P2 — Hardware model và Sandbox (W3)

Phạm vi: gói `hwmodel/` (mô hình thanh ghi + ngữ nghĩa STM32G474), solver, phân tích mã C, header sinh từ SVD, compile check, MCP server `hw-sandbox`.
**Không** đổi vòng lặp ReAct, verifier, guardrail, prompt hệ thống (P4). **Không** đăng ký `hw-sandbox` vào `ToolHub.SERVERS` (S2D là snapshot P1; P4 mới dùng).

## Thêm
- `hwmodel/regmap.py` — lớp chung cho 3 chip từ `data/hw_specs.sqlite`: memory map (một địa chỉ = một thanh ghi; hai cách nhìn Input/Output của `TIMx_CCMRy` gộp),
  reset ưu tiên giá trị manual (`rm_reset_value`), mặt nạ access/reserved/W1C-oneToSet…, op `write | set_bits | clear_bits | toggle_bits | modify | rmw | read`,
  mã `SIM-BADADDR` (error), `SIM-RO`, `SIM-RESERVED`, `SIM-SVDONLY` (warning).
- `hwmodel/errata.py` — hiệu chỉnh SVD theo RM0440 (có trang): `ARR[19:0]`, TIM2/TIM5 là bộ đếm 32 bit, TIM3/4 `CCRx/CNT` 16 bit.
- `hwmodel/clock_tree.py`, `hwmodel/periph/{rcc,gpio,tim,usart,i2c}.py`, `hwmodel/sim.py` — ngữ nghĩa STM32G474: cổng clock, cây clock + giới hạn (VCO, PLL-in, SYSCLK, wait state Flash,
  R1MODE/VOS), GPIO AF từ `pin_functions`, PWM (TIM1/8/20, TIM2–5, TIM15–17), baud USART, f_SCL I2C. Mã: `SIM-CLK-GATE`, `SIM-CLK-LIMIT`, `SIM-CLK-NOSRC`, `SIM-CLK-PROC` (warning),
  `SIM-FLASH-WS`, `SIM-RCC-LOCKED`, `SIM-WRITE-LOCKED` (ghi BRR/PRESC/CR1·CR2 cấu hình khi UE=1, TIMINGR khi PE=1 ⇒ lệnh ghi bị bỏ qua), `SIM-GPIO-AF`, `SIM-GPIO-MODE`, `SIM-TIM-{CEN,OCM,CCE,MOE,ARR0,RANGE}`, `SIM-USART-{UE,TXRX,BRR}`, `SIM-I2C-{PE,TIMING}`.
  Phần không mô hình hoá → `unmodeled` (không bao giờ là pass).
- `hwmodel/solver.py` — `solve_timer_config`.
- `hwmodel/header_gen.py` (+ lớp tương thích `ingestion/header_gen.py`) — header CMSIS-style sinh từ DB (offset khớp DB, macro `_Pos/_Msk`, tên trường GPIO kiểu ST, macro giá trị ST có trang RM).
- `hwmodel/compile_check.py` — clang ARM `-fsyntax-only`; `hwmodel/codeparse.py` — `analyze_c_code` (clang -E + pycparser + thông dịch trừu tượng).
- `mcp_servers/hw_sandbox_server.py` — 4 tool, quyền `sandboxed-exec` (`agent/tools.py::PERMISSIONS`), giới hạn kích thước/thời gian.
- `ingestion/svd_attrs.py` + `data/svd_attrs.json` — `modifiedWriteValues`/`readAction` mức thanh ghi và danh sách ngắt từ SVD (DB P1 không lưu).
- `config.py`: `AGENT_DOTENV=0` tắt nạp `.env` (D22); `tests/conftest.py` ép khoá LLM rỗng và chặn socket ngoài loopback.
- `requirements.txt`: `pycparser>=3.0`.

## Chạy
- Test: `agent/.venv/bin/python -m pytest agent/tests` (gồm golden tests `test_hwmodel_golden_*`, `test_hwmodel_layout`, `test_hwmodel_codeparse`, `test_hw_sandbox_server`).
- Server stdio: `cd agent && .venv/bin/python -m mcp_servers.hw_sandbox_server`.
- Dựng lại sidecar: `cd agent && .venv/bin/python -m ingestion.svd_attrs`.
- Đóng băng cho grader (D19): `agent/.venv/bin/python -m eval.tools.freeze_hwmodel --reason "..." [--force]`; kiểm lệch `--check`.

## Hạn chế đã biết
- Mô hình chỉ cho STM32G474; ESP32/nRF chỉ có lớp chung. ADC, DMA, SPI, ngắt, GPIO ODR/BSRR, TIMx_SR (rc_w0), LPUART, dead-time, PWM canh giữa, dithering, one-pulse → `unmodeled`.
- Cờ RDY lên ngay lập tức; trạng thái ổn định của timer (shadow = preload).
- I2C: hiệu ứng báo dải `[scl_hz_slow, scl_hz]` (tSYNC 1000 ns … cực tiểu 4·tI2CCLK) và ước lượng `t_low_ns`/`t_high_ns`; không mô hình tr/tf thật, SCLDEL/SDADEL, clock stretching.
- USART: `CR2.SWAP/TXINV/RXINV/LINEN/CLKEN` ⇒ `unmodeled` (hiệu ứng `modeled=false`).
- Parser `analyze_c_code` không đọc lại giá trị thanh ghi (`if (REG & X)`, `CCR = REG + 1`) ⇒ `unsupported_construct`; không đoán.
- Không chấm các điều kiện vệ sinh phần cứng (trễ sau bật clock, ≥ 1 µs sau đổi HPRE, HSEBYP).
- SVD ST không khai báo `modifiedWriteValues`; cờ rc_w0 của TIMx_SR chưa được mô hình hoá.
