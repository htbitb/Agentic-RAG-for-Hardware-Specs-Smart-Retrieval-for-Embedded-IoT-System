"""eval_adapter.py: giao thức JSONL, ghép lịch sử, nguồn 1-based, cache record/replay."""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval.tests.rag_venv import RAG, RAG_PY, needs_rag_venv, run_in_rag_venv

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def adapter(monkeypatch):
    monkeypatch.syspath_prepend(str(RAG))
    for n in ("config", "rag_core", "eval_adapter"):
        sys.modules.pop(n, None)
    mod = importlib.import_module("eval_adapter")
    yield mod
    for n in ("config", "rag_core", "eval_adapter"):
        sys.modules.pop(n, None)


def test_parse_request_defaults(adapter):
    r = adapter.parse_request(json.dumps({"id": "t1", "question": "What is X?"}))
    assert r == {"id": "t1", "question": "What is X?", "history": [], "seed": 0}


def test_parse_request_keeps_history_and_seed(adapter):
    r = adapter.parse_request(json.dumps({"id": "t1", "question": "q2", "seed": 2,
                                          "history": [{"user": "q1", "assistant": "a1"}]}))
    assert r["seed"] == 2 and r["history"] == [{"user": "q1", "assistant": "a1"}]


@pytest.mark.parametrize("line", ["not json", "[]", json.dumps({"id": "x"}), json.dumps({"question": "q"}),
                                  json.dumps({"id": "x", "question": ""})])
def test_parse_request_rejects_bad_input(adapter, line):
    with pytest.raises(ValueError):
        adapter.parse_request(line)


def test_compose_question_without_history_is_unchanged(adapter):
    assert adapter.compose_question("What is the reset value?", []) == "What is the reset value?"


def test_compose_question_marks_each_turn_and_current_question(adapter):
    text = adapter.compose_question("And its offset?", [{"user": "RCC_CR reset?", "assistant": "0x63"},
                                                         {"user": "RCC_CFGR reset?", "assistant": "0x0"}])
    assert text.index("Turn 1") < text.index("Turn 2") < text.index("Current question")
    assert "RCC_CR reset?" in text and "0x63" in text
    assert text.rstrip().endswith("And its offset?")


def test_sources_are_one_based_and_deduplicated(adapter):
    d = lambda src, page1, doc: SimpleNamespace(metadata={"source": src, "page_1based": page1, "doc_id": doc})
    docs = [d("/c/pdfs/a.pdf", 3, "A"), d("/c/pdfs/a.pdf", 3, "A"), d("/c/pdfs/b.pdf", 10, "B")]
    assert adapter.sources_from_docs(docs) == [{"doc_id": "A", "file": "a.pdf", "page": 3},
                                               {"doc_id": "B", "file": "b.pdf", "page": 10}]


def test_sources_fall_back_to_zero_based_page(adapter):
    doc = SimpleNamespace(metadata={"source": "/c/x.pdf", "page": 4})
    assert adapter.sources_from_docs([doc]) == [{"doc_id": "x", "file": "x.pdf", "page": 5}]


def test_response_line_is_single_json_object(adapter):
    line = adapter.format_response("t1", answer="a", sources=[], usage={"in": 1, "out": 2}, latency_s=0.123456)
    assert "\n" not in line
    obj = json.loads(line)
    assert obj == {"id": "t1", "answer": "a", "sources": [], "usage": {"in": 1, "out": 2},
                   "latency_s": 0.123, "error": None}


