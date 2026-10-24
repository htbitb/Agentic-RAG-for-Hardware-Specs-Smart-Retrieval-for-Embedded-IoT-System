"""run.py (P4): hệ S3@P4, cờ --ablations (mỗi ablation một biến thể riêng trong lịch), manifest ghim snapshot P4. Hệ cũ không đổi hành vi."""
import json

import pytest

from eval import run as R
from eval.adapters.base import FatalAdapterError
from eval.schema import RunResult
from eval.tests.test_run import CFG, ORIG, RESUME, FakeAdapter, mk


# ------------------------------------------------------------------ đăng ký hệ
def test_s3_p4_is_registered_with_the_measured_cost_assumptions_but_is_not_a_default_system():
    assert R.SYSTEMS_ALL == ["S0", "S1", "S2", "S2D", "S3@P4", "S3@P5"]
    assert R.ASSUMPTIONS["S3@P4"] == {"calls": 13.7, "in": 21600, "out": 240}          # đo ở pilot P4 (38 run dev, 1 seed)
    assert R.DEFAULT_SYSTEMS == ["S0", "S1", "S2", "S2D"]                      # chạy không --systems vẫn đúng như trước P4


def test_cost_estimate_includes_s3_p4_and_repeated_names_accumulate_one_entry_per_variant():
    est = R.estimate_cost(["S3@P4"], n_tasks=10, seeds=3, cfg=CFG)
    assert est["per_system"]["S3@P4"]["runs"] == 30 and est["per_system"]["S3@P4"]["llm_calls"] == round(30 * 13.7)
    two = R.estimate_cost(["S3@P4", "S3@P4"], n_tasks=10, seeds=3, cfg=CFG)             # hai biến thể ablation
    assert two["runs"] == 60 and two["llm_calls"] == 2 * est["llm_calls"] and two["usd"] == pytest.approx(2 * est["usd"], rel=1e-6)
    assert two["per_system"]["S3@P4"]["runs"] == 60


def test_legacy_estimate_is_unchanged():
    est = R.estimate_cost(["S0", "S1", "S2"], n_tasks=27, seeds=3, cfg=CFG)
    assert est["runs"] == 243 and set(est["per_system"]) == {"S0", "S1", "S2"}


# ------------------------------------------------------------------ factory
def test_factory_builds_the_p4_adapter_on_the_p4_snapshot_with_the_agent_venv_and_a_long_turn_timeout():
    f = R.make_factories(CFG, "off", 180)
    a = f["S3@P4"]()
    assert a.name == "S3@P4" and a.variant == "" and a.ablations == []
    assert a.snapshot == R.ROOT / "snapshots" / "agent_p4"
    assert a.cmd[0] == str(R.ROOT / "agent" / ".venv" / "bin" / "python") and a.cmd[1:3] == ["-I", "-B"] and a.cmd[3].endswith("agent_v3_worker.py")
    assert a.timeout == 900                                                    # --timeout 180 (mặc định) quá ngắn so với ngân sách wall của runtime
    assert R.make_factories(CFG, "off", 900)["S3@P4"]().timeout == 900
    assert a.cache_path == f["S2D"]().cache_path                               # cùng cache LLM với S2/S2D (khoá đã gồm messages+tools)


def test_factory_has_one_entry_per_ablation_variant_with_its_code_and_label():
    f = R.make_factories(CFG, "off", 180)
    for code, variant in {"A1": "-Planner", "A2": "-BoardState", "A3": "-Sandbox", "A4": "-Reflection"}.items():
        a = f[("S3@P4", variant)]()
        assert a.variant == variant and a.ablations == [code] and a.name == "S3@P4" and a.snapshot == R.ROOT / "snapshots" / "agent_p4"
    assert f["S3@P4"]() is not f["S3@P4"]()                                    # mỗi lời gọi là một adapter mới (Runner giữ một adapter cho mỗi luồng)


def test_legacy_factories_are_unchanged():
    f = R.make_factories(CFG, "off", 60)
    assert {"S0", "S1", "S2", "S2D"} <= set(f)
    assert f["S2"]().timeout == 60 and f["S2D"]().name == "S2D"


