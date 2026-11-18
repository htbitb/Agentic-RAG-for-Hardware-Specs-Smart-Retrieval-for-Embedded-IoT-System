"""Lớp tương thích: header_gen nằm ở `hwmodel/header_gen.py` (để bản vendor của eval tự đầy đủ). Chạy:

    agent/.venv/bin/python -m ingestion.header_gen --out <thư mục>
"""
from hwmodel.header_gen import *          # noqa: F401,F403
from hwmodel.header_gen import main

if __name__ == "__main__":
    raise SystemExit(main())
