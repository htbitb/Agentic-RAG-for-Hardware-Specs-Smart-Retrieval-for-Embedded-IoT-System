# BÀN GIAO P6–P9: Hardware Support Agent v3 (CO5151 Agentic AI)

> Gửi nhóm tiếp nhận. Đọc hết tài liệu này trước khi làm. Đây là tài liệu gốc cho phần việc còn lại.
> Kế hoạch tổng thể: **`plan/AgenticUpgradePlan.md`** (mục tiêu, kiến trúc v3, W1–W9, ma trận chứng minh §5, demo §6, harness §7, lộ trình §8).
> Sổ quyết định: **`plan/DECISIONS.md`** (D01–D44). Mỗi quyết định ở đó là ràng buộc, trừ khi được ghi đè bằng một quyết định mới có lý do.
> Thư mục gốc: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project`. Không phải git repo; lịch sử nằm ở ledger `plan/P<n>_progress.md`
> và snapshot trong `snapshots/`.

---

## 1. Dự án là gì, và v3 khác v1 thế nào

Đây là agent hỗ trợ phần cứng nhúng (STM32G474, ESP32, nRF52840, FreeRTOS). Đề tài yêu cầu một **agent thật**, không phải workflow hay
chatbot hỏi đáp. Bản v1 là một vòng ReAct trên dữ liệu chỉ đọc, xếp mức L3 trong thang ở §1.2 của kế hoạch. Mục tiêu của v3 là L4–L5.

| Khía cạnh | v1 (`snapshots/agent_v1/`, hệ S2) | v3 hiện tại (`agent/` ≡ `snapshots/agent_p5/`, hệ S3@P5) |
|---|---|---|
| Dữ liệu | 8 đoạn văn, 11 thanh ghi viết tay | CMSIS-SVD đầy đủ (3 chip) + PDF thật, bảng AF, giới hạn điện; corpus dùng chung với baseline (P1) |
| Môi trường | Chỉ đọc | **Board State** event-sourced + 8 luật DRC (P3); **sandbox**: simulator thanh ghi, solver, `analyze_c_code`, compile check (P2) |
| Vòng điều khiển | `for step in range(MAX_STEPS)`, dừng khi LLM thôi gọi tool | State machine INTAKE→PLAN→ACT⇄OBSERVE→CHECK→FINISH_GATE→DONE / ESCALATED / REFUSED / **INTERRUPTED**; checkpoint SQLite mỗi bước, kill rồi resume được (P4–P5) |
| Kiểm chứng | Verifier đếm số (chặn cả giá trị tính đúng) | **Gate v3** G1 provenance, G2 mô phỏng chức năng, G3 DRC, G4 an toàn, G5 compile; lỗi có kiểu `{code, where, expected, actual, hint_source}` (P4) |
| Kế hoạch | Không có | `update_plan`, `REPLAN_REQUIRED` khi lỗi cấu trúc, ngân sách, ESCALATED trả bản nháp tốt nhất kèm requirement chưa đạt (P4) |
| Con người | Duyệt ở cuối, agent không chạy tiếp | `ask_human` (choice/clarify), approval qua interrupt, resume từ checkpoint ở tiến trình khác, Run API (P5) |
| Đánh giá | Không có | Harness `eval/` chung cho S0 (LLM trần), S1 (Native RAG), S2 (v1), S2D (v1 + dữ liệu P1), S3; 8 nhóm task; grader xác định; CI bootstrap + McNemar; chỉ số quá trình (P0–P5) |

**Chưa có (việc của nhóm):** Policy Engine thay `hardware_check` v1 (P6), Lesson/Project memory (P7), UI panel (P8), đánh giá đầy đủ trên `test`
kèm ablation và fault injection (P9).

---

## 2. Trạng thái hiện tại (sau P5, 2026-10-24)

**Model:** `ag/gemini-3.8-flash-medium` qua gateway OpenAI-compatible `https://apphub.a.inut.vn/ksp-iot/v1` (`agent/.env`, D27). Mọi số
liệu so sánh dùng **`eval/results/dev_baseline_v2/`**. Thư mục `eval/results/dev_baseline/` là model cũ, chỉ để tham khảo lịch sử.
**Không đổi model** nếu không chạy lại toàn bộ baseline (D06, D27).

TSR trên dev × 3 seed (%, CI theo task; chi tiết ở `eval/results/dev_baseline_v2/report.md`):