# ------------------------------------------------------------------ lịch chạy với ablation
def test_parse_ablations_maps_codes_to_variants_and_rejects_unknown_codes():
    assert R.parse_ablations("A1, a3,A1") == ["A1", "A3"]
    assert R.parse_ablations("") == [] and R.parse_ablations(None) == []
    assert [R.ABLATION_VARIANTS[c] for c in R.parse_ablations("A1,A2,A3,A4")] == ["-Planner", "-BoardState", "-Sandbox", "-Reflection"]
    with pytest.raises(ValueError, match="A9"):
        R.parse_ablations("A1,A9")


def test_each_ablation_is_its_own_set_of_schedule_entries_and_replaces_the_main_s3_entries():
    tasks = [mk(2), mk(1)]
    sched = R.build_schedule(["S0", "S3@P4"], tasks, seeds=2, ablations=["A1", "A3"])
    assert [s for s in sched if s[0] == "S0"] == [("S0", "", "C1-001", 0), ("S0", "", "C1-001", 1), ("S0", "", "C1-002", 0), ("S0", "", "C1-002", 1)]
    s3 = [s for s in sched if s[0] == "S3@P4"]
    assert [s[1] for s in s3] == ["-Planner"] * 4 + ["-Sandbox"] * 4              # hệ -> biến thể -> task -> seed
    assert s3[0] == ("S3@P4", "-Planner", "C1-001", 0) and s3[5] == ("S3@P4", "-Sandbox", "C1-001", 1)
    assert ("S3@P4", "", "C1-001", 0) not in sched


def test_ablations_leave_the_schedule_of_other_systems_and_the_no_ablation_schedule_unchanged():
    tasks = [mk(1), mk(2)]
    assert R.build_schedule(["S0", "S2D"], tasks, 2, ablations=["A1"]) == R.build_schedule(["S0", "S2D"], tasks, 2)
    assert R.build_schedule(["S3@P4"], tasks, 1) == [("S3@P4", "", "C1-001", 0), ("S3@P4", "", "C1-002", 0)]


def test_resume_keys_include_the_variant(tmp_path):
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps(RunResult(system="S3@P4", variant="-Planner", task_id="C1-001", seed=0).to_dict()) + "\n"
                    + json.dumps(RunResult(system="S3@P4", variant="", task_id="C1-001", seed=0).to_dict()) + "\n")
    sched = R.build_schedule(["S3@P4"], [mk(1), mk(2)], 1, ablations=["A1", "A2"])
    done = R.load_done(runs)
    assert done == {("S3@P4", "-Planner", "C1-001", 0), ("S3@P4", "", "C1-001", 0)}
    assert R.pending(sched, done) == [("S3@P4", "-Planner", "C1-002", 0), ("S3@P4", "-BoardState", "C1-001", 0), ("S3@P4", "-BoardState", "C1-002", 0)]


class VariantAdapter(FakeAdapter):
    """Adapter giả mang nhãn hệ/biến thể của chính nó (như AgentV3Adapter)."""
    name = "S3@P4"
    made: list = []

    def __init__(self, variant=""):
        super().__init__()
        self.variant = variant
        VariantAdapter.made.append(variant)

    def finish(self):
        r = super().finish()
        r.system, r.variant = self.name, self.variant
        return r


def test_runner_keeps_one_adapter_per_system_and_variant_and_labels_every_result(tmp_path):
    VariantAdapter.made = []
    tasks = [mk(i) for i in range(1, 4)]
    sched = R.build_schedule(["S3@P4"], tasks, 2, ablations=["A1", "A3"])
    factories = {("S3@P4", "-Planner"): lambda: VariantAdapter("-Planner"), ("S3@P4", "-Sandbox"): lambda: VariantAdapter("-Sandbox")}
    n = R.Runner(tmp_path, factories, workers=1, rps=0).run(sched, {t.id: t for t in tasks})
    rows = [json.loads(l) for l in (tmp_path / "runs.jsonl").read_text().splitlines()]
    assert n == 12 and sorted(VariantAdapter.made) == ["-Planner", "-Sandbox"]       # một adapter mỗi biến thể (một luồng), được dùng lại giữa các run
    assert {(r["system"], r["variant"]) for r in rows} == {("S3@P4", "-Planner"), ("S3@P4", "-Sandbox")}
    assert R.load_done(tmp_path / "runs.jsonl") == set(sched)


