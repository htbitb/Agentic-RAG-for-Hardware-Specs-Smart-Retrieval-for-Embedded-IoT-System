import json
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from eval.llm_cache import CacheMiss, InfraError, LLMCache, cache_key, wrap_client


def completion(content="hi", tool_calls=None, usage=(10, 3), extra_content=None):
    tc = None
    if tool_calls:
        tc = [{"id": "call_1", "type": "function", "function": {"name": t, "arguments": json.dumps(a)},
               **({"extra_content": extra_content} if extra_content else {})} for t, a in tool_calls]
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 1, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content, "tool_calls": tc}}],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}})


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


MSG = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]


def test_key_depends_on_every_component():
    base = dict(model="m", messages=MSG, tools=None, temperature=0.0, seed=0)
    k = cache_key(**base)
    assert k == cache_key(**base) and len(k) == 64
    for change in ({"model": "m2"}, {"messages": MSG + [{"role": "user", "content": "x"}]}, {"tools": [{"name": "t"}]},
                   {"temperature": 0.5}, {"seed": 1}):
        assert cache_key(**{**base, **change}) != k


def test_record_then_replay_roundtrip_including_tool_calls_and_extra(tmp_path):
    db = tmp_path / "c.sqlite"
    first = completion(content=None, tool_calls=[("get_register_bitfields", {"chip": "stm32g474"})], usage=(120, 9),
                       extra_content={"google": {"thought_signature": "sig"}})
    client = FakeClient([first])
    cache = LLMCache(db, "record")
    wrap_client(client, cache)
    r1 = client.chat.completions.create(model="m", messages=MSG, temperature=0.0)

    client2 = FakeClient([])                                   # replay không được gọi API
    cache2 = LLMCache(db, "replay")
    wrap_client(client2, cache2)
    r2 = client2.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert client2.calls == []
    assert r2.choices[0].message.tool_calls[0].function.name == "get_register_bitfields"
    assert r2.usage.prompt_tokens == 120 and r2.usage.completion_tokens == 9
    assert (r2.choices[0].message.tool_calls[0].model_extra or {}).get("extra_content") == {"google": {"thought_signature": "sig"}}
    assert r1.model_dump() == r2.model_dump()


def test_replay_miss_raises_and_never_calls_api(tmp_path):
    client = FakeClient([completion()])
    wrap_client(client, LLMCache(tmp_path / "c.sqlite", "replay"))
    with pytest.raises(CacheMiss):
        client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert client.calls == []


def test_record_mode_is_read_through(tmp_path):
    client = FakeClient([completion("A")])
    wrap_client(client, LLMCache(tmp_path / "c.sqlite", "record"))
    a = client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    b = client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert len(client.calls) == 1 and a.choices[0].message.content == b.choices[0].message.content == "A"


def test_each_run_seed_is_cached_independently_even_if_api_ignores_seed(tmp_path):
    client = FakeClient([completion("s0"), completion("s1")])
    cache = LLMCache(tmp_path / "c.sqlite", "record")
    wrap_client(client, cache)
    cache.set_seed(0)
    a = client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    cache.set_seed(1)
    b = client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert (a.choices[0].message.content, b.choices[0].message.content) == ("s0", "s1") and len(client.calls) == 2


def test_off_mode_passes_through_and_stores_nothing(tmp_path):
    db = tmp_path / "c.sqlite"
    client = FakeClient([completion("A"), completion("B")])
    wrap_client(client, LLMCache(db, "off"))
    client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert len(client.calls) == 2 and not db.exists()


class Rate(Exception):
    status_code = 429


class Boom(Exception):
    status_code = 503


def test_transient_infra_errors_are_retried_with_backoff(tmp_path):
    sleeps = []
    client = FakeClient([Rate("slow down"), Boom("oops"), completion("ok")])
    wrap_client(client, LLMCache(tmp_path / "c.sqlite", "record", sleep=sleeps.append))
    r = client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert r.choices[0].message.content == "ok" and len(client.calls) == 3 and sleeps == [2, 4]


def test_persistent_infra_error_raises_infra_error_and_is_recorded(tmp_path):
    cache = LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None, max_retries=2)
    client = FakeClient([Rate("a"), Rate("b"), Rate("c")])
    wrap_client(client, cache)
    with pytest.raises(InfraError):
        client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert len(client.calls) == 3 and cache.infra_errors and "429" in cache.infra_errors[0]


def test_non_transient_error_is_not_retried(tmp_path):
    client = FakeClient([ValueError("bad request payload")])
    wrap_client(client, LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None))
    with pytest.raises(ValueError):
        client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert len(client.calls) == 1


