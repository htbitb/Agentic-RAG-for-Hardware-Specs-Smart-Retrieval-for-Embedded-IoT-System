import json
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from eval.adapters.direct_llm import SYSTEM_PROMPT, DirectLLMAdapter
from eval.envload import LLMConfig
from eval.llm_cache import LLMCache, wrap_client
from eval.schema import Task


def completion(text, usage=(100, 20)):
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 1, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
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


CFG = LLMConfig(api_key="k-for-tests", base_url="https://example.invalid/v1/", model="m", temperature=0.0, price_in=1.0, price_out=2.0)
GEMINI = LLMConfig(api_key="k", base_url="https://generativelanguage.googleapis.com/v1beta/openai/", model="m",
                   temperature=0.0, price_in=1.0, price_out=2.0)


def task(turns=("What is X?",)):
    return Task(id="C1-001", category="C1", split="dev", turns=[{"user": u} for u in turns], graders=["exact"])


def make(client, cfg=CFG, mode="off", tmp=None):
    cache = LLMCache((tmp or "/nonexistent") / "c.sqlite" if tmp else "/nonexistent/c.sqlite", mode)
    return DirectLLMAdapter(cfg, client=client, cache=cache)


def test_single_turn_sends_system_prompt_and_reports_usage():
    client = FakeClient([completion("0x10", usage=(1000, 500))])
    a = make(client)
    a.start(task(), seed=2)
    t = a.send("What is X?")
    r = a.finish()
    msgs = client.calls[0]["messages"]
    assert msgs[0] == {"role": "system", "content": SYSTEM_PROMPT} and msgs[-1] == {"role": "user", "content": "What is X?"}
    assert "tools" not in client.calls[0] and client.calls[0]["temperature"] == 0.0
    assert t.answer == "0x10" and r.final_answer == "0x10" and r.system == "S0"
    assert r.usage == {"tokens_in": 1000, "tokens_out": 500, "usd": 0.002, "tool_calls": 0, "llm_calls": 1}
    assert r.errors == [] and r.seed == 2


def test_multi_turn_replays_history():
    client = FakeClient([completion("a1"), completion("a2")])
    a = make(client)
    a.start(task(("q1", "q2")), seed=0)
    a.send("q1")
    a.send("q2")
    msgs = client.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "a1" and msgs[3]["content"] == "q2"
    assert a.finish().usage["llm_calls"] == 2


def test_seed_is_sent_only_when_endpoint_supports_it():
    c1 = FakeClient([completion("x")])
    a = make(c1, CFG)
    a.start(task(), seed=5)
    a.send("q")
    assert c1.calls[0]["seed"] == 5
    c2 = FakeClient([completion("x")])
    g = make(c2, GEMINI)
    g.start(task(), seed=5)
    g.send("q")
    assert "seed" not in c2.calls[0]


class Rate(Exception):
    status_code = 429


def test_infra_error_is_labelled_and_turn_is_error(tmp_path):
    client = FakeClient([Rate("x")] * 10)
    cache = LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None, max_retries=1)
    a = DirectLLMAdapter(CFG, client=client, cache=cache)
    a.start(task(), seed=0)
    t = a.send("q")
    r = a.finish()
    assert t.status == "error" and r.has_infra_error() and r.errors[0].startswith("infra:")


def test_replay_miss_is_an_infra_labelled_error_and_costs_nothing(tmp_path):
    client = FakeClient([])
    a = DirectLLMAdapter(CFG, client=client, cache=LLMCache(tmp_path / "c.sqlite", "replay"))
    a.start(task(), seed=0)
    a.send("q")
    r = a.finish()
    assert client.calls == [] and r.errors == ["infra:cache_miss"] and r.usage["llm_calls"] == 0


def test_replay_reproduces_a_recorded_run(tmp_path):
    db = tmp_path / "c.sqlite"
    rec = DirectLLMAdapter(CFG, client=FakeClient([completion("0x10", usage=(7, 3))]), cache=LLMCache(db, "record"))
    rec.start(task(), seed=1)
    rec.send("What is X?")
    first = rec.finish()
    rep_client = FakeClient([])
    rep = DirectLLMAdapter(CFG, client=rep_client, cache=LLMCache(db, "replay"))
    rep.start(task(), seed=1)
    rep.send("What is X?")
    second = rep.finish()
    assert rep_client.calls == [] and second.final_answer == first.final_answer and second.usage["tokens_in"] == 7


def test_auth_error_aborts_the_whole_run(tmp_path):
    from eval.adapters.base import FatalAdapterError

    class Auth(Exception):
        status_code = 401

    a = DirectLLMAdapter(CFG, client=FakeClient([Auth("invalid api key")]), cache=LLMCache(tmp_path / "c.sqlite", "record", sleep=lambda s: None))
    a.start(task(), seed=0)
    with pytest.raises(FatalAdapterError):
        a.send("q")