@needs_rag_venv
def test_replay_cache_miss_raises_instead_of_calling_api(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json
sys.path.insert(0, {str(RAG)!r})
import eval_adapter
cache = eval_adapter.make_cache("replay", {str(tmp_path / "c.sqlite")!r})
cache.set_seed(0)
try:
    cache.lookup("prompt", "llm-string")
    print(json.dumps({{"raised": False}}))
except eval_adapter.CacheMiss:
    print(json.dumps({{"raised": True}}))
''')
    assert json.loads(out) == {"raised": True}


@needs_rag_venv
def test_record_cache_is_keyed_by_seed(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json
sys.path.insert(0, {str(RAG)!r})
from langchain_core.outputs import Generation
import eval_adapter
db = {str(tmp_path / "c.sqlite")!r}
rec = eval_adapter.make_cache("record", db)
rec.set_seed(0); rec.update("p", "m", [Generation(text="seed0")])
rec.set_seed(1)
miss_other_seed = rec.lookup("p", "m") is None
rec.update("p", "m", [Generation(text="seed1")])
rep = eval_adapter.make_cache("replay", db)
rep.set_seed(0); a = rep.lookup("p", "m")[0].text
rep.set_seed(1); b = rep.lookup("p", "m")[0].text
print(json.dumps({{"miss_other_seed": miss_other_seed, "a": a, "b": b}}))
''')
    assert json.loads(out) == {"miss_other_seed": True, "a": "seed0", "b": "seed1"}


@needs_rag_venv
def test_answer_question_ex_returns_usage_and_keeps_legacy_tuple():
    out = run_in_rag_venv(f'''
import sys, json
sys.path.insert(0, {str(RAG)!r})
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.documents import Document
import rag_core
docs = [Document(page_content="ctx", metadata={{"source": "/x/a.pdf", "page": 0}})]
class VS:
    def as_retriever(self, search_kwargs):
        return RunnableLambda(lambda q: docs)
llm = RunnableLambda(lambda pv: AIMessage(content=" the answer ", usage_metadata={{"input_tokens": 11, "output_tokens": 3, "total_tokens": 14}}))
ex = rag_core.answer_question_ex("q?", VS(), llm)
legacy = rag_core.answer_question("q?", VS(), llm)
print(json.dumps({{"ans": ex["answer"], "usage": ex["usage"], "n_docs": len(ex["docs"]), "legacy_ans": legacy[0], "legacy_docs": len(legacy[1])}}))
''')
    assert json.loads(out) == {"ans": "the answer", "usage": {"in": 11, "out": 3}, "n_docs": 1,
                               "legacy_ans": "the answer", "legacy_docs": 1}


@needs_rag_venv
@pytest.mark.integration
def test_adapter_process_protocol_end_to_end_with_replay_cache_miss(tmp_path):
    """Tiến trình thật: nạp chroma_db, nhận JSONL, ở replay + cache rỗng trả cache_miss (không gọi API)."""
    if not (RAG / "chroma_db").exists():
        pytest.skip("chưa ingest")
    env = {**os.environ, "LLM_CACHE": "replay", "LLM_CACHE_PATH": str(tmp_path / "empty.sqlite")}
    reqs = "\n".join([json.dumps({"id": "a", "question": "What is the maximum CPU frequency of the STM32G474?"}),
                      "not json",
                      json.dumps({"id": "b", "question": "And ESP32?", "history": [{"user": "q", "assistant": "a"}], "seed": 1})]) + "\n"
    r = subprocess.run([str(RAG_PY), str(RAG / "eval_adapter.py")], input=reqs, capture_output=True, text=True,
                       timeout=300, env=env, cwd=str(RAG))
    assert r.returncode == 0, r.stderr[-1500:]
    lines = [json.loads(l) for l in r.stdout.splitlines()]            # stdout chỉ chứa JSONL
    assert [l["id"] for l in lines] == ["a", None, "b"]
    assert lines[0]["error"] == "cache_miss" and lines[2]["error"] == "cache_miss"
    assert lines[1]["error"].startswith("bad_request")
    assert lines[0]["usage"] == {"in": 0, "out": 0}


