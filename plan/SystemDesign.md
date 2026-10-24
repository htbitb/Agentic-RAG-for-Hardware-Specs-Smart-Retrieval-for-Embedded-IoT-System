# BÁO CÁO THIẾT KẾ KIẾN TRÚC HỆ THỐNG (SYSTEM ARCHITECTURE DESIGN)

**Đề tài:** Agentic RAG for Hardware Specs: Smart Retrieval for Embedded IoT Systems

**Môn học:** Advanced Agentic Artificial Intelligence (CO5151)

**Phiên bản:** 2.1 — Final System Design Specification

---

## 1. TỔNG QUAN KIẾN TRÚC TOÀN HỆ THỐNG

Hệ thống được tổ chức theo mô hình **Dual-MCP Decoupled Agentic Architecture**, phân tách triệt để giữa tầng suy luận (Agent Core), giao thức công cụ chuẩn hóa Model Context Protocol (MCP), hạ tầng dữ liệu cục bộ (Embedded Data Engines), và cơ chế chốt chặn bảo vệ phần cứng bằng mã lệnh độc lập (Hardware Safety Guardrails).

```
                                  USER QUERY
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. INPUT SAFETY INTERCEPTOR (Deterministic Pre-check)                       │
│    - Regex / Entity Extraction (Pin, Voltage, Clock frequency)              │
│    - Query Max Ratings từ DuckDB (Absolute Maximum Ratings)                 │
│    - Phát hiện nguy cơ quá áp / quá dòng ──► [YES] ──► [HARD REFUSAL & EXIT]│
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ [NO: Request an toàn]
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. AGENT CORE ORCHESTRATOR (Sequential ReAct / Plan-and-Solve Loop)         │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ (A) REASONING & PLANNING                                              │  │
│  │     - Đọc Working Memory (Scratchpad) & Episodic Memory (DuckDB)      │  │
│  │     - Phân tích mục tiêu: Tra cứu thủ tục trước ──► Tra cứu phần cứng │  │
│  │     - Quyết định công cụ và tham số kế tiếp                           │  │
│  └──────────────────────────────────┬────────────────────────────────────┘  │
│                                     │ Tool Call Decision                    │
│                                     ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ (B) ACTING (Giao tiếp công cụ qua Stdio MCP JSON-RPC 2.0)             │  │
│  │     - Step 1: Gọi Text-Manual MCP lấy quy trình cấu hình              │  │
│  │     - Step 2: Gọi Hardware-Register MCP lấy chân pin, AF & bitfields  │  │
│  └──────────────────┬─────────────────────────────────┬──────────────────┘  │
│                     │                                 │                     │
│                     ▼ JSON-RPC                        ▼ JSON-RPC            │
│       ┌───────────────────────────┐     ┌───────────────────────────┐       │
│       │ MANUAL-TEXT MCP (Read-Only)│     │HARDWARE-REGISTER MCP (R-O)│      │
│       │ └─► LanceDB (Hybrid RAG)  │     │ └─► DuckDB (SQL / Specs)  │       │
│       └─────────────┬─────────────┘     └─────────────┬─────────────┘       │
│                     │ Tool Output Payload             │ Tool Output Payload │
│                     └────────────────┬────────────────┘                     │
│                                      ▼                                      │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ (C) OBSERVATION                                                       │  │
│  │     - Thu nhận kết quả từ MCP Tools, cập nhật vào Working Memory      │  │
│  │     - Đánh giá: Đã đủ thông tin để sinh mã/trả lời chưa?              │  │
│  │       ├─ [Chưa đủ] ──► Quay lại bước (A) để lên kế hoạch gọi tool tiếp│  │
│  │       └─ [Đã đủ]   ──► Chuyển dữ liệu sang sinh mã & cấu hình         │  │
│  └──────────────────────────────────┬────────────────────────────────────┘  │
│                                     │ Draft Response / Code                 │
│                                     ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ (D) REFLECTION & POST-VERIFICATION                                    │  │
│  │     - Output Static Code Analyzer (AST / Regex)                       │  │
│  │     - So khớp tần số / điện áp thực tế với bảng giới hạn DuckDB       │  │
│  │       │                                                               │  │
│  │       ├── [FAIL: Sai thanh ghi / Vượt trần] ──────────────────────────┼──┤
│  │       │   (Kích hoạt Reflection Loop: Gửi phản hồi lỗi nội bộ         │  │
│  │       │    quay lại bước (A) để Agent tự tính toán / sửa lại mã)      │  │
│  └───────┼───────────────────────────────────────────────────────────────┘  │
└──────────┼──────────────────────────────────────────────────────────────────┘
           │
           │ [PASS: Đạt chuẩn an toàn 100%]
           ▼
FINAL VERIFIED RESPONSE / CODE TO USER

```

