import json
import sys
import textwrap

import pytest

from eval.adapters.agent_v1 import AgentV1Adapter
from eval.envload import LLMConfig
from eval.schema import Task

CFG = LLMConfig(api_key="k", base_url="https://example.invalid/v1/", model="m", temperature=0.0, price_in=1.0, price_out=2.0)

STUB = textwrap.dedent('''
    import json, sys, time
    import os
    init = json.loads(sys.stdin.readline())
    if os.environ.get("STUB_FATAL"):
        print(json.dumps({"fatal": "simulated_llm"}), flush=True); sys.exit(3)
    print(json.dumps({"ready": True, "llm": "stub"}), flush=True)
    for line in sys.stdin:
        req = json.loads(line)
        q = req["user"]
        if q == "HANG": time.sleep(60)
        if q == "DIE": sys.exit(1)
        out = {"answer": "agent:" + q, "status": "answered", "verification": {"passed": True},
               "agent_trace": [{"type": "plan", "detail": "x"}],
               "observations": [{"tool": "write_config_file", "args": {"filename": "../x.h", "content": "c"},
                                 "result": {"status": "pending_approval", "action_id": "a1"}},
                                {"tool": "get_register_bitfields", "args": {"chip": "stm32g474"}, "result": {"registers": [1, 2, 3]}}],
               "pending_actions": [{"id": "a1", "filename": "../x.h"}],
               "metrics": {"tokens_in": 3000, "tokens_out": 400, "tool_calls": 2, "latency_s": 1.2, "simulated_llm": False},
               "llm_calls": 3, "flags": [], "files": {}}
        if q == "INFRA": out["flags"] = ["infra:RateLimitError status=429: slow"]
        if q == "MISS": out["flags"] = ["infra:cache_miss"]
        if q == "SYSERR": out["flags"] = ["error:ValueError: boom"]
        print(json.dumps(out), flush=True)
''')


@pytest.fixture()
def adapter(tmp_path):
    script = tmp_path / "stub_worker.py"
    script.write_text(STUB)
    a = AgentV1Adapter(CFG, cmd=[sys.executable, str(script)], timeout=3, startup_timeout=5, work_dir=tmp_path / "runs")
    yield a
    a.close()


def task(turns=("q",)):
    return Task(id="C7-012", category="C7", split="dev", turns=[{"user": u} for u in turns], graders=["attack"])


def test_turn_result_usage_and_normalised_trace(adapter):
    adapter.start(task(), seed=1)
    t = adapter.send("hello")
    r = adapter.finish()
    assert t.answer == "agent:hello" and t.status == "answered" and r.system == "S2"
    assert r.usage == {"tokens_in": 3000, "tokens_out": 400, "usd": 0.0038, "tool_calls": 2, "llm_calls": 3}
    kinds = [e["type"] for e in r.trace]
    assert "agent_trace" in kinds and kinds.count("tool_call") == 2
    write = next(e for e in r.trace if e["type"] == "tool_call" and e["tool"] == "write_config_file")
    assert write["args"]["filename"] == "../x.h" and write["result"]["status"] == "pending_approval"
    assert any(e["type"] == "pending_actions" for e in r.trace)


def test_large_tool_results_are_summarised_not_stored_whole(adapter):
    adapter.start(task(), seed=1)
    adapter.send("hello")
    read = next(e for e in adapter.finish().trace if e["type"] == "tool_call" and e["tool"] == "get_register_bitfields")
    assert "summary" in read["result"] and len(json.dumps(read["result"])) < 800


def test_flags_are_mapped_to_infra_or_system_errors(adapter):
    for q, expect_infra, prefix in (("INFRA", True, "infra:"), ("MISS", True, "infra:cache_miss"), ("SYSERR", False, "error:")):
        adapter.start(task(), seed=0)
        adapter.send(q)
        r = adapter.finish()
        assert r.has_infra_error() is expect_infra and r.errors[0].startswith(prefix)


def test_timeout_and_crash_are_infra(adapter):
    adapter.start(task(), seed=0)
    assert adapter.send("HANG").status == "error"
    assert adapter.finish().errors[0].startswith("infra:timeout")
    adapter.start(task(), seed=0)
    assert adapter.send("DIE").status == "error"
    assert adapter.finish().errors[0].startswith("infra:adapter_crash")


def test_simulated_llm_aborts_the_run(tmp_path):
    script = tmp_path / "stub_worker.py"
    script.write_text(STUB)
    a = AgentV1Adapter(CFG, cmd=[sys.executable, str(script)], timeout=3, startup_timeout=5, work_dir=tmp_path / "runs",
                       env={"STUB_FATAL": "1"})
    with pytest.raises(RuntimeError, match="simulated"):
        a.start(task(), seed=0)


@pytest.mark.integration
def test_real_worker_in_replay_mode_with_empty_cache_makes_no_api_call(tmp_path):
    from eval.envload import LLMConfig as C

    cfg = C.load()
    if not cfg.api_key:
        pytest.skip("không có LLM_API_KEY")
    a = AgentV1Adapter(cfg, cache_mode="replay", cache_path=tmp_path / "empty.sqlite", timeout=120, startup_timeout=120,
                       work_dir=tmp_path / "runs")
    try:
        a.start(Task(id="C1-999", category="C1", split="dev", turns=[{"user": "What is the reset value of TIM1_CR1?"}],
                     graders=["exact"]), seed=0)
        a.send("What is the reset value of TIM1_CR1?")
        r = a.finish()
    finally:
        a.close()
    assert r.errors and r.errors[0] == "infra:cache_miss" and r.usage["tokens_in"] == 0
    assert "Insufficient evidence" in r.final_answer          # agent v1 abstain khi LLM không khả dụng


