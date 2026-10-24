# P4 — Hợp đồng giao diện giữa các phần (runtime ↔ gate ↔ eval)

> Tài liệu nội bộ của session P4 (brief: `plan/P4_Handoff.md`, ràng buộc: `plan/DECISIONS.md` D32). Mọi subagent đọc file này làm nguồn sự thật về TÊN và HÌNH DẠNG dữ liệu.
> Không phải git repo: không commit. Thư mục làm việc: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project`. Python của agent: `agent/.venv/bin/python`; của eval: `eval/.venv/bin/python`.
> Test: `agent/.venv/bin/python -m pytest agent/tests -q -p no:cacheprovider` (baseline 1212 passed), `eval/.venv/bin/python -m pytest eval/tests -q -p no:cacheprovider` (baseline 826 passed). **Không test nào được gọi mạng/LLM thật** (D22).

## 1. Bố cục mã mới (đường dẫn từ gốc dự án)

```
agent/agent/runtime/{__init__,state,checkpoint,trace,flags,control_tools,loop,factory}.py   # phần của controller (session chính)
agent/agent/gate/{__init__,types,codeblocks,provenance,functional,drc_gate,safety,compile_gate}.py   # Gate v3 (subagent G)
agent/agent/prompts/system_v3.md                                                           # controller
agent/agent/scripted.py                                                                    # ScriptedPolicy (chỉ test)
eval/graders/process.py, eval/adapters/agent_v3{,_worker}.py, report.py, run.py            # subagent E / controller
```

## 2. Gate v3 (`agent/agent/gate/`)

### 2.1 Kiểu dữ liệu (`gate/types.py`)

```python
@dataclass(frozen=True)
class Finding:
    gate: str                 # "G1".."G5"
    code: str                 # xem 2.4
    where: str                # vị trí đọc được: "answer", "code block 1, op 3 (TIM1->PSC = 0)", "requirement R1", "board.pins.PA8"
    expected: str
    actual: str
    hint_source: str          # chỉ tool/nguồn giúp sửa: "simulate_register_writes", "get_register_bitfields(TIM1)", "RM0440 p.1279", "solve_timer_config"
    severity: str = "error"   # error | warning | unknown   (unknown = không kiểm được; KHÔNG bao giờ tính là pass)
    kind: str = "local"       # local (agent tự sửa) | structural (cần lập lại kế hoạch -> REPLAN_REQUIRED)
    waivable: bool = False    # có thể xin miễn qua finish(waived_requirements) (chỉ mã trong GateFlags.waivable)
    def to_dict(self) -> dict    # đủ trường, JSON-serializable

@dataclass
class GateReport:
    gates: dict[str, str]     # "G1".."G5" -> "pass" | "fail" | "na" | "skipped" | "off"   (off = tắt bởi cờ ablation; na = không áp dụng, vd không có khối code)
    findings: list[Finding]
    sim: dict | None          # tóm tắt lần mô phỏng của G2: {"ok", "violations":[codes], "effects":[{pin,signal,pwm_hz,duty_pct,...}], "unmodeled":[...], "initial", "n_ops"}
    details: dict             # tự do (vd {"claims_checked": 7, "supported_by": {...}, "unknown_codes": [...]})
    @property passed -> bool  # True iff không có finding severity=="error" và không gate nào "fail"
    def errors(self) -> list[Finding]; def failed_codes(self) -> list[str]  # mã của các finding severity error, không trùng, giữ thứ tự
    def to_dict(self) -> dict  # JSON-serializable (dùng để ghi trace + checkpoint)
    def feedback(self) -> dict  # phần trả cho agent: {"passed", "gates", "findings":[Finding.to_dict() chỉ error/unknown, tối đa 8], "hint": str}
```

### 2.2 Điểm vào (`gate/__init__.py`)

```python
@dataclass
class GateFlags:
    g1: bool = True; g2: bool = True; g3: bool = True; g4: bool = True; g5: bool = True
    board: bool = True               # False (A2): không đọc Board State -> G3 off, G2 không có requirement (chỉ kiểm violation)
    strict_v1_provenance: bool = False   # True (A3): G1 chạy đúng verifier v1 (agent/verifier.py::verify) thay cho G1 mới
    waivable: tuple[str, ...] = ("G2-UNMODELED", "G5-SKIPPED")   # chỉ các mã này được miễn bằng finish(waived_requirements)

