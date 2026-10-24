# CHANGELOG P1 — dữ liệu thật cho agent (W1)

Phạm vi: thay lớp dữ liệu + hai MCP server; **không** đổi vòng lặp ReAct, verifier V1–V4, guardrail, memory, approval (D10).
Snapshot đối chứng: `snapshots/agent_v1/` (không bị sửa).

## Thay đổi
- `mcp_servers/table_register_server.py` (hằng số mô phỏng: 3 chân, 11 thanh ghi) → `mcp_servers/hw_knowledge_server.py` đọc `data/hw_specs.sqlite`
  (91/46/73 peripheral, 1585/2613/2140 thanh ghi). Giữ tên tool cũ; thêm `find_pins_for_signal`, `get_clock_limits`, `search_registers`;
  `get_register_bitfields` nhận thêm `field`, `limit`, `offset` (phân trang, `truncated`/`next_offset`); `check_logic_level_compatibility`
  nhận thêm `dst_io_structure`.
- `mcp_servers/text_manual_server.py`: 5 đoạn văn mô phỏng → text index hybrid thật (9 583 chunk, BM25 + embedding + RRF) với breadcrumb và
  `page_start/page_end`; thêm tham số `doc`; `list_documents` lấy từ manifest (nhúng trong index): FreeRTOS **V8.2.1** (v1 ghi "v10.5.0"),
  `ESP32_Low_Power_AppNote` hiển thị là không có PDF (`indexed: false`) thay vì có 18 trang bịa.
- `agent/tools.py`: `SERVERS` (`table-register` → `hw-knowledge`), `PERMISSIONS` (thêm 3 tool, đều read-only).
- `config.py`: thêm `HW_DB`, `TEXT_INDEX_DB`, `TEXT_INDEX_EMB`.
- `requirements.txt`: ghim `mcp<2` (mcp 2.x đổi `FastMCP` → `MCPServer`, đường stdio của v1 vốn đã hỏng với 2.x); thêm numpy, sentence-transformers,
  pypdf, pdfplumber, pyyaml, pytest. venv chuyển sang Python 3.11 (`agent/.venv`).

## Cố ý KHÔNG đổi
- `agent/llm.py` (SYSTEM_PROMPT, `SimulatedLLM`): giữ nguyên để S2D so với S2 chỉ khác dữ liệu (D04). Quy tắc 6 ("Mention when a source has
  provenance 'simulated'") và `SimulatedLLM` không còn tác dụng với dữ liệu thật nhưng vô hại. Tên tool trong prompt (`get_register_bitfields`, ...)
  vẫn tồn tại; các tool mới được tác tử phát hiện qua `tools/list`.
- `agent/react_agent.py`, `guardrail.py`, `verifier.py`, `memory.py`, `approval.py`, `audit.py`, `ui/`.

## Sửa sau review độc lập (2026-10-22, trước lượt S2D đầy đủ)
- ESP32: khoảng chỉ số của mẫu mảng trong tiêu đề TRM (`GPIO_PINn_REG (n: 0-19, 21-23, 25-27, 32-39)`) nay được áp dụng ⇒ thanh ghi của
  chân GPIO không tồn tại (20, 24, 28–31; `OUT_SEL` 34–39) không còn bị gán trang TRM (chuyển thành `svd_only`).
- nRF52840: `VIH max = VDD` (mép trên dải logic-high, PS tr.370) không còn lưu ở cột `max` (để guardrail không coi nó là giới hạn hỏng và
  từ chối oan 3.4–3.6 V); giá trị giữ trong `condition`, giới hạn hỏng là `VI/O max = VDD+0.3 V` (Table 101, tr.972).
- Hash dữ liệu của snapshot (`snapshot_agent_p1_data_sha256`) được ghim trong manifest và ép khớp khi `--resume`; worker S2D chạy `-I -B` và
  không thừa hưởng `HW_SPECS_DB`/`TEXT_INDEX_*` từ shell.
- Phép đo truy hồi có thêm cột "trang đầu của chunk" (cùng đơn vị với S1).

## Hệ quả cần biết
- `guardrail.evaluate_hw` lấy MIN trên mọi hàng `input_voltage` ⇒ "5 V vào chân STM32G474" bị từ chối kể cả chân FT chịu 5 V (v1 trả
  `insufficient_evidence` vì không có dữ liệu chân STM32). Quá bảo thủ nhưng an toàn; để P6.
- `svd_only` / `manual_reset_value` / `warnings` là trường mới trong kết quả `get_register_bitfields`.
- Chân nRF: `evaluate_hw` chỉ đọc `field_type == supply_voltage` nên "5 V vào VDDH" (loại `supply_voltage_high`) không bị guardrail chặn; chân thì
  dùng `VI/O max = min(VDD+0.3, 3.9)`. Để P6.
- Thanh ghi chỉ có trong SVD (`svd_only`, 779 thanh ghi: STM32 101, ESP32 661, nRF 17) có `page: null`: verifier V3 không thể xác nhận trích dẫn trang cho chúng ⇒ câu trả lời về
  các thanh ghi này thường kết thúc bằng "Insufficient evidence" (hạ điểm S2D trên ESP32/Cortex-M; giữ nguyên theo D10).
- `name` trong kết quả là tên ghép `<PERIPH>_<REG>` (vd. `HRTIM_TIMA_TIMACR`); tên trong manual nằm ở `manual_name` (`HRTIM_TIMxCR`).
