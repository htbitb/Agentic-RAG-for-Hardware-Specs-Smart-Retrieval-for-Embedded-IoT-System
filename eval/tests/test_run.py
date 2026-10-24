import json
import threading
from pathlib import Path

import pytest

from eval import run as R
from eval.adapters.base import FatalAdapterError
from eval.envload import LLMConfig
from eval.schema import RunResult, Task, TurnResult

CFG = LLMConfig(api_key="SECRET-should-never-appear", base_url="https://example.invalid/v1/", model="m", temperature=0.0,
                price_in=0.075, price_out=0.30)


def mk(i, cat="C1", split="dev", turns=("q",)):
    return Task(id=f"{cat}-{i:03d}", category=cat, split=split, turns=[{"user": u} for u in turns], graders=["exact"])


class FakeAdapter:
    name = "S0"
    variant = ""
    boom_on = set()

    def __init__(self):
        self.t = self.seed = None
        self.turns = []

    def start(self, task, seed):
        self.t, self.seed, self.turns = task, seed, []
        if task.id in self.boom_on:
            raise ValueError("adapter exploded")

    def send(self, msg):
        tr = TurnResult(answer=f"ans:{msg}")
        self.turns.append(tr)
        return tr

    def finish(self):
        return RunResult(system=self.name, variant="", task_id=self.t.id, seed=self.seed, turns=self.turns,
                         final_answer=self.turns[-1].answer, usage={"tokens_in": 10, "tokens_out": 2, "usd": 0.0, "tool_calls": 0, "llm_calls": 1})

    def close(self):
        pass


def test_schedule_is_system_task_seed_product_in_stable_order():
    tasks = [mk(2), mk(1)]
    sched = R.build_schedule(["S0", "S1"], tasks, seeds=2)
    assert len(sched) == 2 * 2 * 2
    assert sched[0] == ("S0", "", "C1-001", 0)                       # system-major, rồi task (theo id), rồi seed
    assert [s[2] for s in sched[:4]] == ["C1-001", "C1-001", "C1-002", "C1-002"]
    assert [s[0] for s in sched] == ["S0"] * 4 + ["S1"] * 4
    assert R.build_schedule(["S0", "S1"], tasks, 2) == sched


def test_resume_skips_completed_keys(tmp_path):
    runs = tmp_path / "runs.jsonl"
    done = RunResult(system="S0", variant="", task_id="C1-001", seed=0)
    runs.write_text(json.dumps(done.to_dict()) + "\n")
    sched = R.build_schedule(["S0"], [mk(1), mk(2)], seeds=1)
    todo = R.pending(sched, R.load_done(runs))
    assert [t[2] for t in todo] == ["C1-002"]


def test_load_done_ignores_a_truncated_last_line(tmp_path):
    runs = tmp_path / "runs.jsonl"
    good = json.dumps(RunResult(system="S0", variant="", task_id="C1-001", seed=0).to_dict())
    runs.write_text(good + "\n" + good[:20])
    assert R.load_done(runs) == {("S0", "", "C1-001", 0)}


def test_runner_executes_in_parallel_and_writes_one_valid_line_per_run(tmp_path):
    tasks = [mk(i) for i in range(1, 21)]
    sched = R.build_schedule(["S0"], tasks, seeds=3)
    runner = R.Runner(tmp_path, {"S0": FakeAdapter}, workers=4, rps=0)
    n = runner.run(sched, {t.id: t for t in tasks})
    lines = (tmp_path / "runs.jsonl").read_text().splitlines()
    assert n == 60 and len(lines) == 60
    keys = {tuple(RunResult.from_dict(json.loads(l)).key()) for l in lines}
    assert len(keys) == 60


def test_unexpected_adapter_exception_becomes_a_system_error_not_a_crash(tmp_path):
    FakeAdapter.boom_on = {"C1-002"}
    try:
        tasks = [mk(1), mk(2)]
        runner = R.Runner(tmp_path, {"S0": FakeAdapter}, workers=2, rps=0)
        runner.run(R.build_schedule(["S0"], tasks, 1), {t.id: t for t in tasks})
        rows = {r["task_id"]: r for r in map(json.loads, (tmp_path / "runs.jsonl").read_text().splitlines())}
        assert rows["C1-001"]["errors"] == [] and rows["C1-002"]["errors"][0].startswith("error:ValueError")
    finally:
        FakeAdapter.boom_on = set()