# ---- review finding 9: khoá sai/hết hạn/không đủ quyền phải dừng cả lượt chạy, không bị tính là lỗi hệ -------------
class Auth(Exception):
    status_code = 401


class Forbidden(Exception):
    status_code = 403


def test_auth_errors_are_fatal_and_not_retried(tmp_path):
    from eval.llm_cache import FatalLLMError

    for exc in (Auth("bad key"), Forbidden("no permission")):
        client = FakeClient([exc, completion()])
        wrap_client(client, LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None))
        with pytest.raises(FatalLLMError):
            client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
        assert len(client.calls) == 1


def test_classify_exception():
    from eval.llm_cache import classify_exception

    assert classify_exception(Auth("x")) == "fatal" and classify_exception(Forbidden("x")) == "fatal"
    assert classify_exception(Rate("x")) == "infra" and classify_exception(Boom("x")) == "infra"
    assert classify_exception(ValueError("x")) == "error"


# ---- hết hạn mức NGÀY của gói miễn phí (Gemini 500 req/ngày): dừng ngay, không ngủ hàng giờ ----------------------
class DailyQuota(Exception):
    status_code = 429
    body = [{"error": {"message": "You exceeded your current quota", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "57323s"}]}}]

    def __str__(self):
        return "Error code: 429 - Quota exceeded ... Please retry in 15h55m23.8s."


class LongWait(Exception):
    status_code = 429
    body = {"retryDelay": "3600s"}


def test_daily_quota_exhaustion_is_fatal_and_never_sleeps(tmp_path):
    from eval.llm_cache import FatalLLMError

    slept = []
    client = FakeClient([DailyQuota(), completion()])
    wrap_client(client, LLMCache(tmp_path / "c.sqlite", "record", sleep=slept.append))
    with pytest.raises(FatalLLMError, match="quota"):
        client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert slept == [] and len(client.calls) == 1


def test_server_asking_for_a_very_long_wait_is_fatal(tmp_path):
    from eval.llm_cache import FatalLLMError

    slept = []
    client = FakeClient([LongWait("slow down"), completion()])
    wrap_client(client, LLMCache(tmp_path / "c.sqlite", "record", sleep=slept.append))
    with pytest.raises(FatalLLMError, match="3600"):
        client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert slept == [] and len(client.calls) == 1


def test_short_server_delay_is_still_honoured_and_retried(tmp_path):
    class Short(Exception):
        status_code = 429
        body = {"retryDelay": "30s"}

    slept = []
    client = FakeClient([Short("rpm"), completion("fine")])
    wrap_client(client, LLMCache(tmp_path / "c.sqlite", "record", sleep=slept.append))
    r = client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert r.choices[0].message.content == "fine" and slept == [31.0]


def test_classify_exception_daily_quota_is_fatal():
    from eval.llm_cache import classify_exception

    assert classify_exception(DailyQuota()) == "fatal" and classify_exception(LongWait("x")) == "fatal"
    assert classify_exception(Rate("x")) == "infra"


# ---- post-P0 review #1: khoá Gemini sai/hết hạn trả HTTP 400 (không phải 401/403) -> cũng phải dừng cả lượt chạy -----
class BadRequest(Exception):
    status_code = 400


