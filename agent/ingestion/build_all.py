"""Dựng toàn bộ dữ liệu P1 từ corpus/ bằng một lệnh, đúng thứ tự: SVD -> chân/AF -> giới hạn -> text index.

    agent/.venv/bin/python -m ingestion.build_all --fresh        # xoá DB/index cũ rồi dựng lại (~1.5 phút, nhiều nhất là embedding)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import hwdb, limits_curate, pinout_extract, svd_ingest
from .text_index import DEFAULT_DB as INDEX_DB, DEFAULT_EMB as INDEX_EMB


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(hwdb.DEFAULT_DB))
    ap.add_argument("--fresh", action="store_true", help="xoá hw_specs.sqlite (và text index nếu dựng) trước khi dựng")
    ap.add_argument("--skip-index", action="store_true", help="bỏ qua text index (chunk + embedding)")
    a = ap.parse_args(argv)
    if a.fresh:
        Path(a.db).unlink(missing_ok=True)
        if not a.skip_index:
            INDEX_DB.unlink(missing_ok=True)
            INDEX_EMB.unlink(missing_ok=True)
    for name, step in (("svd_ingest", svd_ingest.main), ("pinout_extract", pinout_extract.main), ("limits_curate", limits_curate.main)):
        print(f"== {name}")
        rc = step(["--db", a.db])
        if rc:
            return rc
    if not a.skip_index:
        from . import build_text_index
        print("== build_text_index")
        return build_text_index.main([])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