def test_call_with_retry_paces_and_honours_server_delay(adapter):
    class Err(Exception):
        status_code = 429

    seq = [Err("Please retry in 12.5s."), Err("again"), "OK"]
    sleeps, acquired = [], []

    class Lim:
        def acquire(self):
            acquired.append(1)

    def fn():
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    assert adapter.call_with_retry(fn, limiter=Lim(), sleep=sleeps.append) == "OK"
    assert sleeps == [pytest.approx(13.5, abs=0.1), 4] and len(acquired) == 3


def test_call_with_retry_does_not_retry_cache_miss_or_logic_errors(adapter):
    for exc in (adapter.CacheMiss("x"), ValueError("bad")):
        calls = []

        def fn(e=exc):
            calls.append(1)
            raise e

        with pytest.raises(type(exc)):
            adapter.call_with_retry(fn, sleep=lambda s: None)
        assert len(calls) == 1


# ---- review finding 9: phân loại lỗi trong tiến trình S1 --------------------------------------------------
class _Status(Exception):
    def __init__(self, code):
        super().__init__(f"http {code}")
        self.status_code = code


def test_classify_exception_fatal_infra_error(adapter):
    assert adapter.classify_exception(_Status(403)) == "fatal" and adapter.classify_exception(_Status(401)) == "fatal"
    assert adapter.classify_exception(_Status(429)) == "infra" and adapter.classify_exception(_Status(503)) == "infra"
    assert adapter.classify_exception(ValueError("x")) == "error"


@pytest.mark.parametrize("exc,prefix", [(_Status(401), "fatal:"), (_Status(503), "infra:"), (ValueError("boom"), "error:")])
def test_answer_request_labels_failures_by_class(adapter, monkeypatch, exc, prefix):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(adapter, "_ask", boom)
    out = json.loads(adapter.answer_request({"id": "t", "question": "q", "history": [], "seed": 0}, None, None))
    assert out["error"].startswith(prefix)


def test_rag_bridge_daily_quota_and_long_wait_are_fatal_without_sleeping(adapter):
    class DailyQuota(Exception):
        status_code = 429
        body = [{"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
                                       {"retryDelay": "57323s"}]}}]

    class LongWait(Exception):
        status_code = 429

        def __str__(self):
            return "429 Please retry in 3600.5s"

    assert adapter.classify_exception(DailyQuota()) == "fatal" and adapter.classify_exception(LongWait()) == "fatal"
    slept = []
    calls = []

    def fn():
        calls.append(1)
        raise DailyQuota()

    with pytest.raises(DailyQuota):
        adapter.call_with_retry(fn, sleep=slept.append)
    assert slept == [] and len(calls) == 1


# ---- retrieval cũng phải record/replay: Chroma/HNSW có thể trả top-k khác nhau giữa các tiến trình -----------------
@needs_rag_venv
def test_retrieval_is_recorded_and_replayed_even_if_live_retrieval_changes(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json
sys.path.insert(0, {str(RAG)!r})
from langchain_core.documents import Document
import eval_adapter
db = {str(tmp_path / "c.sqlite")!r}
A = [Document(page_content="ctx A", metadata={{"source": "/x/a.pdf", "page": 0, "doc_id": "A"}})]
B = [Document(page_content="ctx B", metadata={{"source": "/x/b.pdf", "page": 1, "doc_id": "B"}})]
rec = eval_adapter.make_cache("record", db); rec.set_seed(0)
first = rec.retrieve("q", 4, lambda: A)
rep = eval_adapter.make_cache("replay", db); rep.set_seed(0)
replayed = rep.retrieve("q", 4, lambda: B)
print(json.dumps({{"first": first[0].page_content, "replayed": replayed[0].page_content, "meta": replayed[0].metadata}}))
''')
    got = json.loads(out)
    assert got["first"] == "ctx A" and got["replayed"] == "ctx A" and got["meta"]["doc_id"] == "A"


@needs_rag_venv
def test_retrieval_record_is_keyed_by_seed_and_question(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json
sys.path.insert(0, {str(RAG)!r})
from langchain_core.documents import Document
import eval_adapter
db = {str(tmp_path / "c.sqlite")!r}
mk = lambda t: [Document(page_content=t, metadata={{}})]
rec = eval_adapter.make_cache("record", db)
rec.set_seed(0); a = rec.retrieve("q", 4, lambda: mk("seed0"))[0].page_content
rec.set_seed(1); b = rec.retrieve("q", 4, lambda: mk("seed1"))[0].page_content
rec.set_seed(1); other_q = rec.retrieve("q2", 4, lambda: mk("q2"))[0].page_content
rep = eval_adapter.make_cache("replay", db)
rep.set_seed(0); r0 = rep.retrieve("q", 4, lambda: mk("live"))[0].page_content
rep.set_seed(1); r1 = rep.retrieve("q", 4, lambda: mk("live"))[0].page_content
print(json.dumps([a, b, other_q, r0, r1]))
''')
    assert json.loads(out) == ["seed0", "seed1", "q2", "seed0", "seed1"]


