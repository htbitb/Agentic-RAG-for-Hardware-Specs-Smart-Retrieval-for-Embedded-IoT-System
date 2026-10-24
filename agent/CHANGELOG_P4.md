# CHANGELOG P4 — Agent Runtime v2 + Verification Gate v2 (S3@P4)

Brief: `plan/P4_Handoff.md` · ràng buộc: `plan/DECISIONS.md` D32 · hợp đồng giao diện: `plan/P4_interfaces.md` · ledger/Ruling: `plan/P4_progress.md`.

## Mới
* `agent/runtime/` — `state.py` (`AgentState`, `Budgets`, kế hoạch + diff), `checkpoint.py` (SQLite: trạng thái mới nhất của mỗi run + phiên theo `project_id`),
  `loop.py` (state machine INTAKE → PLAN → ACT ⇄ OBSERVE → CHECK → FINISH_GATE → DONE | REFUSED | ESCALATED), `control_tools.py` (`update_plan`, `finish`),
  `flags.py` (cờ ablation A1–A4), `factory.py` (`build_runtime`), `intake.py` (hardware pre-check của v1, ngữ cảnh dự án), `summary.py`, `cli.py`, `trace.py`.
* `agent/gate/` — Gate v2: G1 provenance, G2 functional (simulator), G3 board DRC, G4 safety, G5 compile; phản hồi lỗi có kiểu `{code, where, expected, actual, hint_source}`.
* `agent/scripted.py` — `ScriptedPolicy` (chỉ test; thay vai trò `SimulatedLLM` trong test runtime).
* `agent/prompts/system_v3.md` — system prompt v2 (mọi lần sửa ghi vào `agent/PROMPT_DEVLOG.md`).
* `ToolHub`: đăng ký `hw-sandbox` và `board-state` (`SERVERS`); **chỉ retry tool `read-only`** (D32) và không retry lỗi tham số; gán `project_id` cho mọi tool board-state
  (ẩn khỏi schema của mô hình); `call(..., internal=True)` cho lời gọi của runtime/Gate; quyền `control` cho `update_plan`/`finish`.
* `config.CHECKPOINT_DB` (`AGENT_CHECKPOINT_DB`).

## Không đổi
`react_agent.py`, `verifier.py`, `guardrail.py`, `memory.py`, `approval.py`, `llm.py` (kể cả `SimulatedLLM`) — UI cũ (`ui/server.py`) vẫn dùng `HardwareAgent` với bộ tool v1
(`disabled_servers` mặc định ẩn `hw-sandbox` và `board-state`).

## Cấu hình khi chạy (không sửa code)
`AGENT_ABLATIONS=A1,A3` · `AGENT_BUDGETS='{"steps":40,"tokens":1500000,"usd":0.5,"wall_s":600}'` · `AGENT_CHECKPOINT_DB` · `AGENT_TRACE_DIR` · `AGENT_COMPACT_KEEP` / `AGENT_COMPACT_CHARS`.

## Chạy thử
`cd agent && .venv/bin/python -m agent.runtime.cli --goal "..." --out /tmp/run [--goal "lượt 2"] [--ablate A1]` (cần LLM_API_KEY; dùng DB tạm trong `--out`).
