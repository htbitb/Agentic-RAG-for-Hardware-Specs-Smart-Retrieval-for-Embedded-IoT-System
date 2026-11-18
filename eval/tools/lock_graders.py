"""Khoá grader, task và snapshot TRƯỚC khi chạy split test (HANDOFF P9 mục 1, D38).

    eval/.venv/bin/python -m eval.tools.lock_graders --write --snapshot snapshots/agent_p7 --note "..."   # ghi eval/GRADER_LOCK.json
    eval/.venv/bin/python -m eval.tools.lock_graders --verify                                           # thoát 1 nếu bất kỳ băm nào đã đổi

Băm: mọi file grader (eval/graders/*.py) + markers/schema/score/stats/sandbox/report, file task (eval/tasks/**), bản vendor hwmodel, và snapshot agent (mã + dữ liệu). eval.run --split test từ chối chạy
khi không có khoá hoặc --verify thất bại. Sửa grader sau khi đã thấy đầu ra test chỉ hợp lệ khi báo CẢ HAI con số và ghi post_run_changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "eval" / "GRADER_LOCK.json"
CODE = ["eval/markers.py", "eval/schema.py", "eval/score.py", "eval/stats.py", "eval/sandbox.py", "eval/report.py", "eval/system_prompts.py"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _group(paths) -> dict:
    return {str(p.relative_to(ROOT)): _sha(p) for p in sorted(paths) if p.is_file()}


def collect(snapshot: str | None = None) -> dict:
    out = {"graders": _group((ROOT / "eval" / "graders").glob("*.py")), "code": _group(ROOT / c for c in CODE),
           "tasks": _group((ROOT / "eval" / "tasks").rglob("*.yaml")), "vendor": _group((ROOT / "eval" / "vendor").rglob("*.py")) if (ROOT / "eval" / "vendor").is_dir() else {}}
    if snapshot:
        sys.path.insert(0, str(ROOT))
        from eval.run import snapshot_checksum, snapshot_data_checksum
        snap = ROOT / snapshot
        out["snapshot"] = {"path": snapshot, "code_sha256": snapshot_checksum(snap), "data_sha256": snapshot_data_checksum(snap)}
    out["combined_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in out.items() if k != "combined_sha256"}, sort_keys=True).encode()).hexdigest()
    return out


def diff(old: dict, new: dict) -> list[str]:
    msgs = []
    for sec in ("graders", "code", "tasks", "vendor"):
        for k in sorted(set(old.get(sec, {})) | set(new.get(sec, {}))):
            if old.get(sec, {}).get(k) != new.get(sec, {}).get(k):
                msgs.append(f"{sec}: {k} " + ("added" if k not in old.get(sec, {}) else "removed" if k not in new.get(sec, {}) else "changed"))
    if old.get("snapshot") != new.get("snapshot"):
        msgs.append("snapshot: changed")
    return msgs


def verify(lock_path: Path = LOCK) -> list[str]:
    if not lock_path.is_file():
        return [f"no lock file at {lock_path.relative_to(ROOT) if lock_path.is_relative_to(ROOT) else lock_path}"]
    old = json.loads(lock_path.read_text(encoding="utf-8"))
    return diff(old, collect((old.get("snapshot") or {}).get("path")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--snapshot", help="đường dẫn snapshot agent cuối (tương đối gốc dự án)")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if a.write:
        if not a.snapshot or not (ROOT / a.snapshot).is_dir():
            ap.error("--write needs --snapshot <existing snapshot dir>")
        data = collect(a.snapshot)
        data["note"] = a.note
        LOCK.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"locked {len(data['graders'])} graders, {len(data['tasks'])} task files, snapshot {a.snapshot}; combined {data['combined_sha256'][:16]}…", file=sys.stderr)
        return 0
    problems = verify()
    for p in problems:
        print("LOCK MISMATCH:", p, file=sys.stderr)
    print("lock OK" if not problems else f"{len(problems)} mismatch(es)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