# ---- post-P0 review #2: replay KHÔNG được rơi về truy hồi trực tiếp; thiếu bản ghi -> cache_miss ---------------------
@needs_rag_venv
def test_replay_without_a_stored_retrieval_raises_cache_miss_and_never_fetches_or_writes(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json, sqlite3
sys.path.insert(0, {str(RAG)!r})
import eval_adapter
res = {{}}
def probe(label, db):
    rep = eval_adapter.make_cache("replay", db); rep.set_seed(0)
    fetched = []
    try:
        rep.retrieve("q", 4, lambda: fetched.append(1) or [])
        res[label] = "returned"
    except eval_adapter.CacheMiss:
        res[label] = "miss"
    res[label + "_fetched"] = bool(fetched)
# (a) file chưa tồn tại: không được tạo file
a = {str(tmp_path / "none.sqlite")!r}
probe("absent", a)
import os
res["absent_created"] = os.path.exists(a)
# (b) file có nhưng chưa có bảng retrieval: không được CREATE TABLE
b = {str(tmp_path / "notable.sqlite")!r}
con = sqlite3.connect(b); con.execute("CREATE TABLE other(x)"); con.commit(); con.close()
probe("notable", b)
res["notable_tables"] = sorted(r[0] for r in sqlite3.connect(b).execute("SELECT name FROM sqlite_master WHERE type='table'"))
# (c) có bảng nhưng không có dòng khớp
c = {str(tmp_path / "empty.sqlite")!r}
rec = eval_adapter.make_cache("record", c); rec.set_seed(0)
rec.retrieve("other question", 4, lambda: [])
probe("norow", c)
print(json.dumps(res))
''')
    got = json.loads(out)
    assert got["absent"] == got["notable"] == got["norow"] == "miss"
    assert not (got["absent_fetched"] or got["notable_fetched"] or got["norow_fetched"])
    assert got["absent_created"] is False and "retrieval" not in got["notable_tables"] and "full_llm_cache" not in got["notable_tables"]


@needs_rag_venv
def test_answer_request_labels_a_replay_retrieval_miss_as_cache_miss(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json
sys.path.insert(0, {str(RAG)!r})
from langchain_core.runnables import RunnableLambda
import eval_adapter
class VS:
    def as_retriever(self, search_kwargs):
        raise AssertionError("live retrieval must not run in replay")
rep = eval_adapter.make_cache("replay", {str(tmp_path / "c.sqlite")!r})
line = eval_adapter.answer_request({{"id": "t", "question": "q", "history": [], "seed": 0}}, VS(), RunnableLambda(lambda pv: pv), rep)
print(line)
''')
    assert json.loads(out)["error"] == "cache_miss"


