"""INTAKE của runtime v3: hardware safety pre-check xác định, chuyển nguyên hành vi từ `HardwareAgent._hardware_check` của v1 (P6 mới sửa guardrail),
và tóm tắt Board State/kế hoạch thành ngữ cảnh dự án cho lượt mới."""
from __future__ import annotations

import json

from agent import audit, guardrail


def hardware_check(hub, question: str, chips: list, ent: dict, emit, observe=None):
    """Trả văn bản từ chối (REFUSED ...) nếu người dùng đòi áp điện áp vượt Absolute Maximum; ngược lại None. Giữ nguyên logic và câu chữ của v1.
    `emit(type, **fields)` ghi sự kiện trace; lời gọi get_electrical_specs là `internal` (không tính vào số tool call của agent);
    `observe({tool, args, result})` (tuỳ chọn) nhận kết quả đó làm bằng chứng cho Gate (m5)."""
    reqs = guardrail.parse_hardware_requests(question)
    if not reqs or not chips:
        return None
    chip = chips[0]
    for req in reqs:
        args = ({"chip": chip, "parameter": "supply voltage VDD"} if req["target"] == "supply"
                else {"chip": chip, "parameter": "input voltage VIH pin", "vdd": ent["vdds"].get(chip, 3.3)})
        res = hub.call("get_electrical_specs", args, internal=True)
        if observe is not None:
            observe({"tool": "get_electrical_specs", "args": args, "result": res})
        emit("tool_call", tool="get_electrical_specs", server=hub.owner.get("get_electrical_specs"), permission="read-only", args=args,
             ok="error" not in res, error=res.get("error"), summary=json.dumps(res, ensure_ascii=False, default=str)[:400], security_flags=res.get("security_flags"),
             internal=True)
        facts = res.get("results", [])
        v = guardrail.evaluate_hw(req, facts, vdd=ent["vdds"].get(chip, 3.3))
        emit("guardrail", stage="hardware_safety", verdict=v["verdict"], limit_V=v["limit"], request=req, blocked=v["verdict"] == "refuse", flags=[])
        audit.log("hardware_safety_check", chip=chip, request=req, verdict=v["verdict"], limit=v["limit"])
        if v["verdict"] == "refuse":
            f = v["fact"]
            op = [x for x in facts if x.get("category") == "recommended_operating" and x.get("field_type") == f.get("field_type")]
            op_txt = "".join(f" Recommended operating range for {o['parameter']}: {o.get('min')}..{o.get('max')} "
                             f"{o['unit']} [{o['doc']} p.{o['page']}]." for o in op[:2])
            return (f"REFUSED (hardware safety): applying {req['volts']} V to the {chip} {req['target']} exceeds "
                    f"the limit of {v['limit']} V ({f['parameter']}, {f['category']}) [{f['doc']} p.{f['page']}]. "
                    f"Exceeding an Absolute Maximum Rating can permanently damage the device, so I will not "
                    f"provide code or instructions for it.{op_txt} Use a level shifter / regulator instead.")
    return None


# ---------------------------------------------------------------------- ngữ cảnh dự án
def _fmt(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def board_summary(st: dict) -> str:
    """Tóm tắt có cấu trúc của Board State (đủ để agent không phải gọi lại get_board_state ngay đầu lượt)."""
    lines = [f"Board State version {st.get('version', 0)}:"]
    for t in st.get("targets", []):
        lines.append(f"- target: {t['chip']} package={t.get('package')} VDD={t.get('vdd')} V")
    clk = st.get("clock") or {}
    if clk:
        lines.append(f"- clock: cfg={_fmt(clk.get('cfg'))} derived={_fmt(clk.get('derived'))}" + (f" violations={_fmt(clk['violations'])}" if clk.get("violations") else ""))
    for pin, p in (st.get("pins") or {}).items():
        lines.append(f"- pin {pin}: {p.get('signal')} AF{p.get('af')} owner={p.get('owner')}" + (f" shared_with={p['shared_with']}" if p.get("shared_with") else ""))
    for r in st.get("requirements", []):
        lines.append(f"- requirement {_fmt({k: v for k, v in r.items() if v not in (None, '')})}")
    for d in st.get("devices", []):
        lines.append(f"- device {_fmt(d)}")
    for n in st.get("nets", []):
        lines.append(f"- net {n.get('from')} -> {n.get('to')} ({n.get('kind')})")
    for d in st.get("decisions", []):
        lines.append(f"- decision {d.get('id')}: {d.get('question')} -> {d.get('chosen')} (by {d.get('by')}; {d.get('rationale')})")
    if len(lines) == 1:
        lines.append("- empty (no target chip, pins or requirements recorded yet)")
    return "\n".join(lines)


def plan_summary(plan: list[dict]) -> str:
    return "\n".join(f"- {p['id']} [{p['status']}] {p['title']}" + (f" (acceptance: {p['acceptance']})" if p.get("acceptance") else "") for p in plan)


def start_summary(start: dict | None) -> str | None:
    """Trạng thái khởi đầu mà runtime đã trích từ lời người dùng (D36): agent mô phỏng đúng trạng thái này, Gate cũng dùng nó."""
    if not start:
        return None
    if start.get("initial"):
        s = f"Start state of the clock, read by the runtime from the user's description ({start.get('source')}): preset '{start['initial']}'"
        s += f", HSE = {start['hse_hz']} Hz" if start.get("hse_hz") else ""
        return s + ". Simulate with exactly this `initial`; the verification gate uses it too, whatever preset you pick."
    if start.get("source") == "user_text_unmapped":
        return ("The user described a clock start state that matches no simulator preset (" + str(start.get("evidence")) +
                "); the verification gate simulates from reset, so configure whatever your code needs or state the assumption.")
    if start.get("hse_hz"):
        return f"HSE frequency stated by the user: {start['hse_hz']} Hz."
    return None


def project_context(project_id: str, board: dict | None, plan: list[dict], start: dict | None = None) -> str | None:
    parts = []
    if board is not None:
        parts.append(board_summary(board))
    if start_summary(start):
        parts.append(start_summary(start))
    if plan:
        parts.append("Plan carried over from the previous turn:\n" + plan_summary(plan))
    if not parts:
        return None
    return (f"PROJECT CONTEXT (project {project_id}; authoritative state recorded by earlier turns; the tools read and change it):\n" + "\n".join(parts))
