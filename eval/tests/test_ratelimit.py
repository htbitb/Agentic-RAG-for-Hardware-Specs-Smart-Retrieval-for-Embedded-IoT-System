import json
import multiprocessing as mp
import threading
import time

import pytest

from eval.llm_cache import LLMCache, retry_delay_from
from eval.ratelimit import FileRateLimiter


def test_limiter_spaces_calls_by_the_minimum_interval(tmp_path):
    lim = FileRateLimiter(tmp_path / "rate.lock", rpm=600)         # 0.1 s
    t0 = time.time()
    for _ in range(5):
        lim.acquire()
    assert time.time() - t0 >= 0.39


def test_limiter_is_shared_by_threads(tmp_path):
    stamps = []
    lock = threading.Lock()

    def worker():
        lim = FileRateLimiter(tmp_path / "rate.lock", rpm=600)
        for _ in range(3):
            lim.acquire()
            with lock:
                stamps.append(time.time())

    ts = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(stamps) == 9 and min(gaps) >= 0.04       # dung sai cho máy đang tải


def _proc(path, q):
    lim = FileRateLimiter(path, rpm=600)
    for _ in range(3):
        lim.acquire()
        q.put(time.time())


def test_limiter_is_shared_by_processes(tmp_path):
    q = mp.Queue()
    ps = [mp.Process(target=_proc, args=(str(tmp_path / "rate.lock"), q)) for _ in range(3)]
    [p.start() for p in ps]
    [p.join(20) for p in ps]
    stamps = sorted(q.get(timeout=5) for _ in range(9))
    assert min(b - a for a, b in zip(stamps, stamps[1:])) >= 0.04


def test_disabled_limiter_does_not_wait(tmp_path):
    lim = FileRateLimiter(tmp_path / "x.lock", rpm=0)
    t0 = time.time()
    for _ in range(50):
        lim.acquire()
    assert time.time() - t0 < 0.5


class Err(Exception):
    def __init__(self, msg, status_code=429, body=None):
        super().__init__(msg)
        self.status_code, self.body = status_code, body


def test_retry_delay_is_parsed_from_message_and_retryinfo():
    assert retry_delay_from(Err("Please retry in 30.999336651s.")) == pytest.approx(31.0, abs=0.01)
    body = [{"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}]}}]
    assert retry_delay_from(Err("quota", body=body)) == 17.0
    assert retry_delay_from(Err("boom", status_code=500)) is None


def test_backoff_respects_server_retry_delay(tmp_path):
    from types import SimpleNamespace

    from openai.types.chat import ChatCompletion

    ok = ChatCompletion.model_validate({"id": "x", "object": "chat.completion", "created": 1, "model": "m",
                                        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    answers = [Err("Please retry in 20.5s."), ok]

    def create(**kw):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    sleeps = []
    cache = LLMCache(tmp_path / "c.sqlite", "record", sleep=sleeps.append)
    cache.call(create, model="m", messages=[], temperature=0)
    assert sleeps == [pytest.approx(21.5, abs=0.1)]


def test_limiter_is_called_before_every_real_api_call_but_not_on_cache_hits(tmp_path):
    from openai.types.chat import ChatCompletion

    ok = ChatCompletion.model_validate({"id": "x", "object": "chat.completion", "created": 1, "model": "m",
                                        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    calls = {"api": 0, "acquire": 0}

    class Lim:
        def acquire(self):
            calls["acquire"] += 1

    def create(**kw):
        calls["api"] += 1
        return ok

    cache = LLMCache(tmp_path / "c.sqlite", "record", limiter=Lim())
    cache.call(create, model="m", messages=[{"role": "user", "content": "q"}], temperature=0)
    cache.call(create, model="m", messages=[{"role": "user", "content": "q"}], temperature=0)      # hit
    assert calls == {"api": 1, "acquire": 1}
