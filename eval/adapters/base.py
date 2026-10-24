"""Giao diện chung của mọi hệ được đánh giá (AgenticUpgradePlan §7.5)."""
from __future__ import annotations

import time
from typing import Protocol

from eval.schema import RunResult, Task, TurnResult


class FatalAdapterError(RuntimeError):
    """Lỗi buộc dừng cả lượt chạy (vd S2 rơi về SimulatedLLM) — khác với lỗi của từng run."""


class SystemAdapter(Protocol):
    name: str
    variant: str

    def start(self, task: Task, seed: int) -> None: ...
    def send(self, user_msg: str) -> TurnResult: ...
    def finish(self) -> RunResult: ...
    def close(self) -> None: ...


class AdapterBase:
    """Gom lượt, usage, trace, lỗi; lớp con chỉ cần cài `_ask(user_msg) -> (TurnResult, usage_delta, events)`."""

    name = "?"
    variant = ""

    def __init__(self, cfg):
        self.cfg = cfg
        self._reset()

    def _reset(self):
        self.task = None
        self.seed = 0
        self.turns: list[TurnResult] = []
        self.trace: list[dict] = []
        self.errors: list[str] = []
        self.files: dict[str, str] = {}
        self.usage = {"tokens_in": 0, "tokens_out": 0, "usd": 0.0, "tool_calls": 0, "llm_calls": 0}
        self.t0 = 0.0

    def start(self, task: Task, seed: int) -> None:
        self._reset()
        self.task, self.seed, self.t0 = task, seed, time.time()

    def add_usage(self, tokens_in=0, tokens_out=0, llm_calls=0, tool_calls=0) -> None:
        self.usage["tokens_in"] += tokens_in
        self.usage["tokens_out"] += tokens_out
        self.usage["llm_calls"] += llm_calls
        self.usage["tool_calls"] += tool_calls
        self.usage["usd"] = round(self.cfg.cost(self.usage["tokens_in"], self.usage["tokens_out"]), 8)

    def finish(self) -> RunResult:
        final = self.turns[-1].answer if self.turns else ""
        return RunResult(system=self.name, variant=self.variant, task_id=self.task.id, seed=self.seed, turns=self.turns,
                         final_answer=final, files=self.files, board_state=None, trace=self.trace, usage=dict(self.usage),
                         latency_s=round(time.time() - self.t0, 3), errors=list(self.errors))

    def close(self) -> None:
        pass
