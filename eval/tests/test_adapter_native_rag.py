import sys
import textwrap

import pytest

from eval.adapters.native_rag import NativeRAGAdapter
from eval.envload import LLMConfig
from eval.schema import Task

CFG = LLMConfig(api_key="k", base_url="https://example.invalid/v1/", model="m", temperature=0.0, price_in=1.0, price_out=2.0)

STUB = textwrap.dedent('''
    import json, os, sys, time
    marker = os.environ["STUB_MARKER"]
    for line in sys.stdin:
        req = json.loads(line)
        q = req["question"]
        if q == "CRASH" and not os.path.exists(marker):
            open(marker, "w").write("x"); sys.exit(1)
        if q == "ALWAYS_CRASH":
            sys.exit(1)
        if q == "HANG":
            time.sleep(60)
        resp = {"id": req["id"], "answer": "echo:" + q + "|hist=" + str(len(req["history"])) + "|seed=" + str(req["seed"]),
                "sources": [{"doc_id": "D", "file": "d.pdf", "page": 3}], "usage": {"in": 1000, "out": 200},
                "latency_s": 0.01, "error": None}
        if q == "CACHE": resp.update(answer="", sources=[], usage={"in": 0, "out": 0}, error="cache_miss")
        if q == "INFRA": resp.update(answer="", sources=[], usage={"in": 0, "out": 0}, error="infra:RateLimitError: slow")
        print(json.dumps(resp), flush=True)
''')


@pytest.fixture()
def adapter(tmp_path, monkeypatch):
    script = tmp_path / "stub.py"
    script.write_text(STUB)
    a = NativeRAGAdapter(CFG, cmd=[sys.executable, str(script)], env={"STUB_MARKER": str(tmp_path / "marker")}, timeout=3,
                         startup_timeout=3, log_dir=tmp_path)
    yield a
    a.close()


def task(turns=("q1",)):
    return Task(id="C1-001", category="C1", split="dev", turns=[{"user": u} for u in turns], graders=["exact"])


def test_roundtrip_usage_sources_and_trace(adapter):
    adapter.start(task(), seed=2)
    t = adapter.send("What is X?")
    r = adapter.finish()
    assert t.answer == "echo:What is X?|hist=0|seed=2" and r.system == "S1"
    assert r.usage == {"tokens_in": 1000, "tokens_out": 200, "usd": 0.0014, "tool_calls": 0, "llm_calls": 1}
    assert r.sources() == [{"doc_id": "D", "file": "d.pdf", "page": 3}] and r.errors == []


def test_multi_turn_sends_history_and_process_is_reused(adapter):
    adapter.start(task(("a", "b")), seed=0)
    adapter.send("a")
    pid = adapter._proc.pid
    t2 = adapter.send("b")
    assert "hist=1" in t2.answer and adapter._proc.pid == pid
    adapter.start(task(), seed=1)                    # task kế tiếp dùng lại tiến trình
    adapter.send("c")
    assert adapter._proc.pid == pid


def test_cache_miss_and_infra_errors_are_labelled_infra(adapter):
    adapter.start(task(), seed=0)
    adapter.send("CACHE")
    assert adapter.finish().errors == ["infra:cache_miss"]
    adapter.start(task(), seed=0)
    adapter.send("INFRA")
    r = adapter.finish()
    assert r.errors == ["infra:RateLimitError: slow"] and r.has_infra_error()


def test_crash_restarts_process_and_retries_once(adapter):
    adapter.start(task(), seed=0)
    t = adapter.send("CRASH")
    assert t.status == "answered" and t.answer.startswith("echo:CRASH")
    assert adapter.finish().errors == []


def test_persistent_crash_is_reported_as_infra(adapter):
    adapter.start(task(), seed=0)
    t = adapter.send("ALWAYS_CRASH")
    r = adapter.finish()
    assert t.status == "error" and r.errors and r.errors[0].startswith("infra:adapter_crash")


def test_timeout_kills_process_and_next_task_still_works(adapter):
    adapter.start(task(), seed=0)
    t = adapter.send("HANG")
    r = adapter.finish()
    assert t.status == "error" and r.errors[0].startswith("infra:timeout")
    adapter.start(task(), seed=0)
    assert adapter.send("ok").answer.startswith("echo:ok")


def test_fatal_error_from_the_rag_process_aborts_the_run(tmp_path):
    from eval.adapters.base import FatalAdapterError

    script = tmp_path / "stub_fatal.py"
    script.write_text("import json,sys\nfor l in sys.stdin:\n    r=json.loads(l)\n    print(json.dumps({'id': r['id'], 'answer': '', 'sources': [], 'usage': {'in':0,'out':0}, 'latency_s': 0, 'error': 'fatal:AuthenticationError status=401'}), flush=True)\n")
    a = NativeRAGAdapter(CFG, cmd=[sys.executable, str(script)], env={}, timeout=3, startup_timeout=3, log_dir=tmp_path)
    try:
        a.start(task(), seed=0)
        with pytest.raises(FatalAdapterError, match="401"):
            a.send("q")
    finally:
        a.close()
