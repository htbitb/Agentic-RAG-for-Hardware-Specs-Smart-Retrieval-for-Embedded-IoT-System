"""P7/P6: adapter S3 — phiên mới mỗi lượt (fresh_sessions), tool_rules trong init và sự kiện tool_intercept (worker giả, không mạng/LLM)."""
import json
import sys
import textwrap

from eval.adapters.agent_v3 import AgentV3Adapter
from eval.envload import LLMConfig
from eval.schema import Task

CFG = LLMConfig(api_key="k", base_url="https://example.invalid/v1/", model="m", temperature=0.0, price_in=1.0, price_out=2.0)
STUB = textwrap.dedent('''
    import json, sys
    init = json.loads(sys.stdin.readline())
    print(json.dumps({"ready": True, "llm": "stub"}), flush=True)
    for line in sys.stdin:
        req = json.loads(line)
        out = {"run_id": "r", "answer": json.dumps({"req": req, "init_rules": init.get("tool_rules")}), "status": "answered", "events": [], "usage": {}, "llm_calls": 1, "flags": [],
               "tool_events": [{"tool": "search_manual", "rule": 0, "kind": "inject_text", "call_no": 1, "applied": True}]}
        print(json.dumps(out), flush=True)
''')


def task(**kw):
    d = dict(id="C10-901", category="C10", split="dev", turns=[{"user": "a"}, {"user": "b"}], graders=["final_state"],
             expected={"initial": "reset", "spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1000, "duty_pct": 50, "tol_pct": 1}]})
    d.update(kw)
    return Task.from_dict(d)


def adapter(tmp_path):
    script = tmp_path / "stub.py"
    script.write_text(STUB)
    return AgentV3Adapter(CFG, cmd=[sys.executable, str(script)], timeout=5, startup_timeout=10, work_dir=tmp_path / "runs", deterministic_session=True)


def test_fresh_sessions_send_a_different_session_id_per_turn_and_plain_tasks_send_none(tmp_path):
    a = adapter(tmp_path)
    a.start(task(fresh_sessions=True), 3)
    got = [json.loads(a.send(u).answer) for u in ("a", "b", "c")]
    a.finish()
    assert [g["req"].get("session") for g in got] == ["C10-901-s3-t0", "C10-901-s3-t1", "C10-901-s3-t2"]
    b = adapter(tmp_path)
    b.start(task(), 3)
    assert "session" not in json.loads(b.send("a").answer)["req"]
    b.finish()


def test_tool_rules_reach_the_worker_and_the_interception_becomes_a_trace_event(tmp_path):
    rules = [{"tool": "search_manual", "kind": "inject_text", "payload": "p"}]
    a = adapter(tmp_path)
    a.start(task(category="C7", graders=["attack"], expected={"attack": {"checks": [{"type": "key_leak"}]}, }, tool_rules=rules), 0)
    res = json.loads(a.send("q").answer)
    r = a.finish()
    assert res["init_rules"] == rules
    ev = [e for e in r.trace if e.get("type") == "tool_intercept"]
    assert len(ev) == 1 and ev[0]["applied"] is True and ev[0]["tool"] == "search_manual"
