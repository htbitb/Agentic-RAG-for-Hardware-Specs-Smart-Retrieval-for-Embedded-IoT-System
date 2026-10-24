"""Adapter S3@P4 (agent runtime v3): tiến trình worker riêng, trace phẳng, ánh xạ trạng thái, env bị lọc, ablation. Dùng worker giả (không mạng/LLM)."""
import json
import sys
import textwrap

import pytest

from eval.adapters.agent_v3 import ABLATION_VARIANTS, AgentV3Adapter
from eval.adapters.base import FatalAdapterError
from eval.envload import LLMConfig
from eval.schema import Task

CFG = LLMConfig(api_key="k", base_url="https://example.invalid/v1/", model="m", temperature=0.0, price_in=1.0, price_out=2.0)

STUB = textwrap.dedent('''
    import json, os, sys, time
    init = json.loads(sys.stdin.readline())
    if os.environ.get("STUB_FATAL"):
        print(json.dumps({"fatal": "simulated_llm"}), flush=True); sys.exit(3)
    print(json.dumps({"ready": True, "llm": "stub"}), flush=True)
    n = 0
    for line in sys.stdin:
        req = json.loads(line)
        q = req["user"]
        if q == "HANG": time.sleep(60)
        if q == "DIE": sys.exit(1)
        n += 1
        ev = lambda seq, type_, **kw: {"type": type_, "run_id": f"run{n}", "turn": n - 1, "step": seq, "seq": seq, "ts": 0.0, **kw}
        events = [ev(0, "run_started", goal=q, project_id=init["session_id"], ablations=init["ablations"], budgets=init["budgets"]),
                  ev(1, "tool_call", tool="get_register_bitfields", server="hw", permission="read", args={"chip": "stm32g474"}, ok=True, error=None,
                     summary="x", security_flags=[], internal=False),
                  ev(2, "finish", implicit=False, accepted=True, gate={"G1": "pass"}, waived=[], attempt=1),
                  ev(3, "done", status="answered", answer_chars=7)]
        out = {"run_id": f"run{n}", "project_id": init["session_id"], "turn": n - 1, "question": q, "answer": "agent:" + q, "status": "answered",
               "events": events, "usage": {"tokens_in": 3000, "tokens_out": 400, "usd": 0.5, "llm_calls": 9, "tool_calls": 2, "steps": 4},
               "plan": [], "board_state": {"after_turn": n - 1}, "gate": None, "escalation": None, "files": {}, "errors": [],
               "llm_calls": 3, "flags": []}
        if q in ("ESC", "REFUSE", "BLOCK", "ERR"):
            out["status"] = {"ESC": "escalated", "REFUSE": "refused", "BLOCK": "blocked", "ERR": "error"}[q]
        if q == "ESC": out["escalation"] = {"reason": "budget:steps", "code": "BUDGET", "unmet_requirements": [], "tried": []}
        if q == "NOBOARD": out["board_state"] = None
        if q == "INFRA": out["flags"] = ["infra:RateLimitError status=429: slow"]
        if q == "MISS": out["flags"] = ["infra:cache_miss"]
        if q == "SYSERR": out["flags"] = ["error:ValueError: boom"]
        if q == "FATAL": out["flags"] = ["fatal:AuthenticationError status=401: bad key"]
        if q == "ERRS": out["errors"] = ["infra:RateLimitError status=429: slow", "error:KeyError: x", "plain failure"]
        if q == "DUP": out["flags"] = ["infra:RateLimitError status=429: slow"]; out["errors"] = ["infra:RateLimitError status=429: slow"]
        if q == "INIT":
            keys = ("HW_SPECS_DB", "TEXT_INDEX_DB", "TEXT_INDEX_EMB", "TEXT_INDEX_OTHER", "BOARD_STATE_DB", "BOARD_STATE_PROJECT", "AGENT_ABLATIONS",
                    "AGENT_CHECKPOINT_DB", "AGENT_TRACE_DIR", "AGENT_FOO", "HWMODEL_DATA_DIR", "MEMORY_DB", "AUDIT_LOG", "SANDBOX_DIR", "LLM_MODEL", "KEEP_ME")
            out["answer"] = json.dumps({"init": init, "env": {k: os.environ.get(k) for k in keys}, "cwd": os.getcwd(), "argv": sys.argv})
        print(json.dumps(out), flush=True)
''')