def test_fatal_runtime_error_aborts_the_whole_run(tmp_path):
    class Fatal(FakeAdapter):
        def start(self, task, seed):
            raise FatalAdapterError("S2 worker refused to run: simulated_llm")

    runner = R.Runner(tmp_path, {"S0": Fatal}, workers=2, rps=0)
    with pytest.raises(RuntimeError, match="simulated_llm"):
        runner.run(R.build_schedule(["S0"], [mk(1)], 1), {"C1-001": mk(1)})


def test_multi_turn_tasks_send_every_turn(tmp_path):
    t = mk(1, turns=("a", "b", "c"))
    R.Runner(tmp_path, {"S0": FakeAdapter}, workers=1, rps=0).run(R.build_schedule(["S0"], [t], 1), {t.id: t})
    row = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])
    assert [x["answer"] for x in row["turns"]] == ["ans:a", "ans:b", "ans:c"]


def test_limit_interleaves_categories():
    tasks = [mk(i, "C1") for i in range(1, 6)] + [mk(i, "C2") for i in range(1, 6)] + [mk(1, "C6")]
    picked = R.select_limit(tasks, 4)
    assert sorted(t.category for t in picked) == ["C1", "C1", "C2", "C6"]       # xoay vòng qua các nhóm


def test_cost_estimate_and_confirmation_threshold():
    est = R.estimate_cost(["S0", "S1", "S2"], n_tasks=27, seeds=3, cfg=CFG)
    assert est["runs"] == 243 and est["llm_calls"] > 243 and est["usd"] > 0
    assert R.needs_confirmation({"usd": 2.5}, threshold=2.0) and not R.needs_confirmation({"usd": 1.0}, threshold=2.0)


def test_cost_estimate_scales_with_the_number_of_user_turns():
    """C4 có 3–6 lượt: số lời gọi LLM tỉ lệ với tổng số LƯỢT (không phải số run); số run không đổi."""
    one = R.estimate_cost(["S0", "S2"], n_tasks=5, seeds=3, cfg=CFG)
    multi = R.estimate_cost(["S0", "S2"], n_tasks=5, seeds=3, cfg=CFG, n_turns=20)
    assert multi["runs"] == one["runs"] == 30
    assert multi["per_system"]["S0"]["llm_calls"] == round(20 * 3 * R.ASSUMPTIONS["S0"]["calls"]) and one["per_system"]["S0"]["llm_calls"] == round(5 * 3 * R.ASSUMPTIONS["S0"]["calls"])
    assert abs(multi["per_system"]["S2"]["llm_calls"] - 4 * one["per_system"]["S2"]["llm_calls"]) <= 4 and multi["usd"] > one["usd"]
    # lịch sử hội thoại được gửi lại: token đầu vào mỗi lời gọi lớn hơn ngoài tỉ lệ số lượt
    assert multi["per_system"]["S0"]["tokens_in"] > 4 * one["per_system"]["S0"]["tokens_in"]


def test_manifest_has_required_fields_and_never_contains_the_key(tmp_path):
    m = R.build_manifest(CFG, systems=["S0", "S1", "S2"], tasks=[mk(1)], seeds=3, split="dev", cache_mode="record", args={"workers": 4})
    for k in ("created_at", "model", "temperature", "base_url", "corpus_manifest_sha256", "snapshot_agent_v1_sha256", "commit",
              "seeds", "systems", "task_set_sha256", "known_issues", "split", "python", "price_in_per_m"):
        assert k in m, k
    assert m["commit"] is None and m["systems"] == ["S0", "S1", "S2"] and m["seeds"] == 3
    assert "SECRET-should-never-appear" not in json.dumps(m)
    assert any("FreeRTOS" in k for k in m["known_issues"])


def test_runner_aborts_after_consecutive_infra_failures(tmp_path):
    class Down(FakeAdapter):
        def finish(self):
            r = super().finish()
            r.errors = ["infra:RateLimitError status=429: quota"]
            return r

    tasks = [mk(i) for i in range(1, 31)]
    runner = R.Runner(tmp_path, {"S0": Down}, workers=1, rps=0, max_consecutive_infra=5)
    with pytest.raises(FatalAdapterError, match="consecutive"):
        runner.run(R.build_schedule(["S0"], tasks, 1), {t.id: t for t in tasks})
    assert 5 <= len((tmp_path / "runs.jsonl").read_text().splitlines()) < 30         # tiến độ đã lưu để resume


