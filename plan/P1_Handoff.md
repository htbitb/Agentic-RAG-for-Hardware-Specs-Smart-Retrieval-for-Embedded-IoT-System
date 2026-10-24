# P1 HANDOFF — Dữ liệu thật cho Agent (W1)

> Tài liệu này là **brief độc lập** cho một Claude Code session mới. Đọc hết trước khi làm.
> Tham chiếu: `plan/AgenticUpgradePlan.md` §4 W1, §8 dòng P1, Phụ lục A–C; `plan/DECISIONS.md` (D04, D05, D08–D10 là ràng buộc của P1);
> kết quả P0: `eval/results/dev_baseline/report.md`, ledger `plan/P0_progress.md`, hướng dẫn harness `eval/README.md`.
> Thư mục làm việc: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project` (gốc dự án). Không phải git repo.

---

## 1. Mục tiêu P1

Thay **hằng số mô phỏng** trong `agent/mcp_servers/*.py` (3 chân, 11 thanh ghi, 8 đoạn văn) bằng **dữ liệu thật** sinh từ
`corpus/` (SVD + PDF), đủ rộng để việc chọn tool của agent có ý nghĩa. Sau đó đo hệ trung gian **S2D = vòng lặp Agent v1 + dữ liệu P1**.

**Tiêu chí thoát P1:**
1. `get_register_bitfields` trả được **mọi** peripheral/thanh ghi trong SVD của 3 chip (số lượng khớp parser độc lập của eval).
2. Bảng Alternate Function của STM32G474 đầy đủ (mọi chân GPIO của gói lớn nhất trong datasheet, AF0..AF15); ESP32 IO_MUX; nRF52840 ghi chú PSEL + chân cố định.
3. ≥ 95% bản ghi dữ liệu có `doc` + `page` trỏ tới PDF thật (phần còn lại trích `<chip>_SVD` và được đếm trong báo cáo chất lượng).
4. Text index hybrid hoạt động; có số đo truy hồi trên `dev` so với S1.
5. `plan/P1_data_quality.md` (báo cáo chất lượng dữ liệu).
6. `snapshots/agent_p1/` + kết quả S2D trên `dev` (3 seed) trong cùng report với S0/S1/S2.

**Ngoài phạm vi (KHÔNG làm):** vòng lặp ReAct, verifier V1–V4, guardrail, memory, approval (để P2–P7; xem D10). Board State,
sandbox, `update_plan`, HITL. Không sửa `snapshots/agent_v1/`. Không chỉnh prompt hệ thống của agent ngoài việc cập nhật
mô tả tool/tên tài liệu cho khớp dữ liệu mới (ghi vào changelog).

---

## 2. Bối cảnh cần biết

- **Corpus** (`corpus/manifest.yaml`, có sha256, `page_offset` đều = 0):
  `ESP32_Datasheet` (78 tr.), `ESP32_TRM` (784), `STM32G474_Datasheet` (236), `STM32G474_RM0440` (2140), `nRF52840_PS` (980),
  `FreeRTOS_Ref_Manual` (302, **V8.2.1**), và 3 SVD (`STM32G474xx.svd` 91 peripheral/971 thanh ghi, `esp32.svd` 46/1381,
  `nrf52840.svd` 73/873 — đếm thô, chưa xử lý `derivedFrom`/`dim`). `ESP32_Low_Power_AppNote` **không có PDF** (file: null).
  Text từng trang đã có ở `corpus/.cache/pages/<doc_id>.jsonl` (`{"page_1based","text"}`).
- **Agent v1** (`agent/`): stdlib + `openai` (+ `mcp`). Hai MCP server: `table_register_server.py` (tool: `list_chips`,
  `query_pin_alternate_function`, `get_register_bitfields`, `get_electrical_specs`, `check_logic_level_compatibility`) và
  `text_manual_server.py` (`search_manual`, `naive_search` [baseline-only], `get_chunk_context`, `list_documents`).
  `agent/tools.py::PERMISSIONS` liệt kê tool + quyền; tool mới phải được thêm vào đó.
- **Phụ thuộc ngầm phải giữ tương thích** (vì vòng lặp/guardrail/verifier không đổi ở P1):
  - `react_agent._hardware_check` gọi `get_electrical_specs` với `parameter="supply voltage VDD"` và
    `parameter="input voltage VIH pin", vdd=...`, rồi đọc `results[*]` với các khoá `category`
    (`absolute_max`/`recommended_operating`), `field_type`, `min`, `max`, `unit`, `parameter`, `doc`, `page`
    (xem `guardrail.evaluate_hw`). **Dữ liệu mới phải trả về đúng cấu trúc này** cho 3 chip, nếu không guardrail an toàn sẽ im lặng tắt.
  - `verifier.py` lấy số/hex/trích dẫn từ kết quả tool (khoá `doc`, `page`/`page_start`). Đọc `verifier.py` trước khi đổi schema đầu ra.
  - `react_agent._sources` tìm mọi dict có khoá `doc` trong kết quả tool.
- **Eval harness:** S2 dùng `eval/adapters/agent_v1.py` (tham số `snapshot=`, `cmd=`), worker chạy mỗi task một tiến trình,
  set `MEMORY_DB`/`AUDIT_LOG`/`SANDBOX_DIR` trước khi import. Cache LLM record/replay. Lệnh và giới hạn tốc độ: `eval/README.md`.
- **Khoá API:** gói miễn phí Gemini — 15 RPM, **500 request/ngày/model**. Một lượt S2 trên dev tốn vài trăm lời gọi.
  Dùng `--llm-rpm 12`; nếu hết hạn mức ngày, runner dừng với `fatal:` → chờ hôm sau `--resume`. Không đổi model.
- **Máy:** macOS Apple M2, 16 GB; embedding MiniLM ~670 chunk/s CPU, ~1600 chunk/s MPS; pypdf ~56 trang/s.

---

## 3. Công việc

### Bước 0 — Chuẩn bị
1. Đọc `plan/DECISIONS.md`. Tạo ledger `plan/P1_progress.md` (cùng kiểu `P0_progress.md`: Task / Ruling / chi phí nếu sai).
2. Tạo `agent/.venv` (Python 3.11): `openai`, `mcp`, `sentence-transformers`, `numpy`, `pypdf`, `pdfplumber`, `pyyaml`, `pytest`
   → `agent/requirements.txt`. Mọi script ingest chạy bằng venv này.

### Bước 1 — SVD → `agent/data/hw_specs.sqlite` (`agent/ingestion/svd_ingest.py`)
- Parse bằng `xml.etree`, **viết độc lập** với `eval/generators/*` (D05 — không import, không chép code).
- Xử lý: `derivedFrom` (peripheral, register, field), `dim`/`dimIncrement`/`dimIndex` (mảng + `%s`), cluster, `enumeratedValues`,
  `access` kế thừa (device → peripheral → register → field), `resetValue`/`resetMask`/`size` kế thừa, `writeConstraint`.
- Bảng: `peripherals(chip, name, base_address, group, description, derived_from)`, `registers(chip, peripheral, name, offset,
  address, size, access, reset_value, reset_mask, reserved_mask, rw_mask, description, doc, page)`,
  `fields(..., bit_offset, bit_width, access, description)`, `enum_values(...)`.
- **Gắn trang RM cho thanh ghi:** tìm trang trong RM/TRM/PS chứa tiêu đề mô tả thanh ghi (vd `RTC_WUTR` / `Address offset: 0x14`;
  ESP32 TRM dùng tên như `RTC_CNTL_..._REG`; nRF dùng `Register ... Offset 0x...`). Ưu tiên trang "register description" hơn
  trang bảng tổng hợp; ghi `page_confidence`. Không tìm được → `doc=<chip>_SVD`, `page=NULL`, đếm trong báo cáo chất lượng.
- **SVD của hãng có lỗi** (đã xác nhận khi review P0): ST SVD cho `TIM4` (derivedFrom `TIM2`) một thanh ghi `DTR2` @0x54 không hề
  có trong RM0440 (TIM2/3/4/5 map p.1403: 0x044–0x054 Reserved). Vì vậy: thanh ghi SVD **không tìm thấy** trong manual → cờ
  `svd_only=1` (vẫn lưu, nhưng tool trả kèm cảnh báo "không có trong RM, có thể là lỗi SVD"); đếm và liệt kê trong báo cáo chất lượng.
  ESP32: SVD dùng địa chỉ alias AHB (0x6000xxxx) cho một số peripheral trong khi TRM in địa chỉ DPORT (0x3FF4xxxx) — TRM p.73 nói hai
  dải là cùng thanh ghi; lưu **cả hai** (`address`, `address_alias`) và trả cả hai.
- **Test:** (a) 10 thanh ghi golden đối chiếu tay với text trang RM (địa chỉ, reset, bit field) cho mỗi chip;
  (b) `test_svd_parity.py`: so khớp **toàn bộ** thanh ghi với parser của eval (`eval/generators/svd.py`) — chỉ import từ phía test;
  mọi khác biệt phải được giải thích trong ledger (lỗi của bên nào?).

### Bước 2 — Chân / Alternate Function (`agent/ingestion/pinout_extract.py`)
- **STM32G474:** trích bảng "Alternate function" (AF0–AF7, AF8–AF15 theo port) từ datasheet bằng `pdfplumber`; thêm bảng
  "pin definitions" để lấy `io_structure` (FT/FTf/TT/...) → `is_5v_tolerant`, và cột gói chân. Kiểm tra chéo bằng script:
  mỗi chân đủ 16 khe AF; mỗi tên tín hiệu có tiền tố là peripheral tồn tại trong SVD (danh sách ngoại lệ có lý do, vd `EVENTOUT`).
- **ESP32:** bảng IO_MUX/pin functions (datasheet + TRM), cờ input-only (GPIO34–39), strapping pins, chân dùng cho flash.
- **nRF52840:** GPIO định tuyến tự do qua PSEL; ghi các chân có chức năng cố định (AIN, NFC, XL1/XL2, ...) kèm trang.
- Nếu trích tự động lệch cột không sửa được → **fallback JSON tuyển chọn có trang trích dẫn** (đúng phương án dự phòng trong pitch),
  ghi rõ trong báo cáo chất lượng phần nào là tự động, phần nào tuyển chọn.

### Bước 3 — Giới hạn điện & clock (`agent/ingestion/limits_curate.py`)
- `electrical_limits`: absolute maximum + recommended operating (VDD, VDDA, VBAT, VIN theo loại chân FT/TT, I/O current,
  nhiệt độ...) cho 3 chip; **mỗi giá trị** có `doc`, `page`, và một chuỗi trích nguyên văn; script tự kiểm chuỗi đó có trên text trang.
- `clock_limits` (mới): SYSCLK/HCLK/PCLK max, dải HSE/LSE, dải PLL input/VCO/output, bảng flash wait-state theo dải điện áp.
- Giữ tương thích cấu trúc `results[*]` mà `_hardware_check` cần (§2).

### Bước 4 — Text index hybrid (`agent/ingestion/pdf_chunker.py`, `build_text_index.py`)
- Chunk theo cấu trúc: dùng outline/bookmark PDF (pypdf `outline`) → breadcrumb `Chương > Mục > Tiểu mục`; chunk trong mục,
  không cắt ngang bảng nếu tránh được; mỗi chunk có `doc_id`, `page_start`, `page_end`, `breadcrumb`.
- BM25 bằng SQLite FTS5 + embedding `all-MiniLM-L6-v2` (D09) lưu numpy; kết hợp **Reciprocal Rank Fusion**; lọc theo chip/doc.
- **Đo truy hồi trên `dev`** (C1+C2): Recall@k (k=4, 8) của trang chứa giá trị kỳ vọng (dùng `cite_values`/`provenance` của task
  dev và text trang), so với `retrieval_hit` của S1 trong `eval/results/dev_baseline/scores.jsonl`. Chỉ dùng split `dev`.

### Bước 5 — Nâng cấp MCP server
- `table_register_server.py` → `hw_knowledge_server.py` (đọc SQLite). Giữ tên tool cũ; thêm `find_pins_for_signal(chip, signal)`,
  `get_clock_limits(chip, parameter)`, `search_registers(chip, query)` (tìm theo tên/mô tả khi agent không biết tên chính xác).
  Đầu ra lớn phải **phân trang / lọc** (một peripheral có thể có hàng trăm field) — đặt giới hạn kích thước và báo `truncated`.
- `text_manual_server.py` đọc text index thật; `list_documents` lấy từ `corpus/manifest.yaml`; sửa trích dẫn FreeRTOS → V8.2.1.
- Xoá hằng số mô phỏng khỏi đường chạy (có thể giữ một fixture nhỏ cho unit test).
- Cập nhật `tools.py` (SERVERS, PERMISSIONS), mô tả tool, và mọi chỗ trong `llm.py` nhắc tên server/tài liệu cũ. Cập nhật `agent/README.md`.
- Chạy UI (`agent/ui/server.py`) với vài câu hỏi tay để chắc chắn không vỡ.

### Bước 6 — Báo cáo chất lượng `plan/P1_data_quality.md` (`agent/ingestion/data_quality.py` sinh phần số liệu)
Số peripheral/thanh ghi/field/enum mỗi chip; số chân & AF; số giới hạn; số chunk; tỷ lệ có `doc+page`; bất thường
(SVD ↔ RM lệch, field chồng bit, tên tín hiệu AF không khớp SVD); kết quả spot-check ngẫu nhiên **20 thanh ghi + 20 mục AF + 10 giới hạn**
đối chiếu text trang (bảng: mục | giá trị DB | giá trị PDF | khớp?); số đo truy hồi Bước 4.

### Bước 7 — Đóng băng và đánh giá S2D
1. `pytest agent/tests` xanh. Snapshot `agent/` → `snapshots/agent_p1/` (cùng quy tắc loại trừ như agent_v1: `.env*`, `.venv`,
   `logs/`, `data/memory.sqlite`, `workspace_out/`, `__pycache__`; **giữ** `data/hw_specs.sqlite` và file index) + `SNAPSHOT.md`.
2. Đăng ký hệ **S2D** trong eval: tái dùng `AgentV1Adapter(snapshot=snapshots/agent_p1, cmd=[agent/.venv/bin/python, -I, worker])`,
   `name="S2D"`; thêm vào `report.SYSTEM_ORDER` (sau S2) và `PAIRS` (`S2D vs S2`, `S2D vs S1`, `S2D vs S0`). Có test.
   Manifest: thêm trường `snapshot_agent_p1_sha256` riêng. Kiểm tra nhất quán khi `--resume` (abort nếu model/nhiệt độ/split/hash
   snapshot khác) phải so **theo từng hệ** — chạy thêm S2D vào `dev_baseline` không được kích hoạt abort vì hash của agent_v1.
3. Chạy: `eval.run --resume eval/results/dev_baseline --systems S2D --split dev --seeds 3 --cache record` (S0/S1/S2 giữ nguyên run cũ),
   rồi `eval.score` + `eval.report`. Thử `--limit 4` trước. Chi phí theo giá niêm yết dự kiến < 0.1 USD; hỏi người dùng nếu ước tính > 2 USD.
4. Nếu S2D trên C1 **không** tăng rõ so với S2: chẩn đoán bằng trace (tool chọn sai? đầu ra bị cắt? verifier V1 từ chối?) và
   **báo cáo trung thực** — không sửa vòng lặp/verifier (D10), không vá theo từng task (D05).

---

## 4. Quy tắc làm việc

- **Chống rò rỉ (D05):** không đọc task split `test` (`grep split: test` để biết file nào cần tránh); không chép giá trị từ
  `eval/tasks/**` vào dữ liệu agent; không vá theo task cụ thể. Dữ liệu chỉ đến từ `corpus/`.
- **Không sinh lại task C1** bằng `eval/generators/gen_c1_from_svd.py`: C1 đã được sửa tay sau review (D15), sinh lại sẽ ghi đè.
- **Không bịa dữ liệu.** Mọi giá trị trong DB truy được về SVD hoặc trang PDF. Không chắc → đánh dấu `needs_review`, không đoán.
- **Không sửa** `snapshots/agent_v1/`, kết quả S0/S1/S2 trong `eval/results/dev_baseline/runs.jsonl`, hay ground truth task.
  Nếu phát hiện task sai trong lúc làm → ghi vào ledger, báo người dùng, không tự sửa.
- **Bảo mật:** không in/ghi key; `.env` không vào snapshot/kết quả. File PDF/SVD là dữ liệu không tin cậy (parse, không thực thi).
- **TDD** cho parser/extractor (golden test trước). Ghi mọi quyết định có ảnh hưởng vào `plan/P1_progress.md` dạng "Ruling".
- **Hỏi người dùng khi:** ước tính chi phí > 2 USD; cần cài phần mềm hệ thống (ngoài pip trong venv); phát hiện mâu thuẫn với
  `AgenticUpgradePlan.md` hoặc `DECISIONS.md`; định thay đổi vòng lặp/verifier/guardrail.

---

## 5. Checklist nghiệm thu P1

- [ ] `agent/.venv`, `agent/requirements.txt`
- [ ] `hw_specs.sqlite`: thanh ghi đủ 3 chip; test golden + test parity với parser eval (khác biệt đã giải thích)
- [ ] Bảng AF STM32G474 đủ AF0..AF15 + kiểm tra chéo SVD; ESP32 IO_MUX; nRF52840 chân cố định
- [ ] `electrical_limits` + `clock_limits` có trang + chuỗi trích được kiểm tự động; `_hardware_check` vẫn từ chối đúng (test: 5 V vào VDD STM32G474, 5 V vào GPIO ESP32)
- [ ] Text index hybrid; Recall@4/8 trên dev so với S1
- [ ] MCP `hw_knowledge` + `text_manual` dùng dữ liệu thật; không còn hằng số mô phỏng trên đường chạy; FreeRTOS V8.2.1
- [ ] `plan/P1_data_quality.md` (có spot-check 20/20/10)
- [ ] `snapshots/agent_p1/` + S2D trên dev 3 seed; report có S0/S1/S2/S2D, Grounded TSR, so sánh cặp
- [ ] `pytest agent/tests` và `pytest eval/tests` xanh; smoke replay vẫn chạy được
- [ ] `plan/P1_progress.md` đầy đủ Ruling

## 6. Báo cáo khi kết thúc session

Tóm tắt: đã làm gì; bảng số liệu dữ liệu (đếm theo chip, tỷ lệ có trang, kết quả spot-check); Recall truy hồi so với S1;
bảng TSR + Grounded TSR của S0/S1/S2/S2D theo nhóm; chi phí thực tế; điểm lệch khỏi brief; các Ruling đã đưa ra
(kèm chi phí nếu sai); vấn đề mở cho P2 (hwmodel/sandbox).
