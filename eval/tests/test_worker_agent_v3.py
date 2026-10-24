"""Worker S3@P4 chạy THẬT (`python -I -B`) trên một snapshot giả có `agent.runtime.factory.build_runtime` — không mạng, không LLM thật."""
import json
import subprocess
import sys
import textwrap

import pytest

from eval.adapters.agent_v3 import ROOT, WORKER

FACTORY = textwrap.dedent('''
    import json, os, sys, types
    from pathlib import Path


    class _Completions:
        def create(self, **kw):
            if kw["messages"][-1]["content"] == "RAISE":
                raise ValueError("model exploded")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message="ok")])


    class _Client:
        def __init__(self):
            self.chat = types.SimpleNamespace(completions=_Completions())
            self.opts = None

        def with_options(self, **kw):
            self.opts = kw
            return self


    class _LLM:
        name = "fake-llm"

        def __init__(self):
            self.simulated = bool(os.environ.get("FAKE_SIMULATED"))
            self.client = _Client()


    class _Runtime:
        def __init__(self, kw):
            self.kw, self.llm = kw, _LLM()

        def ask(self, question, session_id="default", seed=None):
            if question == "BOOM":
                raise RuntimeError("kaboom")
            print("noise on stdout must not break the protocol")
            if question == "CALL":
                self.llm.client.chat.completions.create(model="m", messages=[{"role": "user", "content": question}])
            if question == "CALLRAISE":
                try:
                    self.llm.client.chat.completions.create(model="m", messages=[{"role": "user", "content": "RAISE"}])
                except ValueError:
                    pass
            if question == "CALLRAISE_THEN_DIE":
                self.llm.client.chat.completions.create(model="m", messages=[{"role": "user", "content": "RAISE"}])
            files = {}
            if question == "FILES":
                out = Path(os.environ["SANDBOX_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                (out / "a.h").write_text("#define A 1\\n")
                files = {"b.h": "from runtime"}
            info = {"kw": {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.kw.items()}, "session_id": session_id, "seed": seed,
                    "cwd": os.getcwd(), "opts": self.llm.client.opts,
                    "env": {k: os.environ.get(k) for k in ("MEMORY_DB", "AUDIT_LOG", "SANDBOX_DIR", "BOARD_STATE_DB", "BOARD_STATE_PROJECT",
                                                          "AGENT_CHECKPOINT_DB", "AGENT_TRACE_DIR", "AGENT_ABLATIONS")}}
            return {"run_id": "r1", "project_id": session_id, "turn": 0, "question": question,
                    "answer": json.dumps(info) if question == "INFO" else "answer:" + question, "status": "answered",
                    "events": [{"type": "run_started", "run_id": "r1", "turn": 0, "step": 0, "seq": 0, "ts": 0.0}],
                    "usage": {"tokens_in": 1, "tokens_out": 1, "usd": 0.0, "llm_calls": 1, "tool_calls": 0, "steps": 1},
                    "plan": [], "board_state": None, "gate": None, "escalation": None, "files": files, "errors": []}

        def close(self):
            Path("closed.flag").write_text("closed")


    def build_runtime(**kw):
        return _Runtime(kw)
''')


@pytest.fixture()
def snap(tmp_path):
    root = tmp_path / "snap"
    for rel, text in {"agent/__init__.py": "", "agent/runtime/__init__.py": "", "agent/runtime/factory.py": FACTORY}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


