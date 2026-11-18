"""ScriptedPolicy (trước đây SimulatedLLM): chính sách có kịch bản dùng để kiểm thử luồng trạng thái của runtime mà không tốn API (§4 W4).

CHỈ DÙNG TRONG TEST: mọi kết luận về tính agentic phải dùng LLM thật. `simulated = True` khiến build_runtime từ chối nó khi chạy thật.
Bước thứ k của kịch bản được chọn theo số tin nhắn assistant đã có SAU tin nhắn người dùng (mục tiêu) gần nhất => chỉ phụ thuộc vào trạng thái hội thoại,
nên một instance mới (sau khi kill + resume) tiếp tục đúng chỗ. Nhiều lượt: truyền danh sách các danh sách bước (một danh sách cho mỗi lượt).
"""
from __future__ import annotations

import json
import os

from agent.llm import LLMResponse, _est_tokens


FEEDBACK_PREFIXES = ("FINISH GATE FAILED", "REPLAN_REQUIRED", "BUDGET NOTICE", "ESCALATION NOTICE", "Your reply was empty", "The run limit was reached")


def position(messages) -> tuple[int, int]:
    """(chỉ số lượt, chỉ số bước trong lượt): tin nhắn người dùng không phải phản hồi của runtime là mục tiêu của một lượt mới."""
    turn, last_goal = -1, -1
    for i, m in enumerate(messages):
        if m.get("role") == "user" and not str(m.get("content", "")).startswith(FEEDBACK_PREFIXES):
            turn, last_goal = turn + 1, i
    return max(turn, 0), sum(1 for m in messages[last_goal + 1:] if m.get("role") == "assistant")


def check_pairing(messages) -> None:
    """Mỗi tin nhắn assistant có tool_calls phải được trả lời đủ (mọi id) bởi các tin nhắn `tool` đi liền sau nó; không có tin nhắn `tool` mồ côi.
    Gửi một lịch sử sai cặp tới endpoint chặt là lỗi 400 (review P4 I1) — test của runtime bắt lỗi này ở đây."""
    pending: dict[str, int] = {}
    for i, m in enumerate(messages):
        role = m.get("role")
        if role == "tool":
            cid = m.get("tool_call_id")
            assert cid in pending, f"tool message #{i} answers tool_call_id {cid!r} that no preceding assistant message made"
            del pending[cid]
            continue
        assert not pending, f"tool_call(s) {sorted(pending)} are unanswered before message #{i} ({role})"
        if role == "assistant":
            pending = {c["id"]: i for c in m.get("tool_calls") or []}
    assert not pending, f"tool_call(s) {sorted(pending)} are unanswered at the end of the history"


class SimulatedKill(BaseException):
    """Mô phỏng tiến trình bị kill giữa chừng: kế thừa BaseException để các `except Exception` của runtime không nuốt nó."""


def say(text: str):
    return ("say", text)


def tool(name: str, **arguments):
    return ("calls", [(name, arguments)])


def calls(*specs):
    return ("calls", [(n, a) for n, a in specs])


class ScriptedPolicy:
    simulated = True
    name = "ScriptedPolicy (test only)"

    def __init__(self, steps, kill_at: int | tuple | None = None, hard_kill: bool = False):
        steps = list(steps)
        self.per_turn = bool(steps) and isinstance(steps[0], list)
        self.steps = steps
        self.kill_at = kill_at if isinstance(kill_at, tuple) or kill_at is None else (0, kill_at)      # (lượt, bước trong lượt)
        self.hard_kill = hard_kill                                                                   # True: os._exit(137) (kill tiến trình thật), False: SimulatedKill
        self.offered: list[list[str]] = []

    def chat(self, messages, tools, seed: int | None = None) -> LLMResponse:
        check_pairing(messages)
        turn, idx = position(messages)
        self.offered.append([t["name"] for t in tools or []])
        if self.kill_at is not None and (turn, idx) == self.kill_at:
            if self.hard_kill:
                os._exit(137)
            raise SimulatedKill(f"simulated kill before LLM call #{idx} of turn {turn}")
        script = (self.steps[turn] if turn < len(self.steps) else []) if self.per_turn else self.steps
        assert idx < len(script), f"script exhausted: LLM call #{idx} (turn {turn}) but the script has {len(script)} steps"
        step = script[idx]
        if callable(step):
            step = step(messages, tools)
        kind, payload = step
        usage_in = _est_tokens(messages) + _est_tokens(tools or [])
        if kind == "say":
            return LLMResponse(payload, [], {"in": usage_in, "out": _est_tokens(payload)})
        tcs = [{"id": f"call_{idx}_{j}", "name": n, "arguments": a} for j, (n, a) in enumerate(payload)]
        return LLMResponse(None, tcs, {"in": usage_in, "out": _est_tokens(json.dumps(payload, default=str)) + 5})

    def complete(self, prompt: str) -> str:
        return ""
