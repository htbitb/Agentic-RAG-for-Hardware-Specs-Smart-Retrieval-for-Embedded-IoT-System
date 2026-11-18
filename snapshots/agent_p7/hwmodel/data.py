"""Vị trí dữ liệu của hwmodel. Có thể ghi đè bằng biến môi trường (grader dùng bản vendor/đóng băng, D19)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
DATA_DIR_ENV = "HWMODEL_DATA_DIR"


def data_dir() -> Path:
    """Thư mục chứa hw_specs.sqlite + svd_attrs.json: $HWMODEL_DATA_DIR hoặc `<agent>/data`."""
    raw = os.environ.get(DATA_DIR_ENV, "").strip()
    return Path(raw) if raw else PKG_DIR.parent / "data"


def default_db() -> Path:
    return data_dir() / "hw_specs.sqlite"


def default_attrs() -> Path:
    return data_dir() / "svd_attrs.json"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