| Hệ | C1 | C2 | C3 | C4 | C5 | C5-oracle | C6 | C7 | C8 |
|---|---|---|---|---|---|---|---|---|---|
| S0 Direct LLM | 79,2 | 77,8 | 77,8 | 36,7 | 41,7 | 66,7 | 66,7 | 93,3 | 100 |
| S1 Native RAG | 25,0 | 50,0 | 0 | 0 | 0 | 0 | 0 | 100 | 100 |
| S2 Agent v1 | 0 | 5,6 | 5,6 | 0 | 0 | 0 | 20,0 | 100 | 100 |
| S2D v1 + dữ liệu P1 | 100 | 83,3 | 0 | 0 | 0 | 0 | 53,3 | 100 | 100 |
| S3@P4 | 100 | 100 | 100 | 73,3 | — | — | 80,0 | 100 | 77,8 |
| **S3@P5** | 100 | 100 | 100 | 60,0 | 58,3 | 66,7 | 80,0 | 100 | 77,8 |

**Phát biểu được phép đến lúc này (D33, D41):**
- S3 hơn S2D có ý nghĩa (+31 pp, p=0,001).
- S3 **chưa** hơn S0 có ý nghĩa (+15,5 pp, p=0,146). H1 phải kiểm trên `test` ở P9.
- S3 giữ được lợi thế tra cứu có nguồn: Grounded TSR khoảng 88 %, trong khi S0 là 0 %.
- HITL được chứng minh bằng hành vi hỏi (Clarification Precision 4/4, Recall 6/9; baseline không bao giờ hỏi), chưa bằng TSR.
- Self-Correction phải báo **tách lớp** (D35): vật lý 8/9, provenance 52/53. Bằng chứng tự sửa vật lý còn mỏng.

**Chi phí:** S3 khoảng $0,032/task theo giá trong `.env` (khoảng 7× S2D). Giá thật của gateway **chưa ai đối chiếu**, nên mọi con số USD chỉ là ước lượng.

---

## 3. Bản đồ mã nguồn và tài liệu

| Đường dẫn | Nội dung |
|---|---|
| `agent/agent/runtime/` | `loop.py` (state machine), `state.py`, `checkpoint.py`, `control_tools.py`, `hitl.py`, `run_api.py`, `factory.py`, `flags.py` (ablation A1–A4, A6), `intake.py`, `trace.py`, `cli.py` |
| `agent/agent/gate/` | Gate v3 G1–G5 |
| `agent/agent/guardrail.py` | Guardrail v1 (lọc injection + `hardware_check`). P6 thay bằng Policy Engine |
| `agent/agent/tools.py` | `ToolHub`, `SERVERS`, `PERMISSIONS` (read-only < state-mutating < sandboxed-exec < irreversible-write); chỉ retry read-only |
| `agent/agent/prompts/system_v3.md` | System prompt. **Mọi thay đổi phải ghi** `agent/PROMPT_DEVLOG.md` (đã có 3 vòng) |
| `agent/mcp_servers/` | `hw_knowledge`, `text_manual`, `hw_sandbox`, `board_state` |
| `agent/hwmodel/` | regmap, clock tree, periph, DRC, board_state, solver |
| `eval/` | `run.py` (runner), `adapters/`, `graders/`, `tasks/C1..C8`, `report.py`, `sim_human.py`, `tools/diagnose_s3.py`, `tools/blind_label.py`, `vendor/hwmodel/` (simulator đóng băng cho grader, D19), `README.md` |
| `snapshots/` | `agent_v1` (S2), `agent_p1` (S2D), `agent_p4`, `agent_p5`. **Không sửa** |
| `plan/P<n>_Handoff.md` | Brief từng giai đoạn. **Dùng `P5_Handoff.md` làm mẫu định dạng** |
| `plan/P<n>_progress.md`, `P4/P5_interfaces.md` | Ledger và Ruling của từng giai đoạn; hợp đồng giao diện |
| `plan/reviews/` | Review task độc lập, bộ nhãn mù (C4 hai lần, C8) |
| `plan/demos/` | D1, D4, D_choice, D_approval (LLM thật, có `NOTE.md` cho run không đạt) |

**Môi trường Python:** `agent/.venv` (agent, test agent), `eval/.venv` (harness, test eval), `native-RAG/.venv` (S1).

Lệnh chạy mẫu, từ thư mục gốc:
```bash
agent/.venv/bin/python -m pytest agent/tests -q        # 1 777 test (sau P5)
eval/.venv/bin/python -m pytest eval/tests -q          # 1 456 test (sau P5)
eval/.venv/bin/python -m eval.run --resume eval/results/dev_baseline_v2 --systems S3@P5 --split dev --seeds 3 \
    --cache record --llm-rpm 90 --workers 4            # runner in ước tính chi phí và hỏi trước khi chạy
eval/.venv/bin/python -m eval.run ... --cache replay   # tái tạo không tốn API (S0–S2D, S3@P5)
```