def test_a_success_resets_the_consecutive_infra_counter(tmp_path):
    flip = {"n": 0}

    class Flaky(FakeAdapter):
        def finish(self):
            r = super().finish()
            flip["n"] += 1
            if flip["n"] % 3 != 0:
                r.errors = ["infra:timeout"]
            return r

    tasks = [mk(i) for i in range(1, 13)]
    R.Runner(tmp_path, {"S0": Flaky}, workers=1, rps=0, max_consecutive_infra=3).run(R.build_schedule(["S0"], tasks, 1), {t.id: t for t in tasks})
    assert len((tmp_path / "runs.jsonl").read_text().splitlines()) == 12


# ---- review findings: checksum nhất quán, retry-infra, manifest khi resume -----------------------------------
def test_snapshot_checksum_reproduces_the_value_in_snapshot_md():
    import re as _re

    md = (R.ROOT / "snapshots" / "agent_v1" / "SNAPSHOT.md").read_text(encoding="utf-8")
    recorded = _re.search(r"Checksum tổng[^:]*:\s*([0-9a-f]{64})", md).group(1)
    assert R.snapshot_checksum() == recorded


def test_drop_infra_rows_moves_them_aside_so_they_become_pending(tmp_path):
    runs = tmp_path / "runs.jsonl"
    good = RunResult(system="S0", variant="", task_id="C1-001", seed=0)
    bad = RunResult(system="S0", variant="", task_id="C1-002", seed=0, errors=["infra:timeout"])
    runs.write_text(json.dumps(good.to_dict()) + "\n" + json.dumps(bad.to_dict()) + "\n")
    assert R.drop_infra_rows(runs) == 1
    assert R.load_done(runs) == {("S0", "", "C1-001", 0)}
    side = (tmp_path / "runs_infra_failed.jsonl").read_text().splitlines()
    assert len(side) == 1 and json.loads(side[0])["task_id"] == "C1-002"


def test_resume_with_a_subset_of_systems_keeps_every_system_in_the_manifest():
    merged = R.merge_manifest({"created_at": "T0", "systems": ["S0", "S1", "S2"], "split": "dev"},
                              {"created_at": "T1", "systems": ["S1"], "split": "dev"})
    assert merged["systems"] == ["S0", "S1", "S2"] and merged["created_at"] == "T0"


# ---- post-P0 review #1: breaker cho lỗi 4xx lặp lại từ LLM client (sai model/endpoint/payload) --------------------
class ClientErr(FakeAdapter):
    msg = "error:NotFoundError status=404: models/xyz is not found for API version v1beta"
    bad_from = 3                       # task thứ 3 trở đi lỗi

    def finish(self):
        r = super().finish()
        if int(self.t.id.split("-")[1]) >= self.bad_from:
            r.errors = [self.msg]
        return r


def test_runner_stops_after_n_consecutive_identical_llm_client_errors_and_sets_those_rows_aside(tmp_path):
    tasks = [mk(i) for i in range(1, 31)]
    runner = R.Runner(tmp_path, {"S0": ClientErr}, workers=1, rps=0, max_consecutive_same_error=4)
    with pytest.raises(FatalAdapterError, match="same LLM client error"):
        runner.run(R.build_schedule(["S0"], tasks, 1), {t.id: t for t in tasks})
    kept = [json.loads(l)["task_id"] for l in (tmp_path / "runs.jsonl").read_text().splitlines()]
    aside = [json.loads(l)["task_id"] for l in (tmp_path / "runs_infra_failed.jsonl").read_text().splitlines()]
    assert kept == ["C1-001", "C1-002"] and aside == ["C1-003", "C1-004", "C1-005", "C1-006"]      # --resume sẽ chạy lại chúng
    assert R.load_done(tmp_path / "runs.jsonl") == {("S0", "", "C1-001", 0), ("S0", "", "C1-002", 0)}