---

## 2. PIPELINE NẠP VÀ BIỂU DIỄN DỮ LIỆU (DUAL-SOURCE DATA INGESTION)

Hệ thống triển khai cơ chế **"SVD-First, PDF-Fallback/Enrichment"** nhằm triệt tiêu hoàn toàn rủi ro xé lẻ bảng biểu thanh ghi từ tài liệu kỹ thuật.

```
                     NGUỒN DỮ LIỆU ĐẦU VÀO
             ┌──────────────────┴──────────────────┐
             ▼                                     ▼
     CMSIS-SVD (File XML)                 Datasheets & Manuals (PDF)
             │                                     │
             ▼                                     ▼
     [SVD XML Parser]                     [Layout-Aware Parser: Docling]
             │                                     │
             │                      ┌──────────────┴──────────────┐
             │                      ▼                             ▼
             │              [Table Extractor]             [Markdown Cleaner]
             │              - Pinout & AF Maps            - Bỏ header/footer/rác
             │              - Absolute Max Ratings        - Giữ nguyên H1/H2/H3
             │                      │                             │
             ▼                      ▼                             ▼
    ┌───────────────────────────────────┐         ┌───────────────────────────┐
    │          DUCKDB STORAGE           │         │    STRUCTURAL CHUNKER     │
    │  - peripherals, registers, fields │         │  - Cắt theo ranh giới mục │
    │  - pinout_alternate_functions     │         │    cấu hình (H2/H3)       │
    │  - electrical_characteristics     │         │  - Breadcrumbs metadata   │
    └───────────────────────────────────┘         └─────────────┬─────────────┘
                                                                ▼
                                                  ┌───────────────────────────┐
                                                  │      LANCEDB STORAGE      │
                                                  │  - Dense Embeddings       │
                                                  │  - BM25 Full-text Index   │
                                                  └───────────────────────────┘

```

### 2.1. Nhánh dữ liệu cấu trúc (DuckDB Storage)

* **Parser CMSIS-SVD:** Bóc tách tệp XML chuẩn công nghiệp nạp vào DuckDB cục bộ (`hardware_specs.duckdb`):
* `peripherals(chip_id, name, base_address, description)`
* `registers(peripheral_id, name, offset, size, reset_value, access)`
* `bitfields(register_id, name, bit_offset, bit_width, access, description)`


* **Parser Bảng PDF (Docling):**
* Bảng Pinout/AF: Lưu vào `pin_mappings(chip_id, pin_name, af_number, signal_name, is_5v_tolerant)`.
* Bảng Giới hạn điện: Lưu vào `electrical_limits(chip_id, parameter_name, pin_scope, min_val, max_val, unit)`.


* **Đặc tính:** Không dùng vector search trên nhánh này; toàn bộ truy vấn là SQL/Key Match xác định (Deterministic), đảm bảo chính xác 100% về mặt địa chỉ và bitfield.

### 2.2. Nhánh dữ liệu văn bản hướng dẫn (LanceDB Storage)

* **Structural Chunking Engine:** Không dùng chunking độ dài cố định. Chunking cắt theo ranh giới tiêu đề (`H2`, `H3`) của quy trình cấu hình, giữ nguyên ngữ cảnh đầy đủ của từng bước khởi tạo.
* **Hybrid Search Index:** Lưu trong LanceDB embedded gồm vector embeddings (ngữ nghĩa) song song với chỉ mục BM25 (từ khóa kỹ thuật viết tắt như `CCMR1`, `BDTR`, `MOE`).



---

## 3. ĐẶC TẢ GIAO THỨC MCP SERVERS (READ-ONLY)

Cả hai máy chủ MCP giao tiếp qua kênh `stdio` dùng JSON-RPC 2.0 và hoạt động ở chế độ **Read-Only** hoàn toàn.

### 3.1. `Manual-Text MCP Server`