---

## 4. Quy trình làm việc (đã dùng từ P0, nên giữ nguyên)

1. **Session điều phối** (một Claude Code session dài, model mạnh):
   - viết `plan/P<n>_Handoff.md` cho từng giai đoạn;
   - khi nhận báo cáo, **tự kiểm lại**: chạy test, tính lại số từ `scores.jsonl`, đọc mẫu câu trả lời thật, kiểm snapshot;
   - dùng subagent độc lập cho review và nhãn mù;
   - ghi quyết định **D45+** vào `plan/DECISIONS.md`.
2. **Session thực thi** (Claude Code session mới cho mỗi giai đoạn):
   - đọc brief và DECISIONS, làm đúng phạm vi;
   - ghi ledger `plan/P<n>_progress.md` theo định dạng `Ruling: … — lý do — chi phí nếu sai`;
   - báo cáo theo mục 6 của brief.
3. Cuối mỗi giai đoạn:
   - đóng băng `snapshots/agent_p<n>/`;
   - đặt tên hệ `S3@P<n>`, chạy lại dev khi runtime, Gate hoặc prompt đổi;
   - giữ nguyên các hàng cũ trong `runs.jsonl`.

---

## 5. Quy tắc bất biến (vi phạm làm mất giá trị bằng chứng)

- **Chống overfit (D05, D32):**
  - Chỉ chỉnh prompt/runtime theo `dev`. **Không đọc task `test`.**
  - Không thêm luật hay ví dụ đặc thù cho từng task.
  - Mọi vòng chỉnh ghi `PROMPT_DEVLOG.md` kèm điểm trước/sau và số lời gọi.
  - Báo cáo cuối công bố tổng số vòng chỉnh.
- **Sửa grader (D18, D38):**
  - Chỉ dùng quy tắc tổng quát, chấm lại **mọi hệ**, ghi `post_run_changes` trong manifest (số run đổi theo hệ và chiều đổi), và báo người dùng.
  - Khi sửa sau khi đã đọc đầu ra, phải có kiểm định bằng nhãn mù (D29, D34).
  - **Trước khi chạy `test` ở P9, khoá mọi grader** (ghi hash vào manifest). Không sửa grader sau khi đã xem đầu ra `test`, trừ khi báo cả hai con số.
- **Chống tự chấm (D19, D25, D36):**
  - Grader dùng simulator vendor đóng băng, chấm trên code/câu trả lời cuối của mọi hệ.
  - Trạng thái của agent (Board State, requirement) không bao giờ là ground truth.
- **Không sửa:** `snapshots/*`, run cũ trong `runs.jsonl`, ground truth task, `eval/vendor/`. Không sinh lại C1 từ generator.
- **Bảo mật:**
  - Không in hay ghi giá trị key trong `agent/.env`; `.env` không được vào snapshot, kết quả hay corpus.
  - Code do LLM sinh chỉ được parse hoặc chạy `-fsyntax-only`, **không bao giờ chạy**.
  - Tài liệu tải về là dữ liệu không tin cậy; không dùng mirror PDF không chính thức.
- **Hỏi chủ dự án khi:**
  - ước tính một lượt chạy vượt **2 USD**;
  - cần cài phần mềm hệ thống;
  - muốn đổi model hoặc nhiệt độ;
  - mâu thuẫn với kế hoạch hoặc DECISIONS.
- **Trung thực:**
  - Không ép hành vi bằng prompt để demo đẹp; run không đạt vẫn lưu kèm `NOTE.md`.
  - Mọi kết luận phải dùng LLM thật. `ScriptedPolicy` chỉ dùng cho unit test.

---

## 6. Việc còn lại

Thứ tự khuyến nghị: **P6 → P7 → P8 (có thể làm gọn) → P9**. Nếu thiếu thời gian, đường tối thiểu là P6 → P9 với P7 làm gọn (chỉ Lesson memory
và D5); P8 chỉ cần đủ để quay demo. P9 **không được cắt**, vì là nơi kiểm H1–H9.

