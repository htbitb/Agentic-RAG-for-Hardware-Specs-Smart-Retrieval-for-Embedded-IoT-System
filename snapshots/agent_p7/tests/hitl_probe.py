"""Tiến trình con cho test HITL: MODE=clean (hỏi + người trả lời ngay trong CÙNG tiến trình), crash (ask rồi os._exit(137) khi đang INTERRUPTED),
resume (tiến trình MỚI nạp checkpoint và resume với câu trả lời).   python hitl_probe.py DIR MODE
"""
import json
import os
import sys
from pathlib import Path

DIR = Path(sys.argv[1])
MODE = sys.argv[2]
os.environ.update({"AGENT_DOTENV": "0", "MEMORY_DB": str(DIR / "memory.sqlite"), "BOARD_STATE_DB": str(DIR / "board.sqlite"),
                   "AUDIT_LOG": str(DIR / "audit.jsonl"), "SANDBOX_DIR": str(DIR / "sandbox"), "LLM_API_KEY": ""})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

from agent.runtime.checkpoint import CheckpointStore          # noqa: E402
from agent.runtime.flags import Ablations                     # noqa: E402
from agent.runtime.loop import AgentRuntime                   # noqa: E402
from agent.scripted import ScriptedPolicy, say, tool          # noqa: E402
from agent.tools import ToolHub                               # noqa: E402
import runtime_helpers  # noqa: E402,F401
from runtime_fakes import FakeGate                            # noqa: E402

ASK = tool("ask_human", kind="clarify", question="What is the HSE crystal frequency of your board?", why_needed="PLL settings depend on it")
WRITE = tool("write_config_file", filename="clock.h", content="#define HSE_HZ 8000000\n")
STEPS = [ASK, WRITE, tool("set_target", chip="stm32g474", package="LQFP64", vdd=3.3), say("final answer")]
ANSWERS = [("answer", {"answer": "The board has an 8 MHz crystal on HSE."}), ("approve", {})]

store = CheckpointStore(DIR / ("ck_clean.sqlite" if MODE == "clean" else "ck.sqlite"))
rt = AgentRuntime(hub=ToolHub(transport="inproc"), llm=ScriptedPolicy(STEPS), store=store, gate=FakeGate(), ablations=Ablations(), system_prompt="SYSTEM PROMPT", allow_scripted=True)
events = []


def keep(out):
    events.extend(out["events"])


if MODE == "resume":
    run_id = store.waiting_runs()[0]
    itr = store.load(run_id).pending_interrupt
    out = rt.resume(run_id, itr["id"], *ANSWERS[0 if itr["kind"] == "clarify" else 1])
    keep(out)
    while out["status"] == "interrupted":
        out = rt.resume(run_id, out["interrupt"]["id"], *ANSWERS[0 if out["interrupt"]["kind"] == "clarify" else 1])
        keep(out)
else:
    out = rt.ask("goal", session_id="probe")
    keep(out)
    if MODE == "crash":
        assert out["status"] == "interrupted"
        print(json.dumps({"interrupt": out["interrupt"]["id"], "events": events}, default=str), flush=True)
        os._exit(137)
    while out["status"] == "interrupted":
        out = rt.resume(out["run_id"], out["interrupt"]["id"], *ANSWERS[0 if out["interrupt"]["kind"] == "clarify" else 1])
        keep(out)
drop = {"ts", "run_id", "seq", "latency_s", "wait_s", "interrupt_id"}
print(json.dumps({"answer": out["answer"], "status": out["status"], "tool_calls": out["usage"]["tool_calls"], "asks": out["usage"]["asks"],
                  "events": [{k: v for k, v in e.items() if k not in drop} for e in events], "files": out["files"],
                  "board_version": (out["board_state"] or {}).get("version"), "reqs": [r["id"] for r in (out["board_state"] or {}).get("requirements", [])]}, default=str))
