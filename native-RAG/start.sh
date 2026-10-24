#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# 1. Tạo virtualenv & cài thư viện nếu chưa có
if [ ! -x ".venv/bin/python" ]; then
    echo "[start.sh] Creating Python virtual environment (.venv)..."
    if command -v uv >/dev/null 2>&1; then
        uv venv --python 3.11 .venv
        uv pip install --python .venv/bin/python -r requirements.txt "transformers<5"
    else
        python3 -m venv .venv
        .venv/bin/pip install --upgrade pip
        .venv/bin/pip install -r requirements.txt "transformers<5"
    fi
fi

# 2. Hỗ trợ flag --ingest / --reset hoặc tự động ingest nếu chưa có chroma_db
if [ "${1:-}" = "--ingest" ] || [ "${1:-}" = "--reset" ]; then
    shift
    .venv/bin/python ingest.py
fi

if [ ! -d "chroma_db" ]; then
    echo "[start.sh] Index not found in ./chroma_db. Running ingest.py..."
    .venv/bin/python ingest.py
fi

# 3. Chạy ask.py (truyền câu hỏi nếu có, hoặc vào chế độ interactive)
exec .venv/bin/python ask.py "$@"
