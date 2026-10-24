"""Adapter S3@P5: interrupt -> resume qua worker giả (không mạng/LLM); usage cộng dồn của run chỉ cộng phần tăng thêm; project_id tất định (I3)."""
import json
import sys
import textwrap

import pytest

from eval.adapters.agent_v3 import AgentV3Adapter
from eval.envload import LLMConfig
from eval.schema import Task

CFG = LLMConfig(api_key="k", base_url="https://example.invalid/v1/", model="m", temperature=0.0, price_in=1.0, price_out=2.0)

STUB = textwrap.dedent('''
    import json, sys
    init = json.loads(sys.stdin.readline())
    print(json.dumps({"ready": True, "llm": "stub"}), flush=True)
    used = {"tokens_in": 0, "tokens_out": 0, "tool_calls": 0}
    pending = None
    for line in sys.stdin:
        req = json.loads(line)
        base = {"run_id": "run1", "project_id": init["session_id"], "turn": 0, "plan": [], "board_state": {"v": 1}, "gate": None, "escalation": None,
                "files": {}, "errors": [], "flags": []}
        if "user" in req:
            used.update(tokens_in=1000, tokens_out=100, tool_calls=2)
            pending = {"id": "i_1", "kind": "clarify", "tool": "ask_human", "tool_call_id": "c1", "question": "HSE?", "why_needed": "pll", "options": None, "payload": {}}
            print(json.dumps({**base, "status": "interrupted", "answer": "", "interrupt": pending, "usage": dict(used), "llm_calls": 2,
                              "events": [{"type": "run_started", "seq": 1}, {"type": "interrupt_raised", "seq": 2, "interrupt_id": "i_1"}]}), flush=True)
        else:
            r = req["resume"]
            if pending is None or r["interrupt_id"] != pending["id"]:
                print(json.dumps({"resume_error": "interrupt not pending", "answer": "", "status": "error", "events": [], "usage": {}, "llm_calls": 0, "flags": []}), flush=True)
                continue
            pending = None
            used.update(tokens_in=1800, tokens_out=160, tool_calls=3)
            print(json.dumps({**base, "status": "answered", "answer": "done:" + r["payload"]["answer"], "interrupt": None, "usage": dict(used), "llm_calls": 1,
                              "events": [{"type": "resumed", "seq": 3, "interrupt_id": "i_1"}, {"type": "done", "seq": 4}]}), flush=True)
''')


@pytest.fixture()
def adapter(tmp_path):
    script = tmp_path / "stub_worker.py"
    script.write_text(STUB)
    a = AgentV3Adapter(CFG, cmd=[sys.executable, str(script)], timeout=5, startup_timeout=5, work_dir=tmp_path / "runs", name="S3@P5")
    yield a
    a.close()


def task():
    return Task(id="C5-002", category="C5", split="dev", turns=[{"user": "design"}], graders=["final_state"],
                expected={"spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1, "tol_pct": 1}]})


def test_interrupt_then_resume_gives_one_turn_cumulative_usage_counted_once_and_a_flat_trace(adapter):
    adapter.start(task(), 1)
    t = adapter.send("design")
    assert t.status == "interrupted" and t.interrupt["kind"] == "clarify" and t.answer == "" and adapter.turns == []
    t2 = adapter.resume(t.interrupt["id"], "answer", {"answer": "8 MHz"})
    assert t2.status == "answered" and t2.answer == "done:8 MHz" and len(adapter.turns) == 1
    res = adapter.finish()
    assert res.system == "S3@P5" and res.final_answer == "done:8 MHz"
    assert [e["type"] for e in res.trace if e["type"] != "worker"] == ["run_started", "interrupt_raised", "resumed", "done"]
    assert res.usage["tokens_in"] == 1800 and res.usage["tokens_out"] == 160 and res.usage["tool_calls"] == 3 and res.usage["llm_calls"] == 3
    assert not res.errors


def test_a_rejected_resume_is_a_system_error_and_runs_nothing(adapter):
    adapter.start(task(), 1)
    t = adapter.send("design")
    bad = adapter.resume("i_wrong", "answer", {"answer": "x"})
    assert bad.status == "error"
    res = adapter.finish()
    assert any(e.startswith("error:resume_rejected") for e in res.errors)


def test_resume_without_a_pending_interrupt_is_an_error(adapter):
    adapter.start(task(), 1)
    assert adapter.resume("i_1", "answer", {"answer": "x"}).status == "error"
    assert "error:resume_without_interrupt" in adapter.finish().errors


def test_the_session_id_is_deterministic_for_s3p5_and_unique_for_s3p4(tmp_path):
    seen = []
    script = tmp_path / "w.py"
    script.write_text("import json,sys\ninit=json.loads(sys.stdin.readline())\nopen(%r,'a').write(init['session_id']+'\\n')\nprint(json.dumps({'ready':True,'llm':'s'}),flush=True)\n" % str(tmp_path / "ids.txt"))
    for name in ("S3@P5", "S3@P5", "S3@P4", "S3@P4"):
        a = AgentV3Adapter(CFG, cmd=[sys.executable, str(script)], timeout=5, startup_timeout=5, work_dir=tmp_path / "runs", name=name)
        a.start(task(), 2)
        a.close()
    ids = (tmp_path / "ids.txt").read_text().split()
    assert ids[0] == ids[1] == "C5-002-s2" and ids[2] != ids[3] and ids[2].startswith("C5-002-s2-")
