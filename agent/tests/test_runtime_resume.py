"""Checkpoint + resume (D32): kill rồi resume cho kết quả tương đương chạy liền; tool ghi đang chạy lúc chết không bị chạy lại."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from agent.runtime.checkpoint import CheckpointStore
from agent.scripted import ScriptedPolicy, SimulatedKill, say, tool
from runtime_fakes import FakeGate
from runtime_helpers import build, sid, strip, types

PLAN = [{"id": "s1", "title": "record target", "status": "doing"}]
STEPS = [tool("list_chips"), tool("set_target", chip="stm32g474", package="LQFP64", vdd=3.3), tool("update_plan", steps=PLAN, rationale="r"), say("final answer")]
PROBE = Path(__file__).with_name("resume_probe.py")


def comparable(out):
    """tokens bị loại: ScriptedPolicy ước theo độ dài hội thoại (project_id khác nhau giữa hai lần chạy)."""
    return [{k: v for k, v in e.items() if k not in ("seq", "project_id", "tokens_in", "tokens_out")} for e in strip(out["events"]) if e["type"] != "resumed"]


@pytest.mark.parametrize("kill_at", [0, 1, 2, 3])
def test_resume_after_an_in_process_kill_equals_the_uninterrupted_run(tmp_path, kill_at):
    s = sid()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    clean = build(tmp_path / "a", STEPS).ask("goal", session_id=s + "-clean")
    rt1 = build(tmp_path / "b", [], policy=ScriptedPolicy(STEPS, kill_at=kill_at))
    with pytest.raises(SimulatedKill):
        rt1.ask("goal", session_id=s)
    run_id = rt1.current_run_id
    assert rt1.store.unfinished_runs() == [run_id]
    rt2 = build(tmp_path / "b", STEPS, db=tmp_path / "b" / "ck.sqlite")           # tiến trình mới: hub, policy, store đều mới
    out = rt2.resume(run_id)
    assert out["answer"] == clean["answer"] == "final answer" and out["status"] == clean["status"] == "answered"
    assert out["plan"] == clean["plan"] and out["usage"]["tool_calls"] == clean["usage"]["tool_calls"] and out["usage"]["llm_calls"] == clean["usage"]["llm_calls"]
    assert out["board_state"]["targets"] == clean["board_state"]["targets"] and out["board_state"]["version"] == clean["board_state"]["version"] == 1
    assert comparable(out) == comparable(clean)
    assert "resumed" in types(out) and rt2.store.unfinished_runs() == []


def test_resume_of_a_finished_run_returns_the_stored_result_without_running_anything(tmp_path):
    rt = build(tmp_path, [say("done")])
    out = rt.ask("goal", session_id=sid())
    policy = ScriptedPolicy([])
    rt2 = build(tmp_path, [], policy=policy, db=tmp_path / "ck.sqlite")
    again = rt2.resume(out["run_id"])
    assert again["answer"] == "done" and policy.offered == [] and types(again) == types(out)


def test_resume_of_an_unknown_run_is_an_error(tmp_path):
    with pytest.raises(KeyError):
        build(tmp_path, []).resume("nope")


def test_a_mutating_tool_that_was_running_when_the_process_died_is_not_run_again(tmp_path):
    s = sid()
    steps = [tool("set_target", chip="stm32g474", package="LQFP64", vdd=3.3), say("recovered")]
    rt1 = build(tmp_path, steps)
    real = rt1.hub._fn["set_target"]

    def write_then_die(**kw):
        real(**kw)
        raise SimulatedKill("process died right after the write")

    rt1.hub._fn["set_target"] = write_then_die
    with pytest.raises(SimulatedKill):
        rt1.ask("goal", session_id=s)
    st = rt1.store.load(rt1.current_run_id)
    assert st.in_flight["tool"] == "set_target" and len(st.pending_calls) == 1
    seen = {}

    def after(messages, tools):
        seen["tool"] = [m["content"] for m in messages if m["role"] == "tool"]
        return say("recovered")

    rt2 = build(tmp_path, [tool("set_target", chip="stm32g474", package="LQFP64", vdd=3.3), after], db=tmp_path / "ck.sqlite")
    out = rt2.resume(rt1.current_run_id)
    assert out["answer"] == "recovered"
    assert "interrupted" in seen["tool"][0] and "NOT run again" in seen["tool"][0]
    assert out["board_state"]["version"] == 1 and len(out["board_state"]["targets"]) == 1        # đúng MỘT sự kiện set_target


def test_a_read_only_tool_that_was_pending_is_simply_executed_on_resume(tmp_path):
    s = sid()
    rt1 = build(tmp_path, [tool("list_chips"), say("ok")])
    real = rt1.hub._fn["list_chips"]

    def die(**kw):
        raise SimulatedKill("died before the tool returned")

    rt1.hub._fn["list_chips"] = die
    with pytest.raises(SimulatedKill):
        rt1.ask("goal", session_id=s)
    rt2 = build(tmp_path, [tool("list_chips"), say("ok")], db=tmp_path / "ck.sqlite")
    out = rt2.resume(rt1.current_run_id)
    assert out["answer"] == "ok" and out["usage"]["tool_calls"] == 1


def test_the_checkpoint_database_is_plain_sqlite_readable_after_the_crash(tmp_path):
    rt1 = build(tmp_path, [], policy=ScriptedPolicy(STEPS, kill_at=2))
    with pytest.raises(SimulatedKill):
        rt1.ask("goal", session_id=sid())
    row = sqlite3.connect(tmp_path / "ck.sqlite").execute("select status, state from runs").fetchone()
    st = json.loads(row[1])
    assert row[0] in ("ACT", "PLAN") and st["used"]["llm_calls"] == 2 and len([m for m in st["messages"] if m["role"] == "tool"]) == 2


def _probe(dir_, mode, kill_at=None):
    args = [sys.executable, "-I", str(PROBE), str(dir_), mode] + ([str(kill_at)] if kill_at is not None else [])
    return subprocess.run(args, capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize("kill_at", [1, 3])
def test_resume_after_a_real_process_kill_equals_the_uninterrupted_run(tmp_path, kill_at):
    """Tiến trình thật bị os._exit(137) giữa chừng; một tiến trình khác resume từ SQLite; kết quả phải bằng chạy liền."""
    clean_dir, crash_dir = tmp_path / "clean", tmp_path / "crash"
    clean_dir.mkdir(); crash_dir.mkdir()
    c = _probe(clean_dir, "clean")
    assert c.returncode == 0, c.stderr[-800:]
    k = _probe(crash_dir, "crash", kill_at)
    assert k.returncode == 137, (k.returncode, k.stderr[-800:])
    r = _probe(crash_dir, "resume")
    assert r.returncode == 0, r.stderr[-800:]
    clean, resumed = json.loads(c.stdout.splitlines()[-1]), json.loads(r.stdout.splitlines()[-1])
    assert resumed == clean and resumed["answer"] == "final answer" and resumed["board_version"] == 1