* **Tool: `search_manual_sections**`
* *Schema Input:*
```json
{
  "type": "object",
  "properties": {
    "chip_id": { "type": "string" },
    "peripheral": { "type": "string" },
    "query": { "type": "string" },
    "top_k": { "type": "integer", "default": 3 }
  },
  "required": ["chip_id", "peripheral", "query"]
}

```


* *Schema Output:* Danh sách các đoạn trích dẫn Markdown kèm metadata (`source_doc`, `chapter`, `page_range`).


* **Tool: `get_full_section**`
* *Schema Input:* `chip_id: str`, `section_id: str`
* *Schema Output:* Toàn bộ nội dung của section khi cần ngữ cảnh mở rộng.



### 3.2. `Hardware-Register MCP Server`

* **Tool: `lookup_register_detail**`
* *Schema Input:* `chip_id: str`, `peripheral: str`, `register_name: str`
* *Schema Output:* Base address, offset, reset value, danh sách chi tiết các bit (bit range, access type, enum values).


* **Tool: `query_pin_alternate_function**`
* *Schema Input:* `chip_id: str`, `pin_name: str`, `target_signal: Optional[str]`
* *Schema Output:* Số hiệu AF tương ứng, chế độ I/O, nhãn 5V-Tolerant.




* **Tool: `get_hardware_limit**`
* *Schema Input:* `chip_id: str`, `parameter: str` (ví dụ: `VDD`, `SYSCLK_MAX`)
* *Schema Output:* Ngưỡng vận hành danh định và ngưỡng phá hủy tuyệt đối (Absolute Maximum Ratings).





---

## 4. CƠ CHẾ HOẠT ĐỘNG CỦA HARDWARE SAFETY GUARDRAILS & VERIFICATION GATE

Cơ chế an toàn được hiện thực hóa bằng mã lệnh xác định (Deterministic Code & Static Analysis), bao bọc toàn bộ chu trình hoạt động của Agent.

### 4.1. Lớp 1: Input Safety Interceptor (Tiền kiểm soát yêu cầu)

Trước khi Agent kích hoạt kế hoạch suy luận, yêu cầu người dùng được quét qua bộ lọc tiền xử lý:

1. **Entity Extractor:** Nhận diện các tham số vật lý:
* Chân: `\b(P[A-K][0-1]?[0-9]|VDD|VSS|VIN)\b`
* Mức điện áp: `(\d+(\.\d+)?)\s*(V|Volt|mV)`
* Tần số: `(\d+(\.\d+)?)\s*(MHz|kHz|GHz)`


2. **Deterministic Limit Check:**
* Truy vấn DuckDB lấy giá trị ngưỡng từ bảng `electrical_limits`:


```python
limits = duckdb.query("""
    SELECT is_5v_tolerant, max_voltage 
    FROM pin_mappings 
    WHERE chip_id = ? AND pin_name = ?
""", [chip_id, pin_name]).fetchone()

```


* **Điều kiện ngắt mạch (Circuit Breaker):** Nếu `requested_voltage > limits.max_voltage`, hệ thống ngắt tiến trình ngay lập tức, từ chối thực hiện (Hard Refusal) và xuất thông báo cảnh báo nguy cơ cháy hỏng vi điều khiển kèm trích dẫn tài liệu.





### 4.2. Lớp 2: Output Static Code Analyzer & Reflection Gate (Hậu kiểm soát mã nguồn)

Trước khi gửi phản hồi cuối cùng cho kỹ sư, mã C cấu hình sinh ra được chuyển qua bộ phân tích tĩnh:

1. **AST / Pattern Matching:** Bóc tách các giá trị tham số ghi vào thanh ghi xung nhịp hoặc nguồn (ví dụ: cấu hình bộ nhân PLL trong `RCC_PLLCFGR`).
2. **Tính toán giá trị toán học thực tế:**

$$\text{SYSCLK} = \frac{\text{HSE} \times \text{PLLN}}{\text{PLLM} \times \text{PLLR}}$$


3. **Reflection Execution:** So khớp $\text{SYSCLK}$ với giới hạn tối đa trong DuckDB. Nếu $\text{SYSCLK} > f_{\text{MAX}}$ (ví dụ: tính ra $210\text{MHz}$ trong khi trần chip chỉ cho phép $170\text{MHz}$):
* Gate đánh trượt mã cấu hình này.
* Gửi phản hồi lỗi nội bộ quay về Agent Loop: *"Reflection Error: Tần số SYSCLK đạt 210MHz, vượt ngưỡng tối đa 170MHz. Hãy tính toán lại các hệ số PLLN/PLLR."*
* Agent tự động sửa mã trước khi trả kết quả cuối cùng (tối đa 2 chu kỳ lặp).



