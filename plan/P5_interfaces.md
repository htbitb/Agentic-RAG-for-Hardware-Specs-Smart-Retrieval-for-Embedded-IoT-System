# P5 — Hợp đồng giao diện (HITL runtime ↔ SimulatedHuman/adapter ↔ C5 graders)

> Nội bộ session P5 (brief `plan/P5_Handoff.md`, ràng buộc `plan/DECISIONS.md` D33–D40). Mọi subagent đọc file này làm nguồn sự thật về TÊN và HÌNH DẠNG dữ liệu.
> Thư mục làm việc: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project`. Python agent: `agent/.venv/bin/python`; eval: `eval/.venv/bin/python`.
> Test: `agent/.venv/bin/python -m pytest agent/tests -q -p no:cacheprovider` (baseline 1690), `eval/.venv/bin/python -m pytest eval/tests -q -p no:cacheprovider` (baseline 976).
> **Không test nào được gọi mạng/LLM thật.** Không sửa `snapshots/`, `eval/results/**/runs.jsonl`, `eval/vendor/`, ground truth task có sẵn. Không đọc task `split: test` của C1–C4, C6–C8 (D05).

## 1. Interrupt / Resume (runtime, do controller viết; adapter/Run API/SimulatedHuman dựa vào)

`rt.ask(question, session_id, seed)` và `rt.resume(run_id, interrupt_id, decision, payload)` trả `dict` như P4_interfaces §3 với `status` có thêm `"interrupted"`:

```python
{"run_id", "project_id", "turn", "status": "interrupted", "answer": "", "interrupt": INTERRUPT, "events": [...], "usage": {...}, ...}
INTERRUPT = {"id": "i_ab12cd34", "kind": "choice" | "clarify" | "approval",
             "tool": "ask_human" | "write_config_file", "tool_call_id": str,
             "question": str,                       # câu hỏi/mô tả hiển thị cho người
             "why_needed": str,                     # lý do agent cần (choice/clarify); "" cho approval
             "options": [{"id": "A", "label": str, "pros": str, "cons": str}, ...] | None,   # choice: 2–4 phương án
             "payload": {...}}                      # approval: {"filename", "content", "diff", "bytes", "overwrites": bool}; còn lại {}
```

`resume` trả cùng dạng (có thể lại `interrupted` với interrupt mới, hoặc `answered|refused|blocked|escalated|error`). Tham số `decision`/`payload` theo `kind`:

| kind | decision | payload |
|---|---|---|
| `clarify` | `"answer"` | `{"answer": str}` (văn bản người dùng; được ghi vào Board State và làm bằng chứng loại (c) cho Gate) |
| `clarify` | `"unknown"` | `{"answer": "Không biết, hãy tự chọn phương án hợp lý"}` (hoặc chuỗi tuỳ ý) |
| `choice` | `"choose"` | `{"option": "<id hoặc label>", "comment": str?}` → runtime gọi `record_decision(by="human")` |
| `choice` | `"unknown"` | `{"answer": str}` |
| `approval` | `"approve"` | `{}` → file được ghi (sandbox + audit), kết quả trả agent như observation |
| `approval` | `"reject"` | `{"feedback": str}` → góp ý thành observation, runtime chèn REPLAN_REQUIRED (nếu A1 bật) |

Resume với `interrupt_id` sai/đã dùng hoặc run không ở trạng thái INTERRUPTED ⇒ ném `ResumeError(ValueError)` (thông điệp rõ), KHÔNG chạy gì. `resume(run_id)` (không interrupt_id) chỉ dùng để chạy tiếp run bị kill giữa chừng; gọi nó trên run đang INTERRUPTED ⇒ `ResumeError`.
Ngân sách `ask_human` mỗi run: `Budgets.ask_human` (mặc định 3, `AGENT_BUDGETS='{"ask_human": 3}'`). Cờ A6 `-HITL` (`AGENT_ABLATIONS=A6`): `ask_human` ẩn, `write_config_file` tự duyệt (không interrupt); `Ablations.variant()` = `"-HITL"`.

Sự kiện trace mới (đủ `run_id, turn, step, seq, ts`):
* `interrupt_raised`: `interrupt_id, kind, tool, question, why_needed, options, payload (approval: cắt nội dung 400 ký tự), asks_used`
* `resumed` (sau interrupt): `interrupt_id, kind, decision, payload (cắt 400)`; (sau kill: như P4 `{from_seq}`, không có `interrupt_id`)
* `human_decision` (choice): `interrupt_id, option, decision_id`
* `file_written` (approval approve / A6 auto): `filename, approver ("human"|"auto:A6"), bytes`
* `ask_limit_reached`: `kind` — agent gọi ask_human khi hết lượt.

## 2. SimulatedHuman (`eval/sim_human.py`, do `c5-eval` viết)

```python
class SimulatedHuman:
    def __init__(self, policy: dict | None, hidden_info: list[dict] | None = None): ...
    def respond(self, interrupt: dict) -> HumanReply            # deterministic, không LLM, không mạng
    def detect_question(self, answer_text: str) -> str | None   # baseline: câu hỏi hướng tới người dùng trong câu trả lời (None nếu không có)
    def reply_to_text(self, answer_text: str) -> HumanReply | None   # baseline: HumanReply (decision="answer") nếu detect_question != None
    records: list[dict]                                         # mọi lần hỏi/đáp theo thứ tự