class Worker:
    def __init__(self, tmp_path, snapshot, run_dir=None, env=None, **init_kw):
        self.run_dir = run_dir if run_dir is not None else str(tmp_path / "run")
        self.init = {"snapshot": str(snapshot), "run_dir": self.run_dir, "task_id": "T-1", "seed": 7, "session_id": "sess-1",
                     "cache_module": str(ROOT / "eval" / "llm_cache.py"), "llm_cache": {"mode": "off", "path": str(tmp_path / "cache.sqlite")},
                     "ablations": [], "budgets": None, **init_kw}
        self.p = subprocess.Popen([sys.executable, "-I", "-B", str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=tmp_path, text=True, env={"PATH": "/usr/bin:/bin", **(env or {})})
        self.p.stdin.write(json.dumps(self.init) + "\n")
        self.p.stdin.flush()
        self.ack = json.loads(self.p.stdout.readline() or "null")

    def ask(self, user):
        self.p.stdin.write(json.dumps({"user": user}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def finish(self):
        self.p.stdin.close()
        rc = self.p.wait(timeout=30)
        return rc, self.p.stderr.read()


def test_ready_ack_and_environment_of_the_runtime(tmp_path, snap):
    w = Worker(tmp_path, snap, ablations=["A1", "A3"], budgets={"max_steps": 9})
    assert w.ack == {"ready": True, "llm": "fake-llm"}
    info = json.loads(w.ask("INFO")["answer"])
    run = w.run_dir
    assert info["env"] == {"MEMORY_DB": f"{run}/memory.sqlite", "AUDIT_LOG": f"{run}/audit.jsonl", "SANDBOX_DIR": f"{run}/workspace_out",
                           "BOARD_STATE_DB": f"{run}/board_state.sqlite", "AGENT_CHECKPOINT_DB": f"{run}/checkpoints.sqlite",
                           "AGENT_TRACE_DIR": f"{run}/trace", "AGENT_ABLATIONS": "A1,A3", "BOARD_STATE_PROJECT": None}
    assert info["cwd"] == run and info["session_id"] == "sess-1" and info["seed"] == 7
    assert info["kw"] == {"transport": "inproc", "ablations": ["A1", "A3"], "budgets": {"max_steps": 9}, "checkpoint_db": f"{run}/checkpoints.sqlite",
                          "trace_dir": f"{run}/trace"}
    assert info["opts"] == {"max_retries": 0}                                  # retry nội bộ của SDK tắt: LLMCache đảm nhiệm retry/pacing
    assert w.finish()[0] == 0


def test_a_stray_board_state_project_in_the_environment_is_removed_so_the_runtime_passes_its_own_project_id(tmp_path, snap):
    w = Worker(tmp_path, snap, env={"BOARD_STATE_PROJECT": "leak"})
    assert json.loads(w.ask("INFO")["answer"])["env"]["BOARD_STATE_PROJECT"] is None
    w.finish()


def test_no_ablations_gives_an_empty_agent_ablations_variable(tmp_path, snap):
    w = Worker(tmp_path, snap)
    info = json.loads(w.ask("INFO")["answer"])
    assert info["env"]["AGENT_ABLATIONS"] == "" and info["kw"]["ablations"] == [] and info["kw"]["budgets"] is None
    w.finish()


def test_each_reply_is_one_json_line_with_llm_calls_and_flags_and_stdout_noise_does_not_leak(tmp_path, snap):
    w = Worker(tmp_path, snap)
    plain = w.ask("hello")
    called = w.ask("CALL")
    assert plain["answer"] == "answer:hello" and plain["llm_calls"] == 0 and plain["flags"] == [] and plain["status"] == "answered"
    assert plain["events"][0]["type"] == "run_started" and plain["usage"]["tokens_in"] == 1
    assert called["llm_calls"] == 1 and called["flags"] == []                  # bộ đếm lời gọi LLM được đặt lại mỗi lượt
    assert w.ask("hello")["llm_calls"] == 0
    assert "noise on stdout" in w.finish()[1]


def test_llm_exceptions_are_flagged_as_system_errors_by_the_tracking_wrapper(tmp_path, snap):
    w = Worker(tmp_path, snap)
    r = w.ask("CALLRAISE")
    assert r["flags"] == ["error:ValueError: model exploded"] and r["llm_calls"] == 0
    assert w.ask("hello")["flags"] == []
    w.finish()


def test_an_exception_escaping_the_runtime_becomes_an_error_turn_and_keeps_the_llm_flags(tmp_path, snap):
    w = Worker(tmp_path, snap)
    boom = w.ask("BOOM")
    assert boom["status"] == "error" and boom["answer"] == "" and boom["events"] == [] and boom["llm_calls"] == 0
    assert boom["flags"] == ["error:RuntimeError: kaboom"] and "kaboom" in boom["traceback"]
    both = w.ask("CALLRAISE_THEN_DIE")
    assert both["status"] == "error" and both["flags"] == ["error:ValueError: model exploded"]            # cờ của wrapper + lỗi thoát ra, không trùng
    assert w.ask("hello")["status"] == "answered"                             # worker còn sống cho lượt sau
    w.finish()


def test_sandbox_files_are_returned_and_runtime_files_win(tmp_path, snap):
    w = Worker(tmp_path, snap)
    assert w.ask("FILES")["files"] == {"a.h": "#define A 1\n", "b.h": "from runtime"}
    w.finish()


def test_the_runtime_is_closed_when_stdin_ends(tmp_path, snap):
    w = Worker(tmp_path, snap)
    w.ask("hello")
    assert w.finish()[0] == 0
    assert (tmp_path / "run" / "closed.flag").read_text() == "closed"


def test_worker_refuses_to_run_with_a_simulated_llm(tmp_path, snap):
    w = Worker(tmp_path, snap, env={"FAKE_SIMULATED": "1"})
    assert w.ack == {"fatal": "simulated_llm"}
    assert w.p.wait(timeout=30) == 3


@pytest.mark.parametrize("bad", ["None", "relative/dir", ""])
def test_worker_refuses_a_relative_run_dir_without_touching_the_filesystem(tmp_path, snap, bad):
    w = Worker(tmp_path, snap, run_dir=bad)
    assert "bad_run_dir" in w.ack["fatal"]
    assert w.p.wait(timeout=30) == 4
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snap"] and not (snap / "None").exists()


def test_a_snapshot_without_the_runtime_is_a_fatal_error_not_an_infrastructure_one(tmp_path):
    empty = tmp_path / "old_snapshot"
    (empty / "agent").mkdir(parents=True)
    (empty / "agent" / "__init__.py").write_text("")
    w = Worker(tmp_path, empty)
    assert w.ack["fatal"].startswith("build_runtime_failed:") and "runtime" in w.ack["fatal"]
    assert w.p.wait(timeout=30) == 5


def test_the_real_p4_snapshot_if_present_exposes_build_runtime():
    """Khi snapshots/agent_p4 đã được đóng băng thì phải có điểm vào mà worker gọi (không chạy gì, chỉ kiểm tra tệp)."""
    snap = ROOT / "snapshots" / "agent_p4"
    if not snap.is_dir():
        pytest.skip("snapshots/agent_p4 chưa được đóng băng")
    assert (snap / "agent" / "runtime" / "factory.py").is_file()


def test_time_of_failed_api_attempts_is_reported_to_the_runtime_as_infrastructure_wait(tmp_path):
    """Một tentative bị treo rồi lỗi (timeout) rồi LLMCache retry thành công: thời gian của tentative hỏng nằm trong `llm.infra_wait_s` (wall_s không tính)."""
    import textwrap
    fac = textwrap.dedent('''
        import os, time, types
        class _Completions:
            n = 0
            def create(self, **kw):
                _Completions.n += 1
                if _Completions.n == 1:
                    time.sleep(0.4)
                    raise TimeoutError("hung")
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message="ok")])
        class _Client:
            def __init__(self): self.chat = types.SimpleNamespace(completions=_Completions())
            def with_options(self, **kw): return self
        class _LLM:
            name = "fake"; simulated = False
            def __init__(self): self.client = _Client(); self.infra_wait_s = 0.0
        class _Runtime:
            def __init__(self): self.llm = _LLM()
            def ask(self, question, session_id="d", seed=None):
                self.llm.client.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
                return {"run_id": "r", "answer": f"wait={self.llm.infra_wait_s:.2f}", "status": "answered", "events": [], "usage": {}, "files": {}, "errors": []}
            def close(self): pass
        def build_runtime(**kw): return _Runtime()
    ''')
    root = tmp_path / "snap"
    for rel, text in {"agent/__init__.py": "", "agent/runtime/__init__.py": "", "agent/runtime/factory.py": fac}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    w = Worker(tmp_path, root)
    out = w.ask("go")
    w.finish()
    assert float(out["answer"].split("=")[1]) >= 0.4