def _main_script(db, mode, chroma_dir, count, reqs, pre=""):
    return f'''
import sys, io, os, json
sys.path.insert(0, {str(RAG)!r})
from pathlib import Path
import config, rag_core, eval_adapter
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
config.CHROMA_DIR = Path({str(chroma_dir)!r})
loads = []
def get_vs(*a, **k):
    loads.append(1)
    class VS:
        def as_retriever(self, search_kwargs):
            return RunnableLambda(lambda q: [Document(page_content="live", metadata={{"source": "/x/live.pdf", "page": 0, "doc_id": "LIVE"}})])
    return VS()
rag_core.get_vectorstore = get_vs
rag_core.get_llm = lambda: RunnableLambda(lambda pv: AIMessage(content="ans", usage_metadata={{"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}))
eval_adapter.chroma_count = lambda: {count!r}
os.environ["LLM_CACHE"] = {mode!r}; os.environ["LLM_CACHE_PATH"] = {str(db)!r}
{pre}
sys.stdin = io.StringIO({reqs!r})
buf = io.StringIO(); sys.stdout = buf
rc = eval_adapter.main()
sys.stdout = sys.__stdout__
print(json.dumps({{"rc": rc, "loads": len(loads), "lines": [json.loads(l) for l in buf.getvalue().splitlines()]}}))
'''


REQ = json.dumps({"id": "a", "question": "q", "seed": 0}) + "\n"


@needs_rag_venv
def test_replay_main_works_without_a_chroma_index_and_never_loads_the_vectorstore(tmp_path):
    db = tmp_path / "c.sqlite"
    pre = f'''
rec = eval_adapter.make_cache("record", {str(db)!r}); rec.set_seed(0)
rec.retrieve("q", 4, lambda: [Document(page_content="ctx", metadata={{"source": "/x/a.pdf", "page": 0, "doc_id": "A"}})])
'''
    got = json.loads(run_in_rag_venv(_main_script(db, "replay", tmp_path / "no_such_chroma", None, REQ, pre)))
    assert got["rc"] == 0 and got["loads"] == 0
    assert got["lines"][0]["error"] is None and got["lines"][0]["answer"] == "ans"
    assert got["lines"][0]["sources"] == [{"doc_id": "A", "file": "a.pdf", "page": 1}]


@needs_rag_venv
def test_replay_main_with_an_empty_cache_and_no_index_reports_cache_miss(tmp_path):
    db = tmp_path / "never_created.sqlite"
    got = json.loads(run_in_rag_venv(_main_script(db, "replay", tmp_path / "no_such_chroma", None, REQ)))
    assert got["rc"] == 0 and got["loads"] == 0 and got["lines"][0]["error"] == "cache_miss"
    assert not db.exists()


# ---- post-P0 review #3: dấu vân tay chỉ mục trong bảng meta của cache truy hồi ---------------------------------------
def test_index_fingerprint_covers_model_chunking_collection_and_count(adapter):
    fp = adapter.index_fingerprint(11251)
    cfg = adapter.config
    assert fp == {"embedding_model": cfg.EMBEDDING_MODEL_NAME, "chunk_size": cfg.CHUNK_SIZE, "chunk_overlap": cfg.CHUNK_OVERLAP,
                  "collection": cfg.COLLECTION_NAME, "count": 11251}


FP = {"embedding_model": "m", "chunk_size": 1000, "chunk_overlap": 150, "collection": "c", "count": 100}


