"""Tóm tắt dễ đọc (Markdown) của một hay nhiều lượt chạy từ trace chuẩn hoá — dùng cho demo D1 trong báo cáo (plan/demos/D1/)."""
from __future__ import annotations

import json


def _line(e: dict) -> str | None:
    t = e["type"]
    if t == "plan_updated":
        d = e["diff"]
        bits = [f"+ {x}" for x in d["added"]] + [f"- {x}" for x in d["removed"]] + [f"~ {x}" for x in d["changed"]]
        return f"**plan updated**{' (after REPLAN_REQUIRED)' if e.get('after_replan') else ''}: " + "; ".join(bits) + (f" — _{e['rationale']}_" if e.get("rationale") else "")
    if t == "tool_call" and not e.get("internal"):
        return f"tool `{e['tool']}` ({e.get('permission')}) → {'ok' if e['ok'] else 'ERROR ' + str(e.get('error'))}"
    if t == "sim_result":
        eff = "; ".join(", ".join(f"{k}={v}" for k, v in x.items() if k in ("pin", "signal", "pwm_hz", "duty_pct", "baud", "scl_hz")) for x in e.get("effects", []))
        return (f"simulation `{e['artifact']}` ({e['source']}): " + ("PASS" if e["pass"] else "FAIL " + ", ".join(e["violations"])) + (f" — effects: {eff}" if eff else "")
                + (f" — unmodeled: {', '.join(e['unmodeled'])}" if e.get("unmodeled") else ""))
    if t == "gate_result":
        fs = ", ".join(f"{f['code']} ({f['gate']}, {f['kind']})" for f in e["findings"] if f["severity"] == "error")
        return f"gate `{e['artifact']}` via {e['trigger']}: " + " ".join(f"{g}={s}" for g, s in e["gates"].items()) + (f" — findings: {fs}" if fs else "")
    if t == "replan_required":
        return f"**REPLAN_REQUIRED** ({e['code']}): {e['reason']}"
    if t == "finish":
        return f"finish {'(implicit) ' if e['implicit'] else ''}→ {'ACCEPTED' if e['accepted'] else 'REJECTED'}" + (f", waived {e['waived']}" if e.get("waived") else "")
    if t == "escalated":
        return f"**ESCALATED** ({e['reason']}{', ' + e['code'] if e.get('code') else ''}); unmet: {e.get('unmet_requirements')}"
    if t == "guardrail" and e.get("blocked"):
        return f"guardrail ({e['stage']}) blocked: {e.get('flags') or e.get('verdict')}"
    if t == "resumed":
        if e.get("interrupt_id"):
            return f"**resumed** after the human resolved `{e['interrupt_id']}` ({e.get('kind')}): decision `{e.get('decision')}`, {e.get('payload')}"
        return f"resumed from checkpoint at seq {e['from_seq']}"
    if t == "interrupt_raised":
        opts = "; ".join(f"{o['id']}) {o['label']}" for o in e.get("options") or [])
        what = f"file {e['payload'].get('filename')}" if e["kind"] == "approval" else e["question"]
        return f"**INTERRUPT** `{e['interrupt_id']}` ({e['kind']}): {what}" + (f" — options: {opts}" if opts else "") + (f" — why: {e['why_needed']}" if e.get("why_needed") else "")
    if t == "human_decision":
        return f"decision recorded in the Board State: {e.get('label')} ({e.get('decision_id')})"
    if t == "file_written":
        return f"file `{e['filename']}` written ({e['approver']}, {e['bytes']} bytes)"
    if t == "escalation_invite":
        return f"escalation: the agent was invited to ask the human instead of giving up ({e.get('code')})"
    if t == "ask_limit_reached":
        return f"ask_human refused: question limit {e['limit']} reached"
    return None


def _self_correction(events: list[dict]) -> str:
    checks = [(e["type"], e.get("pass") if e["type"] == "sim_result" else e.get("passed"), e.get("artifact")) for e in events if e["type"] in ("sim_result", "gate_result")]
    if not checks:
        return "No simulation or gate check was run."
    n_bad = len({art or i for i, (_, ok, art) in enumerate(checks) if ok is False})          # Gate ghi cả sim_result lẫn gate_result cho cùng một artifact: đếm một lần
    if checks[-1][1] is not True:
        return "The last check did not pass (see the timeline)."
    if n_bad:
        return f"Self-correction: {n_bad} failing check(s) along the way (simulation failed or the gate rejected the answer), and the last check passed."
    return "No check failed before the final answer (honest record: the agent got it right the first time)."


def render_summary(results: list[dict], title: str = "Run summary") -> str:
    out = [f"# {title}", ""]
    for r in results:
        out += [f"## Turn {r.get('turn', 0)}: {r['question']}", ""]
        u = r.get("usage") or {}
        out.append(f"status **{r['status']}** · LLM calls {u.get('llm_calls')} · tool calls {u.get('tool_calls')} · tokens {u.get('tokens_in')}/{u.get('tokens_out')} · est. USD {u.get('usd')}")
        out += ["", _self_correction(r["events"]), "", "### Timeline", ""]
        n = 0
        for e in r["events"]:
            text = _line(e)
            if text:
                n += 1
                out.append(f"{n}. (step {e.get('step')}) {text}")
        out += ["", "### Final answer", "", r["answer"], ""]
    return "\n".join(out)