@dataclass
class GateContext:
    answer: str                       # câu trả lời ứng viên (văn bản người dùng sẽ nhận, gồm khối code)
    user_texts: list[str]             # mọi tin nhắn người dùng của phiên (bằng chứng loại (c))
    observations: list[dict]          # [{"tool","args","result"}] các tool call của agent trong lượt hiện tại (bằng chứng loại (a),(b))
    prior_answers: list[str] = ()     # câu trả lời đã được Gate chấp nhận ở các lượt trước (bằng chứng; không kiểm lại)
    waived: list[dict] = ()           # [{"id": "R2", "reason": "..."}] từ finish(waived_requirements)
    chip: str | None = None           # chip mục tiêu (từ Board State/đề); None -> "stm32g474" cho mô phỏng
    initial: str | dict = "reset"     # trạng thái khởi đầu cho simulate_register_writes (xem 2.3)
    hse_hz: int | None = None

class Gate:
    def __init__(self, call: Callable[[str, dict], dict], flags: GateFlags | None = None): ...
    def run(self, ctx: GateContext) -> GateReport: ...
```

`call(tool_name, args) -> dict` là cầu nối tới ToolHub (đúng như agent gọi tool; trả `{"error": ...}` khi lỗi — Gate KHÔNG ném khi tool lỗi: mỗi tool lỗi thành finding `severity="unknown"` hoặc gate `skipped`, không bao giờ pass). Gate dùng các tool: `get_board_state`, `run_drc`, `analyze_c_code`, `simulate_register_writes`, `compile_check`, `get_electrical_specs`, `get_clock_limits` (khi cần). Gate không import `config`, không đọc env, không ghi file.

### 2.3 Quy tắc từng cổng

* **G1 Provenance** (`provenance.py`, tái dùng ý tưởng `agent/verifier.py`; V1–V4 vẫn giữ): chỉ kiểm PHẦN VĂN XUÔI (bỏ khối code ```...``` và mã nội tuyến; giá trị trong khối code do G2 kiểm).
  Nguồn hợp lệ của một con số/địa chỉ: (a) kết quả tool tra cứu (`hw-knowledge`, `text-manual`), (b) OUTPUT của solver/simulator/`set_clock_config`/`get_board_state`/`run_drc` (kể cả `final_registers`, `effects`, `clocks`, `derived`), (c) tin nhắn người dùng (`user_texts`) + `prior_answers`.
  Việc phải làm: (1) `V1` giá trị có đơn vị (dùng `ingestion.unit_normalizer.find_quantities`) phải có trong bằng chứng, HOẶC suy ra được bằng phép tính đơn giản từ bằng chứng (±1, nhân/chia hai số bằng chứng, sai số tương đối 0,5 %) → chấp nhận kèm ghi chú "derived"; (2) hex: địa chỉ ngoại vi (≥ 0x2000_0000 hoặc nằm trong bất kỳ kết quả tra cứu) phải có trong bằng chứng loại (a); hex NGẮN (< 0x1_0000_0000 và không phải địa chỉ ngoại vi) chấp nhận nếu bằng GIÁ TRỊ một số trong bằng chứng loại (b)/(c) hoặc `final_registers` (sửa lỗi V2: BRR `0x683` bị coi là địa chỉ); (3) trích dẫn `[doc p.N]` phải do tool trả về (như V3), và thanh ghi `svd_only` (kết quả tool có `doc` dạng `<CHIP>_SVD` và `page` null) được trích `[<doc>]` hoặc `[<doc> SVD]` hợp lệ; (4) bắt buộc có ít nhất một trích dẫn CHỈ KHI câu trả lời có claim được hỗ trợ duy nhất bởi bằng chứng loại (a); (5) V4 field-type confusion giữ nguyên; (6) câu trả lời từ chối/"Insufficient evidence" được chấp nhận (ABSTAIN như v1).
  `GateFlags.strict_v1_provenance=True`: gọi `agent.verifier.verify(question, answer, [o["result"] for o in observations])` (câu hỏi = nối `user_texts`) và đổi mỗi issue `V1/V2/V3/V4` thành Finding `G1-V1..G1-V4`.
* **G2 Functional** (`functional.py`): lấy mọi khối code C của `ctx.answer` (`codeblocks.extract_c_code`, viết ĐỘC LẬP với `eval/graders` — không import `eval`), `analyze_c_code(code, chip)` → nếu `ok` false: finding `G2-UNSUPPORTED` (local, error) nêu dòng + construct; ngược lại `simulate_register_writes(chip, ops, initial, hse_hz)`.
  `initial`/`hse_hz` do runtime đặt vào `ctx` (ưu tiên: trường `initial`/`hse_hz` của requirement > đối số của lần `simulate_register_writes` gần nhất của agent > "reset").
  Mọi violation mức `error` của simulator → finding `G2-<mã sim>` (vd `G2-SIM-TIM-MOE`), local; chỉ violation LIÊN QUAN requirement (cùng quy tắc "chỉ violation gắn với tín hiệu/ngoại vi của requirement hoặc tại một lệnh") — lỗi cuối chuỗi của kênh không nằm trong requirement là vô hại.
  Đọc requirement từ Board State (`get_board_state(section="requirements")` → `data` là list) nếu `flags.board`; kiểu được kiểm: `pwm` {pin|pins, signal?, freq_hz, duty_pct?, tol_pct=1.0, duty_tol_pp=tol_pct}, `uart` {instance, baud, tol_pct=2.0, tx_pin?, rx_pin?}, `i2c` {instance, scl_hz, tol_pct=5.0, scl_pin?, sda_pin?}, `clock` {sysclk_hz, hclk_hz, pclk1_hz, pclk2_hz, *_min_hz, *_max_hz, tol_pct=0.1}. Sai lệch → `G2-FREQ`, `G2-DUTY`, `G2-BAUD`, `G2-SCL`, `G2-CLOCK`, `G2-PIN`, `G2-NO-EFFECT` (không thấy hiệu ứng cho requirement), `G2-INACTIVE` (kênh tồn tại nhưng không chạy, nêu lý do sim). Requirement kiểu mô phỏng được nhưng hiệu ứng `modeled=false`, hoặc kiểu KHÔNG mô hình hoá (`spi`, `adc`, `dac`, `can`, `gpio_out`, `gpio_in`) khi câu trả lời có code → `G2-UNMODELED` (local, error, `waivable=True`; không bao giờ pass). `power`/`other`: G2 bỏ qua. Requirement có id trong `ctx.waived` (kèm `reason` không rỗng) và mã nằm trong `flags.waivable` → hạ thành warning (ghi `details["waived"]`); mã không được phép miễn → vẫn error, thêm ghi chú.
  Không có requirement nào (hoặc `flags.board=False`) → chỉ kiểm cú pháp phân tích + violation cấp lệnh; ghi `details["requirements_checked"]=0`. Không có khối code → gate `na`; nếu có requirement mô hình hoá được thì thêm warning `G2-NO-CODE` (không chặn).
  `report.sim` điền từ lần mô phỏng cuối (compact, JSON-serializable; không nhét `final_registers` dài quá 40 mục).
* **G3 Board DRC** (`drc_gate.py`): `flags.g3 and flags.board`; gọi `run_drc`; mỗi violation severity `error` → Finding (code = mã DRC, vd `DRC-PIN-01`); `unknown` (vd DRC-PWR-01 với STM32G474 luôn unknown vì DB không có số dòng) → Finding severity `unknown` (KHÔNG chặn, KHÔNG tính pass, ghi `details["unknown_codes"]`); `warning` → warning. Gate `pass` nếu không có error. Bảng `kind`: DRC-PIN-01/02/03, DRC-CLK-01, DRC-ELEC-01, DRC-PWR-01 = `structural`; DRC-CLK-02, DRC-REQ-01 = `local`. Không có Board State (chưa `set_target`) → gate `na`.
* **G4 Safety** (`safety.py`): (i) từ Board State: VDD của target > Absolute Maximum (`get_electrical_specs`), nets nối 5 V vào chân không FT (DRC-ELEC-01 đã bắt → G4 chỉ thêm finding `G4-5V-NON-FT` nếu thiết bị/net khai báo ≥ 4,0 V tới chân không FT mà DRC không báo, đừng nhân đôi lỗi), (ii) từ mô phỏng của G2: violation mã `SIM-CLK-LIMIT*`/clock vượt trần → `G4-CLOCK-LIMIT`, (iii) từ văn xuôi: câu khuyên áp một điện áp lên chân/nguồn vượt Absolute Maximum — dùng `agent.guardrail.parse_hardware_requests` + `evaluate_hw` trên câu KHÔNG có phủ định/cảnh báo (bảo thủ: ưu tiên không dương giả; mức `warning` nếu không chắc). Mọi kiểm chứng dùng `get_electrical_specs`/`get_clock_limits` hoặc dữ liệu đã có trong `observations`.
* **G5 Compile** (`compile_gate.py`): `flags.g5`: `compile_check(code)` → `ok` ⇒ pass; `error` ⇒ finding `G5-COMPILE` (local, error, kèm dòng/cột/thông điệp đầu tiên); `skipped` ⇒ gate `skipped` + finding `G5-SKIPPED` severity `unknown` (`waivable`), KHÔNG pass nhưng không chặn khi thiếu toolchain.
* Phản hồi lỗi cho agent: `GateReport.feedback()`; `Finding` luôn đủ năm trường `{code, where, expected, actual, hint_source}` (thêm `gate`, `severity`, `kind`).

### 2.4 Bảng `kind` (local vs structural) — runtime dựa vào `Finding.kind`

structural: mọi finding G3 (trừ DRC-CLK-02, DRC-REQ-01), `G4-*`. local: G1-*, G2-*, G5-*, DRC-CLK-02, DRC-REQ-01.

## 3. Runtime (`agent/agent/runtime/`) — API công khai dùng bởi worker eval và demo

```python
from agent.runtime import build_runtime          # factory.py
rt = build_runtime(llm=None, transport="inproc", ablations=(), budgets=None, checkpoint_db=None, trace_dir=None)  # env: AGENT_ABLATIONS="A1,A3", AGENT_CHECKPOINT_DB, AGENT_TRACE_DIR
out = rt.ask(question: str, session_id: str = "default", seed: int | None = None)   # một lượt người dùng = một run; project_id == session_id
rt.resume(run_id: str) -> dict       # chạy tiếp một run bị dừng giữa chừng (kill) từ checkpoint
rt.close()
```

`ask` / `resume` trả `dict`:

```python
{"run_id", "project_id", "turn", "question", "answer": str,
 "status": "answered" | "refused" | "blocked" | "escalated" | "error",     # adapter eval ánh xạ escalated -> "answered"
 "events": [event, ...],            # trace chuẩn hoá của RIÊNG lượt này (4)
 "usage": {"tokens_in", "tokens_out", "usd", "llm_calls", "tool_calls", "steps"},
 "plan": [PlanStep...], "board_state": dict | None,      # trạng thái Board State cuối lượt (get_board_state) nếu bật
 "gate": GateReport.to_dict() | None,                    # gate cuối cùng
 "escalation": {"reason", "code", "unmet_requirements": [...], "tried": [...]} | None,
 "files": {}, "errors": [str]}      # errors: "infra:..." cho lỗi hạ tầng LLM (adapter gắn tiền tố), "error:..." cho lỗi của hệ
