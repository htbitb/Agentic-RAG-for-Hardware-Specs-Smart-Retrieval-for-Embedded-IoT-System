"""Dựng AgentRuntime cho test: ToolHub inproc THẬT (đủ 4 server), ScriptedPolicy, Gate giả; project_id duy nhất mỗi test."""
from __future__ import annotations

import sys
import types as _types
import uuid
from dataclasses import dataclass, field

try:                                                    # Gate thật (subagent) — thiếu GateContext/GateFlags (chưa xong) thì bù shim tối thiểu để test được runtime riêng
    import agent.gate as _gate
except ImportError:                                     # pragma: no cover
    _gate = _types.ModuleType("agent.gate")
    sys.modules["agent.gate"] = _gate

if not hasattr(_gate, "GateContext"):                   # pragma: no cover
    @dataclass
    class GateContext:
        answer: str
        user_texts: list
        observations: list
        prior_answers: list = field(default_factory=list)
        waived: list = field(default_factory=list)
        chip: str | None = None
        initial: object = "reset"
        hse_hz: int | None = None

    _gate.GateContext = GateContext
if not hasattr(_gate, "GateFlags"):                     # pragma: no cover
    @dataclass
    class GateFlags:
        g1: bool = True; g2: bool = True; g3: bool = True; g4: bool = True; g5: bool = True
        board: bool = True; strict_v1_provenance: bool = False
        waivable: tuple = ("G2-UNMODELED", "G5-SKIPPED")

    _gate.GateFlags = GateFlags

from agent.runtime.checkpoint import CheckpointStore
from agent.runtime.flags import Ablations
from agent.runtime.loop import AgentRuntime
from agent.scripted import ScriptedPolicy
from agent.tools import ToolHub
from runtime_fakes import FakeGate


def build(tmp_path, steps, gate=None, ablations="", budgets=None, policy=None, db=None, trace_dir=None, max_repairs=3, hitl=False, **kw):
    """`hitl=False` (mặc định, giữ nguyên hành vi P4 của các test cũ) thêm cờ A6: ẩn ask_human, approval tự duyệt, không mời hỏi khi leo thang. Test HITL truyền hitl=True."""
    codes = [c for c in str(ablations).replace(" ", "").split(",") if c] if isinstance(ablations, str) else list(ablations)
    abl = Ablations.from_codes(codes if hitl or "A6" in codes else [*codes, "A6"])
    hub = ToolHub(transport="inproc", disabled_servers=abl.disabled_servers())
    store = CheckpointStore(db or tmp_path / "ck.sqlite")
    llm = policy or ScriptedPolicy(steps)
    rt = AgentRuntime(hub=hub, llm=llm, store=store, gate=gate or FakeGate(), ablations=abl, budgets=budgets, system_prompt="SYSTEM PROMPT",
                      trace_dir=trace_dir, max_repairs=max_repairs, allow_scripted=True, **kw)
    if hasattr(rt.gate, "attach"):                      # Gate thật cần runtime.gate_call để gọi tool qua hub
        rt.gate.attach(rt)
    return rt


def sid() -> str:
    return "t-" + uuid.uuid4().hex[:8]


def types(out) -> list[str]:
    return [e["type"] for e in out["events"]]


def of(out, type_):
    return [e for e in out["events"] if e["type"] == type_]


def strip(events):
    """Sự kiện không có trường phụ thuộc thời gian/run (để so sánh hai lần chạy)."""
    drop = {"ts", "run_id", "latency_s", "wait_s"}
    return [{k: v for k, v in e.items() if k not in drop} for e in events]
