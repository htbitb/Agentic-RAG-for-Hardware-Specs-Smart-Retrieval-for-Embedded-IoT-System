# HW-Spec Agentic RAG

Hệ thống **Agentic RAG tra cứu thông số phần cứng nhúng (ESP32, STM32G474, nRF52840, FreeRTOS)** theo kiến trúc **Dual-MCP + ReAct Loop + Deterministic Hardware Safety Guardrail + Post-Verification Gate + Human-in-the-Loop Approval**.

---

## 1. Cấu trúc thư mục

```text
.
├── .env.example.txt              # File mẫu cấu hình biến môi trường
├── .env                          # File cấu hình thực tế (được đọc bởi config.py)
├── config.py                     # Nạp cấu hình từ .env và quản lý đường dẫn hệ thống
├── start.sh                      # Script khởi chạy nhanh Web UI & Agent
├── requirements.txt              # Các thư viện tuỳ chọn (openai, mcp, python-dotenv)
├── agent/
│   ├── react_agent.py            # Vòng lặp ReAct trung tâm + điều phối Guardrail/Verifier/Memory
│   ├── llm.py                    # OpenAICompatLLM (OpenAI/Gemini/Ollama) & SimulatedLLM (offline)
│   ├── tools.py                  # ToolHub kết nối 2 MCP server (inproc hoặc stdio)
│   ├── guardrail.py              # Chốt chặn Prompt Injection & kiểm tra giới hạn điện áp phần cứng
│   ├── verifier.py               # Kiểm chứng số liệu (V1), địa chỉ hex (V2), trích dẫn (V3), loại thông số (V4)
│   ├── memory.py                 # Short-term Memory & Episodic Memory (SQLite)
│   ├── approval.py               # Cổng phê duyệt của con người (Human-in-the-Loop) khi ghi file cấu hình
│   └── audit.py                  # Nhật ký kiểm toán (append-only JSONL, tự động che API key)
├── mcp_servers/
│   ├── text_manual_server.py     # MCP Server tra cứu tài liệu/datasheet/manual (search_manual, get_chunk_context, ...)
│   └── table_register_server.py  # MCP Server tra cứu Pin AF, thanh ghi SVD, thông số điện & tương thích mức logic
├── ingestion/
│   └── unit_normalizer.py        # Chuẩn hoá đơn vị vật lý (V, mV, uA, mA, Hz, ...) & tính biểu thức theo VDD
└── ui/
    ├── server.py                 # HTTP Server phục vụ giao diện Web & REST API (127.0.0.1:8000)
    └── static/index.html         # Giao diện trực quan hoá pipeline suy luận ReAct, Audit Log & MCP Tools
```

---

## 2. Yêu cầu hệ thống

- **Python 3.10+** (Chế độ mặc định `SimulatedLLM` + `MCP_TRANSPORT=inproc` chỉ dùng thư viện chuẩn của Python, **không bắt buộc cài thêm thư viện ngoài**).
- Nếu muốn gọi LLM thật (OpenAI, Google Gemini, Ollama, vLLM) hoặc chạy MCP qua giao thức `stdio` subprocess, cài đặt thêm:
  ```bash
  pip install -r requirements.txt
  ```

---

## 3. Cấu hình `.env`

Tại thư mục gốc của project, tạo file `.env` từ file mẫu `.env.example.txt` (script `./start.sh` sẽ tự động copy nếu chưa có `.env`):

```bash
cp .env.example.txt .env
```

### Các biến môi trường trong `.env`

| Biến | Mặc định | Mô tả |
|---|---|---|
| `LLM_API_KEY` | *(trống)* | API key cho OpenAI-compatible endpoint. **Để trống** nếu muốn dùng `SimulatedLLM` (chạy offline). |
| `OPENAI_API_KEY` | *(trống)* | Thay thế tương đương cho `LLM_API_KEY` khi dùng OpenAI. |
| `GEMINI_API_KEY` | *(trống)* | API key Google Gemini (tự động trỏ sang OpenAI-compatible endpoint của Gemini nếu `LLM_BASE_URL` để trống). |
| `LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | URL endpoint OpenAI-compatible (Gemini, OpenAI, Ollama, vLLM, ...). |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | Tên model sử dụng (VD: `gemini-3.5-flash-lite`, `gpt-4o-mini`, `qwen2.5:7b`). |
| `LLM_TEMPERATURE` | `0.0` | Nhiệt độ sinh văn bản của LLM. |
| `PRICE_IN_PER_M` | `0.075` | Đơn giá ước tính input token (USD / 1M tokens). |
| `PRICE_OUT_PER_M` | `0.30` | Đơn giá ước tính output token (USD / 1M tokens). |
| `TOP_K` | `5` | Số lượng đoạn tài liệu (chunks) trả về mặc định khi tìm kiếm manual. |
| `MCP_TRANSPORT` | `inproc` | Cơ chế gọi MCP server: `inproc` (cùng tiến trình, nhanh) hoặc `stdio` (JSON-RPC subprocess). |
| `MAX_STEPS` | `8` | Số bước suy luận ReAct tối đa cho mỗi câu hỏi. |
| `TOOL_TIMEOUT_S` | `30` | Thời gian chờ tối đa (giây) cho mỗi lệnh gọi MCP tool. |
| `TOOL_RETRIES` | `2` | Số lần thử lại tối đa khi tool read-only gặp lỗi. |
| `PORT` | `8000` | Cổng HTTP của Web UI (`http://127.0.0.1:8000`). |
| `AUDIT_LOG` | `logs/audit.jsonl` | Đường dẫn file ghi nhật ký kiểm toán. |
| `SANDBOX_DIR` | `workspace_out` | Thư mục sandbox chứa các file cấu hình `.h`/`.c` sau khi người dùng bấm Approve. |
| `MEMORY_DB` | `data/memory.sqlite` | Đường dẫn cơ sở dữ liệu SQLite lưu Episodic Memory. |

