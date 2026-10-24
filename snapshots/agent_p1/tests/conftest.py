"""Đưa thư mục `agent/` lên sys.path để test import `ingestion.*`, `mcp_servers.*`, `agent.*` như lúc chạy thật."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# Mọi test chạy agent đều dùng DB/log tạm, không đụng data/memory.sqlite hay logs/audit.jsonl thật.
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="hwspec_test_")
os.environ.setdefault("MEMORY_DB", os.path.join(_TMP, "memory.sqlite"))
os.environ.setdefault("AUDIT_LOG", os.path.join(_TMP, "audit.jsonl"))
os.environ.setdefault("SANDBOX_DIR", os.path.join(_TMP, "sandbox"))
os.environ.setdefault("LLM_API_KEY", "")
