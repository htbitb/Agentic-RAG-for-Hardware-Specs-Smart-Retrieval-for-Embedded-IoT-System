"""Cờ ablation A1–A4 (D32) và A6 `-HITL` (P5): cấu hình, không sửa code khi chạy. Nguồn: tham số `ablations` của build_runtime hoặc env AGENT_ABLATIONS="A1,A3"."""
from __future__ import annotations

from dataclasses import dataclass

_ORDER = ("A1", "A2", "A3", "A4", "A6")
_NAMES = {"A1": "Planner", "A2": "BoardState", "A3": "Sandbox", "A4": "Reflection", "A6": "HITL"}


@dataclass(frozen=True)
class Ablations:
    planner: bool = True        # A1 -Planner: ẩn tool update_plan, bỏ REPLAN_REQUIRED
    board_state: bool = True    # A2 -BoardState: ẩn server board-state; Gate bỏ G3 (và không đọc requirement)
    sandbox: bool = True        # A3 -Sandbox: ẩn server hw-sandbox; G2 tắt; G1 quay về verifier v1
    reflection: bool = True     # A4 -Reflection: ngân sách tự sửa = 0 (Gate fail lần đầu -> ESCALATED)
    hitl: bool = True           # A6 -HITL: ẩn ask_human; write_config_file tự duyệt (không interrupt)

    @classmethod
    def from_codes(cls, codes) -> "Ablations":
        if codes is None:
            items = []
        elif isinstance(codes, str):
            items = [c for c in codes.replace(" ", "").upper().split(",") if c]
        else:
            items = [str(c).strip().upper() for c in codes if str(c).strip()]
        bad = sorted(set(items) - set(_ORDER))
        if bad:
            raise ValueError(f"unknown ablation code(s) {bad}; expected a subset of {list(_ORDER)}")
        off = set(items)
        return cls(planner="A1" not in off, board_state="A2" not in off, sandbox="A3" not in off, reflection="A4" not in off, hitl="A6" not in off)

    def codes(self) -> tuple:
        flags = {"A1": self.planner, "A2": self.board_state, "A3": self.sandbox, "A4": self.reflection, "A6": self.hitl}
        return tuple(c for c in _ORDER if not flags[c])

    def variant(self) -> str:
        """Nhãn đặt vào RunResult.variant: "" cho S3 đầy đủ, "-Planner", "-Planner-Sandbox"..."""
        return "".join("-" + _NAMES[c] for c in self.codes())

    def disabled_servers(self) -> tuple:
        return (("board-state",) if not self.board_state else ()) + (("hw-sandbox",) if not self.sandbox else ())

    def hidden_control_tools(self) -> tuple:
        return (() if self.planner else ("update_plan",)) + (() if self.hitl else ("ask_human",))

    def max_repairs(self, base: int = 3) -> int:
        return base if self.reflection else 0

    def gate_flags(self):
        from agent.gate import GateFlags
        return GateFlags(g2=self.sandbox, g3=self.board_state, g5=self.sandbox, board=self.board_state, strict_v1_provenance=not self.sandbox)