def test_runner_main_and_ablation_variants_use_separate_adapters(tmp_path):
    VariantAdapter.made = []
    tasks = [mk(1), mk(2)]
    sched = [("S3@P4", "", "C1-001", 0), ("S3@P4", "-Planner", "C1-001", 0), ("S3@P4", "", "C1-002", 0), ("S3@P4", "-Planner", "C1-002", 0)]
    factories = {"S3@P4": lambda: VariantAdapter(""), ("S3@P4", "-Planner"): lambda: VariantAdapter("-Planner")}
    R.Runner(tmp_path, factories, workers=1, rps=0).run(sched, {t.id: t for t in tasks})
    assert sorted(VariantAdapter.made) == ["", "-Planner"]
    assert R.load_done(tmp_path / "runs.jsonl") == set(sched)


def test_a_fatal_error_in_an_ablation_variant_still_aborts_the_run(tmp_path):
    class Fatal(VariantAdapter):
        def start(self, task, seed):
            raise FatalAdapterError("S3@P4 worker refused to run: simulated_llm")

    with pytest.raises(FatalAdapterError, match="simulated_llm"):
        R.Runner(tmp_path, {("S3@P4", "-Planner"): lambda: Fatal("-Planner")}, workers=1, rps=0).run(
            [("S3@P4", "-Planner", "C1-001", 0)], {"C1-001": mk(1)})


# ------------------------------------------------------------------ CLI
def _dry(capsys, monkeypatch, *argv):
    monkeypatch.setenv("EVAL_LLM_RPM", "0")
    monkeypatch.setenv("EVAL_RATE_FILE", "")
    rc = R.main([*argv, "--cache", "replay", "--split", "dev", "--limit", "2", "--seeds", "1", "--dry-run"])
    return rc, capsys.readouterr().err


def test_dry_run_counts_one_schedule_entry_per_ablation(capsys, monkeypatch):
    rc, err = _dry(capsys, monkeypatch, "--systems", "S0,S3@P4", "--ablations", "A1,A2,A4")
    assert rc == 0 and "Lịch chạy: 8 run" in err                                 # 2 task: S0 (2) + 3 biến thể x 2
    rc, err = _dry(capsys, monkeypatch, "--systems", "S3@P4")
    assert rc == 0 and "Lịch chạy: 2 run" in err


def test_dry_run_estimate_scales_with_the_number_of_ablation_variants(capsys, monkeypatch):
    def usd(err):
        return float(err.split("~$")[1].split(" ")[0])

    one = usd(_dry(capsys, monkeypatch, "--systems", "S3@P4", "--ablations", "A1")[1])
    three = usd(_dry(capsys, monkeypatch, "--systems", "S3@P4", "--ablations", "A1,A2,A3")[1])
    assert three == pytest.approx(3 * one, rel=0.05) and one > 0