@needs_rag_venv
def test_record_stores_the_fingerprint_and_refuses_a_changed_index(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json, sqlite3
sys.path.insert(0, {str(RAG)!r})
import eval_adapter
db = {str(tmp_path / "c.sqlite")!r}
fp = {FP!r}
res = {{}}
eval_adapter.make_cache("record", db, fp)
res["stored"] = json.loads(sqlite3.connect(db).execute("SELECT value FROM meta WHERE key='index_fingerprint'").fetchone()[0])
eval_adapter.make_cache("record", db, dict(fp))                    # cùng chỉ mục: ổn
res["same_ok"] = True
for label, change in (("count", {{"count": 101}}), ("model", {{"embedding_model": "m2"}}), ("chunk", {{"chunk_size": 500}}),
                      ("overlap", {{"chunk_overlap": 0}}), ("collection", {{"collection": "other"}})):
    try:
        eval_adapter.make_cache("record", db, {{**fp, **change}})
        res[label] = "accepted"
    except eval_adapter.IndexMismatch as exc:
        res[label] = str(exc)
print(json.dumps(res))
''')
    got = json.loads(out)
    assert got["stored"] == FP and got["same_ok"]
    for label in ("count", "model", "chunk", "overlap", "collection"):
        assert got[label] != "accepted", label
    assert "count" in got["count"] and "100" in got["count"] and "101" in got["count"]
    assert "fresh" in got["count"].lower() or "mới" in got["count"]                # chỉ cách xử lý


@needs_rag_venv
def test_replay_compares_the_fingerprint_only_when_an_index_is_present(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json, sqlite3
sys.path.insert(0, {str(RAG)!r})
import eval_adapter
db = {str(tmp_path / "c.sqlite")!r}
fp = {FP!r}
eval_adapter.make_cache("record", db, fp)
res = {{}}
eval_adapter.make_cache("replay", db, None); res["no_index_trusts"] = True          # không có chỉ mục: tin bản đã lưu
eval_adapter.make_cache("replay", db, dict(fp)); res["same_ok"] = True
try:
    eval_adapter.make_cache("replay", db, {{**fp, "count": 5}})
    res["changed"] = "accepted"
except eval_adapter.IndexMismatch as exc:
    res["changed"] = "refused"
print(json.dumps(res))
''')
    assert json.loads(out) == {"no_index_trusts": True, "same_ok": True, "changed": "refused"}