def test_the_same_error_breaker_ignores_varying_messages_system_errors_and_successes(tmp_path):
    class Mixed(FakeAdapter):
        def finish(self):
            r = super().finish()
            n = int(self.t.id.split("-")[1])
            if n % 5 == 0:
                r.errors = []                                                                    # xen kẽ run thành công
            elif n % 2:
                r.errors = [f"error:BadRequestError status=400: prompt has {n} tokens"]          # thông điệp khác nhau
            else:
                r.errors = ["error:ValueError: boom"]                                            # lỗi của hệ, không phải 4xx của client
            return r

    tasks = [mk(i) for i in range(1, 25)]
    R.Runner(tmp_path, {"S0": Mixed}, workers=1, rps=0, max_consecutive_same_error=3).run(
        R.build_schedule(["S0"], tasks, 1), {t.id: t for t in tasks})
    assert len((tmp_path / "runs.jsonl").read_text().splitlines()) == 24
    assert not (tmp_path / "runs_infra_failed.jsonl").exists()


def test_system_errors_that_are_not_llm_client_4xx_never_trip_the_breaker(tmp_path):
    class Same(ClientErr):
        msg = "error:ValueError: boom"
        bad_from = 1

    tasks = [mk(i) for i in range(1, 13)]
    R.Runner(tmp_path, {"S0": Same}, workers=1, rps=0, max_consecutive_same_error=3).run(
        R.build_schedule(["S0"], tasks, 1), {t.id: t for t in tasks})
    assert len((tmp_path / "runs.jsonl").read_text().splitlines()) == 12


def test_llm_client_error_detection_covers_all_three_adapter_label_formats():
    f = R.sole_llm_client_error
    mk_r = lambda *errs: RunResult(system="S0", variant="", task_id="C1-001", seed=0, errors=list(errs))
    assert f(mk_r("error:BadRequestError status=400: x")) == "error:BadRequestError status=400: x"        # S1
    assert f(mk_r("error:NotFoundError: Error code: 404 - models/x")) is not None                          # S0 / S2
    assert f(mk_r("error:BadRequestError: bad")) is not None                                               # theo tên lớp
    assert f(mk_r("error:ValueError: boom")) is None and f(mk_r()) is None
    assert f(mk_r("error:BadRequestError status=400: x", "infra:timeout")) is None                         # không phải lỗi DUY NHẤT
    assert f(mk_r("error:BadRequestError status=400: x", "error:BadRequestError status=400: x")) is not None   # đa lượt, cùng lỗi


# ---- post-P0 review #4: replay mà có run infra:cache_miss thì phải thoát khác 0 và in số lượng ------------------------
def _patch_main(monkeypatch, factory):
    monkeypatch.setattr(R, "make_factories", lambda cfg, cache_mode, timeout: {"S0": factory, "S1": factory, "S2": factory})
    monkeypatch.setenv("EVAL_LLM_RPM", "0")                  # main() ghi đè biến này; monkeypatch khôi phục sau test
    monkeypatch.setenv("EVAL_RATE_FILE", "")


class Miss(FakeAdapter):
    def finish(self):
        r = super().finish()
        if self.t.id.endswith(("1", "2", "3")):
            r.errors = ["infra:cache_miss"]
        return r


def test_replay_with_cache_misses_exits_nonzero_and_prints_the_count(tmp_path, monkeypatch, capsys):
    _patch_main(monkeypatch, Miss)
    rc = R.main(["--suite", "smoke", "--systems", "S0", "--cache", "replay", "--out", str(tmp_path / "r"), "--no-report"])
    err = capsys.readouterr().err
    n = sum(1 for l in (tmp_path / "r" / "runs.jsonl").read_text().splitlines() if "infra:cache_miss" in l)
    assert n >= 1 and rc != 0 and f"{n} run" in err and "cache_miss" in err


def test_replay_without_cache_misses_exits_zero(tmp_path, monkeypatch):
    _patch_main(monkeypatch, FakeAdapter)
    assert R.main(["--suite", "smoke", "--systems", "S0", "--cache", "replay", "--out", str(tmp_path / "r"), "--no-report"]) == 0


# ---- post-P0 review #5: provenance của manifest khi --resume ------------------------------------------------------
ORIG = {"created_at": "T0", "args": {"workers": 4, "resume": None}, "seeds": 3, "split": "dev", "cache_mode": "record", "model": "m",
        "temperature": 0.0, "task_set_sha256": "ts0", "corpus_manifest_sha256": "c0", "snapshot_agent_v1_sha256": "s0",
        "native_rag_changelog_sha256": "n0", "systems": ["S0", "S1", "S2"], "finished_at": "F0", "wall_seconds": 100.0,
        "status": "completed"}
