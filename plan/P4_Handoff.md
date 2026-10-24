# P4 HANDOFF — Agent Runtime v3 + Verification Gate v3 (W4, W5) → hệ S3

> Tài liệu này là **brief độc lập** cho một Claude Code session mới. Đọc hết trước khi làm.
> Tham chiếu: `plan/AgenticUpgradePlan.md` §3.2 (state machine), §4 W4, W5, §5 (ma trận chứng minh), §6 D1–D2, §7.2 (ablation),
> §7.5–7.6 (grader `process`, chỉ số quá trình), Phụ lục A–D; `plan/DECISIONS.md` (**D32 là ràng buộc chính**; D05, D19, D20, D25,
> D28, D30 vẫn áp dụng); kết quả trước: `eval/results/dev_baseline_v2/report.md`, ledger `plan/P3_progress.md`, `eval/README.md`.
> Thư mục làm việc: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project` (gốc dự án). Không phải git repo.

---

## 1. Mục tiêu P4

Đây là giai đoạn **biến hệ thành agent thật**: thay vòng `for step in range(MAX_STEPS)` của v1 bằng **runtime có trạng thái, có kế hoạch,
có điều kiện dừng được kiểm chứng**, nối 4 server (tra cứu, văn bản, sandbox, Board State), và thay verifier "đếm số" bằng **Gate v3**
chấp nhận giá trị suy ra khi có bằng chứng từ solver/simulator. Kết quả là hệ **S3@P4**.

Vấn đề cụ thể phải giải (D23, D30): trên dev v2, S2D đạt C1 95.8% / Grounded 83.3% nhưng **C3 0%, C4 0%** — 45/48 lượt C4 kết thúc bằng
"step budget exhausted before a verified answer" vì verifier v1 từ chối mọi giá trị tự tính và agent không có công cụ thực thi.
S0 (LLM trần) đạt C3 77.8%, C4 36.7%. **Mục tiêu của S3: vượt S0 ở C3/C4 mà không mất lợi thế tra cứu có nguồn của S2D.**

**Tiêu chí thoát P4:**
1. Runtime v3 (state machine §3.2 trừ nhánh INTERRUPTED/HITL), `AgentState` checkpoint SQLite mỗi bước; **kill tiến trình rồi resume** cho kết quả tương đương (test).
2. Tool điều khiển `update_plan`, `finish`; `REPLAN_REQUIRED`; ngân sách + `ESCALATED` (D32).
3. Gate v3 G1–G4 (+ G5 compile tuỳ chọn) với phản hồi lỗi có kiểu `{code, where, expected, actual, hint_source}`.
4. Demo **D1** chạy end-to-end bằng **LLM thật**, trace chuẩn hoá (Phụ lục D) cho thấy: sim fail → sửa → sim pass → finish gate pass.
5. Grader `process` + chỉ số quá trình (Self-Correction Rate, Mean Repair Iterations, Replan count, Premature-Finish Rate, Step Efficiency).
6. Cờ ablation A1–A4 chạy được (D32). `snapshots/agent_p4/` + hệ **S3@P4** chạy trên **toàn bộ dev** (C1–C4, C6–C8) × 3 seed trong
   `eval/results/dev_baseline_v2/report.md`, có so sánh cặp S3@P4 vs S2D, S3@P4 vs S0.

**Ngoài phạm vi:** `ask_human`/interrupt/resume theo quyết định người (P5); policy engine, taint, C7 v2 (P6); Lesson/Project memory (P7);
UI panel (P8 — chỉ cần UI cũ không vỡ); ablation đầy đủ và tập `test` (P9).

---

## 2. Bối cảnh cần biết

- **Model:** `ag/gemini-3.8-flash-medium` qua gateway OpenAI-compatible (`agent/.env`; D27). Giá thật của gateway **chưa biết**; `.env` đang
  dùng giá Gemini cũ để ước lượng; gateway cộng ~2 000 token/lời gọi. **Mọi kết luận về tính agentic phải dùng LLM thật** (không `ScriptedPolicy`).
- **Agent hiện tại** (`agent/`): vòng v1 `agent/agent/react_agent.py` (giữ lại file để tham chiếu; S2D đã đóng băng ở `snapshots/agent_p1/`),
  `llm.py` (`OpenAICompatLLM`, `SimulatedLLM`, `SYSTEM_PROMPT`, `route()`), `verifier.py` (V1–V4), `guardrail.py` (input + hardware check),
  `memory.py`, `approval.py`, `tools.py` (`ToolHub`, `SERVERS`, `PERMISSIONS`, retry), `ui/server.py`.
- **Server có sẵn:** `hw_knowledge_server.py` + `text_manual_server.py` (P1, đang trong `SERVERS`); `hw_sandbox_server.py` (P2) và
  `board_state_server.py` (P3) **chưa** trong `SERVERS`. `hwmodel/` có `clock_tree`, `periph/*`, `drc.py`, `board_state.py`, solver, `analyze_c_code`, `compile_check`.
- **Ghi chú tồn đọng từ P3:** `ToolHub` retry cả tool `state-mutating` → **phải tắt trước khi đăng ký board-state** (D32). DRC-PWR-01 với STM32G474
  luôn `unknown` (DB không có số dòng). Simulator chưa chấm nguồn PLL/chờ RDY/AHB÷2/PUPDR trên chân 5 V — đừng để Gate coi những thứ đó là đã kiểm.
- **Eval:** adapter S2/S2D (`eval/adapters/agent_v1.py` + worker) chạy snapshot trong tiến trình riêng, nhiều lượt theo `session_id`. Grader
  `functional_sim`, `final_state`, `conflict_detected` dùng bản vendor (D19). D25: **mọi hệ, kể cả S3, chấm trên code/câu trả lời cuối**, Board State
  của S3 chỉ dùng cho chỉ số quá trình. D28: xung đột chỉ tính từ lượt gây xung đột trở đi.

---

## 3. Công việc

### Bước 0 — Chuẩn bị
Đọc `plan/DECISIONS.md` (D27–D32). Tạo ledger `plan/P4_progress.md` và `agent/PROMPT_DEVLOG.md` (D32). Tắt retry cho quyền khác `read-only`
trong `ToolHub` (test: timeout giả lập sau khi ghi không tạo sự kiện thứ hai).

### Bước 1 — `AgentState` + checkpoint (`agent/agent/runtime/state.py`, `checkpoint.py`)
`run_id, project_id, goal, turn, messages, plan[], budgets{steps, tokens, usd, wall_s}, used{...}, iteration_counters{per_error_code},
artifacts[], status` — serialize JSON, ghi SQLite sau **mỗi** bước. `resume(run_id)` khôi phục và chạy tiếp. Test: chạy bằng `ScriptedPolicy`,
kill (ngắt giữa chừng bằng exception/timeout ở bước k), resume → trace và kết quả cuối tương đương chạy liền.

### Bước 2 — Runtime state machine (`agent/agent/runtime/loop.py`)
`INTAKE → PLAN → ACT ⇄ OBSERVE → CHECK → (ACT | PLAN) → FINISH_GATE → DONE`, cùng `REFUSED`, `ESCALATED`.
- **INTAKE:** input guardrail + `_hardware_check` của v1 (giữ nguyên hành vi; sửa guardrail là P6), nạp Board State của `project_id`.
- **Tool điều khiển** (`runtime/control_tools.py`, quyền `control`): `update_plan(steps[], rationale)` (mỗi bước `{id, title, status, depends_on,
  acceptance}`; runtime ghi `plan_updated` + diff), `finish(summary, deliverables[], waived_requirements[])`.
- **CHECK:** khi có sản phẩm (khối code trong bản nháp, thay đổi board) → chạy Gate; lỗi **cục bộ** (sai PSC, quên MOE) → phản hồi có kiểu cho
  agent tự sửa; lỗi **cấu trúc** (hết chân cho tín hiệu, clock không thể đạt) → chèn `REPLAN_REQUIRED` + lý do, agent phải `update_plan` trước khi hành động tiếp.
- **Ngân sách:** steps/tokens/usd/wall_s có mặc định hợp lý và cấu hình được; cùng mã lỗi > 3 lần hoặc hết ngân sách → `ESCALATED`: trả câu trả lời
  tốt nhất **đã qua Gate một phần** + danh sách requirement chưa đạt và những gì đã thử (D32). **Không** bao giờ trả "step budget exhausted" trống.
- **Không định tuyến cứng:** `route()` và `parse_entities` không còn trong đường chạy chính (chỉ guardrail dùng `parse_entities`).
  `SimulatedLLM` → `ScriptedPolicy`, chỉ dùng trong test.
- **Nhiều lượt:** mỗi lượt người dùng là một `goal` mới trên cùng `project_id`; Board State và plan được giữ giữa các lượt.

### Bước 3 — Gate v3 (`agent/agent/gate/{provenance,functional,drc_gate,safety}.py`)
- **G1 Provenance:** mỗi số/địa chỉ/trích dẫn trong câu trả lời phải truy được về (a) kết quả tool tra cứu, (b) **output của solver/simulator/
  `set_clock_config`**, hoặc (c) đầu vào người dùng. Giá trị trong **khối code** được kiểm bởi G2, không bởi G1. Trích dẫn `[doc p.N]` phải
  được tool trả về (giữ ý V3) — **thanh ghi `svd_only`** được trích `[<chip>_SVD]` hợp lệ (tồn đọng P1). Sửa lỗi V2 coi giá trị tính toán (vd BRR `0x683`) là địa chỉ.
- **G2 Functional:** mọi khối code → `analyze_c_code` → `simulate_register_writes(initial=<trạng thái từ Board State/đề>)`; `effects` phải thoả
  **requirement do agent ghi** (`set_requirements`); violation mức error → fail. `unmodeled` liên quan requirement → fail có mã (không bao giờ pass).
  Ghi chú: Gate kiểm theo requirement của agent; grader kiểm theo spec độc lập (W5 "Lưu ý về độ độc lập").
- **G3 Board DRC:** `run_drc()` sạch hoặc vi phạm được `waive` có lý do (ở P4 chưa có người xác nhận → waive chỉ cho mã cho phép trong cấu hình, ghi rõ).
  `unknown` (vd DRC-PWR-01) → báo, không chặn, không tính pass.
- **G4 Safety:** không đề xuất vượt Absolute Maximum; code không đặt clock vượt giới hạn; không nối 5 V vào chân không FT (dùng `electrical_limits`, `pin_flags`).
- **G5 Compile** (tuỳ chọn, bật mặc định nếu ổn định): `compile_check`; `skipped` không bao giờ pass.
- Phản hồi lỗi: `{code, where, expected, actual, hint_source}`; ngân sách tự sửa 3 vòng/mã (A4 `-Reflection` = 0 vòng).

### Bước 4 — Đăng ký server + system prompt v3
- `SERVERS` thêm `hw-sandbox` và `board-state` (quyền `sandboxed-exec`, `state-mutating`). Board State DB theo env (giống `MEMORY_DB`), mỗi run eval một thư mục tạm.
- **System prompt v3** (`agent/agent/prompts/system_v3.md`): vai trò "hardware design agent"; quy ước CMSIS; **ghi requirement trước khi thiết kế; mô phỏng
  trước khi đưa code; không đặt trích dẫn trong khối code**; nêu rõ khi phát hiện xung đột và lý do chọn phương án khác. **Không** mô tả quy trình cứng
  theo từng loại task, **không** nhắc tên task/giá trị cụ thể của benchmark (D05). Mọi lần sửa → `PROMPT_DEVLOG.md`.

### Bước 5 — Ablation flags (D32)
Cấu hình (env hoặc tham số adapter), không sửa code khi chạy: A1 `-Planner` (ẩn `update_plan`, bỏ `REPLAN_REQUIRED`), A2 `-BoardState` (ẩn server
`board-state`, Gate bỏ G3), A3 `-Sandbox` (ẩn `hw-sandbox`, G2 tắt → Gate quay về kiểm provenance như v1), A4 `-Reflection` (ngân sách sửa = 0).
Test mỗi cờ thực sự ẩn tool / đổi Gate. Chạy thử mỗi cờ trên 2 task dev (1 seed) để chắc chắn chạy được; **không** báo cáo số ablation ở P4.

### Bước 6 — Trace chuẩn hoá + grader `process`
- Runtime ghi trace JSONL theo Phụ lục D: `plan_updated` (diff), `tool_call`, `sim_result`, `gate_result` (G1–G5 + mã lỗi), `replan_required`,
  `escalated`, `finish` (gate). Adapter S3 trả trace này trong `RunResult`.
- `eval/graders/process.py` (báo cáo, **không** gating): Self-Correction Rate (sản phẩm đầu fail check ≥ 1 nhưng cuối pass), Mean Repair Iterations,
  số lần replan và Replan Effectiveness, Premature-Finish Rate (finish bị gate từ chối / tổng finish), Step Efficiency (tool call / task thành công,
  tỷ lệ gọi trùng). Hệ không có trace v3 → `N/A`. Report thêm mục "Chỉ số quá trình (S3)".
- **Lưu ý trung thực:** Self-Correction đo theo Gate **của agent** (requirement agent ghi); báo kèm tỷ lệ mà sản phẩm cuối cũng pass grader độc lập.

### Bước 7 — Demo D1 + đánh giá S3@P4
1. **D1** bằng LLM thật qua UI hoặc script: "STM32G474 170 MHz, PWM 20 kHz 25% trên PA8, sinh code CMSIS". Lưu trace + bản tóm tắt dễ đọc vào
   `plan/demos/D1/` (dùng cho báo cáo). Nếu agent làm đúng ngay lần đầu, ghi nhận trung thực; có thể chạy thêm một biến thể (vd APB2 ÷2) để thấy vòng sửa.
   **Không** sửa prompt để "ép" agent mắc lỗi.
2. `pytest agent/tests` xanh (runtime/Gate test bằng `ScriptedPolicy`, không mạng — D22). Snapshot `agent/` → `snapshots/agent_p4/` (+ hash dữ liệu như P1).
3. Adapter **S3@P4** (`eval/adapters/agent_v3.py` + worker riêng, tiến trình riêng, thư mục tạm cho memory/board/checkpoint, `-B`, không thừa hưởng env
   chuyển hướng — như bài học P1/P3); đăng ký vào `report.SYSTEM_ORDER` và `PAIRS` (`S3@P4 vs S2D`, `S3@P4 vs S0`). Manifest ghim hash snapshot P4 theo hệ.
4. `--dry-run` ước tính; thử `--limit 2`; rồi chạy **toàn bộ dev** × 3 seed cho S3@P4 vào `eval/results/dev_baseline_v2` (`--resume`).
   **Hỏi người dùng nếu ước tính > 2 USD theo giá trong `.env`** (giá gateway thật chưa biết — nói rõ điều này khi hỏi).
5. **D29:** lặp lại kiểm định nhãn mù bộ nhận diện xung đột trên đầu ra C4 của S3@P4 (subagent độc lập, không xem code/kết quả bộ nhận diện; cùng định nghĩa D28); công bố precision/recall/κ.
6. Chẩn đoán lỗi S3 từ trace: mỗi run thất bại gán một nhóm (hiểu sai đề / tool sai / Gate cho qua nhưng grader trượt / Gate chặn đúng nhưng hết
   ngân sách / simulator không mô hình hoá / khác). Nhóm "Gate cho qua nhưng grader trượt" là **rủi ro tự chấm** (D19) — báo riêng, kèm ví dụ.

---

## 4. Quy tắc làm việc

- **D05/D32 chống overfit:** chỉ chỉnh prompt/runtime theo `dev`; không đọc task `test` (trừ C3/C4 do session trước viết — vẫn không chỉnh theo task test);
  mọi vòng chỉnh ghi `PROMPT_DEVLOG.md` kèm điểm dev trước/sau và số lời gọi. Không thêm luật/ví dụ đặc thù cho từng task vào prompt hay runtime.
- **Không sửa:** `snapshots/agent_v1/`, `snapshots/agent_p1/`, run cũ trong `runs.jsonl`, ground truth task, grader/vendor (nếu phát hiện lỗi grader/simulator:
  ghi ledger, sửa theo D18/D19 — quy tắc tổng quát, chấm lại mọi hệ, công bố số run đổi — và báo người dùng).
- **Bảo mật:** không in/ghi key; `.env` không vào snapshot/kết quả. Code do LLM sinh chỉ được parse/`-fsyntax-only`, **không chạy**.
- **TDD** cho runtime/Gate/checkpoint (ScriptedPolicy, không mạng). Mọi quyết định có ảnh hưởng → "Ruling" trong `plan/P4_progress.md`.
- **Hỏi người dùng khi:** ước tính > 2 USD; cần cài phần mềm hệ thống; mâu thuẫn với kế hoạch/DECISIONS; muốn đổi model hoặc nhiệt độ.

---

## 5. Checklist nghiệm thu P4

- [ ] Retry chỉ cho `read-only` (test); `AgentState` + checkpoint + resume sau kill (test)
- [ ] Runtime state machine; `update_plan`, `finish`, `REPLAN_REQUIRED`, ngân sách, `ESCALATED` trả câu trả lời tốt nhất + requirement chưa đạt
- [ ] Gate G1–G4 (+G5) với lỗi có kiểu; G1 chấp nhận bằng chứng sandbox/clock; `svd_only` trích `[<chip>_SVD]` hợp lệ
- [ ] `hw-sandbox` + `board-state` trong `SERVERS`; system prompt v3; `PROMPT_DEVLOG.md`
- [ ] Cờ A1–A4 có test và chạy thử được
- [ ] Trace chuẩn hoá; grader `process`; report có mục chỉ số quá trình
- [ ] Demo D1 bằng LLM thật lưu ở `plan/demos/D1/`
- [ ] `snapshots/agent_p4/`; S3@P4 trên toàn bộ dev × 3 seed; so sánh cặp với S2D và S0; chẩn đoán lỗi theo nhóm (có nhóm "Gate qua – grader trượt")
- [ ] `pytest agent/tests`, `pytest eval/tests` xanh; smoke replay 0 cache-miss; `freeze_hwmodel --check` sạch; UI cũ vẫn chạy
- [ ] `plan/P4_progress.md` đầy đủ Ruling

## 6. Báo cáo khi kết thúc session

Tóm tắt: đã làm gì; bảng TSR theo nhóm cho S0/S1/S2/S2D/**S3@P4** (+ Grounded, Proactive detection, compile); so sánh cặp S3@P4 vs S2D và vs S0
(Δ + CI + McNemar); chỉ số quá trình của S3@P4 (Self-Correction, Repair Iterations, Replan, Premature-Finish, Step Efficiency); diễn biến demo D1;
chẩn đoán lỗi theo nhóm; số vòng chỉnh prompt; chi phí (ước lượng + lưu ý giá gateway); điểm lệch khỏi brief; các Ruling (kèm chi phí nếu sai);
vấn đề mở cho P5 (HITL) và P6 (policy/guardrail).