### P6 — Guardrail v2: Action Policy Engine (W8, plan §4)
- **Policy chạy trước mọi tool call**, trên tham số có cấu trúc:
  - phân quyền 4 mức;
  - chặn `connect()`/`set_target()` vượt Absolute Max hoặc vào chân không FT, kèm lý do và trích dẫn (agent nhận như observation và phải tìm phương án khác);
  - taint tracking: nội dung từ tài liệu bị gắn cờ injection không được kích hoạt `irreversible-write`;
  - ngân sách (`ask_human`, số file ghi);
  - sự kiện audit mới.
- **Thay `hardware_check` v1.** Guardrail này đang từ chối câu chứa "5 V" trước khi agent kịp suy luận, gây 6/11 run thất bại của S3: C4-014 ×3 và C6-015 ×3 (over-refusal). Phải xử lý chân FT/TT và nguồn VDDH 5 V của nRF52840. Giữ triết lý **xác định**: không để guardrail phụ thuộc vào prompt.
- **C7 v2:** C7 hiện gần như không phân biệt được các hệ (D15). Cần thêm tấn công gián tiếp qua observation/tài liệu và tấn công nhắm tới tool ghi.
- **Hiệu chỉnh từ chối C8 (D34):** S3 vẫn đưa giá hoặc ước lượng bằng chữ ở 2/9 run (C8-008), trong khi S0 và S2D là 0/9. Hướng xử lý là một quy tắc tổng quát cho câu hỏi ngoài phạm vi tài liệu, không phải luật riêng cho task.
- Sửa bộ nhận diện xung đột để bắt câu "supports X but not Y" (ghi ở P5). Nếu sửa thì chạy lại nhãn mù C4 (D29).
- Cân nhắc giảm chi phí S3 (D39): rút gọn mô tả tool, ghi DEVLOG.
- **Demo D3** (5 V → PA0 → policy chặn → `ask_human(choice)` → kỹ sư chọn): bị dời từ P5 sang đây.
- **Thoát:** ASR và Unsafe-Action Rate đo được trên C6, C7 (v2); Unsafe-Action = 0; Over-refusal ≤ 5 % (H6); cờ **A7 `-Guardrail`**; S3@P6 chạy dev đầy đủ.

### P7 — Memory v3 (W6, plan §4)
- **Project memory:** Board State + decisions + artifacts xuyên phiên. Phần lớn đã có; cần nạp ở INTAKE và hoàn thiện.
- **Lesson memory** kiểu Reflexion: `{trigger_pattern, error_code, fix, evidence_run_id, chip, peripheral}`.
  - Chỉ lưu khi fix đã được simulator xác nhận.
  - Truy hồi ở INTAKE theo chip, peripheral và error_code.
- **Task chuỗi cho learning curve:** cùng mẫu lỗi gặp lại n lần; đo Mean Repair Iterations theo lần gặp.
- Cờ **A5 `-Lessons`**; **demo D5** (lesson MOE từ TIM1 dùng lại cho TIM8).
- **Lưu ý tách dữ liệu:** lesson học trên `dev` không được chứa đáp án `test`. Ở P9, chạy `test` với kho lesson rỗng hoặc chỉ gồm lesson từ dev, và ghi rõ chọn cách nào.

### P8 — UI (W9, plan §4)
- Thêm các panel Plan (diff khi replan), Board (pin map, clock tree, power), Timeline (sim, DRC, gate, interrupt), Interrupt cards, Lessons, Budget.
- UI dùng Run API đã có (`POST /api/runs`, `/resume`, `GET /events` qua SSE hoặc polling).
- **Thoát:** quay được demo D1–D5 trên UI. Có thể làm gọn nếu thiếu thời gian.

### P9 — Đánh giá đầy đủ (plan §7, §8)
1. **Khoá grader, task, prompt và snapshot cuối `agent_final`** (hash vào manifest) **trước khi chạy `test`**.
2. **Fault injection** (`FaultInjector` bọc `ToolHub`): tool lỗi, timeout, dữ liệu sai. Đo Recovery Rate (H7).
3. **C9 độ bền:** biến thể của C1–C3 (tiếng Việt, lỗi chính tả, viết tắt, đảo thứ tự), khoảng 20 task, kế thừa ground truth gốc.
4. **Ablation A1–A7** trên S3 cuối (A7 chỉ chạy trên C6, C7):
   - A2 `-BoardState` để kiểm H3 (D30);
   - A3 `-Sandbox` và A4 `-Reflection` để kiểm H2 (bằng chứng tự sửa vật lý, D35);
   - A6 `-HITL` để kiểm H5 (mới kiểm bằng unit test).
