"""Chạy runtime v3 từ dòng lệnh với LLM thật (demo D1, chạy thử cờ ablation):

    cd agent && .venv/bin/python -m agent.runtime.cli --goal "..." [--goal "..." ...] [--session ID] [--ablate A1,A3] [--out DIR] [--budgets '{"steps": 30}']

Mỗi --goal là một lượt người dùng trên cùng project (Board State và kế hoạch được giữ). Ghi vào --out: trace.jsonl (mọi sự kiện), summary.md (bản dễ đọc),
answer_turn<N>.md. Dùng DB tạm trong --out để không đụng dữ liệu của agent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--goal", action="append", required=True)
    ap.add_argument("--session", default=None)
    ap.add_argument("--ablate", default="")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--budgets", default=None)
    ap.add_argument("--title", default="Run summary")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    out = a.out.resolve()
    for k, rel in (("MEMORY_DB", "memory.sqlite"), ("BOARD_STATE_DB", "board_state.sqlite"), ("AGENT_CHECKPOINT_DB", "checkpoints.sqlite"), ("AUDIT_LOG", "audit.jsonl"), ("SANDBOX_DIR", "workspace_out")):
        os.environ[k] = str(out / rel)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from agent.runtime.factory import build_runtime
    from agent.runtime.summary import render_summary

    rt = build_runtime(ablations=a.ablate, budgets=json.loads(a.budgets) if a.budgets else None, trace_dir=out / "trace")
    sid = a.session or "cli-" + uuid.uuid4().hex[:6]
    results = []
    try:
        for goal in a.goal:
            res = rt.ask(goal, session_id=sid)
            results.append(res)
            (out / f"answer_turn{res['turn']}.md").write_text(res["answer"], encoding="utf-8")
            print(f"[turn {res['turn']}] {res['status']} · {res['usage']['llm_calls']} LLM calls · {res['usage']['tool_calls']} tool calls · "
                  f"{res['usage']['tokens_in']}/{res['usage']['tokens_out']} tokens", file=sys.stderr)
    finally:
        rt.close()
    (out / "trace.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for r in results for e in r["events"]), encoding="utf-8")
    (out / "summary.md").write_text(render_summary(results, title=a.title), encoding="utf-8")
    print(f"wrote {out}/summary.md, trace.jsonl", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
