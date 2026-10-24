import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # gốc dự án
for p in (ROOT,):                                    # `import eval...`
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: cần native-RAG/.venv, chroma_db hoặc mạng (bỏ qua bằng -m 'not integration')")