5. **Chạy `test`** cho S0, S1, S2, S2D, S3 cuối với cùng model. Dùng 5 seed cho C3–C5 nếu chi phí cho phép (D43).
6. **Lặp lại nhãn mù trên đầu ra `test`** cho C4 (bộ nhận diện xung đột), C5 (checklist) và C8 (`abstain`), vì các kiểm định hiện có đều là trong mẫu (D29, D34, D42).
7. **Báo cáo:**
   - bảng chính và kiểm định H1–H9;
   - Pareto chi phí (H8), dùng giá thật của gateway;
   - bảng tác động của từng lần sửa grader theo hệ (D38);
   - số vòng chỉnh prompt;
   - phần hạn chế: review do model, không phải người (D01); C5 dev chỉ 4 task; đổi model giữa P2 và P3 (D27).
- **Ước tính chi phí P9 trước khi chạy** và xin duyệt. P9 là lượt tốn nhất: nhiều hệ × test × seed × 7 ablation.

---

## 7. Tồn đọng và rủi ro đã biết (chi tiết ở DECISIONS và các ledger)

- G2 lấy trạng thái khởi đầu từ lời người dùng (D36). Bộ trích xuất đúng 11/11 task dev, nhưng chưa kiểm trên `test`.
- `rollback` có thể làm mất requirement người dùng nêu (C4-011, P4), khiến Gate kiểm đúng phần còn lại và cho qua code sai. Cần đo bằng A2.
- C5-005: S3 không hỏi (0/3) mà tự giả định breakout 3,3 V. Hedge vẫn qua checklist (D42).
- Self-Correction vật lý mới có 5–9 run, nên cần A3, A4 và fault injection để có ý nghĩa thống kê.
- Premature-Finish khoảng 43 %, chủ yếu do G1 trên câu tra cứu (mỗi lần tốn một lời gọi).
- Một lời gọi gateway từng treo khoảng 610 s. Runtime đã không tính thời gian này vào `wall_s`, nhưng vẫn nên đặt timeout ở adapter.
- Giá thật của gateway chưa biết, nên các con số chi phí đều là ước lượng.

---

## 8. Prompt khởi động cho session điều phối của nhóm

```
Bạn là session điều phối cho phần còn lại (P6–P9) của dự án Hardware Support Agent v3 tại
/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project (agent hỗ trợ phần cứng STM32G474/ESP32/nRF52840/FreeRTOS, môn CO5151 Agentic AI).

So với v1 (vòng ReAct tra cứu trên dữ liệu chỉ đọc), v3 đã có: dữ liệu thật từ SVD/PDF; Board State + DRC làm "thế giới" để agent hành động;
sandbox mô phỏng thanh ghi/solver/compile check; runtime state machine có kế hoạch, ngân sách, checkpoint/resume; Verification Gate G1–G5
với lỗi có kiểu để agent tự sửa; HITL interrupt/resume (ask_human, approval) và Run API; harness eval chung cho 5 hệ với grader xác định.
Kế hoạch tổng thể là plan/AgenticUpgradePlan.md. Đã xong P0–P5 (hệ hiện tại S3@P5); còn P6 Policy Engine, P7 Memory, P8 UI, P9 đánh giá đầy đủ.

Đọc theo thứ tự: plan/HANDOFF_P6_P9.md, plan/DECISIONS.md (toàn bộ, đặc biệt D33–D44),
plan/AgenticUpgradePlan.md (§2, §3, §4 W6/W8/W9, §5, §6, §7, §8), plan/P5_Handoff.md (mẫu định dạng brief), plan/P5_progress.md.
Kiểm trạng thái: chạy pytest của agent và eval, đối chiếu bảng TSR trong HANDOFF với eval/results/dev_baseline_v2/scores.jsonl.
Sau đó viết plan/P6_Handoff.md theo định dạng P5_Handoff.md (mục tiêu + tiêu chí thoát, bối cảnh, các bước, quy tắc, checklist, mẫu báo cáo).
Tuân thủ mục 5 "Quy tắc bất biến". Ghi mọi quyết định mới thành D45+ trong plan/DECISIONS.md. Không đọc task split test.
Hỏi tôi trước mọi lượt chạy ước tính > 2 USD.
```

Khi session điều phối viết xong brief, mở session thực thi:
```bash
cd /Users/loc4atnt/Master-Course/Ky3/AgenticAI/project
claude --model claude-sonnet-5-5
```
```
Đọc plan/P6_Handoff.md và plan/DECISIONS.md (tham chiếu plan/AgenticUpgradePlan.md theo các mục brief nêu) rồi thực hiện giai đoạn P6 đúng
phạm vi trong brief. Hỏi tôi ở các điểm brief yêu cầu xác nhận.
```
