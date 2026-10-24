"""Đóng băng `agent/` thành một snapshot bất biến (`snapshots/<tên>/`) kèm SNAPSHOT.md.

    agent/.venv/bin/python -m eval.tools.freeze_snapshot --dst snapshots/agent_p1 --title "Agent P1 (S2D)" --reason "..."

Quy tắc loại trừ (giống agent_v1): `.env*`, `.venv*`, `logs/`, `data/memory.sqlite`, `workspace_out/`, `__pycache__`, `.pytest_cache`,
`.DS_Store`, `*.pyc`; thêm từ P4 (trạng thái chạy của runtime v3, không phải mã/dữ liệu): `data/board_state.sqlite`, `data/checkpoints.sqlite`
(kèm file phụ `-wal`/`-shm`/`-journal` của SQLite) và thư mục `data/traces/`. GIỮ `data/hw_specs.sqlite` và các file chỉ mục. Checksum .py dùng đúng công thức của `eval.run.snapshot_checksum`.
Từ chối ghi đè snapshot đã có và từ chối chạm vào `agent_v1`.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EXCLUDE_DIRS = {"logs", "workspace_out", "__pycache__", ".pytest_cache"}
STATE_FILES = ("memory.sqlite", "board_state.sqlite", "checkpoints.sqlite")      # chỉ bị loại khi nằm trực tiếp trong data/
SQLITE_SIDECARS = ("", "-wal", "-shm", "-journal")


def _excluded(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDE_DIRS or p.startswith(".venv") for p in parts):
        return True
    name = rel.name
    if name.startswith(".env") or name in {".DS_Store"} or name.endswith(".pyc"):
        return True
    if rel.parts[:2] == ("data", "traces"):
        return True
    return len(rel.parts) == 2 and rel.parts[0] == "data" and any(name == f + sfx for f in STATE_FILES for sfx in SQLITE_SIDECARS)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze(src: Path, dst: Path, *, title: str, reason: str, date: str | None = None, known_issues: list[str] | None = None) -> dict:
    from eval.run import snapshot_checksum, snapshot_data_checksum

    src, dst = Path(src), Path(dst)
    if dst.name == "agent_v1":
        raise ValueError("refusing to touch the frozen agent_v1 snapshot")
    if dst.exists():
        raise FileExistsError(f"{dst} already exists; snapshots are immutable (choose a new name)")
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if _excluded(rel):
            continue
        if p.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
        else:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)
    py = sorted(dst.rglob("*.py"), key=lambda p: "./" + p.relative_to(dst).as_posix())
    listing = "".join(f"{_sha(p)}  {p.relative_to(dst).as_posix()}\n" for p in py)
    data = sorted(p for p in dst.rglob("*") if p.is_file() and p.suffix in (".sqlite", ".npy"))
    data_listing = "".join(f"{_sha(p)}  {p.relative_to(dst).as_posix()}  ({p.stat().st_size:,} bytes)\n" for p in data)
    checksum = snapshot_checksum(dst)
    data_checksum = snapshot_data_checksum(dst)
    md = [f"# Snapshot — {title}, đóng băng", "",
          f"- **Ngày chụp:** {date or datetime.date.today().isoformat()}",
          f"- **Nguồn:** `{src.name}/` (gốc dự án)",
          f"- **Lý do:** {reason}",
          "- **Loại trừ:** `.env*`, `.venv*`, `logs/`, `data/memory.sqlite`, `data/board_state.sqlite`, `data/checkpoints.sqlite`, `data/traces/`, "
          "`workspace_out/`, `__pycache__/`, `.pytest_cache/`, `.DS_Store`. "
          "Không chứa bí mật. **Giữ** `data/hw_specs.sqlite` và các file chỉ mục.",
          "- **Cấu hình LLM/đường dẫn:** `config.py` đọc biến môi trường lúc import; snapshot không có `.env` → adapter nạp giá trị vào môi trường "
          "của tiến trình worker (không ghi/in giá trị)."]
    for k in known_issues or []:
        md.append(f"- **Known issue:** {k}")
    md += ["", "## SHA-256 các file dữ liệu", "", "```text", data_listing.rstrip(), "```", "", "## SHA-256 các file .py", "", "```text",
           listing.rstrip(), "```", "",
           "Checksum tổng (sha256 của đầu ra `find . -name '*.py' | sort | xargs shasum -a 256`, đường dẫn dạng `./...`; "
           f"`eval.run.snapshot_checksum()` tái tạo đúng giá trị này): {checksum}", "",
           "Checksum dữ liệu (sha256 của danh sách `sha256  ./đường-dẫn` các file *.sqlite, *.npy, sắp theo đường dẫn; "
           f"`eval.run.snapshot_data_checksum()` tái tạo; manifest ghim và ép khớp khi --resume): {data_checksum}", ""]
    (dst / "SNAPSHOT.md").write_text("\n".join(md), encoding="utf-8")
    return {"checksum": checksum, "data_checksum": data_checksum, "py_files": len(py), "data_files": len(data)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=str(ROOT / "agent"))
    ap.add_argument("--dst", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--known-issue", action="append", default=[])
    a = ap.parse_args(argv)
    info = freeze(Path(a.src), Path(a.dst), title=a.title, reason=a.reason, known_issues=a.known_issue)
    print(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