---

## 4. Cách khởi chạy dự án

### Cách 1: Dùng script `start.sh` (Khuyên dùng)

```bash
chmod +x start.sh
./start.sh
```

Các tuỳ chọn hỗ trợ khi chạy `./start.sh`:
```bash
# Chạy trên cổng tuỳ chỉnh (ví dụ 8080)
./start.sh --port 8080

# Tự động tạo .venv, cài đặt requirements.txt rồi khởi chạy server
./start.sh --install

# Ép chạy MCP qua subprocess stdio (cần cài gói `mcp`)
./start.sh --stdio
```

### Cách 2: Chạy trực tiếp bằng Python

```bash
# Chạy theo cấu hình trong .env (mặc định http://127.0.0.1:8000)
python3 -m ui.server

# Hoặc truyền cờ trực tiếp
python3 -m ui.server --inproc --port 8000
```

Sau khi khởi chạy, mở trình duyệt tại địa chỉ:
👉 **http://127.0.0.1:8000**

---

## 5. Hướng dẫn sử dụng Giao diện Web & Tính năng

Giao diện Web gồm 3 tab chính:

1. **Ask the agent**:
   - Nhập câu hỏi kỹ thuật hoặc bấm trực tiếp vào các **chip câu hỏi mẫu** bên dưới ô nhập để xem toàn bộ pipeline hoạt động theo thời gian thực (`Guardrail` → `Memory` → `Plan` → `MCP Tool Call` → `Observation` → `Verification` → `Answer`).
   - Bấm vào bất kỳ bước nào trên thanh **Agent pipeline** để xem chi tiết JSON payload đầu vào/đầu ra của bước đó.
   - Với các yêu cầu ghi file cấu hình (ví dụ: *"Generate code for PA8 PWM on STM32G474 and save it to a header file"*), hệ thống sẽ dừng ở trạng thái `pending_approval` và hiển thị nút **Approve / Deny** để con người phê duyệt trước khi ghi vào `workspace_out/`.
   - Với các câu hỏi vi phạm giới hạn phần cứng (ví dụ cấp `5V` vào chân nguồn `VDD3P3` của ESP32 có trần `3.6V`) hoặc chứa Prompt Injection, **Guardrail** sẽ tự động chặn và từ chối an toàn.
2. **Audit log**:
   - Theo dõi toàn bộ sự kiện hệ thống từ `logs/audit.jsonl`, hỗ trợ lọc theo loại sự kiện (`question`, `tool_call`, `hardware_safety_check`, `direct_injection_blocked`, `guarded_action_requested`, `answer`, ...) và tự động làm mới mỗi 3 giây.
3. **Tools & permissions**:
   - Liệt kê trạng thái LLM hiện hành, phương thức kết nối MCP (`inproc` / `stdio`), danh sách các MCP tools được khám phá qua `tools/list` và quyền hạn tương ứng (`read-only` hoặc `irreversible-write`).

---

## 6. REST API Endpoints

Nếu muốn gọi Agent từ script hoặc công cụ bên ngoài (như `curl` / Postman):

- **`GET /api/info`**: Lấy thông tin LLM, danh sách MCP tools và quyền hạn.
- **`POST /api/ask`**: Đặt câu hỏi cho Agent:
  ```bash
  curl -s http://127.0.0.1:8000/api/ask \
    -H "Content-Type: application/json" \
    -d '{"question": "What is the ESP32 deep-sleep current with RTC timer and RTC memory?", "session_id": "demo"}'
  ```
- **`POST /api/approve`**: Phê duyệt hoặc từ chối hành động ghi file (`write_config_file`):
  ```bash
  curl -s http://127.0.0.1:8000/api/approve \
    -H "Content-Type: application/json" \
    -d '{"action_id": "<ACTION_ID>", "approve": true}'
  ```
- **`GET /api/audit?n=50`**: Lấy `n` dòng log kiểm toán gần nhất.
- **`GET /api/history?session=demo`**: Xem lịch sử Episodic Memory của phiên làm việc.