```

## 4. Sự kiện trace chuẩn hoá (Phụ lục D, mở rộng) — JSON, mỗi sự kiện có `run_id`, `turn`, `step`, `seq` (tăng dần trong run), `ts`

| `type` | trường riêng |
|---|---|
| `run_started` | `goal`, `project_id`, `ablations`, `budgets` |
| `guardrail` | `stage` ("input" \| "hardware_safety"), `verdict`/`blocked`, `flags` |
| `llm_call` | `tokens_in`, `tokens_out` |
| `tool_call` | `tool`, `server`, `permission`, `args` (cắt 400 ký tự), `ok` (bool), `error` (str\|None), `summary` (cắt 400), `security_flags`, `internal` (true khi do Gate/runtime gọi, không do agent) |
| `board_mutation` | `tool`, `ok`, `version` (str/int\|None), `code` (mã lỗi board nếu bị từ chối) |
| `sim_result` | `tool` ("simulate_register_writes" \| "gate"), `source` ("agent" \| "gate"), `pass` (bool), `violations` (list mã), `effects` (list `{pin, signal, pwm_hz, duty_pct,...}` rút gọn), `unmodeled`, `artifact` ("draft#N") |
| `plan_updated` | `rationale`, `diff` = `{"added":[...], "removed":[...], "changed":[...]}` (chuỗi mô tả/ id), `plan` (đầy đủ) |
| `gate_result` | `trigger` ("finish" \| "draft"), `attempt` (1…), `gates` (G1..G5 -> trạng thái), `findings` (list `{gate,code,severity,kind,where}`), `passed`, `artifact` |
| `replan_required` | `reason`, `code` |
| `finish` | `implicit` (bool; true khi trả lời bằng văn bản không gọi tool `finish`), `accepted` (bool), `gate` (G1..G5 -> trạng thái), `waived` (list id), `attempt` |
| `escalated` | `reason` ("repeated_error" \| "budget:steps\|tokens\|usd\|wall_s"), `code`, `unmet_requirements`, `tried` |
| `refused` | `reason` |
| `resumed` | `from_seq` |
| `done` | `status`, `answer_chars` |

Sự kiện nhận diện "trace v3": tồn tại sự kiện có `type == "run_started"`. Hệ không có sự kiện đó → chỉ số quá trình `N/A`.

## 5. Chỉ số quá trình (grader `process`, `eval/graders/process.py`; báo cáo, KHÔNG gating)

Tính trên `RunResult.trace` (sự kiện phẳng, gom theo `(run, turn)` và trong cả task). Định nghĩa:
* **Chuỗi kiểm tra** của một lượt = các sự kiện `sim_result` (cả `source="agent"` có `artifact`) và `gate_result` theo thứ tự `seq`. Một lượt "có sản phẩm" nếu chuỗi không rỗng.
* **Self-Correction Rate** (cấp task, gộp mọi lượt): task có sản phẩm mà kiểm tra ĐẦU TIÊN fail (pass=false / passed=false) và kiểm tra CUỐI CÙNG pass, / số task có kiểm tra đầu tiên fail. Báo kèm tỷ lệ "sản phẩm cuối cũng pass grader độc lập (tsr_pass)" (nối với điểm TSR của run).
* **Mean Repair Iterations**: với task tự sửa thành công: số `gate_result`+`sim_result` fail từ kiểm tra đầu tiên đến lần pass cuối cùng; trung bình.
* **Replan count** = số `plan_updated` xuất hiện SAU một `replan_required`/`gate_result` fail (tức lập lại kế hoạch có lý do) + tổng `plan_updated`; **Replan Effectiveness** = số `replan_required` mà sau đó run kết thúc `accepted=true`/`tsr_pass` / tổng `replan_required` (báo cả hai cách: kết thúc được chấp nhận; tsr_pass).
* **Premature-Finish Rate** = số `finish` có `accepted=false` / tổng `finish` (kể cả ngầm); báo thêm: tỷ lệ task kết thúc `escalated`.
* **Step Efficiency**: số `tool_call` (internal=false) / số task THÀNH CÔNG (tsr_pass), và tỷ lệ gọi trùng (cùng `tool` + `args` đã gọi trước đó trong cùng lượt).
* Ngoài ra: `plan_updated` ≥ 1 trên task thiết kế (C3/C4) (%), số lượt `escalated`, phân bố mã gate fail.
* Run không có trace v3 ⇒ `N/A`.

## 6. Adapter / worker eval

Worker `eval/adapters/agent_v3_worker.py` (python -I -B, `agent/.venv/bin/python`) giao thức JSONL giống `agent_v1_worker.py`; dòng init thêm `{"ablations": ["A1"], "budgets": {...}|null}`; mỗi yêu cầu `{"user": "..."}` → trả kết quả của `rt.ask(...)` (xem 3) cộng `llm_calls`, `flags`. Thư mục tạm của run chứa: `memory.sqlite`, `audit.jsonl`, `workspace_out/`, `board_state.sqlite` (env `BOARD_STATE_DB`), `checkpoints.sqlite` (env `AGENT_CHECKPOINT_DB`), `trace/` (env `AGENT_TRACE_DIR`). `BOARD_STATE_PROJECT` không đặt (runtime tự truyền `project_id`).
Hệ tên `S3@P4`; ablation đặt trong `RunResult.variant` ("", "-Planner", "-BoardState", "-Sandbox", "-Reflection").
