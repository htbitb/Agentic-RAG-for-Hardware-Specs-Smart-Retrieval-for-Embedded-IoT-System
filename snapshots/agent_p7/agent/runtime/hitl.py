"""Human-in-the-loop v2 (W7): ba loại interrupt — `approval` (write_config_file), `choice` và `clarify` (tool `ask_human`) — thay `approval.py` cho runtime v2.

Runtime lưu checkpoint với `pending_interrupt`, đặt status INTERRUPTED và trả về `status="interrupted"`; `resume(run_id, interrupt_id, decision, payload)` nạp checkpoint,
chèn kết quả như tin nhắn `tool` đúng `tool_call_id` rồi chạy tiếp. Module này chứa phần KHÔNG phụ thuộc vòng lặp: spec của `ask_human`, kiểm tra tham số, dựng
interrupt, kiểm tra quyết định của người, diff của file. Giữ nguyên validate tên file / sandbox / audit của `approval.py`.
"""
from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass, field

import config
from agent import approval

KINDS = ("choice", "clarify", "approval")
DECISIONS = {"clarify": ("answer", "unknown"), "choice": ("choose", "unknown"), "approval": ("approve", "reject")}
UNKNOWN_ANSWER = "Không biết, hãy tự chọn phương án hợp lý"
MAX_OPTIONS = 4

ASK_HUMAN_SPEC = {
    "name": "ask_human",
    "description": ("[control] Pause the run and ask the human user ONE question; the run resumes when they answer and the answer is the result of this call. "
                    "kind='clarify': information that is REQUIRED for a correct result, that the user did not give, and that no tool can look up because it is a fact "
                    "about THEIR project (for example the crystal frequency on their board, the supply voltage of their sensor module, their current budget, the baud rate "
                    "their peer needs). kind='choice': a real design trade-off that depends on the user's preference; give 2-4 `options`, each with a short label and your "
                    "own pros and cons. Never ask for something a tool can tell you (chip facts, pin functions, limits, electrical values), something you can reasonably "
                    "assume (state the assumption instead), or a confirmation. You have a small number of questions per run; ask everything you need in one question. "
                    "`why_needed` says what you cannot decide without the answer."),
    "inputSchema": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": ["clarify", "choice"]},
        "question": {"type": "string", "description": "the question, self-contained"},
        "options": {"type": "array", "description": "for kind=choice: 2-4 alternatives", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "pros": {"type": "string"}, "cons": {"type": "string"}}, "required": ["label"]}},
        "why_needed": {"type": "string", "description": "why the result depends on the answer"}}, "required": ["kind", "question", "why_needed"]},
}


class AskError(ValueError):
    """Tham số của `ask_human` không hợp lệ (thông điệp trả lại cho agent)."""


class ResumeError(ValueError):
    """`resume` bị từ chối: interrupt_id sai/đã dùng, run không chờ người, hoặc quyết định/payload không hợp lệ. Không có gì được chạy hay thay đổi."""


@dataclass
class AskRequest:
    kind: str
    question: str
    why_needed: str
    options: list = field(default_factory=list)


def new_interrupt_id() -> str:
    return "i_" + uuid.uuid4().hex[:8]


def parse_ask_human(args: dict) -> AskRequest:
    if not isinstance(args, dict):
        raise AskError("arguments must be an object {kind, question, why_needed, options?}")
    kind = args.get("kind")
    if kind not in ("clarify", "choice"):
        raise AskError("`kind` must be 'clarify' or 'choice'")
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        raise AskError("`question` must be a non-empty string")
    why = args.get("why_needed")
    if not isinstance(why, str) or not why.strip():
        raise AskError("`why_needed` must say what you cannot decide without the answer")
    options: list[dict] = []
    if kind == "choice":
        raw = args.get("options")
        if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_OPTIONS:
            raise AskError(f"kind=choice needs `options`: a list of 2-{MAX_OPTIONS} alternatives")
        for i, o in enumerate(raw):
            o = {"label": o} if isinstance(o, str) else o
            label = o.get("label") if isinstance(o, dict) else None
            if not isinstance(label, str) or not label.strip():
                raise AskError(f"option #{i}: `label` must be a non-empty string")
            options.append({"id": chr(ord("A") + i), "label": label.strip(), "pros": str(o.get("pros") or "").strip(), "cons": str(o.get("cons") or "").strip()})
        if len({o["label"].lower() for o in options}) != len(options):
            raise AskError("options must have different labels")
    elif args.get("options"):
        raise AskError("`options` is only for kind=choice (a clarify question is free text)")
    return AskRequest(kind=kind, question=question.strip(), why_needed=why.strip(), options=options)