class BadKeyBody(BadRequest):
    body = [{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT",
                       "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}]


@pytest.mark.parametrize("exc", [
    BadRequest("Error code: 400 - [{'error': {'message': 'API key not valid. Please pass a valid API key.'}}]"),
    BadRequest("Error code: 400 - API key expired. Please renew the API key."),
    BadKeyBody("Error code: 400"),                                   # chỉ có reason API_KEY_INVALID trong body
])
def test_gemini_bad_key_400_is_fatal_and_not_retried(tmp_path, exc):
    from eval.llm_cache import FatalLLMError, classify_exception

    assert classify_exception(exc) == "fatal"
    slept = []
    client = FakeClient([exc, completion()])
    wrap_client(client, LLMCache(tmp_path / "c.sqlite", "record", sleep=slept.append))
    with pytest.raises(FatalLLMError):
        client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert len(client.calls) == 1 and slept == []


def test_other_4xx_stay_system_errors_and_locked_db_is_infra():
    from eval.llm_cache import classify_exception

    class NotFound(Exception):
        status_code = 404

    class OperationalError(Exception):          # sqlite3 / sqlalchemy cùng tên lớp
        pass

    assert classify_exception(BadRequest("Error code: 400 - prompt too long")) == "error"
    assert classify_exception(NotFound("models/x is not found")) == "error"
    assert classify_exception(OperationalError("database is locked")) == "infra"
    assert classify_exception(OperationalError("no such table: foo")) == "error"


# ---- gateway lỗi giả (P3): trang HTML 404 và phản hồi không có `choices` là lỗi hạ tầng tạm thời, không phải lỗi của hệ được đo
class FakeNotFound(Exception):
    status_code = 404

    def __init__(self, body):
        super().__init__(body)
        self.body = body


def test_html_error_page_from_the_gateway_is_transient_but_a_real_404_is_not():
    from eval import llm_errors as E

    html = FakeNotFound('<!DOCTYPE html>\n<html lang="vi"><head><title>Loading...</title></head></html>')
    assert E.is_transient(html) and E.classify_exception(html) == "infra"
    assert not E.is_transient(FakeNotFound('{"error": {"message": "model not found"}}')) and E.classify_exception(FakeNotFound("model not found")) == "error"


def test_html_404_is_retried_then_succeeds(tmp_path):
    html = FakeNotFound("<!DOCTYPE html><html><body>Loading...</body></html>")
    client = FakeClient([html, completion("ok")])
    cache = LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None)
    wrap_client(client, cache)
    r = client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    assert r.choices[0].message.content == "ok" and cache.retries == 1


def test_response_without_choices_is_retried_as_a_gateway_error(tmp_path):
    empty = SimpleNamespace(choices=None, usage=None, model_dump=lambda mode="json": {})
    client = FakeClient([empty, completion("ok")])
    cache = LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None)
    wrap_client(client, cache)
    assert client.chat.completions.create(model="m", messages=MSG, temperature=0.0).choices[0].message.content == "ok" and cache.retries == 1


def test_persistently_empty_responses_become_an_infra_error(tmp_path):
    empty = SimpleNamespace(choices=[], usage=None, model_dump=lambda mode="json": {})
    client = FakeClient([empty] * 6)
    cache = LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None, max_retries=5)
    wrap_client(client, cache)
    with pytest.raises(InfraError, match="empty"):
        client.chat.completions.create(model="m", messages=MSG, temperature=0.0)


def test_a_provider_block_is_named_in_the_infra_error(tmp_path):
    blocked = SimpleNamespace(choices=None, usage=None, model_dump=lambda mode="json": {},
                              model_extra={"response": {"promptFeedback": {"blockReason": "OTHER"}}})
    client = FakeClient([blocked] * 4)
    cache = LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None, max_retries=3)
    wrap_client(client, cache)
    with pytest.raises(InfraError, match=r"provider blocked the prompt: OTHER"):
        client.chat.completions.create(model="m", messages=MSG, temperature=0.0)


@pytest.mark.parametrize("mode", ["record", "replay"])
def test_an_old_cache_entry_without_choices_is_evicted_instead_of_replayed(tmp_path, mode):
    """Bản cũ lưu nhầm phản hồi Gemini bị chặn (id/choices = null); replay nó làm pydantic ném ValidationError (bị tính là lỗi của hệ)."""
    cache = LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None)
    key = cache_key("m", MSG, None, 0.0, [None, cache.seed])
    cache.put(key, {"id": None, "choices": None, "created": 1, "model": None, "object": "chat.completion"})
    client = FakeClient([completion("fresh")])
    cache = LLMCache(tmp_path / "c.sqlite", mode, sleep=lambda s: None)
    wrap_client(client, cache)
    if mode == "replay":
        with pytest.raises(CacheMiss):
            client.chat.completions.create(model="m", messages=MSG, temperature=0.0)
    else:
        assert client.chat.completions.create(model="m", messages=MSG, temperature=0.0).choices[0].message.content == "fresh"
    assert cache.get(key) is None or cache.get(key)["choices"]                    # mục hỏng đã bị xoá (hoặc thay bằng phản hồi hợp lệ)


def test_replay_tolerates_a_finish_reason_outside_the_sdk_literal(tmp_path):
    """Phản hồi thật có finish_reason='malformed_function_call' (Gemini): replay không được hỏng vì validate."""
    from eval.llm_cache import _validate_completion
    hit = {"id": "x", "object": "chat.completion", "created": 0, "model": "m",
           "choices": [{"index": 0, "finish_reason": "malformed_function_call", "message": {"role": "assistant", "content": "hi"}}]}
    assert _validate_completion(hit).choices[0].message.content == "hi"
    hit["choices"][0]["finish_reason"] = "stop"
    assert _validate_completion(hit).choices[0].finish_reason == "stop"