@dataclass
class HumanReply: decision: str; payload: dict; record: dict
# record = {"kind": "choice|clarify|approval|text", "question": str, "matched": [hidden_info ids], "necessary": bool, "answered": bool,
#           "decision": str, "answer": str, "source": "interrupt|baseline_text", "index": int}
```
Quy tắc: `human_policy` (xem §3): `approval` (approve | {reject: feedback}) → decision `approve`/`reject`; `choice: {prefer: "<từ khoá>"}` → chọn option đầu tiên có `prefer` (không phân biệt hoa/thường) trong label/pros/cons; không khớp ⇒ `unknown`; `clarify` khớp câu hỏi với `hidden_info[*].keywords` (đủ một từ khoá = khớp; khớp nhiều mục ⇒ trả lời gộp theo thứ tự mục); không khớp ⇒ `unknown` với câu "Không biết, hãy tự chọn phương án hợp lý" và `record.necessary=False` (câu hỏi thừa). Quá `max_answers` trả lời có nội dung ⇒ các câu sau trả `unknown` (ghi `answered=False`). Không bao giờ để lộ thông tin ẩn chưa được hỏi.

## 3. Định dạng task C5 (schema do `c5-eval` cài trong `eval/schema.py`; task do `c5-author` viết)

```yaml
- id: C5-001
  category: C5
  split: dev | test           # gán bằng seed cố định TRƯỚC khi chạy bất kỳ hệ nào; ~4 dev, 8 test
  difficulty: hard
  chips: [stm32g474, esp32]
  tags: [system_goal, missing_info, ...]
  turns:
    - user: "<mục tiêu cấp hệ thống, KHÔNG chứa thông tin ẩn; yêu cầu phân rã ≥ 5 bước>"
  human_policy:
    approval: approve
    choice: {prefer: "level shifter"}
    clarify: {hse_hz: "The board has an 8 MHz crystal on HSE."}      # khoá = id trong hidden_info; giá trị = câu trả lời của người dùng
    max_answers: 3
  hidden_info:                      # [] hoặc thiếu cho task ĐỦ thông tin
    - id: hse_hz
      keywords: ["HSE", "crystal", "oscillator", "external clock"]   # câu hỏi chứa ≥ 1 từ khoá (không phân biệt hoa/thường) ⇒ hỏi đúng mục này
      required: true
      value_patterns: ["\\b8\\s*MHz\\b"]    # regex: nếu câu trả lời của hệ ĐOÁN trùng giá trị ẩn mà không hỏi ⇒ clarify ghi "guessed_correctly" (báo riêng, không gate)
  expected:
    spec: [...]                     # chỉ khi có code (functional_sim/final_state, SPEC_KEYS hiện có; clock spec thêm khoá tuỳ chọn hse_hz)
    checklist: [CHECKLIST_ITEM, ...]
  graders: [checklist, clarify, functional_sim?, final_state?]   # checklist (+functional_sim) gate; clarify KHÔNG gate
  review_status: verified
  provenance: {reference_solution: {...}, reference_calc: "phép tính tay có trang RM/DS/số liệu", wrong_variants: [...], evidence: [...]}
