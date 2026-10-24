"""Đóng băng `agent/hwmodel/` (+ dữ liệu) thành `eval/vendor/hwmodel/` + `eval/vendor/hwmodel_data/` cho grader (D19).

    agent/.venv/bin/python -m eval.tools.freeze_hwmodel --reason "..."          # tạo mới (từ chối ghi đè)
    eval/.venv/bin/python  -m eval.tools.freeze_hwmodel --check                 # agent/hwmodel có lệch bản vendor không? (mã thoát 1 nếu lệch)

Grader CHỈ import bản vendor, không import `agent/hwmodel`, để lỗi simulator của agent (P4 tự kiểm bằng simulator) không "tự khớp" với lỗi của bộ chấm.
Lỗi simulator phát hiện sau P2 ⇒ sửa `agent/hwmodel`, chạy lại `--force`, chấm lại mọi hệ và ghi vào `post_run_changes` của manifest.
Chỉ sao chép *.py (trừ `AGENT_ONLY`: board_state.py, drc.py), `hw_specs.sqlite` và `svd_attrs.json` (không chép chỉ mục văn bản, `.env`, bộ nhớ…).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_FILES = ("hw_specs.sqlite", "svd_attrs.json")
# P3: module chỉ dành cho agent (Board State, DRC) — grader không import chúng nên KHÔNG đóng băng và không tính là "lệch" (chỉ khớp ở gốc gói).
AGENT_ONLY = ("board_state.py", "drc.py")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _py_files(root: Path) -> list[Path]:
    return sorted((p for p in Path(root).rglob("*.py") if "__pycache__" not in p.parts), key=lambda p: "./" + p.relative_to(root).as_posix())


def _src_files(hwmodel_dir: Path) -> list[Path]:
    """File .py của agent/hwmodel được đóng băng (trừ module AGENT_ONLY ở gốc gói)."""
    return [p for p in _py_files(hwmodel_dir) if p.relative_to(hwmodel_dir).as_posix() not in AGENT_ONLY]


def vendor_checksum(vendor_pkg: Path) -> str:
    """sha256 của danh sách `sha256  ./đường-dẫn` các file .py (sắp theo đường dẫn)."""
    listing = "".join(f"{_sha(p)}  ./{p.relative_to(vendor_pkg).as_posix()}\n" for p in _py_files(vendor_pkg))
    return hashlib.sha256(listing.encode()).hexdigest()


def data_checksum(data_dir: Path) -> str:
    listing = "".join(f"{_sha(Path(data_dir) / n)}  ./{n}\n" for n in DATA_FILES)
    return hashlib.sha256(listing.encode()).hexdigest()


def recorded_checksum(vendor_pkg: Path, key: str = "hwmodel_vendor_sha256") -> str | None:
    md = (Path(vendor_pkg) / "VENDOR.md").read_text(encoding="utf-8")
    m = re.search(rf"^{key}: ([0-9a-f]{{64}})\s*$", md, re.M)
    return m.group(1) if m else None


def verify(vendor_root: Path) -> bool:
    """Bản vendor còn nguyên vẹn so với VENDOR.md (cả mã lẫn dữ liệu)?"""
    pkg, data = Path(vendor_root) / "hwmodel", Path(vendor_root) / "hwmodel_data"
    return (vendor_checksum(pkg) == recorded_checksum(pkg)
            and data_checksum(data) == recorded_checksum(pkg, "hwmodel_data_sha256"))


def drift(hwmodel_dir: Path, data_dir: Path, vendor_root: Path) -> list[str]:
    out: list[str] = []
    pkg = Path(vendor_root) / "hwmodel"
    src = {p.relative_to(hwmodel_dir).as_posix(): p for p in _src_files(hwmodel_dir)}
    dst = {p.relative_to(pkg).as_posix(): p for p in _py_files(pkg)}
    for rel in sorted(src.keys() | dst.keys()):
        if rel not in dst:
            out.append(f"new in agent: {rel}")
        elif rel not in src:
            out.append(f"removed from agent: {rel}")
        elif _sha(src[rel]) != _sha(dst[rel]):
            out.append(f"changed: {rel}")
    for n in DATA_FILES:
        if _sha(Path(data_dir) / n) != _sha(Path(vendor_root) / "hwmodel_data" / n):
            out.append(f"changed data: {n}")
    return out


def freeze(hwmodel_dir: Path, data_dir: Path, vendor_root: Path, *, reason: str, date: str | None = None, force: bool = False,
           p1_snapshot_data: Path | None = None) -> dict:
    hwmodel_dir, data_dir, vendor_root = Path(hwmodel_dir), Path(data_dir), Path(vendor_root)
    pkg, vdata = vendor_root / "hwmodel", vendor_root / "hwmodel_data"
    if (pkg.exists() or vdata.exists()) and not force:
        raise FileExistsError(f"{pkg} already exists; the vendor copy is frozen (use --force to re-freeze deliberately)")
    for d in (pkg, vdata):
        if d.exists():
            shutil.rmtree(d)
    for p in _src_files(hwmodel_dir):
        rel = p.relative_to(hwmodel_dir)
        (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, pkg / rel)
    vdata.mkdir(parents=True, exist_ok=True)
    for n in DATA_FILES:
        shutil.copy2(data_dir / n, vdata / n)
    vsum, dsum = vendor_checksum(pkg), data_checksum(vdata)
    listing = "\n".join(f"{_sha(p)}  {p.relative_to(pkg).as_posix()}" for p in _py_files(pkg))
    dlisting = "\n".join(f"{_sha(vdata / n)}  {n}  ({(vdata / n).stat().st_size:,} bytes)" for n in DATA_FILES)
    snap_note = ""
    if p1_snapshot_data is not None and (Path(p1_snapshot_data) / "hw_specs.sqlite").exists():
        same = _sha(Path(p1_snapshot_data) / "hw_specs.sqlite") == _sha(vdata / "hw_specs.sqlite")
        snap_note = (f"- **Đối chiếu snapshot P1:** `hw_specs.sqlite` {'TRÙNG' if same else 'KHÁC'} `snapshots/agent_p1/data/hw_specs.sqlite` "
                     f"(sha256 {_sha(Path(p1_snapshot_data) / 'hw_specs.sqlite')}).")
    md = ["# Bản đóng băng của `hwmodel` dành cho grader (D19)", "",
          f"- **Ngày chụp:** {date or datetime.date.today().isoformat()}",
          f"- **Nguồn:** `agent/hwmodel/` (mã) và `agent/data/{{{', '.join(DATA_FILES)}}}` (dữ liệu), gốc dự án.",
          f"- **Lý do:** {reason}",
          "- **Quy tắc:** KHÔNG sửa tay các file ở đây. Grader (`eval/graders/functional_sim.py`, `compile.py`) chỉ import bản này, **không** import `agent/hwmodel`. "
          "Lỗi simulator phát hiện sau P2 ⇒ sửa `agent/hwmodel`, đóng băng lại (`--force`), chấm lại mọi hệ và ghi vào `post_run_changes` của manifest.",
          "- **Kiểm lệch:** `eval/.venv/bin/python -m eval.tools.freeze_hwmodel --check`.",
          "- **Phụ thuộc ngoài:** `pycparser>=3.0` (Python) và `clang` (hệ thống; thiếu clang ⇒ `compile_check` trả `skipped`, `analyze_c_code` báo `no_toolchain`).",
          snap_note, "",
          "## SHA-256 các file .py", "", "```text", listing, "```", "", "## SHA-256 dữ liệu (`../hwmodel_data/`)", "", "```text", dlisting, "```", "",
          "Checksum mã (sha256 của danh sách `sha256  ./đường-dẫn`, sắp theo đường dẫn; manifest eval ghi giá trị này):", "",
          f"hwmodel_vendor_sha256: {vsum}", "",
          "Checksum dữ liệu (cùng công thức trên `hw_specs.sqlite` và `svd_attrs.json`):", "",
          f"hwmodel_data_sha256: {dsum}", ""]
    (pkg / "VENDOR.md").write_text("\n".join(md), encoding="utf-8")
    return {"vendor_sha256": vsum, "data_sha256": dsum, "py_files": len(_py_files(pkg))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=str(ROOT / "agent" / "hwmodel"))
    ap.add_argument("--data", default=str(ROOT / "agent" / "data"))
    ap.add_argument("--dst", default=str(ROOT / "eval" / "vendor"))
    ap.add_argument("--reason", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        diff = drift(Path(a.src), Path(a.data), Path(a.dst))
        ok = verify(Path(a.dst))
        print("vendor integrity:", "OK" if ok else "TAMPERED")
        print("drift vs agent/hwmodel:", "none" if not diff else "\n  " + "\n  ".join(diff))
        return 0 if ok and not diff else 1
    if not a.reason:
        ap.error("--reason is required")
    info = freeze(Path(a.src), Path(a.data), Path(a.dst), reason=a.reason, force=a.force,
                  p1_snapshot_data=ROOT / "snapshots" / "agent_p1" / "data")
    print(info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
