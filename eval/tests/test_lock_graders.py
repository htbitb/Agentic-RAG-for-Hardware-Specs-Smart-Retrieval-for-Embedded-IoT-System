"""Khoá grader/task/snapshot trước khi chạy test (P9)."""
import json

import pytest

from eval.tools import lock_graders as L


def test_collect_covers_graders_tasks_and_is_stable():
    a, b = L.collect(), L.collect()
    assert a == b and any(k.endswith("attack.py") for k in a["graders"]) and any("c7_indirect.yaml" in k for k in a["tasks"]) and len(a["combined_sha256"]) == 64


def test_diff_reports_changed_added_and_removed_files_and_snapshot_changes():
    old = {"graders": {"g.py": "1", "h.py": "2"}, "code": {}, "tasks": {}, "vendor": {}, "snapshot": {"path": "s", "code_sha256": "a"}}
    new = {"graders": {"g.py": "9", "i.py": "3"}, "code": {}, "tasks": {}, "vendor": {}, "snapshot": {"path": "s", "code_sha256": "b"}}
    assert L.diff(old, new) == ["graders: g.py changed", "graders: h.py removed", "graders: i.py added", "snapshot: changed"]
    assert L.diff(old, old) == []


def test_verify_without_a_lock_file_fails_and_with_a_fresh_lock_passes(tmp_path):
    assert L.verify(tmp_path / "none.json")
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(L.collect()), encoding="utf-8")
    assert L.verify(lock) == []
    data = json.loads(lock.read_text())
    data["graders"][next(iter(data["graders"]))] = "0" * 64
    lock.write_text(json.dumps(data), encoding="utf-8")
    assert len(L.verify(lock)) == 1


def test_the_runner_refuses_the_test_split_while_the_lock_does_not_verify_but_allows_dry_runs(monkeypatch, capsys):
    from eval import run as R
    monkeypatch.setattr(L, "verify", lambda *a, **k: ["graders: x.py changed"])
    with pytest.raises(SystemExit) as e:
        R.main(["--systems", "S0", "--split", "test", "--seeds", "1"])
    assert e.value.code == 2 and "khoá" in capsys.readouterr().err
    monkeypatch.setattr(L, "verify", lambda *a, **k: [])
    assert R.main(["--systems", "S0", "--split", "test", "--seeds", "1", "--dry-run"]) == 0