RESUME = {"created_at": "T1", "args": {"workers": 2, "resume": "x"}, "seeds": 1, "split": "dev", "cache_mode": "replay", "model": "m",
          "temperature": 0.0, "task_set_sha256": "ts1", "corpus_manifest_sha256": "c1", "snapshot_agent_v1_sha256": "s0",
          "native_rag_changelog_sha256": "n1", "systems": ["S1"]}


def test_resume_keeps_the_original_provenance_and_appends_a_resume_entry():
    m = R.merge_manifest(ORIG, RESUME)
    for k in ("created_at", "args", "seeds", "split", "cache_mode", "model", "temperature", "task_set_sha256",
              "corpus_manifest_sha256", "snapshot_agent_v1_sha256", "native_rag_changelog_sha256", "finished_at", "wall_seconds"):
        assert m[k] == ORIG[k], k
    assert m["systems"] == ["S0", "S1", "S2"] and m["resumed_at"] == ["T1"]
    (entry,) = m["resumes"]
    assert entry["args"] == RESUME["args"] and entry["started_at"] == "T1" and entry["cache_mode"] == "replay"
    assert (entry["task_set_sha256"], entry["corpus_manifest_sha256"], entry["snapshot_agent_v1_sha256"],
            entry["native_rag_changelog_sha256"]) == ("ts1", "c1", "s0", "n1")
    m2 = R.merge_manifest(m, {**RESUME, "created_at": "T2"})
    assert [e["started_at"] for e in m2["resumes"]] == ["T1", "T2"] and m2["created_at"] == "T0" and m2["resumed_at"] == ["T1", "T2"]


@pytest.mark.parametrize("key,val", [("model", "other"), ("temperature", 0.7), ("split", "test"), ("snapshot_agent_v1_sha256", "zzz")])
def test_resume_aborts_when_model_temperature_split_or_snapshot_differ(key, val):
    with pytest.raises(R.ManifestMismatch, match=key):
        R.merge_manifest(ORIG, {**RESUME, key: val})


def test_resume_mismatch_aborts_main_before_touching_any_file(tmp_path, monkeypatch, capsys):
    _patch_main(monkeypatch, FakeAdapter)
    d = tmp_path / "r"
    d.mkdir()
    bad_row = json.dumps(RunResult(system="S0", variant="", task_id="C1-001", seed=0, errors=["infra:timeout"]).to_dict()) + "\n"
    (d / "runs.jsonl").write_text(bad_row)
    (d / "manifest.json").write_text(json.dumps({**ORIG, "model": "some-other-model"}))
    before = (d / "manifest.json").read_text()
    rc = R.main(["--resume", str(d), "--suite", "smoke", "--systems", "S0", "--cache", "replay", "--retry-infra", "--no-report"])
    assert rc == 2 and "model" in capsys.readouterr().err
    assert (d / "runs.jsonl").read_text() == bad_row and not (d / "runs_infra_failed.jsonl").exists()   # --retry-infra chưa chạy
    assert (d / "manifest.json").read_text() == before


def test_finish_manifest_records_end_time_status_and_reason_for_a_fresh_run_and_a_resume():
    fresh = {"created_at": "T0"}
    R.finish_manifest(fresh, 12.34, "stopped_fatal", "S2: boom")
    assert fresh["finished_at"] and fresh["wall_seconds"] == 12.3 and fresh["status"] == "stopped_fatal" and fresh["stop_reason"] == "S2: boom"
    merged = R.merge_manifest(ORIG, RESUME)
    R.finish_manifest(merged, 5.0, "stopped_fatal", "boom")
    last = merged["resumes"][-1]
    assert last["finished_at"] and last["wall_seconds"] == 5.0 and last["status"] == "stopped_fatal" and last["stop_reason"] == "boom"
    assert merged["wall_seconds"] == 100.0 and merged["finished_at"] == "F0" and merged["status"] == "completed"   # lần chạy gốc giữ nguyên


