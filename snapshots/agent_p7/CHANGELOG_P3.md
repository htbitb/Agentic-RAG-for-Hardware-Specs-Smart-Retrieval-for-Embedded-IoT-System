# CHANGELOG P3 — Board State, DRC và server `board-state` (W2)

Phạm vi: bản sao số của bo mạch (event-sourced), bộ luật thiết kế DRC, MCP server `board-state`.
**Không** đổi vòng lặp ReAct, verifier, guardrail, prompt hệ thống (P4). **Không** đăng ký `board-state` (cũng như `hw-sandbox`) vào `ToolHub.SERVERS` (S2D là snapshot P1; P4 mới dùng).

## Thêm
- `hwmodel/board_state.py` — Board State event-sourced: bảng `events(project_id, version, ts, actor, type, payload_json)` (trigger chặn UPDATE/DELETE), trạng thái = fold thuần các sự kiện
  (`fold`/`history`, không DB, không đồng hồ), `snapshot(v)`, `diff(a, b)`, `rollback(v)` = sự kiện `rolled_back` mới (lịch sử còn nguyên), optimistic concurrency (`expected_version`).
  Mười loại sự kiện: `target_set, requirements_set, pin_allocated, pin_released, clock_configured, device_added, net_connected, decision_recorded, artifact_recorded, rolled_back`.
  DB: env `BOARD_STATE_DB` (mặc định `data/board_state.sqlite`, `config.BOARD_STATE_DB`).
- `hwmodel/drc.py` — 8 luật xác định (`DRC-PIN-01/02/03`, `DRC-CLK-01/02`, `DRC-ELEC-01`, `DRC-PWR-01`, `DRC-REQ-01`); mức `error | warning | unknown` (thiếu số liệu ⇒ `unknown`, không bao giờ pass);
  `evaluate_clock_config` (tái dùng `Simulator`/`clock_tree`: tần số dẫn xuất + `CLOCK_LIMIT:*`), `evaluate_net` (mức logic, `LEVEL_MISMATCH:*`, `NOT_5V_TOLERANT:<pin>`), `power_budget`,
  `Catalog` (bảng AF, gói, phương án thay thế). Module chỉ dành cho agent (`eval.tools.freeze_hwmodel.AGENT_ONLY`, không đóng băng cho grader).
- `mcp_servers/board_state_server.py` — 13 tool: `get_board_state, set_target, set_requirements, allocate_pin, release_pin, set_clock_config, add_device, connect, get_power_budget, run_drc,
  record_decision, diff, rollback`; mọi tool nhận `project_id` tuỳ chọn. Phản hồi có cấu trúc: `{"ok", ...}` / `{"ok": false, "error": {"code", "message", ...}}` kèm phương án thay thế
  (`CONFLICT`, `NO_SUCH_AF`, `INPUT_ONLY`, `NO_SUCH_PIN`, `PIN_NOT_IN_PACKAGE`, `SHARED_NOT_BUS`, `LEVEL_MISMATCH:*`, `NOT_5V_TOLERANT:*`...). `allocate_pin`/`connect` vi phạm bị từ chối (không ghi sự kiện);
  `set_clock_config` được ghi kèm vi phạm.
- `agent/tools.py::PERMISSIONS`: 9 tool ghi = `state-mutating`, 4 tool đọc (`get_board_state, get_power_budget, run_drc, diff`) = `read-only`.
- `mcp_servers/hw_queries.py`: `HwStore.chip_logic_levels(chip, vdd, io_structure)` (VIH/VIL/VOH/VOL và điện áp vào tối đa theo loại chân, kèm trang) dùng chung cho `check_logic_level_compatibility`,
  `connect` và DRC; sửa `_pin_type_applies` (hàng "FT_c" không còn áp cho mọi chân FT_*; công thức `MIN(MIN(VDD,VDDA)+3,6; 5,5)` của Table 17).

