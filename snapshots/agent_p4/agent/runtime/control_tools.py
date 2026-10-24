"""Tool điều khiển của runtime v3 (quyền `control`, không đi qua MCP): update_plan và finish (§4 W4)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from agent.runtime.state import normalize_plan

UPDATE_PLAN_SPEC = {
    "name": "update_plan",
    "description": ("[control] Write or revise your explicit plan for the goal. `steps` is the COMPLETE new plan (it replaces the previous one): each step has "
                    "{id, title, status: todo|doing|done|dropped, depends_on: [step ids], acceptance: how you will know the step is done}. Call it before acting on any "
                    "goal that needs more than one step, whenever you learn something that changes the approach (a failed check, a resource conflict, missing "
                    "information, a requirement that cannot be met), and to mark progress. The runtime records the difference between plans; when it reports "
                    "REPLAN_REQUIRED you must call this tool before any other action."),
    "inputSchema": {"type": "object", "properties": {
        "steps": {"type": "array", "description": "the complete plan", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "title": {"type": "string"},
            "status": {"type": "string", "enum": ["todo", "doing", "done", "dropped"]},
            "depends_on": {"type": "array", "items": {"type": "string"}}, "acceptance": {"type": "string"}}, "required": ["id", "title"]}},
        "rationale": {"type": "string", "description": "why the plan changed"}}, "required": ["steps"]},
}

FINISH_SPEC = {
    "name": "finish",
    "description": ("[control] Declare the work finished and submit the final answer. `summary` must be the COMPLETE answer exactly as the user should read it: the "
                    "explanation, every conflict or problem you found and why you chose the alternative, and all code in fenced code blocks (this is the only text "
                    "the user receives from this call). `deliverables` names the artifacts it contains (e.g. [\"pwm_tim1.c\"]). `waived_requirements` lists recorded "
                    "requirements you could NOT verify, each with a reason: [{id, reason}] (only things the tools cannot model can be waived). The runtime checks the "
                    "answer against its gates (provenance of numbers and citations, simulation of your code against the requirements you recorded, board design "
                    "rules, safety, compile); if a gate fails you receive typed findings {code, where, expected, actual, hint_source} and must fix the problem or "
                    "explain why it cannot be fixed. Call finish on its own, not together with other tool calls."),
    "inputSchema": {"type": "object", "properties": {
        "summary": {"type": "string", "description": "the complete final answer for the user"},
        "deliverables": {"type": "array", "items": {"type": "string"}},
        "waived_requirements": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
                                                           "required": ["id", "reason"]}}}, "required": ["summary"]},
}

CONTROL_SPECS = {"update_plan": UPDATE_PLAN_SPEC, "finish": FINISH_SPEC}


class FinishError(ValueError):
    """Tham số của `finish` không hợp lệ (thông điệp trả lại cho agent)."""


@dataclass
class FinishRequest:
    answer: str
    deliverables: list = field(default_factory=list)
    waived: list = field(default_factory=list)
    implicit: bool = False


def parse_update_plan(args: dict):
    """-> (kế hoạch chuẩn hoá, lý do). Ném PlanError."""
    from agent.runtime.state import PlanError
    if not isinstance(args, dict) or "steps" not in args:
        raise PlanError("`steps` is required (the complete plan as a list of steps)")
    return normalize_plan(args["steps"]), str(args.get("rationale") or "").strip()


def parse_finish(args: dict) -> FinishRequest:
    summary = args.get("summary") if isinstance(args, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        raise FinishError("`summary` must be the complete final answer as a non-empty string")
    deliverables = args.get("deliverables") or []
    if not isinstance(deliverables, list) or not all(isinstance(d, str) for d in deliverables):
        raise FinishError("`deliverables` must be a list of strings")
    waived = args.get("waived_requirements") or []
    if isinstance(waived, str):
        try:
            waived = json.loads(waived)
        except json.JSONDecodeError:
            raise FinishError("`waived_requirements` is not valid JSON") from None
    if not isinstance(waived, list) or not all(isinstance(w, dict) and isinstance(w.get("id"), str) and w["id"].strip() for w in waived):
        raise FinishError("`waived_requirements` must be a list of {id, reason}")
    if any(not isinstance(w.get("reason"), str) or not w["reason"].strip() for w in waived):
        raise FinishError("every waived requirement needs a non-empty `reason`")
    return FinishRequest(answer=summary.strip(), deliverables=list(deliverables), waived=[{"id": w["id"].strip(), "reason": w["reason"].strip()} for w in waived])