def test_ablations_are_only_valid_with_s3_p4(capsys, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _dry(capsys, monkeypatch, "--systems", "S0,S2D", "--ablations", "A1")
    assert e.value.code == 2 and "S3@P4" in capsys.readouterr().err


def test_unknown_ablation_code_is_a_usage_error(capsys, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _dry(capsys, monkeypatch, "--systems", "S3@P4", "--ablations", "A7")
    assert e.value.code == 2 and "A7" in capsys.readouterr().err


def test_the_default_systems_do_not_include_s3_p4(capsys, monkeypatch):
    rc, err = _dry(capsys, monkeypatch)
    assert rc == 0 and "S3@P4" not in err.split("Lịch chạy:")[1].splitlines()[0]


# ------------------------------------------------------------------ manifest
def test_manifest_pins_the_p4_snapshot_code_and_data_hashes(tmp_path, monkeypatch):
    snap = tmp_path / "agent_p4"
    (snap / "agent").mkdir(parents=True)
    (snap / "agent" / "x.py").write_text("X = 1\n")
    (snap / "data").mkdir()
    (snap / "data" / "hw_specs.sqlite").write_text("DB")
    monkeypatch.setattr(R, "SNAPSHOT_P4", snap)
    m = R.build_manifest(CFG, ["S3@P4"], [mk(1)], 1, "dev", "off", {})
    assert m["snapshot_agent_p4_sha256"] == R.snapshot_checksum(snap) and m["snapshot_agent_p4_data_sha256"] == R.snapshot_data_checksum(snap)
    assert len(m["snapshot_agent_p4_sha256"]) == 64 and len(m["snapshot_agent_p4_data_sha256"]) == 64


def test_manifest_has_none_hashes_when_the_p4_snapshot_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "SNAPSHOT_P4", tmp_path / "missing")
    m = R.build_manifest(CFG, ["S0"], [mk(1)], 1, "dev", "off", {})
    assert m["snapshot_agent_p4_sha256"] is None and m["snapshot_agent_p4_data_sha256"] is None


def test_p4_hashes_are_enforced_on_resume_and_recorded_in_resume_entries():
    assert {"snapshot_agent_p4_sha256", "snapshot_agent_p4_data_sha256"} <= set(R.RESUME_MUST_MATCH)
    assert {"snapshot_agent_p4_sha256", "snapshot_agent_p4_data_sha256"} <= set(R.RESUME_ENTRY_KEYS)
    p4 = {**RESUME, "systems": ["S3@P4"], "snapshot_agent_p4_sha256": "c0", "snapshot_agent_p4_data_sha256": "d0"}
    m = R.merge_manifest(ORIG, p4)                                             # ORIG (dev_baseline) không có khoá P4: thêm S3@P4 không bị chặn
    assert m["snapshot_agent_p4_sha256"] == "c0" and m["resumes"][-1]["snapshot_agent_p4_data_sha256"] == "d0"
    R.merge_manifest(m, {**p4, "created_at": "T2"})
    with pytest.raises(R.ManifestMismatch, match="snapshot_agent_p4_sha256"):
        R.merge_manifest(m, {**p4, "snapshot_agent_p4_sha256": "other"})
    with pytest.raises(R.ManifestMismatch, match="snapshot_agent_p4_data_sha256"):
        R.merge_manifest(m, {**p4, "snapshot_agent_p4_data_sha256": "other"})


def test_a_manifest_that_lacks_the_p4_keys_keeps_resuming_and_a_none_p4_hash_never_blocks():
    R.merge_manifest(ORIG, {**RESUME, "snapshot_agent_p4_sha256": None, "snapshot_agent_p4_data_sha256": None})
    R.merge_manifest(ORIG, RESUME)                                             # lần resume không hề có khoá
    old_with_none = {**ORIG, "snapshot_agent_p4_sha256": None}
    R.merge_manifest(old_with_none, {**RESUME, "snapshot_agent_p4_sha256": "c0"})


# ------------------------------------------------------------------ chạy → chấm → báo cáo (worker giả, không mạng)
def test_end_to_end_ablation_run_scores_and_reports_variants_separately_with_process_metrics(tmp_path, monkeypatch):
    import sys

    from eval.adapters.agent_v3 import AgentV3Adapter
    from eval.tests.test_adapter_agent_v3 import STUB

    stub = tmp_path / "stub_worker.py"
    stub.write_text(STUB)

    def factories(cfg, cache_mode, timeout):
        mk_adapter = lambda **kw: AgentV3Adapter(cfg, cmd=[sys.executable, str(stub)], timeout=5, startup_timeout=10, work_dir=tmp_path / "runs", **kw)
        return {("S3@P4", "-Planner"): lambda: mk_adapter(ablations=["A1"]), ("S3@P4", "-Sandbox"): lambda: mk_adapter(ablations=["A3"])}

    monkeypatch.setattr(R, "make_factories", factories)
    monkeypatch.setenv("EVAL_LLM_RPM", "0")
    monkeypatch.setenv("EVAL_RATE_FILE", "")
    out = tmp_path / "res"
    rc = R.main(["--systems", "S3@P4", "--ablations", "A1,A3", "--split", "dev", "--limit", "2", "--seeds", "1", "--cache", "replay", "--workers", "1",
                 "--out", str(out)])
    assert rc == 0
    rows = [json.loads(l) for l in (out / "runs.jsonl").read_text().splitlines()]
    assert sorted((r["system"], r["variant"]) for r in rows) == [("S3@P4", "-Planner")] * 2 + [("S3@P4", "-Sandbox")] * 2
    assert all(any(e.get("type") == "run_started" for e in r["trace"]) for r in rows)
    scores = [json.loads(l) for l in (out / "scores.jsonl").read_text().splitlines()]
    assert {s["variant"] for s in scores} == {"-Planner", "-Sandbox"} and all(s["graders"]["process"]["details"]["v3"] for s in scores)
    md = (out / "report.md").read_text()
    assert "| S3@P4 [-Planner] |" in md and "| S3@P4 [-Sandbox] |" in md and "## Chỉ số quá trình (S3)" in md
    assert "| S3@P4 |" not in md                                                      # không có lượt chạy chính ⇒ không có hàng S3@P4 trơn
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["status"] == "completed" and "snapshot_agent_p4_sha256" in manifest