## Sửa sau review mã độc lập (23/10)
Báo cáo `p3-code-reviewer` (8 Important, 15 Minor); phần agent đã sửa theo TDD (test đỏ trước, mutation-check 25 mutant đều bị giết). Mục 5 của báo cáo (vòng retry áp cho tool `state-mutating` ở `agent/agent/tools.py`) **hoãn sang P4**: đó là vòng lặp agent, ngoài phạm vi P3; khi P4 đăng ký `board-state` phải tắt retry cho quyền `state-mutating` (hoặc thêm khoá idempotent), nếu không một timeout sau khi đã ghi sẽ nhân đôi sự kiện.
- **Không crash khi dữ liệu xấu** (mục 1, 2, 12): `set_requirements` kiểm kiểu mọi trường lồng (`drc.validate_requirement`: `pin` chuỗi, `pins` list chuỗi, số hữu hạn không phải bool, `*_pct` 0–100, `*_hz`/`baud` > 0, `type` thuộc tập đã biết, `power` bắt buộc `mode` + `budget_ua` > 0) và **từ chối cả lời gọi** (`INVALID_REQUIREMENT` + `problems`, không ghi nửa chừng). DRC chịu log cũ có dữ liệu xấu: `REQ_INVALID:<id>` (unknown), `POWER_BUDGET_MISSING:<mode>` (unknown), và `run_drc` bọc từng luật — luật ném ngoại lệ thành `DRC_INTERNAL_ERROR:<luật>` (unknown, không bao giờ pass). `set_clock_config` với `hse_hz` nan/inf, `pll` sai kiểu, `ahb_div`/`voltage_range` là list, `enabled_peripherals` sai kiểu → `INVALID_CLOCK_CONFIG`, không ghi. `diff(None, None)` giờ là `INVALID_ARGUMENT` (trước đây trả diff rỗng).
- **DRC-PIN-03 / allocate_pin** (mục 3): tín hiệu hướng vào (RX, MISO, ADC...) lưu `mode = AF_IN`; tín hiệu chưa rõ hướng trên chân chỉ-nhập lưu `mode = null` → `INPUT_ONLY_UNVERIFIED` (unknown) thay vì `INPUT_ONLY` oan (ESP32 GPIO34 + U1RXD hợp lệ).
- **DRC-CLK-01** (mục 4): số chu kỳ chờ Flash ghi `max(latency, WS cần cho HSI16 16 MHz)` TRƯỚC khi đổi nguồn và hạ về `latency` SAU (RM0440 p.98) ⇒ HSE 8 MHz Range 2 (0 WS) và HSI16 ÷2/÷4 Range 2 không còn báo `CLOCK_LIMIT:FLASH_WS` oan; latency thấp hơn nhu cầu của HCLK cuối vẫn bị bắt.
- **Mức logic / ADC** (mục 9, 16): hàng "other pins" (NRST, PG10) của Table 14 nay áp đúng (4,0 V; trước đó không bao giờ khớp ⇒ 5 V vào PG10 qua PASS); thiếu giới hạn vào ⇒ `NET_INPUT_MAX_UNKNOWN` (unknown) và `connect` trả `LEVEL_DATA_UNKNOWN`, không PASS; `connect(kind=analog)` tới chân có kênh ADC: tín hiệu > 3,6 V (VDDA tối đa, Table 17 p.84) ⇒ `ADC_RANGE:<pin>`, trong (VDD, 3,6 V] ⇒ `ADC_RANGE_UNVERIFIED` (VDDA/VREF+ không có trong Board State), ≤ VDD ⇒ PASS kèm giả định "VDDA/VREF+ = VDD"; chân FT nhận > VDD + 0,3 V có ghi chú tắt pull-up/pull-down nội (Table 17 p.84).
- **Tên chân** (mục 10): `drc.norm_pin` (bỏ khoảng trắng, viết hoa, bỏ tiền tố `<chip>.` của target đã khai báo) dùng cho mọi chân trong requirement: `pa8`, ` PA8 `, `stm32g474.PA8` đều va chạm đúng với PA8 đã cấp; tiền tố lạ không bị cắt âm thầm.
- **Nhập số** (mục 11): `set_target` (vdd hữu hạn trong (0, 60], package chuỗi) và `add_device` (mọi số hữu hạn; dòng ≥ 0; `vin_max`, `io_vdd` > 0) từ chối nan/inf/âm/bool.
- **Event store** (mục 13, 14): trigger `events_no_replace` chặn `INSERT OR REPLACE`/`REPLACE INTO` ghi đè sự kiện (tự thêm khi mở DB cũ); `append` kiểm hình dạng payload từng loại sự kiện và **chạy thử `apply_event`** trên log hiện có trong cùng giao dịch ⇒ `rolled_back` tới version chưa có, `pin_released` thiếu `pin`... bị `ValueError`, log không bao giờ chứa sự kiện không phát lại được; payload không phải JSON hợp lệ (NaN) bị từ chối.
- **Các lỗ hở rẻ** (mục 15): `project_id` toàn khoảng trắng / không phải chuỗi → `INVALID_PROJECT_ID` (chuỗi rỗng vẫn nghĩa là "mặc định"); cùng tín hiệu ngoại vi lên hai chân khác nhau của STM32 → `SIGNAL_ALREADY_ROUTED` (kèm chân hiện tại; ESP32/nRF có GPIO matrix và tín hiệu GPIO chung được miễn); cấp lại cùng chân với `mode` khác không còn trả `unchanged`; `add_device` từ chối id trùng tên chip hoặc chỉ khác hoa/thường id có sẵn; mô tả `set_requirements` nêu khoá `shared`.

## Chạy
- Test: `agent/.venv/bin/python -m pytest agent/tests` (gồm `test_board_state`, `test_drc`, `test_board_state_server` — có stdio thật và kịch bản D2).
- Server stdio: `cd agent && BOARD_STATE_DB=/tmp/bs.sqlite .venv/bin/python -m mcp_servers.board_state_server`.

## Hạn chế đã biết
- (review mục 15, không sửa) Chủ B có thể chia sẻ chân bus của chủ A dù A không khai báo `shared` (Board State không lưu cờ `shared` của chủ gốc; thêm cờ đổi hình dạng bản ghi chân); `release_pin` xoá hết người chia sẻ (không có tham số chủ); tín hiệu bịa trên ESP32/nRF (`FOO_BAR`) được nhận là `routable` vì chip không có bảng AF cố định.
- (review mục 5, hoãn P4) vòng retry của `ToolHub` áp cả tool `state-mutating`: khi đăng ký `board-state` cần tắt retry cho quyền này.
- DB P1 không có dòng tiêu thụ của STM32G474 ⇒ DRC-PWR-01 cho `unknown` với chip này (ESP32 có dòng `power_consumption`; chỉ dùng khi đúng MỘT dòng khớp chế độ).
- Thiết bị ngoài không khai báo ngưỡng logic được GIẢ ĐỊNH CMOS (0,7/0,3·VDDIO, VOH ≥ VDDIO−0,4 V, VOL ≤ 0,4 V, vào tối đa VDDIO+0,3 V) và giả định được báo trong kết quả.
- Cây clock chỉ cho STM32G474 (D21). Không có tool gỡ kết nối (đúng 13 tool theo brief): sửa net sai bằng `rollback`.