---

## 5. THIẾT KẾ BỘ NHỚ HỆ THỐNG (MEMORY ARCHITECTURE)

* **Short-term Memory (RAM):** Lưu trữ dấu vết suy luận (reasoning scratchpad), các plan con và dữ liệu JSON trung gian từ các cuộc gọi MCP trong phiên hiện tại.


* **Episodic Memory Store (DuckDB):**
* Lưu vào bảng `chat_episodes(session_id, timestamp, peripheral, pin_context, register_context, summary)`.


* Phục vụ các câu hỏi nối tiếp (multi-turn queries) mà không cần truy vấn lại cơ sở dữ liệu từ đầu.





---

## 6. KẾ HOẠCH THỰC HIỆN VÀ MA TRẬN QUẢN LÝ RỦI RO

### 6.1. Phân bổ tiến độ thực hiện

| Giai đoạn | Tuần | Mục tiêu kỹ thuật & Sản phẩm bàn giao cụ thể | Phân công

 |
| --- | --- | --- | --- |
| **P1** | W1–W2 | Hoàn thiện Proposal và tài liệu thiết kế kiến trúc hệ thống.

 | Cả nhóm |
| **P2** | W3–W4 | Viết SVD Parser nạp DuckDB; viết Table Extractor nạp Pinout; dựng khung `Hardware-Register MCP` và `Manual-Text MCP`.

 | Nhâm, Bình |
| **P3** | W5–W6 | Tích hợp LanceDB Hybrid Search; hoàn thiện Sequential Agent Loop và tích hợp Reflection Gate.

 | Nhâm, Huy |
| **P4** | W7 | Báo cáo Checkpoint Demo (Nộp D2 Progress Report) trên 5–10 task thực tế.

 | Cả nhóm |
| **P5** | W8–W9 | Đánh giá Benchmark 40+ tasks; thực hiện Ablation studies và thử nghiệm Prompt Injection.

 | Bình, Huy |
| **P6** | W10–W12 | Đóng gói local container/binary; tối ưu hóa độ trễ và bảo vệ D3 Final Defense.

 | Cả nhóm |

### 6.2. Ma trận quản lý rủi ro kỹ thuật

| Rủi ro kỹ thuật | Mức độ | Biện pháp giảm thiểu (Mitigation Strategy) |
| --- | --- | --- |
| **Lỗi parse bảng PDF đa trang** | Cao | Lấy file SVD làm chân lý gốc cho thanh ghi. Dùng Docling với bounding-box layout parsing cho Pinout; fallback bằng file cấu hình JSON cho các ngoại vi ngoại lệ. |
| **Độ trễ Agent Loop quá cao** | Trung bình | Sử dụng DuckDB và LanceDB in-process (embedded) để giảm overhead mạng xuống dưới $5\text{ms}$; cache kết quả thanh ghi trên RAM; giới hạn Reflection tối đa 2 chu kỳ. |
| **Bypass cổng an toàn phần cứng** | Cao | Tách biệt hoàn toàn logic an toàn khỏi System Prompt; kiểm tra bằng mã lệnh xác định (Regex + AST Static Analyzer) trước khi xuất kết quả.

 |

---

## 7. BỘ CHỈ SỐ VÀ KHUNG ĐÁNH GIÁ (EVALUATION FRAMEWORK)

* Tập Benchmark (40+ Tasks):


* *15 tasks Register Lookup:* Tra cứu offset, bitfields, reset value từ SVD.
* *15 tasks Cross-Referencing:* Tra cứu kết hợp giữa Pinout AF (Datasheet) và Register/Steps (Reference Manual).


* *10 tasks Hardware Safety Injection:* Các câu hỏi cố tình yêu cầu cấu hình vượt áp, sai chân I/O.




* Hệ thống Baselines so sánh:


* *Baseline 1 (Naïve RAG):* Fixed-size chunking (500 tokens) + Vector Search đơn thuần.


* *Baseline 2 (Raw LLM):* Gọi trực tiếp mô hình ngôn ngữ lớn không có công cụ hỗ trợ.


* **Chỉ số đo lường:** Exact Match (EM) cho địa chỉ thanh ghi, Multi-hop Accuracy, Hallucination Rate, và Safety Refusal Success Rate.