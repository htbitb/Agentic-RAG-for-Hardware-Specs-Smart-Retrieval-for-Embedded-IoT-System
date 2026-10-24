"""Helper: chạy đoạn Python trong native-RAG/.venv (langchain/chroma) từ pytest của eval."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RAG = ROOT / "native-RAG"
RAG_PY = RAG / ".venv" / "bin" / "python"

needs_rag_venv = pytest.mark.skipif(not RAG_PY.exists(), reason="native-RAG/.venv không tồn tại")


def run_in_rag_venv(code: str, env: dict | None = None, timeout: int = 120) -> str:
    import os

    e = {**os.environ, **(env or {})}
    r = subprocess.run([str(RAG_PY), "-c", code], capture_output=True, text=True, timeout=timeout, env=e, cwd=str(RAG))
    if r.returncode != 0:
        raise RuntimeError(f"rag venv script failed:\n{r.stderr[-2000:]}")
    return r.stdout
