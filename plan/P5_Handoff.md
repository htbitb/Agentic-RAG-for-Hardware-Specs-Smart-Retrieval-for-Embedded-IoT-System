# P5 HANDOFF — Sửa tồn đọng P4 + Human-in-the-Loop v2 (W7) + task C5 → hệ S3@P5

> Tài liệu này là **brief độc lập** cho một Claude Code session mới. Đọc hết trước khi làm.
> Tham chiếu: `plan/AgenticUpgradePlan.md` §3.2 (nhánh INTERRUPTED), §4 W7 (HITL v2), §5 (ma trận chứng minh: P5, P7), §6 D2, D4,
> §7.2 (A6 `-HITL`), §7.3–7.6 (C5, `human_policy`, SimulatedHuman, oracle-info, grader `checklist`/`clarify`, Clarification P/R,
> Resume Success, Autonomy Ratio); `plan/DECISIONS.md` (**D33–D40 là ràng buộc chính**; D05, D18, D19, D25, D28, D32 vẫn áp dụng);
> ledger trước `plan/P4_progress.md`, giao diện `plan/P4_interfaces.md`, review `plan/P4_reports/runtime_review.md`,
> `plan/P4_reports/gate_review.md`; kết quả `eval/results/dev_baseline_v2/report.md` + `diagnosis_s3p4.md`.
> Thư mục làm việc: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project` (gốc dự án). Không phải git repo.

---

## 1. Mục tiêu P5

P4 cho S3 một vòng kín tự kiểm (plan → act → Gate → sửa). P5 đưa **con người vào trong vòng điều khiển**: agent tạm dừng có trạng thái
khi cần quyết định hoặc thiếu thông tin bắt buộc, rồi **chạy tiếp từ checkpoint** sau khi người trả lời. Đồng thời phải sửa các lỗ hổng
đo được ở P4 trước khi đo lại (D36, D37, D34).

**Tiêu chí thoát P5:**
1. **Sửa trước (Bước 1–3)** xong, có test: G2 khởi đầu không do agent tự chọn (D36), lỗi review runtime I1/I3/I4/I5/m1/m4/m5/m6 (D37),
   S3 replay được từ LLM cache, grader `abstain` sửa theo D18 với kiểm định κ trước/sau trên bộ nhãn mù C8 (D34).
2. Trạng thái `INTERRUPTED` + `ask_human(kind=choice|clarify)` + `write_config_file` qua interrupt `approval`; `resume(run_id, interrupt_id,
   decision, payload)` từ checkpoint **trong tiến trình mới** (test kill/resume giữa interrupt). Giới hạn `ask_human` mỗi run. Cờ **A6 `-HITL`**.
3. Run API tối thiểu (tạo run, resume, đọc sự kiện) dùng chung cho UI và eval.
4. `SimulatedHuman` xác định theo `human_policy`; adapter S3 trả lời interrupt qua nó; baseline chỉ nhận câu trả lời khi tự hỏi (§7.5).
5. **Task C5** (12 task, nửa thiếu thông tin bắt buộc) + grader `checklist`, `clarify` + biến thể `oracle-info`; review độc lập.
6. Demo **D4** (clarify HSE) bằng LLM thật + một demo `choice` + một demo `approval` (resume sau duyệt, agent chạy tiếp) lưu `plan/demos/`.
7. `snapshots/agent_p5/`; **S3@P5 trên toàn bộ dev × 3 seed** (C1–C4, C6–C8) + **C5 dev** cho S0, S1, S2D, S3@P5 (S2 nếu chi phí cho phép);
   Clarification Precision/Recall, Resume Success, Autonomy Ratio; so sánh cặp S3@P5 vs S3@P4, vs S0, vs S2D.

**Ngoài phạm vi:** policy engine, taint, sửa `hardware_check` v1, C7 v2, hiệu chỉnh từ chối C8 (P6); Lesson/Project memory (P7);
UI panel mới (P8 — chỉ cần UI cũ không vỡ và Run API dùng được); fault injection, ablation đầy đủ, tập `test` (P9).

---

## 2. Bối cảnh cần biết

- **Model:** `ag/gemini-3.8-flash-medium` qua gateway OpenAI-compatible (`agent/.env`; D27). Giá thật của gateway **chưa biết**; ước tính theo giá
  trong `.env`. S3@P4 tốn ~$0,026/task (6× S2D) — schema 31 tool ≈ 6 900 token/lời gọi + ~2 000 token gateway (D39).
- **S3@P4 (đóng băng `snapshots/agent_p4/`, sha `5b5cf25f…`):** dev × 3 seed TSR 90,4 % (C1 100, C2 100, C3 100, C4 73,3, C6 80, C7 100, C8 55,6);
  vs S2D +28,1 pp (p=0,003); vs S0 +15,4 pp (p=0,109, **chưa có ý nghĩa**). Chỉ số quá trình: Self-Correction 47/47 nhưng 42 là G1 (D35);
  Premature-Finish 41 %; 18,5 tool call/task thành công. 11 run thất bại: 6 do `hardware_check` v1 (C4-014, C6-015 — để P6), 4 C8, 1 C4-011
  (`rollback` làm mất requirement buzzer).
- **C8 thật ra (D34):** nhãn mù cho S3@P4 7/9 (grader 55,6 %). Grader trượt oan 3 run (dữ kiện đúng về thực thể khác) và bỏ sót 1 run
  ("sub-two microamps"). S0/S1/S2/S2D: grader khớp nhãn 36/36. Nhãn: `plan/reviews/c8_blind_labels_dev_v2_unblinded.csv`.
- **Runtime v3** ở `agent/agent/runtime/` (`loop.py`, `state.py`, `checkpoint.py`, `control_tools.py`, `factory.py`, `flags.py`, `intake.py`,
  `summary.py`, `trace.py`, `cli.py`); Gate ở `agent/agent/gate/`; `ScriptedPolicy` ở `agent/agent/scripted.py`. HITL v1 hiện là
  `agent/agent/approval.py` (pending dict trong bộ nhớ, CLI/UI duyệt) + `agent/ui/server.py` (`http.server`, không phải FastAPI).
- **Eval:** adapter `eval/adapters/agent_v3.py` + worker; grader `process`; `eval/tools/diagnose_s3.py`, `eval/tools/blind_label.py`.
  D25: mọi hệ chấm trên code/câu trả lời cuối; Board State chỉ cho chỉ số quá trình. D28: xung đột tính từ lượt gây xung đột.

---

## 3. Công việc

### Bước 0 — Chuẩn bị
Đọc `plan/DECISIONS.md` D33–D40. Tạo ledger `plan/P5_progress.md` (định dạng như P4: `Task <N>` / `Ruling: … — lý do — chi phí nếu sai`).
Chạy baseline test (`pytest agent/tests` = 1 690, `pytest eval/tests` = 976) và ghi vào ledger. Sao lưu `eval/results/dev_baseline_v2/`
(runs/scores/manifest) vào scratchpad trước khi thêm hệ mới.

### Bước 1 — Sửa runtime theo review P4 (D37), TDD
Theo `plan/P4_reports/runtime_review.md`:
- **I1:** escalate giữa lô tool call → trả tool message "not executed (run escalated)" cho mọi call còn lại; wrap-up dùng `_view` (đã nén);
  `ScriptedPolicy` kiểm cặp `tool_call`/`tool` hợp lệ (để lỗi kiểu này không lọt lần nữa).
- **I3:** `project_id` xác định theo `(task_id, seed)` trong eval (hoặc không đưa vào prompt/kết quả tool) ⇒ **`--cache replay` tái tạo được S3**.
  Test: chạy ScriptedPolicy hai lần cùng `(task, seed)` cho cùng khoá cache; smoke replay S3 0 cache-miss ở cuối P5.
- **I4:** chân trang ESCALATED không chứa mã xung đột thô (để bộ nhận diện không cộng điểm cho chân trang của runtime).
- **I5:** loại bản nháp có finding G4 khỏi "ứng viên tốt nhất"; wrap-up phải qua ít nhất G4.
- **m1** (tham số tool không phải object), **m4** (sandboxed-exec: chọn một — chạy lại khi resume như Ruling, hoặc sửa Ruling; ghi ledger),
  **m5** (đưa ảnh chụp Board State ở INTAKE vào `state.observations` để G1 dùng được), **m6** (`CLOCK_LIMIT:FLASH_WS` không phải lỗi cấu trúc).
  m2/m3/m7/m8 làm nếu rẻ (m2 `args_sha` nên làm vì ảnh hưởng chỉ số gọi trùng).
- I2 (thời gian hạ tầng tính vào `wall_s`): tách `wall_s` của agent khỏi thời gian chờ rate-limiter nếu dễ; nếu không, ghi telemetry riêng.

### Bước 2 — G2: trạng thái khởi đầu không do agent tự chọn (D36), TDD
Thứ tự mới: (1) `initial` do **INTAKE** trích từ lời người dùng (SYSCLK/HSE/preset được nêu) hoặc cấu hình clock đã có trong Board State;
(2) code tự cấu hình clock ⇒ reset; (3) reset mặc định. Preset trong lần mô phỏng của agent **chỉ được dùng khi khớp (1)**; lệch ⇒ finding
`G2-START-MISMATCH` (kiểu lỗi có `expected/actual`). Ghi `gate_result.start.source`. Báo cáo phân bố `source` của S3@P5 so với S3@P4
(P4: `agent_simulation` 56/97 lần Gate C3/C4; 21/33 lần Gate cuối).
Cân nhắc thêm (Ruling, không bắt buộc): chặn `rollback` làm mất requirement do người dùng nêu (C4-011 s0), hoặc G3 so số trong lời người dùng
với requirement đã ghi. Nếu làm, phải là quy tắc tổng quát, không đặc thù task.

### Bước 3 — Grader `abstain` (D34, theo D18)
Quy tắc tổng quát, áp dụng mọi hệ: (a) giá trị chỉ là bịa khi được gán cho **đối tượng/thuộc tính được hỏi** (dữ kiện về thực thể khác — giải
mã mã linh kiện, thanh ghi thật lân cận, chip so sánh — không tính); (b) bắt **ước lượng bằng chữ** ("single-digit USD", "sub-two microamps",
"a few mA", "low single-digit microampere range"). Test trước bằng câu thật từ bộ nhãn. Chấm lại toàn bộ `dev_baseline_v2`, ghi
`post_run_changes` (số run đổi theo hệ, chiều đổi) và **κ trước/sau so với `plan/reviews/c8_blind_labels_dev_v2_unblinded.csv`**.
Không chỉnh prompt để "vượt" grader mới. Ghi rõ đây là kiểm định trong mẫu; P9 lặp lại nhãn mù trên `test`.

### Bước 4 — Interrupt/Resume (`agent/agent/runtime/hitl.py`; thay `approval.py` cho runtime v3)
- Tool điều khiển `ask_human(kind, question, options?, why_needed)`:
  - `choice`: đánh đổi thiết kế, 2–4 phương án kèm ưu/nhược do agent viết; kết quả ghi bằng `record_decision` (sự kiện + requirement/ghi chú
    trong Board State nếu phù hợp).
  - `clarify`: thiếu thông tin **bắt buộc**; câu trả lời được ghi vào requirement rồi tiếp tục.
- `write_config_file` (irreversible-write) tạo interrupt `approval` thay vì chặn đồng bộ: Approve ⇒ ghi file (giữ validate tên, sandbox, audit
  của `approval.py`), kết quả trả về agent như observation và **agent chạy tiếp**; Reject + góp ý ⇒ góp ý thành observation, agent lập lại kế hoạch.
- Khi interrupt: checkpoint `AgentState` với `pending_interrupt{id, kind, tool_call_id, payload}`, `status=INTERRUPTED`, trả `status="interrupted"`.
  `resume(run_id, interrupt_id, decision, payload)` nạp checkpoint, chèn `tool` message đúng `tool_call_id`, chạy tiếp. Resume với `interrupt_id`
  sai/đã dùng ⇒ lỗi rõ ràng, không chạy hai lần. Ngân sách `wall_s` **không** tính thời gian chờ người.
- Giới hạn `ask_human` mỗi run (mặc định 3, `AGENT_BUDGETS`); vượt ⇒ observation "đã hết lượt hỏi, hãy tự chọn phương án hợp lý và nêu giả định".
- ESCALATED (D32) ở P5: nếu còn lượt hỏi, agent được mời `ask_human` với tóm tắt những gì đã thử (plan §4 W4); nếu không, giữ hành vi P4.
- Cờ **A6 `-HITL`**: ẩn `ask_human`, approval tự duyệt. Test bằng ScriptedPolicy: interrupt → kill tiến trình (`os._exit`) → resume trong
  tiến trình mới cho kết quả bằng chạy liền; resume hai lần bị từ chối; A6 không phát sinh interrupt.
- Prompt v3: thêm hướng dẫn khi nào được hỏi (chỉ khi thiếu thông tin **bắt buộc** cho kết quả đúng, hoặc đánh đổi thực sự phụ thuộc sở thích
  người dùng), và không hỏi điều tra được bằng tool. Ghi `PROMPT_DEVLOG.md`.

### Bước 5 — Run API (`agent/ui/server.py` hoặc module mới) — tối thiểu
`POST /api/runs {question, project_id?, ablations?}` → `{run_id, status, interrupt?|answer}`; `POST /api/runs/{run_id}/resume {interrupt_id,
decision, payload}`; `GET /api/runs/{run_id}/events` (SSE hoặc polling theo `seq`). Eval adapter dùng **cùng** lớp Python bên dưới (không qua HTTP
nếu không cần). UI cũ (`ui.server --inproc`) vẫn chạy; panel mới để P8.

### Bước 6 — SimulatedHuman + adapter + task C5
- `eval/sim_human.py`: xác định theo `human_policy` của task (§7.4): `approval: approve|reject{feedback}`, `choice: {prefer: "<từ khoá>"}`,
  `clarify: {<khoá>: "<câu trả lời>"}`, `max_answers`. Ghép câu hỏi với khoá bằng quy tắc xác định (từ khoá/khái niệm khai báo trong task,
  không gọi LLM). Câu hỏi ngoài policy ⇒ "Không biết, hãy tự chọn phương án hợp lý" và ghi là **câu hỏi thừa**.
- Adapter S3: nhận interrupt → SimulatedHuman → resume; ghi mọi lần hỏi/trả lời vào trace (`interrupt_raised`, `resumed`).
- Baseline (S0, S1, S2D): runner gửi câu trả lời SimulatedHuman như lượt tiếp theo **chỉ khi** câu trả lời của baseline chứa câu hỏi hướng tới
  người dùng (quy tắc phát hiện xác định, có test); câu hỏi đó cũng được chấm `clarify` như của S3.
- **Task C5** (`eval/tasks/C5/c5_curated.yaml`, 12 task, ~4 dev, gán split bằng seed cố định TRƯỚC khi chạy hệ nào; chip STM32G474 cho phần có
  code, có thể có ESP32/nRF ở phần tương thích mức logic/ngân sách dòng):
  - Mục tiêu cấp hệ thống (kiểu D4): phân rã ≥ 5 bước; **6 task thiếu ≥ 1 thông tin bắt buộc** (HSE, mức áp cảm biến, ngân sách dòng, tốc độ baud…)
    mà **không thể tra bằng tool**; 6 task đủ thông tin (đo "không hỏi khi không cần").
  - `human_policy` + `hidden_info` (danh sách thông tin bắt buộc) + `expected.checklist` (mục kiểm xác định: vd có level shifter khi lệch áp,
    SYSCLK ≤ 170 MHz, PLL đúng với HSE được trả lời, tổng dòng ngủ ≤ ngân sách) + `expected.spec` khi có code (`functional_sim`/`final_state`).
  - Biến thể **`oracle-info`**: mọi thông tin ẩn đưa sẵn ở lượt đầu cho mọi hệ (tách năng lực thiết kế khỏi năng lực hỏi).
  - `provenance.reference_solution` + phép tính tay; ≥ 1 biến thể sai mỗi task làm checklist trượt.
- Grader `checklist` (xác định) và `clarify` (so câu hỏi với `hidden_info`: Clarification Precision = câu hỏi cần thiết / tổng câu hỏi; Recall =
  thông tin bắt buộc được hỏi / tổng). TSR của C5 gate bởi `checklist` (+ `functional_sim`/`final_state` nếu có code). Với task thiếu thông tin,
  đoán thay vì hỏi mà đoán sai ⇒ checklist trượt; đoán **trùng** giá trị ẩn vẫn bị ghi "không hỏi" ở `clarify` (báo riêng, không gate).
- **Review độc lập** (subagent mới): đề rõ, thông tin ẩn thực sự bắt buộc và không tra được, checklist đúng và đủ, lời giải tham chiếu pass.
  Lưu `plan/reviews/review_C5.md`; áp dụng sửa trước khi chạy bất kỳ hệ nào. `verify_tasks` mở rộng cho C5.

### Bước 7 — Chỉ số và report
Thêm vào `process`/report: **Clarification Precision/Recall** (theo hệ, theo nửa thiếu/đủ thông tin), **Resume Success** (run tiếp tục đúng sau
interrupt / số interrupt), **Autonomy Ratio** (bước không cần người / tổng bước; số can thiệp trung bình), số `ask_human` thừa, Replan sau Reject.
Self-Correction tách **vật lý** / **provenance** (D35) — áp dụng cho cả S3@P4 (tính lại từ trace) và S3@P5.

### Bước 8 — Demo (LLM thật, lưu `plan/demos/`)
- **D4** (`plan/demos/D4/`): mục tiêu cấp hệ thống thiếu HSE → `ask_human(clarify)` → tính PLL theo câu trả lời → tiếp tục → Gate pass.
- **choice** (`plan/demos/D_choice/`): LEVEL_MISMATCH cảm biến 1,8 V (không dùng kịch bản 5 V vì `hardware_check` v1 còn chặn — D3 để P6):
  agent đưa ≥ 2 phương án, người chọn, agent làm tiếp theo phương án đó.
- **approval** (`plan/demos/D_approval/`): `write_config_file` → interrupt → kill tiến trình → resume trong tiến trình mới → Approve → agent cập nhật
  artifact và `finish`; thêm một lần Reject + góp ý → agent lập lại kế hoạch.
Trung thực như P4: không chỉnh prompt để ép hành vi; run không đạt vẫn lưu kèm `NOTE.md`.

### Bước 9 — Đóng băng và đánh giá
1. Đóng băng `snapshots/agent_p5/` (code + manifest sha; **không** `.env`). Hệ **S3@P5**; giữ nguyên hàng S3@P4.
2. **Ước tính chi phí trước khi chạy** (dev × 3 seed S3@P5 ≈ $3–4 theo P4, + C5 dev cho 4–5 hệ × 3 seed × 2 biến thể) — **hỏi người dùng nếu > 2 USD**.
3. S3@P5 trên toàn bộ dev × 3 seed (C1–C4, C6–C8) + C5 dev (cả `oracle-info`) cho S0, S1, S2D, S3@P5 (S2 tuỳ chi phí). Cờ A6 chỉ kiểm chạy được
   trên 1–2 task C5 dev (ablation đầy đủ để P9).
4. So sánh cặp: S3@P5 vs S3@P4 (tác động của bước sửa + HITL trên C1–C8 — kỳ vọng không giảm), vs S0, vs S2D; C5 riêng.
5. Smoke replay S3@P5 0 cache-miss (kiểm I3). Chẩn đoán lỗi theo nhóm như P4 (+ nhóm "hỏi thừa", "không hỏi khi cần", "resume sai").
6. D29 lần 3 chỉ nếu bộ nhận diện xung đột bị đổi (I4) — nếu đổi, chạy lại nhãn mù trên C4 của S3@P5.

---

## 4. Quy tắc làm việc

- **D05/D32 chống overfit:** chỉ chỉnh prompt/runtime theo `dev`; không đọc task `test` của C1–C4, C6–C8 (task C5 do chính session viết — vẫn
  không chỉnh theo task test). Mọi vòng chỉnh ghi `agent/PROMPT_DEVLOG.md` kèm điểm dev trước/sau và số lời gọi. Không thêm luật/ví dụ đặc thù task.
- **Không sửa:** `snapshots/agent_v1/`, `snapshots/agent_p1/`, `snapshots/agent_p4/`, run cũ trong `runs.jsonl`, ground truth task, vendor.
  Lỗi grader/simulator: sửa theo D18/D19 (quy tắc tổng quát, chấm lại mọi hệ, công bố số run đổi, báo người dùng).
- **Bảo mật:** không in/ghi key; `.env` không vào snapshot/kết quả. Code do LLM sinh chỉ parse/`-fsyntax-only`, **không chạy**. File do
  `write_config_file` ghi chỉ nằm trong sandbox đã có.
- **TDD** cho hitl/resume/sim_human/grader (ScriptedPolicy, không mạng). Mọi quyết định có ảnh hưởng → "Ruling" trong `plan/P5_progress.md`.
- **Hỏi người dùng khi:** ước tính > 2 USD; cần cài phần mềm hệ thống; mâu thuẫn với kế hoạch/DECISIONS; muốn đổi model hoặc nhiệt độ.

---

## 5. Checklist nghiệm thu P5

- [ ] D37: I1, I3, I4, I5, m1, m4, m5, m6 sửa có test; S3 replay được (smoke 0 cache-miss)
- [ ] D36: G2 khởi đầu theo thứ tự mới, `G2-START-MISMATCH`, phân bố `source` trước/sau
- [ ] D34: grader `abstain` sửa; chấm lại 570+ run; số run đổi + κ trước/sau ghi manifest
- [ ] `ask_human` (choice/clarify), approval qua interrupt, `INTERRUPTED`, resume sau kill (test), giới hạn hỏi, A6
- [ ] Run API tối thiểu; UI cũ vẫn chạy
- [ ] SimulatedHuman + adapter S3 + quy tắc baseline; C5 12 task + review độc lập + `oracle-info`; grader `checklist`, `clarify`
- [ ] Clarification P/R, Resume Success, Autonomy Ratio, Self-Correction tách lớp trong report
- [ ] Demo D4, choice, approval lưu `plan/demos/`
- [ ] `snapshots/agent_p5/`; S3@P5 dev × 3 seed + C5 dev; so sánh cặp; chẩn đoán lỗi
- [ ] `pytest agent/tests`, `pytest eval/tests` xanh; `freeze_hwmodel --check` sạch; smoke replay S0–S2D và S3@P5 0 cache-miss
- [ ] `plan/P5_progress.md` đầy đủ Ruling; `PROMPT_DEVLOG.md` cập nhật

## 6. Báo cáo khi kết thúc session

Tóm tắt: đã làm gì; kết quả các bước sửa (D34: κ trước/sau và số run đổi; D36: phân bố `source`; I3: replay); bảng TSR theo nhóm cho
S0/S1/S2/S2D/S3@P4/**S3@P5** (+ C5 thường và `oracle-info`); so sánh cặp (Δ + CI + McNemar); Clarification P/R, Resume Success, Autonomy Ratio,
Self-Correction tách lớp; diễn biến các demo; chẩn đoán lỗi; số vòng chỉnh prompt; chi phí (ước lượng + lưu ý giá gateway); điểm lệch khỏi brief;
các Ruling (kèm chi phí nếu sai); vấn đề mở cho P6 (policy, `hardware_check`, C8, C7 v2) và P7 (memory).
