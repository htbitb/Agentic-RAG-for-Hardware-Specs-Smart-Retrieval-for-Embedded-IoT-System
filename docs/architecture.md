# Kiến trúc hệ thống: Agentic RAG for Hardware Specs

Tài liệu này mô tả kiến trúc của dự án (môn CO5151 Agentic AI), gồm ba phần:

1. **Hệ của nhóm (Agent v2)**: agent hỗ trợ thiết kế phần cứng nhúng cho STM32G474, ESP32, nRF52840 và FreeRTOS.
2. **Các hệ baseline**: Direct LLM, Native RAG, Agent v1 và biến thể Agent v1 + dữ liệu thật.
3. **Pipeline đánh giá**: chạy từng hệ trên cùng bộ task, chấm bằng grader xác định, rồi sinh ra bảng số liệu so sánh.

Trạng thái hiện tại: P0–P5 đã xong (hệ đo được gọi là `S3@P5`). P6–P9 chưa làm (xem [§9](#9-trạng-thái-và-việc-còn-lại)).

---

## 1. Bức tranh tổng thể

```
                        corpus/  (dữ liệu gốc dùng chung cho MỌI hệ)
          6 PDF (datasheet, manual)  +  3 file SVD  +  header CMSIS  +  manifest.yaml (sha256, page_offset)
              │                                   │
              │ ingestion/ (agent)                │ ingest.py (native-RAG)
              ▼                                   ▼
   ┌──────────────────────────────┐      ┌─────────────────────────┐
   │ agent/data/                  │      │ native-RAG/chroma_db    │
   │  hw_specs.sqlite  (có cấu trúc)│     │  11.251 chunk 1000/150  │
   │  text_index.sqlite+.npy (BM25+emb)│  │  MiniLM, ChromaDB       │
   └──────────────┬───────────────┘      └────────────┬────────────┘
                  │                                   │
                  ▼                                   ▼
   ┌──────────────────────────────┐      ┌─────────────────────────┐
   │ agent/  (Agent v2 = S3)      │      │ native-RAG/  (S1)       │
   │ runtime + MCP tools + Gate   │      │ top-4 → 1 lời gọi LLM   │
   └──────────────┬───────────────┘      └────────────┬────────────┘
                  │       snapshots/ (S2, S2D, S3@P4, S3@P5 đóng băng)
                  │       S0 = LLM trần (không có thành phần nào ở trên)
                  ▼                                   ▼
        ┌─────────────────────────────────────────────────────────┐
        │ eval/  adapters ──► run.py ──► runs.jsonl                │
        │        score.py (graders + vendor/hwmodel) ──► scores.jsonl │
        │        report.py ──► report.md + figures/ + manifest.json │
        └─────────────────────────────────────────────────────────┘
```

| Thư mục | Vai trò |
|---|---|
| `corpus/` | Nguồn dữ liệu duy nhất cho mọi hệ. `manifest.yaml` ghi `doc_id`, sha256 và `page_offset` của từng PDF. `.cache/pages/` chứa text từng trang để grader kiểm trích dẫn. |
| `agent/` | Agent v2: runtime, Gate, MCP server, `hwmodel/`, ingestion, UI. Có `agent/README.md`. |
| `native-RAG/` | Baseline S1. Giữ nguyên bản chất "naive" (xem [§6.2](#62-s1--native-rag)). |
| `eval/` | Harness đánh giá: adapter, runner, task C1–C8, grader, báo cáo, kết quả. Có `eval/README.md`. |
| `snapshots/` | Bản đóng băng của agent theo từng giai đoạn (`agent_v1`, `agent_p1`, `agent_p4`, `agent_p5`). Harness chỉ import từ đây, không import từ `agent/`. |
| `plan/` | Kế hoạch, sổ quyết định (`DECISIONS.md`, D01–D44), brief và ledger từng giai đoạn, review. |

Có ba môi trường Python riêng: `agent/.venv`, `eval/.venv` và `native-RAG/.venv` (thư mục ẩn, `ls -a` mới thấy). Thư mục `evaluator/` ở gốc hiện rỗng, không dùng. Dự án là git repo (HANDOFF ghi "không phải git repo" là cũ); lịch sử giai đoạn vẫn nằm ở ledger `plan/P<n>_progress.md`.

---

## 2. Dữ liệu và ingestion

Mọi hệ đọc cùng một corpus để so sánh công bằng. Corpus gồm 6 PDF (4.520 trang), 3 file SVD (STM32G474, ESP32, nRF52840) và header CMSIS của ST.

| PDF (`doc_id`) | Nội dung |
|---|---|
| `STM32G474_Datasheet`, `STM32G474_RM0440` | Datasheet và Reference Manual STM32G474 |
| `ESP32_Datasheet`, `ESP32_TRM` | Datasheet và Technical Reference Manual ESP32 |
| `nRF52840_PS` | Product Specification nRF52840 |
| `FreeRTOS_Ref_Manual` | FreeRTOS Reference Manual V8.2.1 |

Agent v2 không đọc PDF trực tiếp. `agent/ingestion/` dựng hai kho dữ liệu, chạy bằng một lệnh `python -m ingestion.build_all --fresh`:

```
svd_ingest ──► pinout_extract ──► limits_curate ──► build_text_index
  (SVD)         (bảng AF,           (giới hạn điện        (chunk + BM25
                IO_MUX, PSEL)        và clock có trích dẫn)  + embedding)
       └────────────── hw_specs.sqlite ───────────────┘      └─► text_index.sqlite + .npy
```

| Kho | Nội dung | Cách truy vấn |
|---|---|---|
| `data/hw_specs.sqlite` | Thanh ghi, field, enum từ SVD (xử lý `derivedFrom`, `dim`, cluster) kèm trang tài liệu; bảng chân và Alternate Function; giới hạn điện và clock. | SQL xác định, không dùng vector search. |
| `data/text_index.sqlite` + `.npy` | Chunk theo cấu trúc tiêu đề (có breadcrumb và số trang, không cắt ngang bảng); BM25 (SQLite FTS5) và embedding `all-MiniLM-L6-v2`. | Hybrid search, trộn bằng Reciprocal Rank Fusion. |
| `data/board_state.sqlite` | Board State của từng project (xem [§4.4](#44-board-state-và-drc)). | Event-sourced. |
| `data/memory.sqlite` | Episodic memory (không nằm trong snapshot). | SQLite. |

Nguyên tắc dữ liệu: **SVD là chân lý cho thanh ghi**, PDF bổ sung ngữ cảnh và trang trích dẫn. Mỗi dòng giới hạn điện trong `limits_curate.py` mang `doc/page/trích nguyên văn` và được tự động kiểm với text trang PDF; một trích dẫn không khớp thì bước dựng dừng lại. Báo cáo chất lượng dữ liệu nằm ở `plan/P1_data_quality.md`.

**Quy mô thực tế** (đo từ `agent/data/`):

| Kho | Số liệu |
|---|---|
| `hw_specs.sqlite` | 3 chip, 210 peripheral, 6.338 thanh ghi, 27.186 field, 12.311 giá trị enum, 189 chân, 1.045 chức năng chân (AF), 65 giới hạn điện, 39 giới hạn clock |
| `text_index.sqlite` | 9.583 chunk của 6 tài liệu, tối đa 1.100 ký tự, overlap 120, embedding 384 chiều |

Số chunk khác với S1 (11.251 chunk): index của agent cắt theo cấu trúc tiêu đề và không cắt ngang bảng, còn S1 cắt cố định 1000/150 ký tự.

---

## 3. Agent v2: tổng quan

Agent v2 là một agent thật, không phải workflow cố định: LLM tự chọn tool, tự lập kế hoạch, tự viết code và tự quyết định khi nào dừng. Runtime chỉ quyết định **được phép làm gì** và **khi nào mới được coi là xong**.

```
 Người dùng
     │  goal (một lượt)
     ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ AgentRuntime  (agent/agent/runtime/loop.py)                                    │
│                                                                                │
│  INTAKE ─► PLAN ─► ACT ◄──► OBSERVE ─► (CHECK) ─► FINISH_GATE ─► DONE          │
│    │                 │                               │  fail                   │
│    │ hardware_check  │ tool call                     └──► feedback có kiểu     │
│    ▼                 ▼                                     (local) hoặc        │
│  REFUSED        ┌──────────────┐                           REPLAN_REQUIRED     │
│                 │ ToolHub (MCP)│                           (cấu trúc)          │
│  INTERRUPTED ◄──┤ + control    │                                │              │
│  (chờ người)    └──────┬───────┘                                ▼              │
│                        │                               cùng mã lỗi > 3 lần     │
│  CheckpointStore       │                               hoặc hết ngân sách      │
│  (SQLite, mỗi bước)    │                                       ▼              │
└────────────────────────┼───────────────────────────────────  ESCALATED ───────┘
                         ▼
   ┌─────────────┬─────────────┬────────────────┬─────────────────┐
   │ text-manual │ hw-knowledge│ hw-sandbox     │ board-state     │   4 MCP server
   │ (tra PDF)   │ (SVD, AF,   │ (solver, mô    │ (digital twin   │
   │             │  giới hạn)  │  phỏng, compile)│  của bo mạch)  │
   └──────┬──────┴──────┬──────┴───────┬────────┴────────┬────────┘
          ▼             ▼              ▼                 ▼
   text_index     hw_specs.sqlite   hwmodel/ (simulator, DRC, solver)
```

So với v1 (một vòng ReAct trên dữ liệu chỉ đọc), v2 bổ sung năm thứ:

| Khía cạnh | v1 | v2 |
|---|---|---|
| Dữ liệu | 8 đoạn văn, 11 thanh ghi viết tay | SVD + PDF thật |
| Môi trường | Chỉ đọc | Board State, DRC, sandbox mô phỏng thanh ghi |
| Vòng điều khiển | `for step in range(MAX_STEPS)` | State machine có kế hoạch, ngân sách, checkpoint, resume |
| Kiểm chứng | Verifier đếm số | Gate G1–G5 với lỗi có kiểu |
| Con người | Duyệt ở cuối, agent không chạy tiếp | `ask_human`, interrupt và resume |

---

## 4. Các thành phần của Agent v2

### 4.1. Runtime (`agent/agent/runtime/`)

| File | Vai trò |
|---|---|
| `loop.py` | `AgentRuntime`: state machine, thực thi tool, phân loại lỗi, leo thang, tổng hợp kết quả. |
| `state.py` | `AgentState` (toàn bộ trạng thái một run, serialize được sang JSON), `Budgets`, chuẩn hoá và diff kế hoạch. |
| `checkpoint.py` | `CheckpointStore`: ghi `AgentState` vào SQLite sau **mỗi bước**; bảng `runs` và `sessions`. |
| `control_tools.py` | Tool điều khiển không đi qua MCP: `update_plan`, `finish`. |
| `hitl.py` | `ask_human`, dựng interrupt, kiểm tra quyết định của người, diff file ghi. |
| `run_api.py` | `RunService`: `create_run`, `resume`, `events`, `get`. Dùng chung cho UI và eval. |
| `intake.py` | Pre-check an toàn xác định và tóm tắt Board State cho lượt mới. |
| `start_state.py` | Trích trạng thái khởi đầu của clock từ lời người dùng (D36) cho G2. |
| `flags.py` | Cờ ablation A1–A4, A6. |
| `factory.py` | `build_runtime`: dựng hub, LLM thật, Gate, checkpoint từ tham số hoặc biến môi trường. |
| `trace.py`, `summary.py`, `cli.py` | Sự kiện chuẩn hoá `trace.jsonl`, `summary.md`, dòng lệnh. |

**Vòng đời một run:**

- **INTAKE**: lọc injection trực tiếp, `hardware_check` xác định (từ chối nếu người dùng đòi áp điện áp vượt Absolute Maximum), nạp Board State và kế hoạch của project, trích trạng thái khởi đầu. Vi phạm thì sang `REFUSED`.
- **PLAN / ACT / OBSERVE**: LLM gọi tool, kết quả được ghi vào `observations` làm bằng chứng cho Gate. Kết quả tool cũ hơn 12 tin nhắn bị rút còn 1.500 ký tự khi gửi LLM.
- **FINISH_GATE**: mọi câu trả lời đều qua Gate, kể cả khi LLM trả văn bản thường không kèm tool call (coi là `finish` ngầm). Gate không qua thì agent nhận lỗi có kiểu `{code, where, expected, actual, hint_source}`.
- **Hai loại phản hồi lỗi**:
  - Lỗi cục bộ (Gate, mô phỏng): quay về agent để sửa.
  - Lỗi cấu trúc (board từ chối gán chân, xung đột clock, DRC): runtime chèn `REPLAN_REQUIRED`, agent phải gọi `update_plan` trước khi hành động tiếp.
- **ESCALATED**: cùng một mã lỗi quá `max_repairs` (3) lần, hoặc cạn ngân sách. Runtime trả câu trả lời tốt nhất kèm các requirement chưa đạt và những gì đã thử, không bao giờ là câu "hết ngân sách" trống. Văn bản wrap-up vẫn phải qua cổng an toàn G4.
- **INTERRUPTED**: run chờ người (xem [§4.7](#47-human-in-the-loop-và-run-api)). Đây không phải trạng thái cuối.

**Ngân sách mỗi run** (`Budgets`): 40 lời gọi LLM, 1,5 triệu token, 0,50 USD, 600 giây hoạt động (không tính thời gian chờ người hay chờ hạ tầng LLM), 3 lần `ask_human`.

**Độ bền:** checkpoint SQLite sau mỗi bước nên run bị kill vẫn `resume` được ở tiến trình khác. Tool không-read-only đang chạy lúc chết **không** bị chạy lại (at-most-once); agent nhận một observation nói rõ hiệu ứng chưa biết. Chỉ tool read-only mới được retry.

**Luật cứng:** runtime từ chối chạy với LLM mô phỏng (`allow_scripted` chỉ dành cho unit test). Mọi kết luận về tính agentic phải dùng model thật.

### 4.2. Tầng công cụ (`agent/agent/tools.py`, `agent/mcp_servers/`)

`ToolHub` kết nối bốn MCP server. Có hai transport: `stdio` (JSON-RPC thật, subprocess) và `inproc` (cùng tiến trình, kết quả giống hệt, dùng cho chạy đánh giá lớn). Mỗi tool có một mức quyền (nguyên tắc quyền tối thiểu) và có timeout.

| Server | Tool | Quyền |
|---|---|---|
| `text-manual` | `search_manual`, `get_chunk_context`, `list_documents` (và `naive_search`, bị ẩn khỏi agent) | read-only |
| `hw-knowledge` | `list_chips`, `query_pin_alternate_function`, `find_pins_for_signal`, `get_register_bitfields`, `search_registers`, `get_electrical_specs`, `get_clock_limits`, `check_logic_level_compatibility` | read-only |
| `hw-sandbox` | `solve_timer_config`, `simulate_register_writes`, `analyze_c_code`, `compile_check` | sandboxed-exec |
| `board-state` (13 tool) | Ghi: `set_target`, `set_requirements`, `allocate_pin`, `release_pin`, `set_clock_config`, `add_device`, `connect`, `record_decision`, `rollback`. Đọc: `get_board_state`, `get_power_budget`, `run_drc`, `diff` | ghi = state-mutating; đọc = read-only |
| `local-guarded` | `write_config_file` | irreversible-write (cần người duyệt) |
| Điều khiển (runtime xử lý) | `update_plan`, `finish`, `ask_human` | control |

`project_id` do hub gán cho server `board-state`; mô hình không thấy tham số này nên không thể sang project khác. Kết quả tool đi qua `sanitize_observation` để quét injection gián tiếp; tool output luôn bị coi là dữ liệu không tin cậy.

### 4.3. Sandbox và mô hình phần cứng (`agent/hwmodel/`)

`hwmodel/` là "thế giới" để agent thử nghiệm trước khi trả lời.

| Module | Vai trò |
|---|---|
| `regmap.py` | Bản đồ thanh ghi dựng từ SVD. |
| `sim.py` + `periph/{rcc,gpio,tim,usart,i2c}.py` | Simulator ghi thanh ghi, ra `effects` (PWM Hz/duty, baud, SCL, clock...) và vi phạm có mã `SIM-*`. |
| `clock_tree.py`, `solver.py` | Cây clock; solver cho timer (PSC/ARR/CCR). |
| `codeparse.py` | `analyze_c_code`: parse C kiểu CMSIS (không chạy code) thành chuỗi thao tác ghi thanh ghi. Cấu trúc không hỗ trợ thì báo `unsupported_construct`. |
| `header_gen.py`, `compile_check.py` | Sinh `stm32g474xx.h` từ DB và biên dịch `clang -fsyntax-only` cho ARM. Header sinh được đối chiếu với header chính thức của ST (v1.2.6), xem `corpus/headers/parity/`. |
| `errata.py` | Hiệu chỉnh SVD theo Reference Manual (SVD của hãng có lỗi; ví dụ mặt nạ ghi), mỗi mục kèm trang bằng chứng. |

Phần không mô hình hoá được ghi là `unmodeled` và **không bao giờ được tính là pass**. Code do LLM sinh chỉ được parse hoặc `-fsyntax-only`, không bao giờ chạy.

### 4.4. Board State và DRC

Board State là digital twin của project, được lưu theo kiểu event-sourced (có phiên bản, `diff`, `rollback`): chip đích, package, VDD, cây clock, gán chân, thiết bị ngoài, net, requirement có cấu trúc và nhật ký quyết định. Nó đóng vai trò **project memory** xuyên các lượt hội thoại.

`run_drc` chạy 8 luật xác định; mỗi vi phạm có mã, thông điệp và phương án thay thế nếu có:

| Luật | Nội dung |
|---|---|
| `DRC-PIN-01` | Mỗi chân một chủ, trừ bus chia sẻ khai báo rõ |
| `DRC-PIN-02` | Tín hiệu phải có trong bảng AF của chân; chân phải có trong package |
| `DRC-PIN-03` | Không gán output cho chân input-only |
| `DRC-CLK-01` | Tần số dẫn xuất không vượt giới hạn clock |
| `DRC-CLK-02` | Peripheral dùng phải được bật clock (RCC) |
| `DRC-ELEC-01` | Nối giữa hai miền điện áp phải qua kiểm mức logic; chân không FT không nhận 5 V |
| `DRC-PWR-01` | Tổng dòng theo chế độ không vượt ngân sách |
| `DRC-REQ-01` | Mọi requirement phải `satisfied` hoặc `waived` có lý do |

Mức: `error`, `warning`, `unknown`. `unknown` (thiếu số liệu) không bao giờ được tính là đạt.

### 4.5. Verification Gate (`agent/agent/gate/`)

Gate là cổng kết thúc: `Gate.run(ctx) -> GateReport`. Gate chỉ gọi tool read-only, không đọc env, không ghi file, không phụ thuộc prompt. Tool lỗi thì thành finding `unknown` và cổng `skipped`, không bao giờ thành pass. Cổng có thứ cần kiểm mà lỗi nội bộ thì fail closed.

| Cổng | Kiểm cái gì |
|---|---|
| **G1 Provenance** | Mọi số, địa chỉ hex và trích dẫn `[doc p.N]` trong câu trả lời phải truy được về kết quả tool, lời người dùng hoặc câu trả lời trước. Số tự tính hợp lệ khi solver, simulator hoặc clock tool xác nhận. |
| **G2 Functional** | Mô phỏng code trong câu trả lời với requirement agent đã ghi (chân, tần số, duty, baud, SCL...), xuất phát từ trạng thái khởi đầu lấy từ lời người dùng. |
| **G3 Board DRC** | Chạy 8 luật DRC trên Board State. |
| **G4 Safety** | (i) VDD của target vượt Absolute Maximum, hoặc nguồn ≥ 4 V đẩy vào chân MCU không chịu được; (ii) vi phạm giới hạn clock do simulator báo; (iii) văn xuôi khuyên áp điện áp vượt Absolute Maximum (luật tiếng Anh và tiếng Việt, chỉ là lỗi khi câu là lời khuyên). Cũng là cổng duy nhất áp cho văn bản wrap-up khi leo thang. |
| **G5 Compile** | `clang -fsyntax-only` trên khối code. `skipped` không bao giờ là pass. |

Chỉ `G2-UNMODELED` và `G5-SKIPPED` mới được miễn (`finish(waived_requirements=[{id, reason}])`, lý do không rỗng).

### 4.6. Guardrail và bộ nhớ

- **Guardrail v1** (`guardrail.py`): mã xác định, không phải prompt, nên lời injection không tắt được. Gồm lọc injection trực tiếp trong câu hỏi, quét injection gián tiếp trong observation, và `hardware_check` (từ chối "áp X V vào chân Y" nếu vượt giới hạn). Hạn chế đã biết: `hardware_check` từ chối cả câu chứa "5 V" trước khi agent suy luận nên gây over-refusal (6/11 run thất bại của S3). P6 sẽ thay bằng Policy Engine.
- **Bộ nhớ**: short-term (danh sách tin nhắn của run, kết quả tool được cắt), episodic (SQLite, chỉ lưu câu trả lời đã được kiểm, phục vụ câu hỏi nối tiếp) và Board State làm project memory. Lesson memory kiểu Reflexion chưa có (P7).
- **Audit** (`audit.py`): nhật ký JSONL append-only, tự che API key.

### 4.7. Human-in-the-loop và Run API

Có ba loại interrupt, đều dừng run ở `INTERRUPTED` với checkpoint đã lưu:

| Loại | Khi nào | Quyết định của người |
|---|---|---|
| `clarify` (`ask_human`) | Thiếu thông tin bắt buộc mà không tool nào tra được (tần số thạch anh trên board của họ, điện áp module cảm biến...) | `answer`, `unknown` |
| `choice` (`ask_human`) | Đánh đổi thiết kế thật sự, 2–4 phương án kèm ưu nhược | `choose`, `unknown` |
| `approval` (`write_config_file`) | Ghi file vào `workspace_out/` | `approve`, `reject` (kèm góp ý) |

`resume(run_id, interrupt_id, decision, payload)` nạp checkpoint, chèn kết quả vào đúng `tool_call_id` rồi chạy tiếp, kể cả ở tiến trình khác. Prompt hệ thống (`prompts/system_v3.md`) cấm hỏi thứ tool tra được hoặc thứ có thể giả định hợp lý.

`RunService` là Run API (Python) dùng chung. `ui/server.py` bọc nó thành HTTP: `POST /api/runs`, `POST /api/runs/<id>/resume`, `GET /api/runs/<id>/events`; ngoài ra có `/api/ask`, `/api/approve`, `/api/audit`, `/api/history`, `/api/info`. UI hiện tại (`ui/static/index.html`) vẫn chủ yếu hiển thị pipeline v1 (panel của v2 là P8).

### 4.8. Cờ ablation

Mỗi cờ tắt đúng một cơ chế bằng cấu hình (`AGENT_ABLATIONS="A1,A3"`), không sửa code:

| Cờ | Tắt | Cách tắt |
|---|---|---|
| A1 `-Planner` | Lập kế hoạch | Ẩn `update_plan`, bỏ `REPLAN_REQUIRED` |
| A2 `-BoardState` | Board State | Ẩn server `board-state`; Gate bỏ G3 và không đọc requirement |
| A3 `-Sandbox` | Simulator, solver, compile | Ẩn `hw-sandbox`; G2, G5 tắt; G1 quay về verifier v1 |
| A4 `-Reflection` | Tự sửa | Ngân sách sửa = 0 (Gate fail lần đầu thì leo thang) |
| A6 `-HITL` | Hỏi người | Ẩn `ask_human`; `write_config_file` tự duyệt |
| A5, A7 | Lesson memory, Guardrail | Chưa có (P7, P6) |

---

## 5. Cấu trúc thư mục `agent/`

```
agent/
├── config.py, .env(.example.txt), start.sh
├── agent/
│   ├── runtime/        state machine, checkpoint, HITL, Run API       (§4.1, §4.7)
│   ├── gate/           G1–G5                                          (§4.5)
│   ├── prompts/system_v3.md
│   ├── tools.py        ToolHub + bảng quyền                           (§4.2)
│   ├── guardrail.py, approval.py, audit.py, memory.py, llm.py
│   ├── react_agent.py, verifier.py   vòng lặp v1 (UI cũ)
│   └── scripted.py     LLM kịch bản, chỉ dùng cho test
├── mcp_servers/        4 server + hw_queries.py (lớp truy vấn SQLite)
├── hwmodel/            simulator, DRC, Board State, solver, header_gen  (§4.3, §4.4)
├── ingestion/          dựng hw_specs.sqlite và text index             (§2)
├── data/               sqlite, text index
├── ui/                 server.py + static/index.html
└── tests/              pytest (không gọi mạng)
```

---

## 6. Các hệ baseline và hệ so sánh

Mọi hệ dùng **cùng model, cùng endpoint, cùng temperature (0,0) và cùng corpus**. Model hiện tại là `ag/gemini-3.8-flash-medium` qua gateway OpenAI-compatible (D27).

| Mã | Hệ | Có gì | Cài đặt | Vai trò trong so sánh |
|---|---|---|---|---|
| **S0** | Direct LLM | Chỉ LLM, không tool, không truy hồi | `eval/adapters/direct_llm.py` | Cận dưới: LLM biết gì từ tham số |
| **S1** | Native RAG | Chroma, chunk cố định, top-4, một lời gọi LLM | `native-RAG/` qua `adapters/native_rag.py` | Baseline RAG kinh điển |
| **S2** | Agent v1 (đóng băng) | Vòng ReAct, 8 đoạn văn, 11 thanh ghi viết tay | `snapshots/agent_v1/` | Điểm xuất phát trước khi nâng cấp |
| **S2D** | Agent v1 + dữ liệu thật | Vòng lặp v1 giữ nguyên byte, dữ liệu P1 | `snapshots/agent_p1/` | Tách đóng góp của **dữ liệu** |
| **S3@P4** | Agent v2 | Runtime, Board State, sandbox, Gate | `snapshots/agent_p4/` | Đóng góp của **kiến trúc agentic** |
| **S3@P5** | Agent v2 + HITL | S3@P4 cộng `ask_human`, interrupt/resume, sửa D36/D37 | `snapshots/agent_p5/` | Hệ hiện tại |

Chuỗi so sánh được thiết kế để mỗi bước chỉ đổi một biến: `S0 → S1` (thêm truy hồi), `S2 → S2D` (đổi dữ liệu), `S2D → S3` (đổi kiến trúc, cùng dữ liệu), và các ablation A1–A6 trên S3.

### 6.1. S0: Direct LLM

Một lời gọi chat với system prompt ngắn (`eval/system_prompts.py`), lịch sử hội thoại được ghép lại cho nhiều lượt. Không có tool, không có truy hồi, nên không thể trích dẫn trang. Vì vậy `citation` không được dùng làm cổng TSR (xem [§7.5](#75-chấm-điểm)).

### 6.2. S1: Native RAG

```
INGEST (một lần)                              ASK (mỗi câu hỏi)
PDF ─► PyPDFDirectoryLoader                   câu hỏi ─► embed (MiniLM)
    ─► RecursiveCharacterTextSplitter                 ─► ChromaDB top-4 (similarity)
        (1000 ký tự, overlap 150)                     ─► ghép 4 chunk thành CONTEXT
    ─► embed all-MiniLM-L6-v2                         ─► 1 lời gọi LLM theo PROMPT_TEMPLATE
    ─► ChromaDB (11.251 chunk)                        ─► câu trả lời + sources (doc_id, trang)
```

- Năm thành phần: dữ liệu PDF, embedding `all-MiniLM-L6-v2`, ChromaDB, LLM, LangChain làm orchestrator.
- Prompt buộc trả lời "chỉ từ CONTEXT"; không tìm thấy thì trả đúng câu `"I could not find this in the documents."`.
- Đa lượt: các lượt trước được gộp vào khối QUESTION; truy hồi chỉ dùng câu hỏi hiện tại.
- **Cố tình giữ naive**: không đổi chunking, không rerank, không hybrid, không tool, không lặp. Mọi thay đổi phục vụ đánh giá nằm trong `native-RAG/CHANGELOG_EVAL.md` và không nhằm tăng điểm: đọc PDF từ `corpus/`, gắn metadata `page_1based` và `doc_id`, trả token usage, cache LLM.
- Cầu nối với harness là `native-RAG/eval_adapter.py`, một tiến trình sống lâu giao tiếp JSONL qua stdin/stdout (log chỉ ra stderr):

```
stdin : {"id", "question", "history": [{"user","assistant"}], "seed"}
stdout: {"id", "answer", "sources": [{"doc_id","file","page"}], "usage": {"in","out"}, "latency_s", "error"}
```

- Cache `record`/`replay` ghi cả kết quả truy hồi vì Chroma/HNSW có thể trả top-k khác nhau giữa các tiến trình. Bảng `meta` lưu dấu vân tay chỉ mục (embedding model, chunk size/overlap, collection, số chunk); `record` từ chối chạy nếu chỉ mục đã đổi.

Điểm yếu cấu trúc của S1, và cũng là lý do nó là baseline hữu ích: truy hồi top-4 trên 11 nghìn chunk rất nhiễu; không có cơ chế tính toán nên không làm được C3; không có trạng thái nên không làm được C4.

### 6.3. S2 và S2D: Agent v1

`HardwareAgent` (`react_agent.py`) chạy theo thứ tự: guardrail đầu vào, ngữ cảnh episodic, pre-check an toàn phần cứng, vòng ReAct (LLM nghĩ, gọi MCP tool, quan sát đã sanitize), verifier (V1 số, V2 hex, V3 trích dẫn, V4 loại thông số), ghi memory, audit. Có hai MCP server: `text-manual` và `hw-knowledge`. S2 chạy trên dữ liệu viết tay nhỏ; S2D giữ nguyên mã và thay dữ liệu bằng dữ liệu thật của P1, nên chênh lệch `S2 → S2D` là đóng góp của dữ liệu.

---

## 7. Pipeline chạy so sánh và ra số liệu

```
tasks/*.yaml ──► build_schedule(hệ × variant × task × seed)
                        │
                        ▼
                ┌───────────────┐   adapter.start/send/finish   ┌─────────────────────────┐
                │ eval/run.py   │ ────────────────────────────► │ S0: OpenAI client       │
                │ Runner        │                               │ S1: subprocess JSONL    │
                │ (song song,   │ ◄──────────────────────────── │ S2/S2D/S3: worker       │
                │  resume,      │        RunResult              │   `python -I -B`        │
                │  rate limit)  │                               │   trên snapshot đóng băng│
                └──────┬────────┘                               └─────────────────────────┘
                       │ (C5: HumanLoop — SimulatedHuman trả lời interrupt)
                       ▼
                runs.jsonl + manifest.json
                       │  python -m eval.score        (KHÔNG gọi LLM)
                       ▼
                scores.jsonl  ◄── graders + vendor/hwmodel đóng băng + corpus/.cache/pages
                       │  python -m eval.report       (KHÔNG gọi LLM)
                       ▼
                report.md + figures/{tsr_by_category, cost_vs_tsr}.png
```

### 7.1. Bộ task

Task là file YAML trong `eval/tasks/C1..C8`, mỗi task khai báo `turns`, `expected`, `graders`, `review_status` và `provenance` (bằng chứng trên trang PDF).

| Nhóm | Nội dung | Số task | Grader chính (cổng TSR) |
|---|---|---|---|
| C1 | Tra cứu địa chỉ, offset, reset, bitfield (sinh tự động từ SVD) | 25 | `exact` |
| C2 | Multi-hop xuyên tài liệu (chân → AF → timer → thanh ghi) | 20 | `keyfacts` |
| C3 | Sinh code PWM, UART, I2C, PLL | 20 | `functional_sim` |
| C4 | Thiết kế nhiều lượt có xung đột cài sẵn (3–6 lượt) | 15 | `final_state`, `conflict_detected` |
| C5 | Mục tiêu cấp hệ thống, một nửa cố ý thiếu thông tin | 12 | `checklist` |
| C6 | An toàn phần cứng (quá áp, nối 5 V, clock vượt trần) | 15 | `safety` |
| C7 | Bảo mật (prompt injection, vượt duyệt, path traversal, lộ khoá) | 15 | `attack` |
| C8 | Câu hỏi không trả lời được (phải abstain) | 10 | `abstain` |
| C9, FI | Độ bền và fault injection | chưa có (P9) | |

Tổng cộng 132 task: 42 `dev` và 90 `test` (C1 8/17, C2 6/14, C3 6/14, C4 5/10, C5 4/8, C6 5/10, C7 5/10, C8 3/7). Báo cáo `dev_baseline_v2` ghi 44 task vì tính thêm 2 biến thể oracle-info của C5. `eval/tasks/INDEX.md` còn là bản P0 (120 task, chưa có C5); chạy lại `python -m eval.tools.make_index` để cập nhật.

**Chia tập:** `dev` (khoảng 30%, phân tầng theo nhóm, seed `20261021`) dùng để chỉnh prompt và runtime; `test` (khoảng 70%) bị niêm phong, chỉ chạy một lần cho báo cáo cuối. Mọi giá trị trong task phải kiểm được trên PDF hoặc SVD (`eval.tools.verify_tasks`); task không chắc thì đặt `needs_human` và bị loại khỏi chạy chính thức.

### 7.2. Adapter

Mọi hệ cắm vào cùng giao diện `SystemAdapter` (`start(task, seed)`, `send(user_msg) -> TurnResult`, `finish() -> RunResult`), nên runner và grader không phân biệt hệ.

| Hệ | Cách chạy | Cô lập |
|---|---|---|
| S0 | Gọi trực tiếp OpenAI client bọc cache | Trong tiến trình |
| S1 | Subprocess `native-RAG/eval_adapter.py` | Chết thì khởi động lại, thử lại đúng một lần |
| S2, S2D | Worker một tiến trình/task, import từ `snapshots/`, `-I -B` | `MEMORY_DB`, `AUDIT_LOG`, `SANDBOX_DIR` trỏ vào thư mục tạm của run |
| S3 | Worker như trên; `rt.ask(...)` rồi `rt.resume(...)` khi có interrupt | Thêm `BOARD_STATE_DB`, `AGENT_CHECKPOINT_DB`, `AGENT_TRACE_DIR`; các biến `AGENT_*`, `HW_SPECS_DB`... trong shell bị lọc để một cờ lạc không âm thầm biến hệ chính thành ablation |

Worker từ chối chạy nếu agent rơi về LLM mô phỏng. `RunResult` gồm câu trả lời từng lượt, file đã ghi, Board State cuối, `trace` chuẩn hoá, `usage` (token, USD, số lời gọi) và `latency_s`.

### 7.3. Runner (`eval/run.py`)

- **Lịch**: tích Descartes (hệ × variant × task × seed). `--dry-run` in lịch và ước tính chi phí mà không gọi API.
- **Kiểm soát chi phí**: từ chối chạy nếu ước tính > 2 USD trừ khi có `--yes` (chỉ dùng sau khi người dùng đã xác nhận).
- **Cache LLM** (`--cache off|record|replay`): khoá = sha256(model, messages, tools, temperature, seed). `replay` tái tạo toàn bộ dev (243 run) với 0 lời gọi API; thiếu cache thì run bị gắn `infra:cache_miss`, runner thoát với mã 4.
- **Giới hạn tốc độ** `--llm-rpm`: điều tiết mọi lời gọi LLM thật, dùng chung giữa luồng và tiến trình qua file lock.
- **Phân loại lỗi** (`eval/llm_errors.py`): `fatal` (khoá API sai, S2 rơi về mô phỏng) dừng cả lượt; `infra` (429, 5xx, timeout) loại khỏi TSR nhưng được đếm riêng; còn lại là lỗi của hệ, tính vào TSR. Liên tiếp ≥ 12 run lỗi hạ tầng thì runner dừng để `--resume`.
- **Resume**: bỏ qua bộ (hệ, variant, task, seed) đã có trong `runs.jsonl`; từ chối nếu model, temperature, split hoặc hash snapshot khác manifest cũ. `--retry-infra` chạy lại các run lỗi hạ tầng.
- **Người dùng mô phỏng** (`HumanLoop` + `sim_human.py`, cho C5): adapter có `resume` thì interrupt được `SimulatedHuman` trả lời theo `human_policy` của task rồi resume; adapter không có `resume` (S0–S2D) thì câu hỏi trong câu trả lời được coi là một lượt người dùng tiếp theo. Biến thể oracle-info `C5-xxx-O` đưa sẵn thông tin ẩn ở lượt đầu để tách "thiếu thông tin" khỏi "không giải được".

### 7.4. Manifest (tái lập)

`manifest.json` ghim: model, temperature, giá, sha256 của corpus, của từng snapshot (mã và dữ liệu), của task set, của bản `hwmodel` đóng băng, của changelog native-RAG; cùng seeds, split, cache mode, phiên bản Python, danh sách `resumes[]` và `post_run_changes` (mỗi lần sửa grader sau khi chạy).

### 7.5. Chấm điểm

`eval/score.py` đọc `runs.jsonl` và ghi `scores.jsonl`, không gọi LLM. Mỗi task khai báo grader; các grader đều xác định (không LLM-judge).

| Grader | Nhóm | Ý nghĩa | Cổng TSR |
|---|---|---|---|
| `exact` | C1 | Hex, khoảng bit, quyền truy cập, đại lượng + đơn vị; mâu thuẫn cho cùng thuộc tính thì trượt | có |
| `keyfacts` | C2 | Fact bắt buộc và fact cấm, precision/recall/F1 | có |
| `functional_sim` | C3 | Chạy code trong câu trả lời qua simulator và so `effects` với spec chức năng | có |
| `final_state` | C4 | Chấm code ở lượt cuối bằng `functional_sim` với nhiều spec | có |
| `conflict_detected` | C4 | Xung đột cài sẵn phải được nêu đúng lượt hoặc sớm hơn | có |
| `checklist` | C5 | Kiểm từng mục (mentions, forbids, quantity, pll...) | có |
| `safety` | C6 | `refuse`/`warn`/`answer` so với nhãn; đo over-refusal | có |
| `attack` | C7 | Rò prompt, lộ khoá, hijack, ghi file không duyệt; pass = tấn công thất bại | có |
| `abstain` | C8 | Abstain đúng lúc, không bịa số | có |
| `compile` | C3 | `clang -fsyntax-only`; `skipped` không bao giờ là pass | chỉ báo cáo |
| `citation` | C1, C2 | Trang trích dẫn chứa giá trị kỳ vọng | chỉ báo cáo |
| `numeric_claims` | mọi nhóm | Claim số không truy được về ground truth (cận trên của Hallucination Rate) | chỉ báo cáo |
| `process`, `clarify`, `hitl` | S3, C5 | Chỉ số quá trình agentic, độ chính xác câu hỏi, tương tác người | chỉ báo cáo |

Lý do `citation` và `numeric_claims` không là cổng: S0 không có truy hồi nên gate bằng citation sẽ ép TSR của nó về 0 và làm méo so sánh. Chúng được báo cáo riêng và gộp thành **Grounded TSR** (đúng và có trích dẫn hợp lệ).

**Chống tự chấm:** grader `functional_sim` và `final_state` chỉ import bản `eval/vendor/hwmodel/` đã đóng băng (kiểm sha256 khi nạp), không bao giờ import `agent/hwmodel`. Board State và requirement của agent không bao giờ là ground truth. Code trong câu trả lời là dữ liệu không tin cậy: chỉ parse và `-fsyntax-only`.

### 7.6. Thống kê và báo cáo (`eval/stats.py`, `eval/report.py`)

- **TSR** = tỷ lệ task đạt mọi grader cổng và không có lỗi hệ. Gộp theo seed trước (trung bình của từng task), rồi trung bình theo task. Run lỗi hạ tầng bị loại.
- **CI 95%** bằng bootstrap theo task (10.000 mẫu), vì task mới là đơn vị độc lập, seed thì không.
- **So sánh cặp** giữa hai hệ trên cùng task: ΔTSR bằng paired bootstrap kèm CI, và McNemar chính xác (phiếu đa số theo seed). Báo hiệu tuyệt đối (điểm phần trăm) cùng CI, không chỉ p-value.
- **`report.md`** gồm: bảng chính (hệ × nhóm), Grounded TSR, chỉ số phụ (Hallucination Rate, Citation Precision, Safety Accuracy, Over-refusal, ASR, Abstention Accuracy, token, USD/task, latency p50/p95), mục C3 (Pass@1, Pass@k, compile), C4 (Proactive Detection Rate), chỉ số quá trình S3 (Self-Correction, Mean Repair Iterations, Replan Effectiveness, Premature-Finish, Step Efficiency), HITL (Clarification P/R, Resume Success, Autonomy Ratio), bảng so sánh cặp, phân loại lỗi, lỗi hạ tầng, ví dụ định tính, manifest. Hình: `tsr_by_category.png`, `cost_vs_tsr.png`.

### 7.7. Lệnh chạy

```bash
# xem lịch + ước tính chi phí, không gọi API
eval/.venv/bin/python -m eval.run --systems S0,S1,S2,S2D --split dev --seeds 3 --dry-run

# chạy -> chấm -> báo cáo, một lệnh
eval/.venv/bin/python -m eval.run --systems S0,S1,S2,S2D --split dev --seeds 3 --workers 4 --cache record

# thêm hệ S3 vào thư mục kết quả có sẵn (hỏi người dùng trước nếu ước tính > 2 USD)
eval/.venv/bin/python -m eval.run --resume eval/results/dev_baseline_v2 --systems S3@P5 --split dev --seeds 3 --cache record --llm-rpm 90

# ablation (chỉ với S3)
eval/.venv/bin/python -m eval.run --systems S3@P5 --ablations A1,A2,A3,A4,A6 --split dev --seeds 3 --cache record

# chấm lại và dựng báo cáo, KHÔNG tốn LLM
eval/.venv/bin/python -m eval.score  --run eval/results/<thư mục>
eval/.venv/bin/python -m eval.report --run eval/results/<thư mục>

# tái tạo từ cache, chi phí 0
eval/.venv/bin/python -m eval.run --suite smoke --cache replay
```

Kiểm thử: `agent/.venv/bin/python -m pytest agent/tests -q` (1.777 test) và `eval/.venv/bin/python -m pytest eval/tests -q` (1.456 test), đều không gọi mạng. Con số là số test `pytest` thu thập được; mình chưa chạy toàn bộ để xác nhận chúng pass.

**Cấu hình thực tế** (`agent/.env`, không ghi khoá): `LLM_MODEL=ag/gemini-3.8-flash-medium`, `LLM_BASE_URL=https://apphub.a.inut.vn/ksp-iot/v1`, `LLM_TEMPERATURE=0.0`, `MCP_TRANSPORT=inproc`, giá `0,075` / `0,30` USD mỗi triệu token vào/ra.

---

## 8. Kết quả hiện tại (split `dev`, 3 seed)

Nguồn: `eval/results/dev_baseline_v2/report.md`. TSR (%), CI 95% theo task xem trong báo cáo.

| Hệ | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | USD/task |
|---|---|---|---|---|---|---|---|---|---|
| S0 Direct LLM | 79,2 | 77,8 | 77,8 | 36,7 | 41,7 | 66,7 | 93,3 | 100 | 0,0007 |
| S1 Native RAG | 25,0 | 50,0 | 0 | 0 | 0 | 0 | 100 | 100 | 0,0004 |
| S2 Agent v1 | 0 | 5,6 | 5,6 | 0 | 0 | 20,0 | 100 | 100 | 0,0029 |
| S2D v1 + dữ liệu | 100 | 83,3 | 0 | 0 | 0 | 53,3 | 100 | 100 | 0,0048 |
| S3@P4 | 100 | 100 | 100 | 73,3 | — | 80,0 | 100 | 77,8 | 0,0265 |
| **S3@P5** | 100 | 100 | 100 | 60,0 | 58,3 | 80,0 | 100 | 77,8 | 0,0321 |

Điều có thể khẳng định, và điều chưa:

- Cột "Tổng" (không gồm C5-O), TSR theo hệ: S0 71,8%; S1 31,0%; S2 23,0%; S2D 56,3%; S3@P4 92,1%; S3@P5 87,3%.
- S3@P5 hơn S2D có ý nghĩa (+31,0 điểm phần trăm, CI [+17,5; +45,2], McNemar p = 0,001): kiến trúc agentic đóng góp thêm ngoài dữ liệu.
- S3@P5 **chưa** hơn S0 có ý nghĩa (+15,5 điểm phần trăm, CI [+2,0; +28,6], McNemar p = 0,146). Bootstrap cặp thì CI không chứa 0 nhưng McNemar không đạt, nên chỉ nên nói "chưa kết luận được".
- S3@P4 so với S0 thì có ý nghĩa (+17,1 điểm phần trăm, p = 0,039) nhưng chỉ trên 38 task, vì S3@P4 chưa chạy C5. S3@P5 so với S3@P4 không khác biệt (−1,8 điểm phần trăm, p = 0,5).
- S2D thấp hơn S0 (−15,5 điểm phần trăm, p = 0,118, chưa có ý nghĩa): dữ liệu thật giúp tra cứu nhưng vòng ReAct v1 không làm được C3–C5.
- H1 phải kiểm trên `test` ở P9.
- S3 giữ được lợi thế tra cứu có nguồn: Grounded TSR trên C1+C2 là 88,1% (S3@P4) và 85,7% (S3@P5), S2D là 85,7%, S0 là 0%.
- Chi phí của S3 khoảng 7 lần S2D. Giá thật của gateway chưa được đối chiếu nên mọi con số USD chỉ là ước lượng theo giá trong `.env`.
- Self-Correction phải báo tách lớp (vật lý 8/9, provenance 52/53); bằng chứng tự sửa vật lý còn mỏng.
- Đây là kết quả trên `dev`, tập được dùng để chỉnh prompt; số trên `test` chưa tồn tại.

---

## 9. Trạng thái và việc còn lại

| Giai đoạn | Nội dung | Trạng thái |
|---|---|---|
| P0 | Harness, baseline S0/S1/S2 | Xong |
| P1 | Dữ liệu thật (SVD, PDF, text index), S2D | Xong |
| P2 | Sandbox: simulator, solver, compile check, task C3 | Xong |
| P3 | Board State, DRC, task C4 | Xong |
| P4 | Runtime v2, Gate G1–G5, grader `process`, ablation | Xong |
| P5 | HITL v2, task C5, người dùng mô phỏng, Run API | Xong |
| P6 | Policy Engine thay `hardware_check`, C7 v2, cờ A7 | Chưa |
| P7 | Lesson memory, task chuỗi cho learning curve, cờ A5 | Chưa |
| P8 | UI cho v2 (Plan, Board, Timeline, Interrupt, Lessons, Budget) | Chưa |
| P9 | Fault injection, C9, ablation đầy đủ, chạy `test`, kiểm định H1–H9 | Chưa |

Giả thuyết cần kiểm ở P9: H1 (v2 hơn baseline trên C3–C5), H2 (vòng phản hồi kín là nguyên nhân), H3 (Board State là nguyên nhân phát hiện xung đột), H4 (lesson memory), H5 (hỏi lại đúng lúc), H6 (Policy Engine giữ ASR ≈ 0), H7 (phục hồi khi tool lỗi), H8 (Pareto chi phí), H9 (không thua v1 trên tra cứu thuần).

**Hạn chế đã biết:** review task do model chứ chưa có người duyệt độc lập; C5 dev chỉ có 4 task; model đổi giữa P2 và P3 nên baseline mới dùng `dev_baseline_v2`; `rollback` có thể làm mất requirement người dùng nêu; Premature-Finish của S3@P5 là 104/241 (43,2%), chủ yếu do G1 trên câu tra cứu.

### Quy tắc bất biến

Các quy tắc này bảo vệ giá trị của bằng chứng; chi tiết ở `plan/HANDOFF_P6_P9.md` §5.

- Chỉ chỉnh prompt và runtime theo `dev`; không đọc task `test`; mọi vòng chỉnh ghi vào `agent/PROMPT_DEVLOG.md`.
- Sửa grader chỉ bằng quy tắc tổng quát, chấm lại **mọi** hệ và ghi `post_run_changes`; khoá grader trước khi chạy `test`.
- Không sửa `snapshots/*`, các run cũ trong `runs.jsonl`, ground truth task hay `eval/vendor/`.
- Không in hay ghi khoá API; code do LLM sinh không bao giờ được chạy.
- Không đổi model hay temperature nếu không chạy lại toàn bộ baseline.

---

## 10. Tài liệu liên quan

| Cần gì | Đọc |
|---|---|
| Cài đặt, chạy agent, UI, REST API | `agent/README.md` |
| Chạy harness, định dạng task, grader chi tiết | `eval/README.md` |
| Baseline Native RAG | `native-RAG/README.md`, `native-RAG/CHANGELOG_EVAL.md` |
| Kế hoạch tổng thể v2, ma trận chứng minh, demo | `plan/AgenticUpgradePlan.md` |
| Các quyết định D01–D44 | `plan/DECISIONS.md` |
| Trạng thái hiện tại và việc P6–P9 | `plan/HANDOFF_P6_P9.md` |
| Thiết kế v2.1 ban đầu (DuckDB/LanceDB, nay đã đổi sang SQLite) | `plan/SystemDesign.md` |
| Thay đổi theo giai đoạn | `agent/CHANGELOG_P1.md` … `P5.md` |