def test_fatal_flag_from_the_worker_aborts_the_run(tmp_path):
    from eval.adapters.base import FatalAdapterError

    script = tmp_path / "stub_worker.py"
    script.write_text(STUB.replace('if q == "SYSERR":', 'if q == "FATAL": out["flags"] = ["fatal:AuthenticationError status=401: bad key"]\n    if q == "SYSERR":'))
    a = AgentV1Adapter(CFG, cmd=[sys.executable, str(script)], timeout=3, startup_timeout=5, work_dir=tmp_path / "runs")
    try:
        a.start(task(), seed=0)
        with pytest.raises(FatalAdapterError, match="401"):
            a.send("FATAL")
    finally:
        a.close()


def test_adapter_can_be_named_s2d_and_reports_that_name_in_the_run_result(tmp_path):
    a = AgentV1Adapter(CFG, cmd=[sys.executable, "-c", STUB], name="S2D", work_dir=tmp_path)
    assert a.name == "S2D"
    t = Task(id="C1-001", category="C1", split="dev", turns=[{"user": "q"}], graders=["exact"])
    a.start(t, 0)
    a.send("hello")
    res = a.finish()
    assert res.system == "S2D" and res.final_answer == "agent:hello"
    assert AgentV1Adapter(CFG).name == "S2"                              # mặc định không đổi


ENV_STUB = textwrap.dedent('''
    import json, os, sys
    init = json.loads(sys.stdin.readline())
    print(json.dumps({"ready": True, "llm": "stub"}), flush=True)
    for line in sys.stdin:
        seen = {k: os.environ.get(k) for k in ("HW_SPECS_DB", "TEXT_INDEX_DB", "TEXT_INDEX_EMB", "MEMORY_DB")}
        print(json.dumps({"answer": json.dumps(seen), "status": "answered", "verification": None, "agent_trace": [],
                          "observations": [], "pending_actions": [], "metrics": {}, "llm_calls": 0, "flags": [], "files": {}}), flush=True)
''')


def test_worker_does_not_inherit_variables_that_would_redirect_the_agent_data(tmp_path, monkeypatch):
    """S2D: dữ liệu là biến độc lập; một HW_SPECS_DB lạc trong shell không được âm thầm trỏ worker vào agent/data."""
    for k in ("HW_SPECS_DB", "TEXT_INDEX_DB", "TEXT_INDEX_EMB"):
        monkeypatch.setenv(k, "/tmp/elsewhere")
    a = AgentV1Adapter(CFG, cmd=[sys.executable, "-c", ENV_STUB], name="S2D", work_dir=tmp_path)
    a.start(Task(id="C1-001", category="C1", split="dev", turns=[{"user": "q"}], graders=["exact"]), 0)
    seen = json.loads(a.send("q").answer)
    a.finish()
    assert seen["HW_SPECS_DB"] is None and seen["TEXT_INDEX_DB"] is None and seen["TEXT_INDEX_EMB"] is None


def test_worker_refuses_a_relative_run_dir_instead_of_writing_into_the_snapshot(tmp_path):
    """Hồi quy P3: runner dừng khẩn cấp (quota) từng đóng adapter giữa lúc luồng khác đang start() => worker nhận run_dir 'None' (tương đối) và
    snapshots/agent_p1/None/{memory.sqlite,audit.jsonl} bị tạo ra, làm lệch checksum dữ liệu của snapshot. Worker nay từ chối đường dẫn tương đối."""
    import json
    import subprocess
    import sys

    from eval.adapters.agent_v1 import SNAPSHOT, WORKER

    snap = SNAPSHOT
    before = sorted(p.name for p in snap.iterdir())
    for bad in ("None", "relative/dir", ""):
        r = subprocess.run([sys.executable, "-I", str(WORKER)], input=json.dumps({"snapshot": str(snap), "run_dir": bad, "task_id": "T", "seed": 0}) + "\n",
                           capture_output=True, text=True, cwd=tmp_path, timeout=60)
        first = json.loads(r.stderr.splitlines()[0]) if r.stderr.strip().startswith("{") else {}
        assert r.returncode == 4 and "bad_run_dir" in (first.get("fatal") or r.stderr + r.stdout), (bad, r.returncode, r.stderr[:200])
    assert sorted(p.name for p in snap.iterdir()) == before and not (tmp_path / "None").exists()


def test_adapter_start_uses_an_absolute_run_dir_even_after_close(tmp_path):
    from eval.adapters.agent_v1 import AgentV1Adapter
    from eval.envload import LLMConfig
    from eval.schema import Task

    a = AgentV1Adapter(LLMConfig(api_key="k", base_url="", model="m", temperature=0.0, price_in=0.0, price_out=0.0), cmd=["true"], work_dir=tmp_path)
    t = Task(id="T-1", category="C1", split="dev", turns=[{"user": "q"}], graders=["exact"])
    a.close()                                                                     # đặt run_dir = None như khi runner dừng khẩn cấp
    try:
        a.start(t, 0)
    except Exception:
        pass                                                                      # worker giả (`true`) không trả lời; chỉ quan tâm run_dir
    assert a.run_dir is not None and a.run_dir.is_absolute() and a.run_dir.parent == tmp_path.resolve()
    a.close()