```

**`CHECKLIST_ITEM`** (tất cả không phân biệt hoa/thường, áp trên TOÀN BỘ câu trả lời cuối kể cả khối code; `id` duy nhất trong task; `desc` bắt buộc, người đọc được):

| `type` | Trường | Đạt khi |
|---|---|---|
| `mentions` | `any_of: [regex]` | ≥ 1 regex khớp |
| `forbids` | `patterns: [regex]` | không regex nào khớp |
| `quantity` | `patterns: [regex]` (mỗi regex có nhóm có tên `(?P<v>số>)` và tuỳ chọn `(?P<u>đơn vị>)`), `unit` (đơn vị mặc định nếu regex không bắt, ví dụ `MHz`, `V`, `uA`, `mA`, `Hz`, `bps`), `min`, `max` (đã đổi về đơn vị chuẩn SI: Hz, V, A, bps — hoặc ghi `unit_out` để chọn), `match: any|all` (mặc định `all`), `required: true` | có ≥ 1 khớp (nếu `required`) và các khớp thoả `min ≤ giá trị ≤ max` theo `match` |
| `pll` | `hse_hz`, `sysclk_hz`, `tol_pct` | câu trả lời hoặc code chứa cấu hình PLL (PLLM/PLLN/PLLR, dạng văn bản `PLLM = 2` hoặc ghi thanh ghi `RCC->PLLCFGR`) cho SYSCLK = `hse_hz`/M×N/R trong dung sai và ≤ 170 MHz; xác định, không dùng simulator |
| `one_of_groups` | `groups: [[regex,...], ...]`, `min_groups` | ≥ `min_groups` nhóm có ít nhất 1 regex khớp (kiểm "đưa đánh đổi / ≥ 2 phương án") |
| `bullets_min` | `count` | số bước đánh số/gạch đầu dòng ≥ `count` (kiểm phân rã ≥ 5 bước) |

Grader `checklist`: `{"pass": all items pass, "reasons": ["item <id>: <lý do>"], "details": {"items": {id: bool}}}`.
Grader `clarify` (không gate): `{"pass": True (luôn), "details": {"precision", "recall", "asked": n, "necessary": n, "required": n, "covered": [ids], "missed": [ids], "unnecessary": n, "guessed_correctly": [ids], "asked_from": {"interrupt": n, "baseline_text": n}}}` — tính từ `trace` các sự kiện `human_reply`.
Sự kiện trace do RUNNER/adapter ghi cho mọi hệ: `{"type": "human_reply", "turn": int, "kind", "question", "matched": [...], "necessary": bool, "answered": bool, "decision", "source": "interrupt|baseline_text"}`.

**Biến thể `oracle-info`** (suy ra TẤT ĐỊNH từ task thường, không viết tay): task `C5-xxx` có `hidden_info` sinh thêm task `C5-xxx-O` (cùng split; `tags += [oracle_info]`): lượt đầu = `turns[0].user` + `" Additional information from the user: "` + các `human_policy.clarify[id]` nối bằng khoảng trắng (theo thứ tự `hidden_info`); `human_policy.clarify = {}` (mọi câu hỏi đều thừa); `graders` bỏ `clarify`. Task đủ thông tin không có biến thể oracle. Loader: `load_tasks(root, ..., oracle=False)` mặc định KHÔNG trả `-O`; `oracle=True` trả cả hai; `eval.score` luôn nạp cả hai; `eval.run --c5-oracle` chọn chạy.

## 4. Adapter / runner (controller viết phía S3; `c5-eval` viết phía runner)

`TurnResult(answer, status, interrupt)`; `status` có thêm `"interrupted"` và `interrupt` = INTERRUPT (§1). Adapter hỗ trợ HITL có thêm
`resume(interrupt_id: str, decision: str, payload: dict) -> TurnResult`. Runner (mỗi (hệ, task, seed), cho mỗi lượt người dùng):

```
turn = adapter.send(user_msg)
while turn.status == "interrupted":             # chỉ adapter v3
    reply = human.respond(turn.interrupt); runner.log_human_reply(reply)        # ghi sự kiện human_reply vào trace
    turn = adapter.resume(turn.interrupt["id"], reply.decision, reply.payload)  # số vòng tối đa = policy.max_answers + 3 (chống vòng lặp)
# baseline (adapter không có resume): nếu human.detect_question(turn.answer) và task có human_policy.clarify ⇒ gửi reply.payload["answer"] như lượt người dùng KẾ TIẾP
# (tối đa max_answers lần; không tính là một lượt của task; ghi human_reply source=baseline_text); hệ có HITL (S3@P5) KHÔNG áp quy tắc này lên văn bản.
```
Nếu một hệ kết thúc task mà vẫn `interrupted` (vượt giới hạn vòng) ⇒ gắn lỗi `error:hitl_loop` (lỗi hệ, không phải hạ tầng).

## 5. Chỉ số HITL (grader `hitl` hoặc mở rộng `process`, báo cáo — KHÔNG gate)

* **Clarification Precision** = số câu hỏi `necessary` / tổng số câu hỏi `clarify` (+ câu hỏi văn bản của baseline); **Recall** = số `hidden_info` bắt buộc được hỏi (`covered`) / tổng số `hidden_info` bắt buộc. Báo theo hệ, theo nửa thiếu/đủ thông tin (task đủ thông tin: chỉ báo số câu hỏi thừa/task).
* **Resume Success** = số lần resume mà run tiếp tục tới một trạng thái cuối hợp lệ (answered/escalated/lại interrupted hợp lệ, không `error`) / số interrupt (chỉ v3).
* **Autonomy Ratio** = số tool call của agent (không internal) trên tổng (tool call + số interrupt); số can thiệp trung bình = interrupt/task.
* Số `ask_human` thừa (interrupt `clarify` với `necessary=False`), **Replan sau Reject** = số `plan_updated` xuất hiện sau `resumed(decision=reject)`.
* Self-Correction tách **vật lý** (G2/G3/G5/simulator/DRC) / **provenance** (G1) — định nghĩa D35; áp dụng cho S3@P4 (tính lại từ trace) và S3@P5.
