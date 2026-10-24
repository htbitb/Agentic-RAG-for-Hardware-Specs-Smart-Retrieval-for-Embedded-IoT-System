"""Human-in-the-Loop approval gate for irreversible-write tools (plan 4.3, AT4).

The agent can only *request* `write_config_file`; nothing is written until a
human approves the pending action (CLI prompt or UI button). Writes are
sandboxed to config.SANDBOX_DIR, filenames are whitelisted, every step is audited.
"""
import re
import threading
import uuid

import config
from agent import audit

ALLOWED_EXT = {".h", ".c", ".txt", ".json", ".md"}
MAX_BYTES = 20_000
_pending: dict[str, dict] = {}
_lock = threading.Lock()

WRITE_TOOL_SPEC = {
    "name": "write_config_file",
    "description": "[irreversible-write, requires human approval] Save a generated firmware configuration snippet "
                   "into the sandboxed workspace_out/ folder. Only plain file names (no paths).",
    "inputSchema": {"type": "object", "properties": {
        "filename": {"type": "string", "description": "e.g. pa8_pwm_config.h"},
        "content": {"type": "string"}}, "required": ["filename", "content"]},
}


def validate(filename: str, content: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}\.[a-z]{1,4}", filename or ""):
        return "filename must be a plain name like 'config.h' (no directories, no '..')"
    if "." + filename.rsplit(".", 1)[-1] not in ALLOWED_EXT:
        return f"extension not allowed; allowed: {sorted(ALLOWED_EXT)}"
    if len((content or "").encode()) > MAX_BYTES:
        return "content too large"
    target = (config.SANDBOX_DIR / filename).resolve()
    if config.SANDBOX_DIR.resolve() not in target.parents:
        return "path escapes sandbox"
    return None


def request(filename: str, content: str, session_id: str, reason: str = "") -> dict:
    err = validate(filename, content)
    if err:
        audit.log("guarded_action_rejected_by_policy", tool="write_config_file", filename=filename, reason=err,
                  session=session_id)
        return {"status": "rejected_by_policy", "error": err}
    aid = uuid.uuid4().hex[:8]
    with _lock:
        _pending[aid] = {"id": aid, "filename": filename, "content": content, "session": session_id, "reason": reason}
    audit.log("guarded_action_requested", action_id=aid, tool="write_config_file", filename=filename,
              bytes=len(content), session=session_id)
    return {"status": "pending_approval", "action_id": aid,
            "message": "A human must approve this write before it is executed."}


def pending(session_id: str | None = None) -> list[dict]:
    with _lock:
        return [a for a in _pending.values() if session_id in (None, a["session"])]


def write_approved(filename: str, content: str, session_id: str = "", approver: str = "user", action_id: str | None = None) -> dict:
    """Ghi file đã được DUYỆT vào sandbox (kiểm lại tên/nội dung/đường dẫn ngay lúc ghi, ghi audit). Dùng chung cho HITL v1 (`decide`) và interrupt `approval` của runtime v3."""
    err = validate(filename, content)
    if err:
        audit.log("guarded_action_rejected_by_policy", action_id=action_id, reason=err, session=session_id)
        return {"status": "rejected_by_policy", "error": err}
    target = config.SANDBOX_DIR / filename
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    audit.log("guarded_action_executed", action_id=action_id, approver=approver, path=str(target), overwrote=existed, bytes=len(content), session=session_id)
    return {"status": "executed", "action_id": action_id, "path": str(target), "overwrote": existed}


def decide(action_id: str, approve: bool, approver: str = "user") -> dict:
    with _lock:
        act = _pending.pop(action_id, None)
    if not act:
        return {"status": "unknown_action", "action_id": action_id}
    if not approve:
        audit.log("guarded_action_denied", action_id=action_id, approver=approver, filename=act["filename"])
        return {"status": "denied", "action_id": action_id}
    res = write_approved(act["filename"], act["content"], act["session"], approver, action_id)  # kiểm lại lúc thực thi
    return {k: res[k] for k in ("status", "action_id", "path", "error") if k in res}
