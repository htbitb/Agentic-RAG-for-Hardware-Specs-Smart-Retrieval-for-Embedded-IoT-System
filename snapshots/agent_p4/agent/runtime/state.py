"""AgentState: toàn bộ trạng thái của MỘT run (một lượt người dùng) của runtime v3, serialize được sang JSON (W4).

`checkpoint.CheckpointStore` ghi nó vào SQLite sau mỗi bước nên run có thể resume sau khi tiến trình bị kill. Mọi thứ cần để chạy tiếp
(messages gửi LLM, kế hoạch, ngân sách đã dùng, bộ đếm lỗi, tool call còn dang dở) nằm ở đây; không có trạng thái ẩn trong tiến trình.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, fields

PLAN_STATUSES = ("todo", "doing", "done", "dropped")
TERMINAL = ("DONE", "REFUSED", "ESCALATED")


class PlanError(ValueError):
    """Kế hoạch gửi tới `update_plan` không hợp lệ (thông điệp được trả lại cho agent)."""


@dataclass
class Budgets:
    steps: int = 40            # số lời gọi LLM tối đa mỗi run
    tokens: int = 1_500_000    # tokens vào + ra tối đa mỗi run (pilot: ~28 nghìn token/lời gọi ở bước 35 => 900 000 chạm trước 40 bước; steps là giới hạn chính)
    usd: float = 0.50          # theo giá cấu hình (config.PRICE_*); giá thật của gateway chưa biết, nên đây chủ yếu là lưới an toàn
    wall_s: float = 600.0      # giây hoạt động (không tính thời gian chờ giữa các lần resume); phải nhỏ hơn timeout của adapter (900 s)

    @classmethod
    def from_overrides(cls, overrides: dict | None) -> "Budgets":
        base = cls()
        for k, v in (overrides or {}).items():
            if v is not None and hasattr(base, k):
                setattr(base, k, type(getattr(base, k))(v))
        return base

    def to_dict(self) -> dict:
        return asdict(self)


def _used() -> dict:
    return {"steps": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0, "wall_s": 0.0, "llm_calls": 0, "tool_calls": 0}


@dataclass
class AgentState:
    run_id: str
    project_id: str
    goal: str
    turn: int
    status: str = "INTAKE"                       # INTAKE PLAN ACT OBSERVE CHECK FINISH_GATE | DONE REFUSED ESCALATED
    seed: int | None = None
    messages: list = field(default_factory=list)
    plan: list = field(default_factory=list)
    budgets: dict = field(default_factory=lambda: Budgets().to_dict())
    used: dict = field(default_factory=_used)
    iteration_counters: dict = field(default_factory=dict)       # mã lỗi -> số lần gặp (Gate, từ chối của board, mô phỏng)
    artifacts: list = field(default_factory=list)                # ứng viên câu trả lời: {id, text, gate: {...}, accepted}
    observations: list = field(default_factory=list)             # [{tool, args, result}] bằng chứng cho Gate (không cắt)
    pending_calls: list = field(default_factory=list)            # tool call của tin nhắn assistant cuối chưa có kết quả
    in_flight: dict | None = None                                # tool không-read-only đang chạy khi tiến trình chết (at-most-once)
    replan_pending: dict | None = None                           # {reason, code}: agent phải update_plan trước khi hành động tiếp
    sim_context: dict = field(default_factory=dict)              # {"initial", "hse_hz"} lấy từ lần simulate_register_writes gần nhất
    waived: list = field(default_factory=list)                   # [{"id", "reason"}] từ finish(waived_requirements)
    finish_attempts: int = 0
    notice_sent: bool = False                                    # đã gửi BUDGET NOTICE (một lần mỗi run)
    gate_attempts: int = 0
    answer: str | None = None
    outcome: str | None = None                                   # answered | refused | blocked | escalated | error
    escalation: dict | None = None
    events: list = field(default_factory=list)                   # trace chuẩn hoá (P4_interfaces §4) của run này
    seq: int = 0
    errors: list = field(default_factory=list)
    created: float = field(default_factory=time.time)

    # ------------------------------------------------------------------ dựng / serialize
    @classmethod
    def new(cls, run_id: str, project_id: str, goal: str, turn: int, budgets: Budgets | dict | None = None, seed: int | None = None) -> "AgentState":
        b = budgets.to_dict() if isinstance(budgets, Budgets) else dict(budgets or Budgets().to_dict())
        return cls(run_id=run_id, project_id=project_id, goal=goal, turn=turn, budgets=b, seed=seed)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, text: str) -> "AgentState":
        d = json.loads(text)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    # ------------------------------------------------------------------ ngân sách / bộ đếm
    def budget_exceeded(self) -> str | None:
        """Tên chiều ngân sách đầu tiên đã cạn (steps, tokens, usd, wall_s) hoặc None."""
        b, u = self.budgets, self.used
        if u["steps"] >= b["steps"]:
            return "steps"
        if u["tokens_in"] + u["tokens_out"] >= b["tokens"]:
            return "tokens"
        if u["usd"] >= b["usd"]:
            return "usd"
        if u["wall_s"] >= b["wall_s"]:
            return "wall_s"
        return None

    def budget_pressure(self, ratio: float = 0.75) -> tuple[str, float, float] | None:
        """(chiều, đã dùng, giới hạn) của chiều ngân sách đầu tiên đã dùng ≥ `ratio` giới hạn, hoặc None."""
        b, u = self.budgets, self.used
        for dim, used, limit in (("steps", u["steps"], b["steps"]), ("wall_s", u["wall_s"], b["wall_s"]), ("tokens", u["tokens_in"] + u["tokens_out"], b["tokens"])):
            if limit and used >= ratio * limit:
                return dim, used, limit
        return None

    def count_error(self, code: str) -> int:
        self.iteration_counters[code] = self.iteration_counters.get(code, 0) + 1
        return self.iteration_counters[code]

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL


# ---------------------------------------------------------------------- kế hoạch
def normalize_plan(steps) -> list[dict]:
    """`update_plan(steps)` -> danh sách bước chuẩn hoá {id, title, status, depends_on, acceptance}. Ném PlanError với thông điệp cho agent."""
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except json.JSONDecodeError as exc:
            raise PlanError(f"steps is not valid JSON: {exc}") from None
    if not isinstance(steps, list) or not steps:
        raise PlanError("steps must be a list with at least one step")
    out, seen = [], set()
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            raise PlanError(f"step #{i} must be an object, got {type(s).__name__}")
        sid = s.get("id")
        if not isinstance(sid, str) or not sid.strip():
            raise PlanError(f"step #{i}: `id` must be a non-empty string")
        sid = sid.strip()
        if sid in seen:
            raise PlanError(f"duplicate id {sid!r}")
        seen.add(sid)
        title = s.get("title")
        if not isinstance(title, str) or not title.strip():
            raise PlanError(f"step {sid}: `title` must be a non-empty string")
        status = s.get("status", "todo")
        if status not in PLAN_STATUSES:
            raise PlanError(f"step {sid}: `status` must be one of {list(PLAN_STATUSES)}, got {status!r}")
        deps = s.get("depends_on") or []
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise PlanError(f"step {sid}: `depends_on` must be a list of step ids")
        acc = s.get("acceptance") or ""
        if not isinstance(acc, str):
            raise PlanError(f"step {sid}: `acceptance` must be a string")
        out.append({"id": sid, "title": title.strip(), "status": status, "depends_on": list(deps), "acceptance": acc.strip()})
    ids = {p["id"] for p in out}
    for p in out:
        if p["id"] in p["depends_on"]:
            raise PlanError(f"step {p['id']} depends on itself")
        missing = [d for d in p["depends_on"] if d not in ids]
        if missing:
            raise PlanError(f"step {p['id']} depends_on unknown step(s) {missing}")
    return out


def diff_plans(old: list[dict], new: list[dict]) -> dict:
    """Khác biệt giữa hai phiên bản kế hoạch, dạng chuỗi đọc được (ghi vào sự kiện `plan_updated`)."""
    o, n = {p["id"]: p for p in old}, {p["id"]: p for p in new}
    added = [f"{i}: {p['title']}" for i, p in n.items() if i not in o]
    removed = [f"{i}: {p['title']}" for i, p in o.items() if i not in n]
    changed = []
    for i, p in n.items():
        if i in o and o[i] != p:
            parts = [f"{k} {o[i][k]} -> {p[k]}" for k in ("title", "status", "depends_on", "acceptance") if o[i][k] != p[k]]
            changed.append(f"{i}: " + ", ".join(parts))
    return {"added": added, "removed": removed, "changed": changed}
