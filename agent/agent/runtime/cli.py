"""Chạy runtime v3 từ dòng lệnh với LLM thật (demo D1/D4, chạy thử cờ ablation, interrupt/resume):

    cd agent && .venv/bin/python -m agent.runtime.cli --goal "..." [--goal "..." ...] [--session ID] [--ablate A1,A3] [--out DIR] [--budgets '{"steps": 30}']
        [--answers '[{"decision":"answer","payload":{"answer":"8 MHz crystal"}}, ...]' | --interactive | --stop-on-interrupt]
    cd agent && .venv/bin/python -m agent.runtime.cli --out DIR --resume RUN_ID --interrupt ID --decision approve [--payload '{"feedback": "..."}']

Mỗi --goal là một lượt người dùng trên cùng project (Board State và kế hoạch được giữ). Khi agent tạm dừng (interrupt): --answers trả lời lần lượt theo danh sách,
--interactive hỏi trên terminal, --stop-on-interrupt dừng tiến trình (mã thoát 3, in interrupt) để resume ở một tiến trình KHÁC bằng --resume (cùng --out).
Ghi vào --out: trace.jsonl (mọi sự kiện), summary.md (bản dễ đọc), answer_turn<N>.md. Dùng DB tạm trong --out để không đụng dữ liệu của agent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path


def _ask_terminal(itr: dict) -> tuple[str, dict]:
    print(f"\n[agent asks · {itr['kind']}] {itr['question']}", file=sys.stderr)
    if itr.get("why_needed"):
        print(f"  why: {itr['why_needed']}", file=sys.stderr)
    if itr["kind"] == "clarify":
        return "answer", {"answer": input("> ").strip()}
    if itr["kind"] == "choice":
        for o in itr["options"]:
            print(f"  {o['id']}) {o['label']} — pros: {o['pros']} · cons: {o['cons']}", file=sys.stderr)
        return "choose", {"option": input("option> ").strip()}
    print((itr["payload"].get("diff") or "")[:2000], file=sys.stderr)
    if input("approve? [y/N] ").strip().lower().startswith("y"):
        return "approve", {}
    return "reject", {"feedback": input("feedback> ").strip()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--goal", action="append")
    ap.add_argument("--session", default=None)
    ap.add_argument("--ablate", default="")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--budgets", default=None)
    ap.add_argument("--title", default="Run summary")
    ap.add_argument("--answers", default=None, help="JSON list of {decision, payload}, consumed in order at each interrupt")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--stop-on-interrupt", action="store_true")
    ap.add_argument("--resume", default=None, help="run_id of a run waiting on an interrupt (new process)")
    ap.add_argument("--interrupt", default=None)
    ap.add_argument("--decision", default=None)
    ap.add_argument("--payload", default="{}")
    a = ap.parse_args(argv)
    if not a.resume and not a.goal:
        ap.error("--goal is required unless --resume is given")
    a.out.mkdir(parents=True, exist_ok=True)
    out = a.out.resolve()
    for k, rel in (("MEMORY_DB", "memory.sqlite"), ("BOARD_STATE_DB", "board_state.sqlite"), ("AGENT_CHECKPOINT_DB", "checkpoints.sqlite"), ("AUDIT_LOG", "audit.jsonl"), ("SANDBOX_DIR", "workspace_out")):
        os.environ[k] = str(out / rel)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from agent.runtime.factory import build_runtime
    from agent.runtime.summary import render_summary

    rt = build_runtime(ablations=a.ablate, budgets=json.loads(a.budgets) if a.budgets else None, trace_dir=out / "trace")
    sid = a.session or "cli-" + uuid.uuid4().hex[:6]
    answers = json.loads(a.answers) if a.answers else []
    results, rc = [], 0
    prev = out / "trace.jsonl"
    older = [json.loads(line) for line in prev.read_text(encoding="utf-8").splitlines()] if a.resume and prev.is_file() else []

    def settle(res: dict) -> dict:
        """Trả lời các interrupt của `res` (theo --answers / terminal) cho tới khi run xong hoặc phải dừng."""
        nonlocal rc
        events = list(res["events"])
        while res["status"] == "interrupted":
            itr = res["interrupt"]
            print(f"[interrupt {itr['id']}] {itr['kind']}: {itr['question']}", file=sys.stderr)
            if a.stop_on_interrupt:
                print(json.dumps({"run_id": res["run_id"], "interrupt": itr}, ensure_ascii=False))
                rc = 3
                break
            if answers:
                nxt = answers.pop(0)
                decision, payload = nxt["decision"], nxt.get("payload") or {}
            elif a.interactive:
                decision, payload = _ask_terminal(itr)
            else:
                print("no answer available for this interrupt (use --answers / --interactive / --stop-on-interrupt)", file=sys.stderr)
                rc = 4
                break
            res = rt.resume(res["run_id"], itr["id"], decision, payload)
            events += res["events"]
        return {**res, "events": events}

    try:
        if a.resume:
            res = settle(rt.resume(a.resume, a.interrupt, a.decision, json.loads(a.payload)))
            results.append(res)
        else:
            for goal in a.goal:
                res = settle(rt.ask(goal, session_id=sid))
                results.append(res)
                if rc:
                    break
        for res in results:
            if res["status"] != "interrupted":
                (out / f"answer_turn{res['turn']}.md").write_text(res["answer"], encoding="utf-8")
            print(f"[turn {res['turn']}] {res['status']} · {res['usage']['llm_calls']} LLM calls · {res['usage']['tool_calls']} tool calls · "
                  f"{res['usage']['tokens_in']}/{res['usage']['tokens_out']} tokens", file=sys.stderr)
    finally:
        rt.close()
    (out / "trace.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in [*older, *(e for r in results for e in r["events"])]), encoding="utf-8")
    (out / "summary.md").write_text(render_summary(results, title=a.title), encoding="utf-8")
    print(f"wrote {out}/summary.md, trace.jsonl", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