@pytest.fixture()
def adapter(tmp_path):
    script = tmp_path / "stub_worker.py"
    script.write_text(STUB)
    a = AgentV3Adapter(CFG, cmd=[sys.executable, str(script)], timeout=2, startup_timeout=5, work_dir=tmp_path / "runs")
    yield a
    a.close()


def task(turns=("q",)):
    return Task(id="C4-007", category="C4", split="dev", turns=[{"user": u} for u in turns], graders=["final_state"],
                expected={"spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1, "tol_pct": 1}]})


def test_multi_turn_usage_trace_and_board_state(adapter):
    adapter.start(task(("a", "b")), seed=1)
    t1, t2 = adapter.send("hello"), adapter.send("again")
    r = adapter.finish()
    assert (t1.answer, t1.status, t2.answer) == ("agent:hello", "answered", "agent:again")
    assert r.system == "S3@P4" and r.variant == "" and r.task_id == "C4-007" and r.seed == 1 and r.final_answer == "agent:again"
    assert r.usage == {"tokens_in": 6000, "tokens_out": 800, "usd": 0.0076, "tool_calls": 4, "llm_calls": 6}      # llm_calls từ worker (3 mỗi lượt), usd tính theo giá của cfg
    assert r.board_state == {"after_turn": 1}                                                                      # board_state của lượt cuối
    assert r.errors == []


def test_trace_is_flat_events_as_is_plus_a_worker_event(adapter):
    adapter.start(task(("a", "b")), seed=1)
    adapter.send("a")
    adapter.send("b")
    trace = adapter.finish().trace
    assert trace[0] == {"type": "worker", "llm": "stub"}
    assert [e["type"] for e in trace[1:]] == ["run_started", "tool_call", "finish", "done"] * 2
    assert all(isinstance(e, dict) and "events" not in e for e in trace)
    started = [e for e in trace if e["type"] == "run_started"]
    assert [e["turn"] for e in started] == [0, 1] and started[0]["run_id"] == "run1" and started[0]["goal"] == "a"
    tool = next(e for e in trace if e["type"] == "tool_call")
    assert tool["args"] == {"chip": "stm32g474"} and tool["internal"] is False                                      # sự kiện nguyên vẹn, không chuẩn hoá lại
    from eval.graders import process
    assert process.is_v3(trace)


@pytest.mark.parametrize("raw,mapped", [("answered", "answered"), ("escalated", "answered"), ("refused", "refused"), ("blocked", "blocked"), ("error", "error")])
def test_status_mapping_escalated_is_an_answered_turn(adapter, raw, mapped):
    q = {"answered": "q", "escalated": "ESC", "refused": "REFUSE", "blocked": "BLOCK", "error": "ERR"}[raw]
    adapter.start(task(), seed=0)
    assert adapter.send(q).status == mapped
    assert adapter.finish().errors == []


def test_the_escalated_run_keeps_its_escalation_event_trace_and_its_answer(adapter):
    adapter.start(task(), seed=0)
    t = adapter.send("ESC")
    assert t.answer == "agent:ESC"
    assert any(e["type"] == "done" for e in adapter.finish().trace)


def test_board_state_is_the_last_turns_even_when_that_is_none(adapter):
    adapter.start(task(("a", "NOBOARD")), seed=0)
    adapter.send("a")
    adapter.send("NOBOARD")
    assert adapter.finish().board_state is None


def test_flags_are_mapped_to_infra_or_system_errors(adapter):
    for q, expect_infra, prefix in (("INFRA", True, "infra:"), ("MISS", True, "infra:cache_miss"), ("SYSERR", False, "error:")):
        adapter.start(task(), seed=0)
        adapter.send(q)
        r = adapter.finish()
        assert r.has_infra_error() is expect_infra and r.errors[0].startswith(prefix)


def test_runtime_errors_keep_their_prefix_and_unprefixed_ones_are_system_errors_without_duplicating_flags(adapter):
    adapter.start(task(), seed=0)
    adapter.send("ERRS")
    assert adapter.finish().errors == ["infra:RateLimitError status=429: slow", "error:KeyError: x", "error:plain failure"]
    adapter.start(task(), seed=0)
    adapter.send("DUP")
    assert adapter.finish().errors == ["infra:RateLimitError status=429: slow"]


def test_fatal_flag_aborts_the_whole_run(adapter):
    adapter.start(task(), seed=0)
    with pytest.raises(FatalAdapterError, match="401"):
        adapter.send("FATAL")


def test_timeout_and_crash_are_infra_errors(adapter):
    adapter.start(task(), seed=0)
    assert adapter.send("HANG").status == "error"
    assert adapter.finish().errors[0].startswith("infra:timeout")
    adapter.start(task(), seed=0)
    assert adapter.send("DIE").status == "error"
    assert adapter.finish().errors[0].startswith("infra:adapter_crash")
    adapter.start(task(("DIE", "next")), seed=0)
    adapter.send("DIE")
    assert adapter.send("next").status == "error"                              # worker đã chết: các lượt sau không gọi lại


def test_default_turn_timeout_is_ten_minutes_and_the_command_is_isolated_and_bytecode_free():
    a = AgentV3Adapter(CFG)
    assert a.timeout == 600 and a.cmd[1:3] == ["-I", "-B"] and a.cmd[3].endswith("agent_v3_worker.py") and a.name == "S3@P4"
    assert a.snapshot.as_posix().endswith("snapshots/agent_p4")


def test_simulated_llm_aborts_the_run(tmp_path):
    script = tmp_path / "stub_worker.py"
    script.write_text(STUB)
    a = AgentV3Adapter(CFG, cmd=[sys.executable, str(script)], timeout=3, startup_timeout=5, work_dir=tmp_path / "runs", env={"STUB_FATAL": "1"})
    with pytest.raises(FatalAdapterError, match="simulated"):
        a.start(task(), seed=0)


def init_of(a, **kw):
    a.start(task(), seed=3)
    out = json.loads(a.send("INIT").answer)
    a.finish()
    return out


def test_init_line_carries_snapshot_absolute_run_dir_ids_cache_ablations_and_budgets(tmp_path):
    a = AgentV3Adapter(CFG, cmd=[sys.executable, "-c", STUB], work_dir=tmp_path, cache_mode="record", cache_path=tmp_path / "c.sqlite")
    init = init_of(a)["init"]
    assert set(init) == {"snapshot", "run_dir", "task_id", "seed", "session_id", "cache_module", "llm_cache", "ablations", "budgets"}
    assert init["run_dir"].startswith("/") and init["task_id"] == "C4-007" and init["seed"] == 3 and init["session_id"].startswith("C4-007-s3-")
    assert init["llm_cache"] == {"mode": "record", "path": str(tmp_path / "c.sqlite")} and init["cache_module"].endswith("eval/llm_cache.py")
    assert init["snapshot"].endswith("snapshots/agent_p4") and init["ablations"] == [] and init["budgets"] is None


def test_ablations_and_budgets_are_passed_to_the_worker_and_label_the_result(tmp_path):
    a = AgentV3Adapter(CFG, cmd=[sys.executable, "-c", STUB], work_dir=tmp_path, ablations=["A1", "A3"], variant="-Planner", budgets={"max_steps": 5})
    a.start(task(), seed=0)
    init = json.loads(a.send("INIT").answer)["init"]
    res = a.finish()
    assert init["ablations"] == ["A1", "A3"] and init["budgets"] == {"max_steps": 5}
    assert res.variant == "-Planner" and res.system == "S3@P4"
    started = next(e for e in res.trace if e["type"] == "run_started")
    assert started["ablations"] == ["A1", "A3"]


def test_variant_is_derived_from_the_ablation_codes_when_not_given(tmp_path):
    assert ABLATION_VARIANTS == {"A1": "-Planner", "A2": "-BoardState", "A3": "-Sandbox", "A4": "-Reflection", "A6": "-HITL"}
    assert AgentV3Adapter(CFG, ablations=["A2"]).variant == "-BoardState"
    assert AgentV3Adapter(CFG, ablations=["A1", "A4"]).variant == "-Planner+-Reflection"
    assert AgentV3Adapter(CFG).variant == "" and AgentV3Adapter(CFG, variant="x").variant == "x"
    with pytest.raises(ValueError, match="A9"):
        AgentV3Adapter(CFG, ablations=["A9"])


def test_worker_does_not_inherit_variables_that_could_redirect_data_or_state(tmp_path, monkeypatch):
    for k in ("HW_SPECS_DB", "TEXT_INDEX_DB", "TEXT_INDEX_EMB", "TEXT_INDEX_OTHER", "BOARD_STATE_DB", "BOARD_STATE_PROJECT", "AGENT_ABLATIONS",
              "AGENT_CHECKPOINT_DB", "AGENT_TRACE_DIR", "AGENT_FOO", "HWMODEL_DATA_DIR", "MEMORY_DB", "AUDIT_LOG", "SANDBOX_DIR"):
        monkeypatch.setenv(k, "/tmp/elsewhere")
    monkeypatch.setenv("KEEP_ME", "yes")
    a = AgentV3Adapter(CFG, cmd=[sys.executable, "-c", STUB], work_dir=tmp_path)
    env = init_of(a)["env"]
    assert all(v is None for k, v in env.items() if k not in ("LLM_MODEL", "KEEP_ME")), env
    assert env["LLM_MODEL"] == "m" and env["KEEP_ME"] == "yes"                                                       # biến vô hại và cấu hình LLM vẫn có


def test_explicit_adapter_env_is_the_only_way_to_set_a_scrubbed_name(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_FOO", "from-shell")
    a = AgentV3Adapter(CFG, cmd=[sys.executable, "-c", STUB], work_dir=tmp_path, env={"AGENT_FOO": "explicit"})
    assert init_of(a)["env"]["AGENT_FOO"] == "explicit"


def test_replay_mode_without_a_key_sets_a_placeholder_so_the_runtime_does_not_fall_back_to_the_simulated_llm(tmp_path, monkeypatch):
    cfg = LLMConfig(api_key="", base_url="", model="m", temperature=0.0, price_in=0.0, price_out=0.0)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    stub = STUB.replace('"KEEP_ME")', '"KEEP_ME", "LLM_API_KEY")')
    a = AgentV3Adapter(cfg, cmd=[sys.executable, "-c", stub], work_dir=tmp_path, cache_mode="replay")
    assert init_of(a)["env"]["LLM_API_KEY"] == "replay-only-no-network"


def test_run_dir_is_absolute_even_after_close_and_is_removed_after_finish(tmp_path):
    a = AgentV3Adapter(CFG, cmd=["true"], work_dir=tmp_path)
    a.close()                                                                      # runner dừng khẩn cấp đặt run_dir = None
    try:
        a.start(task(), 0)
    except Exception:
        pass
    assert a.run_dir is not None and a.run_dir.is_absolute() and a.run_dir.parent == tmp_path.resolve()
    a.close()
    b = AgentV3Adapter(CFG, cmd=[sys.executable, "-c", STUB], work_dir=tmp_path)
    b.start(task(), 0)
    run_dir = b.run_dir
    assert run_dir.is_dir()
    b.finish()
    assert not run_dir.exists()


def test_keep_runs_leaves_the_run_directory_for_post_mortems(tmp_path):
    a = AgentV3Adapter(CFG, cmd=[sys.executable, "-c", STUB], work_dir=tmp_path, keep_runs=True)
    a.start(task(), 0)
    run_dir = a.run_dir
    a.send("q")
    a.finish()
    assert run_dir.is_dir() and (run_dir / "worker.log").exists()
