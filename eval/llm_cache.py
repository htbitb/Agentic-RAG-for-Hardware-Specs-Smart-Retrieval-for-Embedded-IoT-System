"""Cache LLM record/replay cho S0 và S2 (bọc `client.chat.completions.create`) + retry lỗi hạ tầng.

Khoá = sha256(model, messages, tools, temperature, seed). `seed` gồm cả seed gửi lên API (nếu có) lẫn seed
của lần chạy hiện tại (`cache.set_seed`) nên mỗi seed được ghi nhận độc lập kể cả khi endpoint (Gemini) bỏ qua seed.

Chế độ:  off (không cache) | record (đọc-xuyên: hit dùng lại, miss gọi API rồi lưu) | replay (chỉ cache; miss -> CacheMiss).
Lỗi hạ tầng (429, 5xx, timeout, mất kết nối) được retry với backoff 2,4,8... giây; hết lượt -> InfraError
(runner gắn nhãn `infra`, không tính vào TSR nhưng đếm trong report).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from openai.types.chat import ChatCompletion


def _load_errors():
    """Nạp llm_errors.py (cùng thư mục) theo đường dẫn: worker S2 (`python -I`) nạp file này độc lập, không có package `eval`."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("eval_llm_errors", Path(__file__).with_name("llm_errors.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_errs = _load_errors()
TRANSIENT_STATUS, FATAL_STATUS, FATAL_NAMES, TRANSIENT_NAMES = (_errs.TRANSIENT_STATUS, _errs.FATAL_STATUS,
                                                                 _errs.FATAL_NAMES, _errs.TRANSIENT_NAMES)
MAX_RETRY_WAIT = _errs.MAX_RETRY_WAIT
_status, is_transient, quota_wait, is_fatal, classify_exception, retry_delay_from = (
    _errs.status_of, _errs.is_transient, _errs.quota_wait, _errs.is_fatal, _errs.classify_exception, _errs.retry_delay_from)


def _block_reason(resp) -> str:
    """Gateway Gemini trả 200 không có `choices` khi bộ lọc của Gemini chặn prompt: ghi lý do vào thông báo để phân biệt với sự cố mạng."""
    extra = getattr(resp, "model_extra", None) or {}
    feedback = (extra.get("response") or {}).get("promptFeedback") if isinstance(extra.get("response"), dict) else None
    return f" [provider blocked the prompt: {feedback.get('blockReason')}]" if isinstance(feedback, dict) and feedback.get("blockReason") else ""


class EmptyResponse(Exception):
    """Gateway trả 200 nhưng không có `choices` (phản hồi rỗng): coi như lỗi 502 tạm thời để retry."""
    status_code = 502


class CacheMiss(Exception):
    """Chế độ replay nhưng lời gọi LLM không có trong cache."""


class InfraError(Exception):
    """Lỗi hạ tầng API (429/5xx/timeout) vẫn còn sau khi đã retry."""


class FatalLLMError(Exception):
    """Khoá sai/hết hạn/không đủ quyền (401/403, 400 API_KEY_INVALID của Gemini) hoặc hết hạn mức ngày: dừng cả lượt chạy."""