def test_a_resume_that_stops_on_fatal_still_gets_a_finished_at_and_keeps_the_original_provenance(tmp_path, monkeypatch):
    d = tmp_path / "r"
    _patch_main(monkeypatch, FakeAdapter)
    assert R.main(["--suite", "smoke", "--systems", "S0", "--cache", "replay", "--out", str(d), "--no-report"]) == 0
    first = json.loads((d / "manifest.json").read_text())
    assert first["status"] == "completed" and first["finished_at"] and "wall_seconds" in first

    class Fatal(FakeAdapter):
        def start(self, task, seed):
            raise FatalAdapterError("S0: key rejected")

    _patch_main(monkeypatch, Fatal)
    assert R.main(["--resume", str(d), "--suite", "smoke", "--systems", "S0", "--seeds", "2", "--cache", "replay", "--no-report"]) == 3
    m = json.loads((d / "manifest.json").read_text())
    assert m["created_at"] == first["created_at"] and m["args"] == first["args"] and m["seeds"] == 1
    (entry,) = m["resumes"]
    assert entry["status"] == "stopped_fatal" and entry["finished_at"] and "key rejected" in entry["stop_reason"]
    assert entry["args"]["seeds"] == 2 and entry["args"]["resume"] == str(d)


# ---- post-P0 review #6: resume khi runs.jsonl không kết thúc bằng xuống dòng ----------------------------------------
def test_resume_writes_a_newline_before_appending_if_the_last_line_was_cut(tmp_path):
    runs = tmp_path / "runs.jsonl"
    good = json.dumps(RunResult(system="S0", variant="", task_id="C1-001", seed=0).to_dict())
    runs.write_text(good + "\n" + good[:25])                                  # tiến trình chết giữa chừng, không có \n cuối
    tasks = [mk(2), mk(3)]
    R.Runner(tmp_path, {"S0": FakeAdapter}, workers=1, rps=0).run(R.build_schedule(["S0"], tasks, 1), {t.id: t for t in tasks})
    parsed = []
    for line in runs.read_text().splitlines():
        try:
            parsed.append(json.loads(line)["task_id"])
        except json.JSONDecodeError:
            pass
    assert parsed == ["C1-001", "C1-002", "C1-003"]                           # hai run mới không bị dính vào dòng cụt
    assert R.load_done(runs) == {("S0", "", f"C1-00{i}", 0) for i in (1, 2, 3)}


# ---- S2D: Agent v1 loop + dữ liệu P1 (snapshot agent_p1) -----------------------------------------------------------
def test_s2d_is_a_registered_system_with_its_own_cost_assumptions():
    assert R.SYSTEMS_ALL == ["S0", "S1", "S2", "S2D", "S3@P4", "S3@P5"] and R.DEFAULT_SYSTEMS == ["S0", "S1", "S2", "S2D"] and "S2D" in R.ASSUMPTIONS
    est = R.estimate_cost(["S2", "S2D"], n_tasks=27, seeds=3, cfg=CFG)
    assert est["per_system"]["S2D"]["runs"] == 81 and est["per_system"]["S2D"]["llm_calls"] > 0 and est["per_system"]["S2D"]["tokens_in"] > 0


def test_factory_builds_s2d_on_the_p1_snapshot_with_the_agent_venv_interpreter():
    s2d = R.make_factories(CFG, "off", 60)["S2D"]()
    s2 = R.make_factories(CFG, "off", 60)["S2"]()
    assert s2d.name == "S2D" and s2.name == "S2"
    assert s2d.snapshot == R.ROOT / "snapshots" / "agent_p1" and s2.snapshot == R.ROOT / "snapshots" / "agent_v1"
    assert s2d.cmd[0] == str(R.ROOT / "agent" / ".venv" / "bin" / "python") and s2d.cmd[1] == "-I"
    assert s2d.cache_path == s2.cache_path                             # cùng cache LLM (khoá đã gồm messages+tools nên không đụng nhau)


def test_p1_snapshot_checksum_matches_snapshot_md():
    snap = R.ROOT / "snapshots" / "agent_p1"
    md = (snap / "SNAPSHOT.md").read_text(encoding="utf-8")
    assert R.snapshot_checksum(snap) in md


def test_manifest_records_a_separate_hash_per_snapshot():
    tasks = [mk(1)]
    m = R.build_manifest(CFG, ["S2", "S2D"], tasks, 1, "dev", "off", {})
    assert m["snapshot_agent_v1_sha256"] == R.snapshot_checksum(R.ROOT / "snapshots" / "agent_v1")
    assert m["snapshot_agent_p1_sha256"] == R.snapshot_checksum(R.ROOT / "snapshots" / "agent_p1")
    assert m["snapshot_agent_v1_sha256"] != m["snapshot_agent_p1_sha256"]


