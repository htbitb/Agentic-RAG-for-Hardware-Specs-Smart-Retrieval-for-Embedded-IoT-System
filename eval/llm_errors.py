"""Phân loại lỗi LLM DÙNG CHUNG cho S0/S2 (eval/llm_cache.py) và S1 (native-RAG/eval_adapter.py).

'fatal' (dừng cả lượt chạy) | 'infra' (tạm thời, retry; không tính vào TSR) | 'error' (lỗi của hệ được đo).
Chỉ dùng thư viện chuẩn và nạp được theo đường dẫn (worker S2 chạy `python -I`, S1 chạy trong venv riêng), nên
không import gì từ package `eval`.
"""
from __future__ import annotations

import json
import re

TRANSIENT_STATUS = {408, 409, 425, 429}
FATAL_STATUS = {401, 403}
FATAL_NAMES = {"AuthenticationError", "PermissionDeniedError"}
MAX_RETRY_WAIT = 300.0        # server đòi chờ lâu hơn (vd 16 giờ khi hết hạn mức NGÀY) -> không ngủ, dừng cả lượt chạy
TRANSIENT_NAMES = {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError", "ReadTimeout",
                   "ConnectTimeout", "TimeoutError", "ConnectError", "RemoteProtocolError"}
# Endpoint OpenAI-compatible của Gemini trả HTTP 400 (không phải 401/403) cho khoá sai/hết hạn
BAD_KEY_MARKERS = ("api_key_invalid", "api key not valid", "api key expired")


def status_of(exc) -> int | None:
    s = getattr(exc, "status_code", None)
    if s is None:
        s = getattr(getattr(exc, "response", None), "status_code", None)
    return s if isinstance(s, int) else None


def _blob(exc) -> str:
    return f"{exc} {json.dumps(getattr(exc, 'body', None), default=str)}"


def is_locked_db(exc) -> bool:
    """sqlite3 / sqlalchemy OperationalError 'database is locked' (cache dùng chung giữa các tiến trình): tạm thời."""
    return type(exc).__name__ == "OperationalError" and "database is locked" in str(exc).lower()


def is_html_error_page(exc) -> bool:
    """Gateway/proxy trả một TRANG HTML (vd 'Loading...' kèm 404) thay vì lỗi JSON của API: lỗi hạ tầng tạm thời, không phải lỗi của hệ được đo."""
    return "<!doctype html" in str(exc).lower()[:400] or "<html" in str(exc).lower()[:400]


def is_transient(exc) -> bool:
    s = status_of(exc)
    if s is not None and (s in TRANSIENT_STATUS or s >= 500):
        return True
    if is_html_error_page(exc):
        return True
    return type(exc).__name__ in TRANSIENT_NAMES or is_locked_db(exc)


def is_bad_key(exc) -> bool:
    blob = _blob(exc).lower()
    return any(m in blob for m in BAD_KEY_MARKERS)


def retry_delay_from(exc) -> float | None:
    """Thời gian chờ do server gợi ý (Gemini: 'Please retry in 30.99s' hoặc RetryInfo.retryDelay), nếu có."""
    m = re.search(r"retry in ([0-9.]+)s", str(exc))
    if m:
        return float(m.group(1))
    m = re.search(r"""retryDelay['"]?:\s*['"]([0-9.]+)s['"]""", _blob(exc))
    return float(m.group(1)) if m else None


def quota_wait(exc) -> float | None:
    """Số giây server đòi chờ nếu đây là hết hạn mức ngày hoặc phải chờ quá MAX_RETRY_WAIT; ngược lại None."""
    delay = retry_delay_from(exc)
    if "PerDay" in _blob(exc):
        return delay if delay is not None else float("inf")
    return delay if delay is not None and delay > MAX_RETRY_WAIT else None


def is_fatal(exc) -> bool:
    return (status_of(exc) in FATAL_STATUS or type(exc).__name__ in FATAL_NAMES or is_bad_key(exc)
            or quota_wait(exc) is not None)


def classify_exception(exc) -> str:
    if is_fatal(exc):
        return "fatal"
    return "infra" if is_transient(exc) else "error"
