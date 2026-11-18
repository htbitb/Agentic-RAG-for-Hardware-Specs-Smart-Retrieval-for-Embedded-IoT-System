"""build_runtime: dựng AgentRuntime (hub + LLM thật + Gate + checkpoint) từ tham số hoặc biến môi trường — cấu hình, không sửa code khi chạy.

    AGENT_ABLATIONS="A1,A3"      cờ ablation (A1 -Planner, A2 -BoardState, A3 -Sandbox, A4 -Reflection)
    AGENT_BUDGETS='{"steps": 40}' ghi đè ngân sách (steps, tokens, usd, wall_s)
    AGENT_COMPACT_KEEP=12 / AGENT_COMPACT_CHARS=1500   nén kết quả tool cũ trong ngữ cảnh gửi LLM (0 = tắt)
    AGENT_CHECKPOINT_DB, AGENT_TRACE_DIR, BOARD_STATE_DB, MEMORY_DB ...   đường dẫn (config.py)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import config
from agent.runtime.checkpoint import CheckpointStore
from agent.runtime.flags import Ablations
from agent.runtime.loop import AgentRuntime
from agent.tools import ToolHub

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "system_v3.md"


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def real_llm():
    """LLM thật (OpenAI-compatible). Không có khoá => lỗi rõ ràng, KHÔNG rơi về mô phỏng (mọi kết luận về tính agentic phải dùng model thật)."""
    if not config.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is not set (agent/.env or the environment): the v3 runtime does not fall back to a simulated model")
    from agent.llm import OpenAICompatLLM
    return OpenAICompatLLM()


def build_runtime(llm=None, transport: str | None = None, ablations=None, budgets: dict | None = None, checkpoint_db=None, trace_dir=None,
                  system_prompt: str | None = None, allow_scripted: bool = False, **kw) -> AgentRuntime:
    from agent.gate import Gate
    abl = ablations if isinstance(ablations, Ablations) else Ablations.from_codes(os.environ.get("AGENT_ABLATIONS", "") if ablations is None else ablations)
    if budgets is None and os.environ.get("AGENT_BUDGETS", "").strip():
        budgets = json.loads(os.environ["AGENT_BUDGETS"])
    llm = llm if llm is not None else real_llm()
    if getattr(llm, "simulated", False) and not allow_scripted:
        raise ValueError("refusing to build the v3 runtime with a simulated/scripted LLM (tests pass allow_scripted=True)")
    if "compact_keep" not in kw and os.environ.get("AGENT_COMPACT_KEEP", "").strip():
        k = int(os.environ["AGENT_COMPACT_KEEP"])
        kw["compact_keep"] = k if k > 0 else None
    if "compact_chars" not in kw and os.environ.get("AGENT_COMPACT_CHARS", "").strip():
        kw["compact_chars"] = int(os.environ["AGENT_COMPACT_CHARS"])
    hub = ToolHub(transport=transport or config.MCP_TRANSPORT, disabled_servers=abl.disabled_servers())
    store = CheckpointStore(checkpoint_db or os.environ.get("AGENT_CHECKPOINT_DB") or config.CHECKPOINT_DB)
    tdir = trace_dir or os.environ.get("AGENT_TRACE_DIR") or None
    rt = AgentRuntime(hub=hub, llm=llm, store=store, gate=None, ablations=abl, budgets=budgets, system_prompt=system_prompt or load_system_prompt(),
                      trace_dir=tdir, allow_scripted=allow_scripted, **kw)
    rt.gate = Gate(rt.gate_call, abl.gate_flags())
    return rt
