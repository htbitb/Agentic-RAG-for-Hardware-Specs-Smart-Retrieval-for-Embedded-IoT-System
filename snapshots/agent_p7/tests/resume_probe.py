"""Tiến trình con cho test resume: chạy một kịch bản trong một tiến trình RIÊNG (có thể bị os._exit giữa chừng) rồi in kết quả JSON.

    python resume_probe.py DIR MODE [KILL_AT]      MODE = clean | crash | resume
"""
import json
import os
import sys
from pathlib import Path

DIR = Path(sys.argv[1])
MODE = sys.argv[2]
KILL_AT = int(sys.argv[3]) if len(sys.argv) > 3 else None
os.environ.update({"AGENT_DOTENV": "0", "MEMORY_DB": str(DIR / "memory.sqlite"), "BOARD_STATE_DB": str(DIR / "board.sqlite"),
                   "AUDIT_LOG": str(DIR / "audit.jsonl"), "SANDBOX_DIR": str(DIR / "sandbox"), "LLM_API_KEY": ""})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

from agent.runtime.checkpoint import CheckpointStore          # noqa: E402
from agent.runtime.flags import Ablations                     # noqa: E402
from agent.runtime.loop import AgentRuntime                   # noqa: E402
from agent.scripted import ScriptedPolicy, say, tool          # noqa: E402
from agent.tools import ToolHub                               # noqa: E402
import runtime_helpers  # noqa: E402,F401  (cài shim agent.gate nếu Gate thật chưa có)
from runtime_fakes import FakeGate                            # noqa: E402

PLAN = [{"id": "s1", "title": "record target", "status": "doing"}]
STEPS = [tool("list_chips"), tool("set_target", chip="stm32g474", package="LQFP64", vdd=3.3), tool("update_plan", steps=PLAN, rationale="r"), say("final answer")]

policy = ScriptedPolicy(STEPS, kill_at=KILL_AT if MODE == "crash" else None, hard_kill=True)
store = CheckpointStore(DIR / ("ck_clean.sqlite" if MODE == "clean" else "ck.sqlite"))
rt = AgentRuntime(hub=ToolHub(transport="inproc"), llm=policy, store=store, gate=FakeGate(), ablations=Ablations(), system_prompt="SYSTEM PROMPT", allow_scripted=True)
if MODE == "resume":
    run_id = store.unfinished_runs()[0]
    out = rt.resume(run_id)
else:
    out = rt.ask("goal", session_id="probe")
drop = {"ts", "run_id", "seq", "latency_s", "wait_s"}
print(json.dumps({"answer": out["answer"], "status": out["status"], "plan": out["plan"], "usage_calls": out["usage"]["llm_calls"], "tool_calls": out["usage"]["tool_calls"],
                  "events": [{k: v for k, v in e.items() if k not in drop} for e in out["events"] if e["type"] != "resumed"],
                  "board_version": (out["board_state"] or {}).get("version"), "board_targets": (out["board_state"] or {}).get("targets")}, default=str))