def cache_key(model, messages, tools, temperature, seed) -> str:
    payload = json.dumps([model, messages, tools, temperature, seed], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_FINISH_REASONS = {"stop", "length", "tool_calls", "content_filter", "function_call"}


def _validate_completion(hit: dict) -> ChatCompletion:
    """Phát lại một phản hồi đã lưu. Gateway/Gemini đôi khi trả `finish_reason` ngoài danh sách của SDK (vd 'malformed_function_call'): lúc chạy thật
    SDK vẫn trả về đối tượng, nhưng `model_validate` lúc replay từ chối ⇒ run replay hỏng một cách giả (pilot P5: 3/114). Giá trị lạ được thay bằng 'stop'
    CHỈ khi validate thất bại; runtime không đọc `finish_reason` (nội dung và tool_calls mới quyết định)."""
    try:
        return ChatCompletion.model_validate(hit)
    except Exception:
        fixed = json.loads(json.dumps(hit))
        for ch in fixed.get("choices") or []:
            if ch.get("finish_reason") not in _FINISH_REASONS:
                ch["finish_reason"] = "stop"
        return ChatCompletion.model_validate(fixed)


class LLMCache:
    def __init__(self, path, mode: str = "off", sleep=time.sleep, max_retries: int = 5, limiter=None):
        if mode not in ("off", "record", "replay"):
            raise ValueError(f"cache mode must be off|record|replay, got {mode!r}")
        self.path, self.mode, self.sleep, self.max_retries = Path(path), mode, sleep, max_retries
        self.limiter = limiter
        self.seed = 0
        self.infra_errors: list[str] = []
        self.retries = 0
        self.hits = self.misses = 0
        self._lock = threading.Lock()
        self._con: sqlite3.Connection | None = None

    def set_seed(self, seed: int) -> None:
        self.seed = int(seed)

    # ------------------------------------------------------------------ storage
    def _connect(self, create: bool) -> sqlite3.Connection | None:
        if self._con is None:
            if not create and not self.path.exists():
                return None
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._con = sqlite3.connect(str(self.path), check_same_thread=False, timeout=60)
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("CREATE TABLE IF NOT EXISTS llm(key TEXT PRIMARY KEY, response TEXT NOT NULL, created REAL)")
            self._con.commit()
        return self._con

    def get(self, key: str) -> dict | None:
        with self._lock:
            con = self._connect(create=False)
            if con is None:
                return None
            row = con.execute("SELECT response FROM llm WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def delete(self, key: str) -> None:
        with self._lock:
            con = self._connect(create=False)
            if con is not None:
                con.execute("DELETE FROM llm WHERE key=?", (key,))
                con.commit()

    def put(self, key: str, response: dict) -> None:
        with self._lock:
            con = self._connect(create=True)
            con.execute("INSERT OR REPLACE INTO llm VALUES (?,?,?)", (key, json.dumps(response, ensure_ascii=False), time.time()))
            con.commit()

    # --------------------------------------------------------------------- calls
    def call(self, create, **kw):
        if self.mode == "off":
            return self._with_retry(create, kw)
        key = cache_key(kw.get("model"), kw.get("messages"), kw.get("tools"), kw.get("temperature"),
                        [kw.get("seed"), self.seed])
        hit = self.get(key)
        if hit is not None and not hit.get("choices"):
            self.delete(key)                       # mục cũ lưu nhầm một phản hồi rỗng (vd Gemini chặn prompt: promptFeedback.blockReason): không phải phản hồi hợp lệ để replay
            hit = None
        if hit is not None:
            self.hits += 1
            return _validate_completion(hit)
        self.misses += 1
        if self.mode == "replay":
            raise CacheMiss(f"LLM call {key[:12]} not in cache")
        resp = self._with_retry(create, kw)
        self.put(key, resp.model_dump(mode="json"))
        return resp

    def _with_retry(self, create, kw):
        attempt = 0
        while True:
            try:
                if self.limiter is not None:
                    self.limiter.acquire()
                resp = create(**kw)
                if not getattr(resp, "choices", None):
                    raise EmptyResponse("empty response from the API (no choices)" + _block_reason(resp))
                return resp
            except Exception as exc:
                if is_fatal(exc):
                    wait = quota_wait(exc)
                    why = f"quota exhausted (server asks to wait {wait:.0f}s) " if wait is not None else ""
                    raise FatalLLMError(f"{why}{type(exc).__name__} status={_status(exc)}: {str(exc)[:160]}") from exc
                if not is_transient(exc):
                    raise
                if attempt >= self.max_retries:
                    msg = f"{type(exc).__name__} status={_status(exc)}: {str(exc)[:160]}"
                    self.infra_errors.append(msg)
                    raise InfraError(msg) from exc
                attempt += 1
                self.retries += 1
                hinted = retry_delay_from(exc)
                self.sleep(max(2 ** attempt, hinted + 1.0) if hinted else 2 ** attempt)


def wrap_client(client, cache: LLMCache):
    """Thay `client.chat.completions.create` bằng bản đi qua cache (patch trên instance)."""
    original = client.chat.completions.create

    def create(**kw):
        return cache.call(original, **kw)

    client.chat.completions.create = create
    return client
