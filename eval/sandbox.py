"""Nạp bản VENDOR đóng băng của `hwmodel` (eval/vendor/hwmodel + hwmodel_data) cho grader (D19).

* Không bao giờ import `agent/hwmodel`: bản vendor được nạp dưới tên `hwmodel_vendored` (không đụng tên `hwmodel` nếu tiến trình có cả hai).
* Kiểm toàn vẹn trước khi nạp: sha256 mã và dữ liệu phải khớp VENDOR.md; lệch ⇒ RuntimeError (sửa `agent/hwmodel` rồi đóng băng lại).
* Dữ liệu (SQLite + sidecar) lấy từ `eval/vendor/hwmodel_data`, không từ `agent/data`.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "eval" / "vendor"
PKG_NAME = "hwmodel_vendored"
_STATE: SimpleNamespace | None = None


def load() -> SimpleNamespace:
    global _STATE
    if _STATE is not None:
        return _STATE
    from eval.tools.freeze_hwmodel import data_checksum, recorded_checksum, vendor_checksum

    pkg, data_dir = VENDOR / "hwmodel", VENDOR / "hwmodel_data"
    if not (pkg / "VENDOR.md").is_file():
        raise RuntimeError(f"vendored hwmodel not found at {pkg}: run `python -m eval.tools.freeze_hwmodel --reason ...`")
    got_code, got_data = vendor_checksum(pkg), data_checksum(data_dir)
    if got_code != recorded_checksum(pkg) or got_data != recorded_checksum(pkg, "hwmodel_data_sha256"):
        raise RuntimeError("the vendored hwmodel (eval/vendor) does not match VENDOR.md: it was modified after freezing (D19). "
                           "Fix agent/hwmodel and re-freeze with eval.tools.freeze_hwmodel --force")
    for name in [n for n in sys.modules if n == PKG_NAME or n.startswith(PKG_NAME + ".")]:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(PKG_NAME, pkg / "__init__.py", submodule_search_locations=[str(pkg)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = mod
    spec.loader.exec_module(mod)
    data = importlib.import_module(f"{PKG_NAME}.data")
    data.data_dir = lambda: data_dir                      # dữ liệu cũng là bản đóng băng
    _STATE = SimpleNamespace(
        codeparse=importlib.import_module(f"{PKG_NAME}.codeparse"), sim=importlib.import_module(f"{PKG_NAME}.sim"),
        compile_check=importlib.import_module(f"{PKG_NAME}.compile_check"), gpio=importlib.import_module(f"{PKG_NAME}.periph.gpio"), data=data, vendor_sha256=got_code, data_sha256=got_data)
    return _STATE


def vendor_hashes() -> dict:
    """Cho manifest: hash mã + dữ liệu của bản vendor (không nạp mã)."""
    from eval.tools.freeze_hwmodel import data_checksum, vendor_checksum
    return {"hwmodel_vendor_sha256": vendor_checksum(VENDOR / "hwmodel"), "hwmodel_data_sha256": data_checksum(VENDOR / "hwmodel_data")}