@needs_rag_venv
def test_legacy_retrieval_rows_without_a_fingerprint_block_record_but_not_replay_and_replay_writes_nothing(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json, sqlite3
sys.path.insert(0, {str(RAG)!r})
import eval_adapter
db = {str(tmp_path / "c.sqlite")!r}
old = eval_adapter.make_cache("record", db); old.set_seed(0)           # không truyền fingerprint: như bản cache cũ
old.retrieve("q", 4, lambda: [])
res = {{}}
try:
    eval_adapter.make_cache("record", db, {FP!r})
    res["record"] = "accepted"
except eval_adapter.IndexMismatch:
    res["record"] = "refused"
snap = lambda: (sorted(r[0] for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'")),
                sqlite3.connect(db).execute("SELECT count(*) FROM meta").fetchone()[0])
before = snap()
eval_adapter.make_cache("replay", db, {FP!r}); res["replay"] = "ok"
res["unchanged"] = snap() == before and before[1] == 0          # không có dòng fingerprint nào được ghi
print(json.dumps(res))
''')
    got = json.loads(out)
    assert got["record"] == "refused" and got["replay"] == "ok" and got["unchanged"]


@needs_rag_venv
def test_main_answers_every_request_with_fatal_when_the_index_changed(tmp_path):
    db = tmp_path / "c.sqlite"
    chroma = tmp_path / "chroma"
    chroma.mkdir()
    pre = f'''
eval_adapter.make_cache("record", {str(db)!r}, eval_adapter.index_fingerprint(100))
'''
    for mode in ("record", "replay"):
        got = json.loads(run_in_rag_venv(_main_script(db, mode, chroma, 101, REQ, pre)))
        err = got["lines"][0]["error"]
        assert got["rc"] == 0 and err.startswith("fatal:") and "fingerprint" in err, (mode, got)


@needs_rag_venv
def test_ask_uses_the_recorded_retrieval_in_replay(tmp_path):
    out = run_in_rag_venv(f'''
import sys, json
sys.path.insert(0, {str(RAG)!r})
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
import eval_adapter
db = {str(tmp_path / "c.sqlite")!r}
def vs(doc_id):
    docs = [Document(page_content="ctx " + doc_id, metadata={{"source": "/x/" + doc_id + ".pdf", "page": 0, "doc_id": doc_id}})]
    class VS:
        def as_retriever(self, search_kwargs):
            return RunnableLambda(lambda q: docs)
    return VS()
llm = RunnableLambda(lambda pv: AIMessage(content="ans", usage_metadata={{"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}))
req = {{"id": "t", "question": "q", "history": [], "seed": 0}}
rec = eval_adapter.make_cache("record", db); rec.set_seed(0)
a = eval_adapter._ask(req, vs("A"), llm, cache=rec)
rep = eval_adapter.make_cache("replay", db); rep.set_seed(0)
b = eval_adapter._ask(req, vs("B"), llm, cache=rep)
print(json.dumps([[d.metadata["doc_id"] for d in a["docs"]], [d.metadata["doc_id"] for d in b["docs"]]]))
''')
    assert json.loads(out) == [["A"], ["A"]]


# ---- post-P0 review #1: S1 và eval/ dùng CHUNG một bộ phân loại lỗi (parity) --------------------------------------
def _exc(name, msg="boom", status=None, body=None, base=Exception):
    attrs = {}
    if status is not None:
        attrs["status_code"] = status
    if body is not None:
        attrs["body"] = body
    return type(name, (base,), attrs)(msg)


def _classification_table():
    daily = [{"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}]
    return [
        (_exc("AuthenticationError", status=401), "fatal"),
        (_exc("X", status=403), "fatal"),
        (_exc("PermissionDeniedError"), "fatal"),
        (_exc("BadRequestError", "Error code: 400 - API key not valid. Please pass a valid API key.", status=400), "fatal"),
        (_exc("BadRequestError", "Error code: 400 - API key expired. Please renew the API key.", status=400), "fatal"),
        (_exc("BadRequestError", "Error code: 400", status=400,
              body=[{"error": {"details": [{"reason": "API_KEY_INVALID"}]}}]), "fatal"),
        (_exc("RateLimitError", "quota", status=429, body=daily), "fatal"),
        (_exc("RateLimitError", "429 Please retry in 3600.5s", status=429), "fatal"),
        (_exc("RateLimitError", "429 Please retry in 12s", status=429), "infra"),
        (_exc("X", status=408), "infra"), (_exc("X", status=503), "infra"), (_exc("X", status=500), "infra"),
        (_exc("APIConnectionError"), "infra"), (_exc("APITimeoutError"), "infra"), (_exc("ReadTimeout"), "infra"),
        (_exc("ConnectTimeout"), "infra"), (TimeoutError("t"), "infra"), (_exc("ConnectError"), "infra"),
        (_exc("RemoteProtocolError"), "infra"),
        (_exc("OperationalError", "database is locked"), "infra"),
        (_exc("OperationalError", "no such table: x"), "error"),
        (_exc("BadRequestError", "Error code: 400 - prompt too long", status=400), "error"),
        (_exc("NotFoundError", "models/x is not found", status=404), "error"),
        (ValueError("x"), "error"),
    ]


def test_s1_and_eval_classify_the_same_table_of_exceptions(adapter):
    from eval import llm_cache

    for exc, want in _classification_table():
        label = f"{type(exc).__name__}({exc}) status={getattr(exc, 'status_code', None)}"
        assert llm_cache.classify_exception(exc) == want, f"eval: {label}"
        assert adapter.classify_exception(exc) == want, f"S1: {label}"


def test_sqlite_database_is_locked_during_retrieval_is_labelled_infra_not_error(adapter, monkeypatch):
    import sqlite3

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(adapter, "_ask", locked)
    out = json.loads(adapter.answer_request({"id": "t", "question": "q", "history": [], "seed": 0}, None, None))
    assert out["error"].startswith("infra:")                      # retry-able, loại khỏi TSR
    from eval.adapters.native_rag import _label_error

    assert _label_error(out["error"]).startswith("infra:")
