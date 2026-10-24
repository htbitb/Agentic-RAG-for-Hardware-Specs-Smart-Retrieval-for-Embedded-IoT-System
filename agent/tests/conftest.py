"""Đưa thư mục `agent/` lên sys.path để test import `ingestion.*`, `mcp_servers.*`, `agent.*` như lúc chạy thật."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# Mọi test chạy agent đều dùng DB/log tạm, không đụng data/memory.sqlite hay logs/audit.jsonl thật.
import os
import tempfile

# D22: không nạp .env trong test (sự cố P1: khoá thật trong .env ghi đè biến rỗng => test gọi Gemini thật).
# Phải đặt TRƯỚC khi bất kỳ test nào import `config`.
os.environ["AGENT_DOTENV"] = "0"

_TMP = tempfile.mkdtemp(prefix="hwspec_test_")
os.environ.setdefault("MEMORY_DB", os.path.join(_TMP, "memory.sqlite"))
os.environ.setdefault("BOARD_STATE_DB", os.path.join(_TMP, "board_state.sqlite"))
os.environ.setdefault("AGENT_CHECKPOINT_DB", os.path.join(_TMP, "checkpoints.sqlite"))
os.environ.setdefault("AUDIT_LOG", os.path.join(_TMP, "audit.jsonl"))
os.environ.setdefault("SANDBOX_DIR", os.path.join(_TMP, "sandbox"))
for _k in ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
    os.environ[_k] = ""                 # ép rỗng (không setdefault): khoá trong shell cũng không được lọt vào test


# D22: chốt chặn mạng. Mọi kết nối/DNS tới máy khác loopback đều lỗi => một test lỡ gọi LLM thật sẽ ĐỎ thay vì tốn hạn mức.
import socket as _socket

_LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}
_real_getaddrinfo = _socket.getaddrinfo
_real_connect = _socket.socket.connect
_real_connect_ex = _socket.socket.connect_ex


def _is_local(address) -> bool:
    if isinstance(address, (str, bytes)):          # AF_UNIX
        return True
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    return host in _LOOPBACK or str(host).startswith("127.")


def _blocked(what: str):
    return RuntimeError(f"network access is blocked in agent tests (D22): {what}")


def _guard_getaddrinfo(host, *a, **k):
    if not _is_local((host,)):
        raise _blocked(f"getaddrinfo({host!r})")
    return _real_getaddrinfo(host, *a, **k)


def _guard_connect(self, address):
    if not _is_local(address):
        raise _blocked(f"connect({address!r})")
    return _real_connect(self, address)


def _guard_connect_ex(self, address):
    if not _is_local(address):
        raise _blocked(f"connect_ex({address!r})")
    return _real_connect_ex(self, address)


_socket.getaddrinfo = _guard_getaddrinfo
_socket.socket.connect = _guard_connect
_socket.socket.connect_ex = _guard_connect_ex
