"""Run API (P5 bước 5): lớp RunService dùng chung + các route HTTP /api/runs trong ui/server.py (server thật trên cổng loopback, ScriptedPolicy)."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from agent.runtime.hitl import ResumeError
from agent.runtime.run_api import RunService
from agent.scripted import ScriptedPolicy, say, tool
from runtime_helpers import build

ASK = tool("ask_human", kind="clarify", question="What is the HSE crystal frequency of your board?", why_needed="PLL depends on it")


def svc_for(tmp_path, steps, **kw):
    return RunService(build(tmp_path, steps, hitl=True, **kw))


def test_create_run_returns_the_interrupt_and_resume_returns_the_answer(tmp_path):
    svc = svc_for(tmp_path, [ASK, say("PLL for 8 MHz")])
    r = svc.create_run("Design the clock", project_id="proj-1")
    assert r["status"] == "interrupted" and r["interrupt"]["kind"] == "clarify" and r["project_id"] == "proj-1" and "answer" in r and r["answer"] == ""
    done = svc.resume(r["run_id"], r["interrupt"]["id"], "answer", {"answer": "8 MHz crystal on HSE"})
    assert done["status"] == "answered" and done["answer"] == "PLL for 8 MHz"
    with pytest.raises(ResumeError):
        svc.resume(r["run_id"], r["interrupt"]["id"], "answer", {"answer": "again"})
    with pytest.raises(KeyError):
        svc.resume("nope", "i_x", "answer", {})


def test_events_are_polled_by_seq_from_the_checkpoint(tmp_path):
    svc = svc_for(tmp_path, [ASK, say("done")])
    r = svc.create_run("goal")
    ev = svc.events(r["run_id"])
    assert ev["status"] == "interrupted" and ev["events"][-1]["type"] == "interrupt_raised" and ev["next"] == ev["events"][-1]["seq"]
    svc.resume(r["run_id"], r["interrupt"]["id"], "answer", {"answer": "x"})
    later = svc.events(r["run_id"], after=ev["next"])
    assert [e["type"] for e in later["events"]][0] == "resumed" and later["events"][-1]["type"] == "done" and later["status"] == "answered"
    assert svc.events(r["run_id"], after=later["next"])["events"] == []


def test_async_runs_return_at_once_and_can_be_polled(tmp_path):
    class Slow(ScriptedPolicy):
        def chat(self, messages, tools, seed=None):
            time.sleep(0.3)
            return super().chat(messages, tools, seed)

    rt = build(tmp_path, [], policy=Slow([say("done")]), hitl=True)
    svc = RunService(rt)
    r = svc.create_run("goal", wait=False)
    assert r["status"] == "running"
    for _ in range(100):
        if svc.get(r["run_id"])["status"] != "running":
            break
        time.sleep(0.05)
    got = svc.get(r["run_id"])
    assert got["status"] == "answered" and got["answer"] == "done"


def test_ablations_per_run_need_a_factory(tmp_path):
    svc = svc_for(tmp_path, [say("x")])
    with pytest.raises(ValueError, match="factory"):
        svc.create_run("goal", ablations=["A1"])
    calls_ = []

    def factory(codes):
        calls_.append(codes)
        return build(tmp_path, [say("ablated")], hitl=True, ablations=",".join(codes))

    svc = RunService(build(tmp_path, [say("x")], hitl=True), factory=factory)
    r = svc.create_run("goal", ablations=["A1"])
    assert calls_ == [("A1",)] and r["answer"] == "ablated"
    svc.create_run("goal2", ablations=["A1"])
    assert calls_ == [("A1",)]                                   # runtime theo ablation được tái dùng


@pytest.fixture
def server(tmp_path):
    from ui import server as srv
    old = srv.RUNS
    srv.RUNS = RunService(build(tmp_path, [ASK, say("final answer")], hitl=True))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    srv.RUNS = old


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_http_create_resume_events_and_errors(server):
    code, r = _post(server + "/api/runs", {"question": "Design the clock", "project_id": "p1"})
    assert code == 200 and r["status"] == "interrupted" and r["interrupt"]["kind"] == "clarify"
    rid, iid = r["run_id"], r["interrupt"]["id"]
    code, ev = _get(f"{server}/api/runs/{rid}/events?after=0")
    assert code == 200 and ev["events"][-1]["type"] == "interrupt_raised"
    assert _post(f"{server}/api/runs/{rid}/resume", {"interrupt_id": "i_wrong", "decision": "answer", "payload": {"answer": "x"}})[0] == 409
    assert _post(f"{server}/api/runs/{rid}/resume", {"interrupt_id": iid, "decision": "answer", "payload": {}})[0] == 409
    code, done = _post(f"{server}/api/runs/{rid}/resume", {"interrupt_id": iid, "decision": "answer", "payload": {"answer": "8 MHz crystal on HSE"}})
    assert code == 200 and done["status"] == "answered" and done["answer"] == "final answer"
    assert _post(f"{server}/api/runs/{rid}/resume", {"interrupt_id": iid, "decision": "answer", "payload": {"answer": "again"}})[0] == 409     # không chạy hai lần
    assert _get(f"{server}/api/runs/{rid}")[1]["status"] == "answered"
    assert _get(f"{server}/api/runs/zzz")[0] == 404 and _post(server + "/api/runs", {"question": ""})[0] == 400 and _post(f"{server}/api/runs/zzz/resume", {})[0] == 404


def test_http_server_sent_events_stream_ends_with_the_status(server):
    _, r = _post(server + "/api/runs", {"question": "goal"})
    req = urllib.request.Request(f"{server}/api/runs/{r['run_id']}/events", headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode()
    assert "event: run_started" in text and "event: interrupt_raised" in text and text.rstrip().endswith('data: {"status": "interrupted"}')
