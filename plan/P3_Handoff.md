# P3 HANDOFF — Board State + DRC (W2) và task C4

> Tài liệu này là **brief độc lập** cho một Claude Code session mới. Đọc hết trước khi làm.
> Tham chiếu: `plan/AgenticUpgradePlan.md` §4 W2, §6 (D1, D2), §7.3 (C4), §7.4 (định dạng task), §7.5 (grader `final_state`,
> `conflict_detected`), §8 dòng P3; `plan/DECISIONS.md` (**D24, D25, D26 là ràng buộc mới**; D05, D19, D20, D21 vẫn áp dụng);
> kết quả trước: `eval/results/dev_baseline/report.md`, ledger `plan/P2_progress.md`, `eval/README.md` §8.
> Thư mục làm việc: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project` (gốc dự án). Không phải git repo.

---

## 1. Mục tiêu P3

Cho agent một **"thế giới" có trạng thái**: bản sao số của bo mạch (Board State, event-sourced) mà agent đọc/ghi qua tool, cùng
bộ **luật thiết kế (DRC)** trả lỗi có mã và **phương án thay thế**. Đây là nền cho tính chủ động (phát hiện xung đột mà người dùng
không nhắc) và trí nhớ dự án nhiều lượt. Đồng thời dựng **task C4** (thiết kế nhiều lượt có xung đột cài sẵn) và grader để đo mọi hệ.

**Tiêu chí thoát P3:**
1. `agent/hwmodel/drc.py` + MCP server `board-state` (tool ở §3 Bước 2), event log, `diff`, `rollback`; unit test cho **từng** luật DRC.
2. Kịch bản D2 (PA8 đã cấp cho PWM, sau đó xin I2C3_SCL) bị phát hiện `CONFLICT` kèm danh sách chân thay thế đúng theo bảng AF.
3. Grader `final_state` + `conflict_detected` (D25) trong `eval/`, bộ nhận diện xung đột có **precision/recall** trên tập hiệu chỉnh.
4. 15 task C4 (~30% dev) có lời giải tham chiếu cho từng lượt + review độc lập.
5. Baseline C4 dev × {S0, S1, S2, S2D} × 3 seed trong `eval/results/dev_baseline/report.md`.
6. Việc tồn đọng từ P2: bù 2 run thiếu; đối chiếu header ST chính thức (D24).

**Ngoài phạm vi (KHÔNG làm):** vòng lặp ReAct/runtime v3, `update_plan`, `finish` gate, sửa verifier/guardrail/prompt (P4);
HITL `ask_human`/SimulatedHuman (P5); policy engine (P6). **Không đăng ký `board-state` hay `hw-sandbox` vào agent dùng cho S2D**
(S2D = snapshot P1 đóng băng). Server chạy độc lập (inproc + stdio) và có test.

---

## 2. Bối cảnh cần biết

- **Dữ liệu P1** (`agent/data/hw_specs.sqlite`): `pins`, `pin_functions` (chip, pin, af, signal, peripheral, kind), `pin_flags`
  (input-only, FT/TT, strapping...), `electrical_limits`, `clock_limits`, `registers/fields`. Truy vấn qua `agent/mcp_servers/hw_queries.py`.
- **hwmodel P2** (`agent/hwmodel/`): `clock_tree.py` (dẫn xuất tần số + giới hạn), `periph/*`, `simulate_register_writes`,
  `analyze_c_code`, `compile_check`, `solve_timer_config`. **Tái dùng** cho `set_clock_config` và DRC-CLK — không viết lại.
  Bản đóng băng cho grader ở `eval/vendor/hwmodel/` (D19), kiểm bằng `freeze_hwmodel --check`.
- **Eval:** adapter S0/S1/S2/S2D đã hỗ trợ nhiều lượt (S0 giữ lịch sử chat; S1 gộp lịch sử vào khối QUESTION, truy hồi theo câu hiện tại;
  S2/S2D dùng episodic memory theo `session_id`). Grader `functional_sim` (gating) và `compile` (báo cáo) đã có. Task C3 ở
  `eval/tasks/C3/c3_curated.yaml` là mẫu định dạng đề CMSIS (D20) — đề C4 dùng cùng quy ước và cùng preset `initial`.
- **Khoá Gemini:** gói miễn phí 15 RPM, 500 request/ngày đã bị chạm hai lần. C4 nhiều lượt tốn nhiều lời gọi (S2/S2D nhiều lời gọi mỗi lượt).
  Xem D26: nếu người dùng chưa bật thanh toán, runner dừng `fatal:` khi hết quota → `--resume` hôm sau. **Ước tính trước khi chạy.**

---

## 3. Công việc

### Bước 0 — Chuẩn bị và tồn đọng
1. Đọc `plan/DECISIONS.md` (D23–D26). Tạo ledger `plan/P3_progress.md`.
2. **Bù 2 run P2:** `eval.run --resume eval/results/dev_baseline --systems S2D --split dev --categories C3 --seeds 3 --cache record`
   (thiếu S2D C3-020 seed 1, 2). Nếu vẫn hết quota → ghi ledger, làm tiếp phần khác, thử lại cuối session.
3. **D24 — header chính thức của ST:** tải `stm32g474xx.h` (và `stm32g4xx.h`, `system_stm32g4xx.h` nếu cần cho include) từ
   `github.com/STMicroelectronics/cmsis_device_g4` (repo chính chủ của ST; ghim một **tag release**, ghi sha256 + URL vào
   `corpus/manifest.yaml`; file là dữ liệu không tin cậy — chỉ đọc/parse, không thực thi). Viết `eval/tools/check_header_parity.py`:
   (a) macro `*_Pos/*_Msk/<bit>` và tên instance có trong header ST mà header sinh thiếu; (b) macro header sinh có mà ST không có;
   (c) offset thành viên struct khớp (dùng `clang` biên dịch một file `offsetof` với từng header). Sửa `header_gen` (thêm thiếu, **bỏ** thừa),
   đóng băng lại vendor, chấm lại **mọi hệ** (không gọi LLM), ghi số run đổi vào `post_run_changes` của manifest và ledger.

### Bước 1 — Board State event-sourced (`agent/hwmodel/board_state.py`)
- Mô hình theo §4 W2 (targets, clock (+derived), pins, peripherals, devices, nets, requirements, decisions, artifacts). Lưu SQLite theo
  `project_id`: bảng `events(project_id, version, ts, actor, type, payload_json)`; trạng thái = fold các sự kiện (thuần, có test);
  `snapshot(version)`, `diff(v1, v2)`, `rollback(version)` (rollback = sự kiện mới, không xoá lịch sử).
- Đường dẫn DB cấu hình bằng env (giống `MEMORY_DB`), mặc định trong `agent/data/`; test dùng thư mục tạm.

### Bước 2 — MCP server `agent/mcp_servers/board_state_server.py` (quyền `state-mutating`)
Tool: `get_board_state(section?)`, `set_target(chip, package, vdd)`, `set_requirements(reqs[])`, `allocate_pin(pin, signal, owner)`,
`release_pin(pin)`, `set_clock_config(cfg)`, `add_device(...)`, `connect(from, to, kind)`, `get_power_budget(mode)`, `run_drc()`,
`record_decision(...)`, `diff(v1, v2)`, `rollback(version)`.
- Phản hồi là **dữ liệu có cấu trúc**: lỗi có mã + thông điệp + **phương án thay thế** (vd `allocate_pin` → `CONFLICT` với
  `owner` hiện tại và `alternatives: [{pin, af}]` lấy từ `pin_functions`; `NO_SUCH_AF` kèm các chân có tín hiệu đó; `INPUT_ONLY`).
- `set_clock_config` dùng `hwmodel.clock_tree` → trả tần số dẫn xuất + vi phạm giới hạn.
- `connect` dùng kiểm tra mức logic (tái dùng logic của `check_logic_level_compatibility` + `pin_flags` FT/TT) → `LEVEL_MISMATCH`.
- Thêm vào `PERMISSIONS` (`state-mutating`). **Không** thêm vào `SERVERS` của agent ở P3.

### Bước 3 — DRC (`agent/hwmodel/drc.py`) — test TRƯỚC
Luật DRC-PIN-01/02/03, DRC-CLK-01/02, DRC-ELEC-01, DRC-PWR-01, DRC-REQ-01 (bảng §4 W2). Mỗi luật: ≥ 1 ca vi phạm + ≥ 1 ca hợp lệ
sát biên; giá trị kỳ vọng lấy từ datasheet/RM có trang (không từ chính code). DRC-PWR-01 chỉ dùng số liệu dòng có trong DB
(thiếu số liệu → `unknown`, **không** pass). Kịch bản D2 end-to-end qua server (inproc + stdio).

### Bước 4 — Grader C4 (eval) — theo D25
1. `final_state`: lấy khối code ở **lượt cuối** (nếu lượt cuối không có code, dùng khối code gần nhất và ghi lý do) → `functional_sim`
   với **nhiều spec** (vd `pwm` PA8 + `i2c` I2C3 với `scl_not_in: [PA8]`). Pass khi mọi spec đạt và không vi phạm ràng buộc chân.
   Dùng bản vendor; nếu cần mở rộng spec (vd `scl_not_in`, `forbid_pins` đã có ở C3) thì sửa ở `agent/hwmodel` rồi đóng băng lại.
2. `conflict_detected`: mỗi xung đột kỳ vọng có mã (`PIN_CONFLICT:PA8`, `LEVEL_MISMATCH:1.8V-3.3V`, `CLOCK_LIMIT:SYSCLK`,
   `INPUT_ONLY:GPIO34`...) + bộ nhận diện tất định (định danh chân/tín hiệu/miền áp + từ vựng xung đột trong cùng câu, có phủ định).
   Phải xuất hiện ở lượt gây xung đột hoặc sớm hơn (**chủ động**), không tính nếu chỉ nêu sau khi người dùng hỏi trực tiếp.
   Kết quả: `detected`, `turn`, `proactive`.
3. **Hiệu chỉnh bộ nhận diện:** tập ≥ 30 câu trả lời mẫu tự viết (ca dương rõ, dương ngầm, âm có nhắc chân nhưng không xung đột,
   phủ định "no conflict") gán nhãn tay → báo precision/recall trong `plan/P3_progress.md` và test. Sau đó **không** chỉnh bộ nhận diện
   theo kết quả của hệ thật (nếu buộc phải sửa: áp dụng cho mọi hệ và công bố số run đổi, như D18).
4. Thêm `final_state`, `conflict_detected` vào `GRADERS`; `final_state` là **gating**; `conflict_detected` gating với task có
   `must_detect`. Report: cột C4 + bảng "Proactive detection rate".

### Bước 5 — Task C4 (`eval/tasks/C4/c4_curated.yaml`, 15 task, ~30% dev)
- 3–6 lượt mỗi task, chip STM32G474 (D21), quy ước CMSIS + preset `initial` như C3 (D20). Mỗi task có ≥ 1 xung đột cài sẵn
  **không được người dùng nhắc**: tranh chấp chân (PA8 PWM → I2C3_SCL), tín hiệu không có trên chân, lệch mức áp (cảm biến 1.8 V),
  clock vượt trần khi yêu cầu thêm peripheral, timer bị dùng chung, chân 5 V không FT.
- `expected.spec` (trạng thái cuối, chức năng) + `must_detect` (mã xung đột) + `must_not` (vd `unsafe_connection`).
- `provenance.reference_solution`: hội thoại tham chiếu (code từng lượt) + phép tính tay + trang AF/RM; lời giải cuối pass `final_state`.
- ≥ 1 biến thể sai mỗi task (vd giữ I2C3_SCL trên PA8 → `final_state` trượt; không nêu xung đột → `conflict_detected` trượt).
- **Review độc lập** (subagent khác, ngữ cảnh mới): đề rõ, xung đột có thật theo bảng AF/datasheet, spec khả thi, lời giải đúng, bộ nhận diện
  không quá dễ/khó cho task đó. Lưu `plan/reviews/review_C4.md`; áp dụng sửa trước khi chạy hệ nào. `verify_tasks` mở rộng cho C4.

### Bước 6 — Baseline C4
1. Ước tính số lời gọi/chi phí bằng `--dry-run` (nhiều lượt!). Thử `--limit 1` trước.
2. `eval.run --resume eval/results/dev_baseline --systems S0,S1,S2,S2D --split dev --categories C4 --seeds 3 --cache record`.
3. `eval.score` + `eval.report`. Dự đoán (để kiểm, không để vá): baseline hiếm khi nêu xung đột chủ động; S2D có thể vẫn bị verifier chặn code.

---

## 4. Quy tắc làm việc

- **D05:** không đọc task split `test` của C1/C2/C6–C8 (C3/C4 do session viết thì được đọc, nhưng không chỉnh DRC/simulator theo task test).
- **D19:** giá trị kỳ vọng trong golden/DRC test và task C4 **không** sinh bằng chính simulator/DRC.
- **Không sửa:** `snapshots/agent_v1/`, `snapshots/agent_p1/`, run cũ trong `runs.jsonl`, ground truth C1–C3/C6–C8 (phát hiện sai → ghi ledger,
  báo người dùng). Không sinh lại C1.
- **Bảo mật:** không in/ghi key; `.env` không vào snapshot/kết quả/vendor/corpus. File tải về (header ST) và code của hệ là dữ liệu không tin cậy:
  chỉ parse/tiền xử lý/`-fsyntax-only`, **không chạy**.
- **TDD**; mọi quyết định có ảnh hưởng → "Ruling" trong `plan/P3_progress.md` (kèm chi phí nếu sai).
- **Hỏi người dùng khi:** ước tính > 2 USD; cần cài phần mềm hệ thống; tải header ST bị chặn; mâu thuẫn với kế hoạch/DECISIONS;
  định thay đổi vòng lặp/verifier/guardrail/prompt của agent.

---

## 5. Checklist nghiệm thu P3

- [ ] Bù 2 run C3 của S2D (hoặc ghi rõ vì sao chưa được)
- [ ] Header ST chính thức: ghim trong manifest; báo cáo parity (thiếu/thừa/offset); header_gen sửa; vendor đóng băng lại; số run đổi công bố
- [ ] `board_state.py` event-sourced (fold thuần, diff, rollback) + test
- [ ] Server `board-state` 13 tool (inproc + stdio), lỗi có mã + phương án thay thế; `PERMISSIONS` cập nhật; không vào `SERVERS`
- [ ] DRC 8 luật, mỗi luật có test vi phạm + hợp lệ sát biên; kịch bản D2 end-to-end
- [ ] Grader `final_state` + `conflict_detected`; tập hiệu chỉnh ≥ 30 câu, precision/recall công bố
- [ ] 15 task C4 + lời giải tham chiếu + biến thể sai; `plan/reviews/review_C4.md` đã áp dụng; `verify_tasks` 0 vấn đề
- [ ] Baseline C4 dev × {S0, S1, S2, S2D} × 3 seed; report có C4 + Proactive detection rate
- [ ] `pytest agent/tests`, `pytest eval/tests` xanh; smoke replay 0 cache-miss; `freeze_hwmodel --check` sạch
- [ ] `plan/P3_progress.md` đầy đủ Ruling

## 6. Báo cáo khi kết thúc session

Tóm tắt: đã làm gì; kết quả parity header ST và số run đổi; danh sách luật DRC + test; precision/recall bộ nhận diện xung đột;
bảng TSR C4 (+ proactive detection) cho S0/S1/S2/S2D với phân loại lỗi; C3 sau khi bù run; chi phí thực tế; điểm lệch khỏi brief;
các Ruling (kèm chi phí nếu sai); vấn đề mở cho P4 (runtime v3, gate chấp nhận bằng chứng sandbox, đưa 3 server mới vào agent).