def make_interrupt(kind: str, tool: str, tool_call_id: str, question: str, why_needed: str = "", options: list | None = None, payload: dict | None = None) -> dict:
    return {"id": new_interrupt_id(), "kind": kind, "tool": tool, "tool_call_id": tool_call_id, "question": question, "why_needed": why_needed,
            "options": options or None, "payload": payload or {}}


def public(interrupt: dict | None) -> dict | None:
    """Phần của interrupt trả cho UI/adapter (đúng hình dạng P5_interfaces §1)."""
    return dict(interrupt) if interrupt else None


# ---------------------------------------------------------------------- approval
def file_diff(filename: str, content: str) -> tuple[str, bool]:
    """(diff unified so với file hiện có trong sandbox, có ghi đè không). File chưa có => diff của toàn bộ nội dung mới."""
    target = config.SANDBOX_DIR / filename
    old = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    diff = "".join(difflib.unified_diff(old.splitlines(True), content.splitlines(True), fromfile=f"a/{filename}" if old else "/dev/null", tofile=f"b/{filename}", n=2))
    return diff[:4000], target.is_file()


def approval_interrupt(tool_call_id: str, filename: str, content: str) -> dict:
    diff, overwrites = file_diff(filename, content)
    return make_interrupt("approval", "write_config_file", tool_call_id, f"Allow the agent to write {filename} ({len(content.encode())} bytes) to the workspace?",
                          payload={"filename": filename, "content": content, "diff": diff, "bytes": len(content.encode()), "overwrites": overwrites})


def check_args_for_write(args: dict) -> str | None:
    """Lỗi chính sách (tên/đuôi/kích thước/đường dẫn) hoặc None. Chạy TRƯỚC khi tạo interrupt: không hỏi người về thứ chắc chắn bị từ chối."""
    if not isinstance(args, dict) or not isinstance(args.get("filename"), str) or not isinstance(args.get("content"), str):
        return "filename and content must be strings"
    return approval.validate(args["filename"], args["content"])


# ---------------------------------------------------------------------- quyết định của người
def validate_resolution(interrupt: dict, decision, payload) -> dict:
    """Kiểm tra `decision`/`payload` theo kind; trả payload đã chuẩn hoá. Ném ResumeError (thông điệp rõ) — chưa có gì thay đổi."""
    kind = interrupt["kind"]
    payload = payload if isinstance(payload, dict) else {}
    if decision not in DECISIONS[kind]:
        raise ResumeError(f"interrupt {interrupt['id']} is a {kind!r}: decision must be one of {list(DECISIONS[kind])}, got {decision!r}")
    if kind == "clarify":
        ans = payload.get("answer")
        if decision == "answer" and (not isinstance(ans, str) or not ans.strip()):
            raise ResumeError("decision 'answer' needs payload.answer (non-empty text)")
        return {"answer": ans.strip() if isinstance(ans, str) and ans.strip() else UNKNOWN_ANSWER}
    if kind == "choice":
        if decision == "unknown":
            return {"answer": str(payload.get("answer") or UNKNOWN_ANSWER).strip()}
        opt = payload.get("option")
        match = next((o for o in interrupt["options"] or [] if isinstance(opt, str) and opt.strip().lower() in (o["id"].lower(), o["label"].lower())), None)
        if match is None:
            raise ResumeError(f"payload.option must be one of {[o['id'] for o in interrupt['options'] or []]} or its label, got {opt!r}")
        return {"option": match["id"], "label": match["label"], "comment": str(payload.get("comment") or "").strip()}
    return {"feedback": str(payload.get("feedback") or "").strip()}


def choice_rationale(interrupt: dict, res: dict) -> str:
    o = next(o for o in interrupt["options"] if o["id"] == res["option"])
    parts = [f"chosen by the user: {o['label']}"]
    if o.get("pros"):
        parts.append(f"pros: {o['pros']}")
    if o.get("cons"):
        parts.append(f"cons: {o['cons']}")
    if res.get("comment"):
        parts.append(f"user comment: {res['comment']}")
    return "; ".join(parts)


def clarify_requirement(interrupt: dict, answer: str, n: int) -> dict:
    """Câu trả lời clarify ghi vào Board State như một requirement kiểu `other` đã thoả (bằng chứng: lời người dùng)."""
    return {"id": f"CLARIFY-{n}", "type": "other", "status": "satisfied", "evidence": f"human:{interrupt['id']}", "question": interrupt["question"][:300], "answer": answer[:500]}
