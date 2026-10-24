#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# 1. Tự động khởi tạo .env từ .env.example.txt nếu chưa có
if [ ! -f ".env" ]; then
  if [ -f ".env.example.txt" ]; then
    cp ".env.example.txt" ".env"
    echo "[start.sh] Đã tạo file .env từ .env.example.txt"
  fi
fi

# 2. Tuỳ chọn --install: tạo virtualenv và cài đặt requirements.txt
if [ "${1:-}" = "--install" ]; then
  shift
  if [ ! -d ".venv" ]; then
    echo "[start.sh] Đang tạo môi trường ảo .venv..."
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  echo "[start.sh] Đang cài đặt dependencies từ requirements.txt..."
  pip install -r requirements.txt
elif [ -d ".venv" ] && [ -x ".venv/bin/python" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [ -d "venv" ] && [ -x "venv/bin/python" ]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

# Tự động cài đặt openai vào .venv nếu LLM_API_KEY đã cấu hình nhưng thiếu thư viện openai
if ! "$PYTHON_BIN" -c "import config; assert not config.LLM_API_KEY or __import__('openai')" >/dev/null 2>&1; then
  echo "[start.sh] Phát hiện LLM_API_KEY đã cấu hình nhưng thiếu gói 'openai'. Đang chuẩn bị .venv..."
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  PYTHON_BIN="python3"
  pip install -q -r requirements.txt
fi
echo "============================================================"
echo "  Starting HW-Spec Agentic RAG Web Server"
echo "  Working directory : $ROOT_DIR"
echo "  Config file       : $ROOT_DIR/.env"
echo "============================================================"

exec "$PYTHON_BIN" -m ui.server "$@"