P1_RESUME = {**RESUME, "systems": ["S2D"], "snapshot_agent_p1_sha256": "p1hash"}


def test_adding_s2d_to_a_baseline_manifest_does_not_abort_and_records_the_p1_hash():
    m = R.merge_manifest(ORIG, P1_RESUME)                               # ORIG (dev_baseline) không có khoá snapshot_agent_p1_sha256
    assert m["snapshot_agent_p1_sha256"] == "p1hash" and m["snapshot_agent_v1_sha256"] == "s0"
    assert m["systems"] == ["S0", "S1", "S2", "S2D"]
    assert m["resumes"][-1]["snapshot_agent_p1_sha256"] == "p1hash"


def test_a_changed_p1_snapshot_aborts_a_later_resume_but_an_unchanged_one_does_not():
    m = R.merge_manifest(ORIG, P1_RESUME)
    R.merge_manifest(m, {**P1_RESUME, "created_at": "T2"})              # cùng hash: ổn
    with pytest.raises(R.ManifestMismatch, match="snapshot_agent_p1_sha256"):
        R.merge_manifest(m, {**P1_RESUME, "snapshot_agent_p1_sha256": "other"})


def test_hash_of_the_v1_snapshot_is_still_enforced_when_only_s2d_is_resumed():
    with pytest.raises(R.ManifestMismatch, match="snapshot_agent_v1_sha256"):
        R.merge_manifest(ORIG, {**P1_RESUME, "snapshot_agent_v1_sha256": "changed"})


def test_manifest_pins_the_data_files_of_the_p1_snapshot():
    m = R.build_manifest(CFG, ["S2D"], [mk(1)], 1, "dev", "off", {})
    assert m["snapshot_agent_p1_data_sha256"] == R.snapshot_data_checksum(R.ROOT / "snapshots" / "agent_p1")
    md = (R.ROOT / "snapshots" / "agent_p1" / "SNAPSHOT.md").read_text(encoding="utf-8")
    assert m["snapshot_agent_p1_data_sha256"] in md


def test_a_rebuilt_data_file_inside_the_p1_snapshot_aborts_a_later_resume():
    m = R.merge_manifest(ORIG, {**P1_RESUME, "snapshot_agent_p1_data_sha256": "d0"})
    assert m["snapshot_agent_p1_data_sha256"] == "d0"
    R.merge_manifest(m, {**P1_RESUME, "snapshot_agent_p1_data_sha256": "d0", "created_at": "T2"})
    with pytest.raises(R.ManifestMismatch, match="snapshot_agent_p1_data_sha256"):
        R.merge_manifest(m, {**P1_RESUME, "snapshot_agent_p1_data_sha256": "d1"})


def test_s2d_worker_does_not_write_bytecode_into_the_frozen_snapshot():
    s2d = R.make_factories(CFG, "off", 60)["S2D"]()
    assert s2d.cmd[1:3] == ["-I", "-B"]


def test_manifest_pins_the_frozen_hwmodel_used_by_the_c3_grader():
    from eval import sandbox
    m = R.build_manifest(CFG, ["S0"], [mk(1)], 1, "dev", "off", {})
    h = sandbox.vendor_hashes()
    assert m["hwmodel_vendor_sha256"] == h["hwmodel_vendor_sha256"] and m["hwmodel_data_sha256"] == h["hwmodel_data_sha256"]
    assert len(m["hwmodel_vendor_sha256"]) == 64


def test_resume_entries_record_the_hwmodel_hashes_but_a_new_freeze_does_not_block_resuming():
    # chấm điểm xảy ra SAU khi chạy (đọc runs.jsonl), nên đổi bản vendor giữa hai lần resume là hợp lệ (ghi vào post_run_changes) — không như snapshot agent
    assert "hwmodel_vendor_sha256" in R.RESUME_ENTRY_KEYS and "hwmodel_data_sha256" in R.RESUME_ENTRY_KEYS
    assert "hwmodel_vendor_sha256" not in R.RESUME_MUST_MATCH
    old = {**ORIG, "hwmodel_vendor_sha256": "a" * 64}
    merged = R.merge_manifest(old, {**RESUME, "hwmodel_vendor_sha256": "b" * 64})
    assert merged["hwmodel_vendor_sha256"] == "a" * 64 and merged["resumes"][-1]["hwmodel_vendor_sha256"] == "b" * 64
