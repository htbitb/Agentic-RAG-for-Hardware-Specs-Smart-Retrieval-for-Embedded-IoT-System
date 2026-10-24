"""
eval_adapter.py  —  JSONL bridge between the evaluation harness (eval/) and this RAG
====================================================================================

Long-lived process: loads the vector store and the LLM ONCE, then answers one request
per stdin line.  Logs go to stderr; stdout carries ONLY response JSON lines.

  stdin  : {"id": "...", "question": "...", "history": [{"user": "...", "assistant": "..."}], "seed": 0}
  stdout : {"id": "...", "answer": "...", "sources": [{"doc_id": "...", "file": "...", "page": <1-based>}],
            "usage": {"in": n, "out": n}, "latency_s": x, "error": null}

LLM cache (env LLM_CACHE):
  unset/off : no cache
  record    : read-through SQLite cache (hit -> reuse, miss -> call API and store)
  replay    : cache only; a miss (LLM call OR retrieval) returns error "cache_miss" and NEVER calls the API or
              retrieves live; the Chroma index / embedder are not even loaded
The cache key includes the request `seed`, so each seed is recorded independently.
The retrieval cache carries an index fingerprint (embedding model, chunking, collection, chunk count) in table `meta`:
record refuses a changed index (-> every request answers "fatal:"), replay compares it when an index is present.
Path: env LLM_CACHE_PATH or <project>/eval/.cache/native_rag_llm.sqlite.

Run:  .venv/bin/python eval_adapter.py < requests.jsonl
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote

import config
import rag_core

DEFAULT_CACHE_PATH = config.ROOT.parent / "eval" / ".cache" / "native_rag_llm.sqlite"


class CacheMiss(Exception):
    """Raised in replay mode when the LLM call or the retrieval is not in the cache."""


class IndexMismatch(Exception):
    """The retrieval cache was recorded against a different index than the current one (see index_fingerprint)."""


def _load_eval_module(name: str):
    """Nạp eval/<name>.py theo đường dẫn (chỉ dùng thư viện chuẩn; venv này không có package `eval`)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"eval_{name}", config.ROOT.parent / "eval" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_errs = _load_eval_module("llm_errors")        # CÙNG bộ phân loại lỗi với S0/S2 (eval/llm_cache.py)
classify_exception = _errs.classify_exception  # 'fatal' (dừng cả lượt chạy) | 'infra' (tạm thời) | 'error' (lỗi của hệ)
_server_delay = _errs.retry_delay_from


def call_with_retry(fn, limiter=None, sleep=time.sleep, max_retries: int = 5):
    """Gọi LLM có điều tiết tốc độ (limiter dùng chung với S0/S2) và retry lỗi hạ tầng; CacheMiss/lỗi logic đi thẳng lên."""
    attempt = 0
    while True:
        try:
            if limiter is not None:
                limiter.acquire()
            return fn()
        except CacheMiss:
            raise
        except Exception as exc:
            if classify_exception(exc) != "infra" or attempt >= max_retries:
                raise
            attempt += 1
            hint = _server_delay(exc)
            sleep(max(2 ** attempt, hint + 1.0) if hint else 2 ** attempt)


def _limiter():
    """Bộ giới hạn tốc độ dùng chung (eval/ratelimit.py) khi harness đặt EVAL_LLM_RPM / EVAL_RATE_FILE."""
    rpm, path = float(os.getenv("EVAL_LLM_RPM", "0") or 0), os.getenv("EVAL_RATE_FILE", "")
    if rpm <= 0 or not path:
        return None
    return _load_eval_module("ratelimit").FileRateLimiter(path, rpm)


def log(msg: str) -> None:
    print(f"[eval_adapter] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------- protocol
def parse_request(line: str) -> dict:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("request must be a JSON object")
    rid, question = obj.get("id"), obj.get("question")
    if not rid or not isinstance(rid, str):
        raise ValueError("missing 'id'")
    if not question or not isinstance(question, str):
        raise ValueError("missing 'question'")
    return {"id": rid, "question": question, "history": list(obj.get("history") or []),
            "seed": int(obj.get("seed") or 0)}


def compose_question(question: str, history: list[dict]) -> str:
    """Multi-turn: fold earlier turns into the QUESTION block; retrieval still uses the current question only."""
    if not history:
        return question
    lines = ["Conversation so far:"]
    for i, turn in enumerate(history, start=1):
        lines.append(f"[Turn {i}] User: {turn.get('user', '')}")
        lines.append(f"[Turn {i}] Assistant: {turn.get('assistant', '')}")
    lines.append("")
    lines.append(f"Current question: {question}")
    return "\n".join(lines)


def sources_from_docs(docs) -> list[dict]:
    out, seen = [], set()
    for d in docs:
        m = d.metadata or {}
        name = Path(m.get("source", "")).name
        page = m.get("page_1based") or (int(m.get("page", 0)) + 1)
        item = {"doc_id": m.get("doc_id") or Path(name).stem, "file": name, "page": int(page)}
        key = (item["doc_id"], item["page"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def format_response(rid, answer, sources, usage, latency_s, error=None) -> str:
    return json.dumps({"id": rid, "answer": answer, "sources": sources, "usage": usage,
                       "latency_s": round(latency_s, 3), "error": error}, ensure_ascii=False)


# ----------------------------------------------------------------------- cache
_RETRIEVAL_DDL = "CREATE TABLE IF NOT EXISTS retrieval (key TEXT PRIMARY KEY, docs TEXT NOT NULL)"
_META_DDL = "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
_FP_KEY = "index_fingerprint"


def index_fingerprint(count) -> dict:
    """Dấu vân tay chỉ mục: khoá retrieval (câu hỏi, k, seed) không chứa chỉ mục nên phải ghi kèm để phát hiện ingest lại."""
    return {"embedding_model": config.EMBEDDING_MODEL_NAME, "chunk_size": config.CHUNK_SIZE,
            "chunk_overlap": config.CHUNK_OVERLAP, "collection": config.COLLECTION_NAME, "count": count}


def chroma_count():
    """Số chunk trong collection Chroma (không nạp embedder); None nếu chưa có chỉ mục dùng được."""
    if not config.CHROMA_DIR.exists():
        return None
    try:
        import chromadb

        return chromadb.PersistentClient(path=str(config.CHROMA_DIR)).get_collection(config.COLLECTION_NAME).count()
    except Exception as exc:
        log(f"cannot read the Chroma collection: {type(exc).__name__}: {str(exc)[:160]}")
        return None


def _open_ro(path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=60, check_same_thread=False)


def _read_fp_state(con):
    """(fingerprint đã lưu | None, số dòng retrieval); chịu được việc chưa có bảng."""
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (_FP_KEY,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    try:
        n = con.execute("SELECT count(*) FROM retrieval").fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    return (json.loads(row[0]) if row else None), n


def check_index_fingerprint(mode: str, path, fp: dict) -> None:
    """record: lưu fp lần đầu, từ chối nếu khác bản đã lưu (hoặc đã có dòng retrieval mà chưa có fp). replay: so khi đã lưu fp; không ghi gì."""
    path = Path(path)
    hint = "Use a fresh cache file (move or rename it) rather than reusing retrieval recorded for another index."
    if mode == "replay":
        if not path.exists():
            return
        con = _open_ro(path)
        try:
            stored, _ = _read_fp_state(con)
        finally:
            con.close()
        n = 0
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), timeout=60, isolation_level=None)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(_RETRIEVAL_DDL)
            con.execute(_META_DDL)
            stored, n = _read_fp_state(con)
            if stored is None and n == 0:
                con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (_FP_KEY, json.dumps(fp, sort_keys=True)))
            con.execute("COMMIT")
        finally:
            con.close()
    if stored is not None and stored != fp:
        diff = ", ".join(f"{k}: {stored.get(k)!r} -> {fp.get(k)!r}" for k in sorted({*stored, *fp}) if stored.get(k) != fp.get(k))
        raise IndexMismatch(f"index fingerprint mismatch for the retrieval cache {path} (stored -> current: {diff}). {hint}")
    if stored is None and n:
        raise IndexMismatch(f"the retrieval cache {path} has {n} entries but no index fingerprint (recorded before fingerprinting); "
                            f"back-fill the meta row after verifying the index is unchanged. {hint}")


def make_cache(mode: str, path, fingerprint: dict | None = None):
    """SQLite LLM cache keyed by (prompt, llm_string, seed). `replay` never writes (read-only) and raises CacheMiss on a miss.
    With `fingerprint` the retrieval cache is bound to that index (see check_index_fingerprint; raises IndexMismatch)."""
    from langchain_community.cache import SQLAlchemyCache, SQLiteCache

    if fingerprint is not None:
        check_index_fingerprint(mode, path, fingerprint)
    if mode == "record":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    class SeededCache(SQLiteCache):
        def __init__(self, database_path):
            if mode != "replay":
                super().__init__(database_path=database_path)
            else:                       # chỉ đọc: không tạo file/bảng; chưa có cache thì dùng DB rỗng trong bộ nhớ (mọi lookup đều miss)
                from sqlalchemy import create_engine

                if Path(database_path).exists():
                    try:
                        SQLAlchemyCache.__init__(self, create_engine("sqlite://", creator=lambda: _open_ro(database_path)))
                    except Exception:
                        SQLAlchemyCache.__init__(self, create_engine("sqlite://"))
                else:
                    SQLAlchemyCache.__init__(self, create_engine("sqlite://"))
            self._seed = 0

        def set_seed(self, seed: int) -> None:
            self._seed = int(seed)

        def _key(self, llm_string: str) -> str:
            return f"{llm_string}|seed={self._seed}"

        def lookup(self, prompt, llm_string):
            hit = super().lookup(prompt, self._key(llm_string))
            if hit is None and mode == "replay":
                raise CacheMiss("LLM call not in cache")
            return hit

        def update(self, prompt, llm_string, return_val):
            if mode == "record":
                super().update(prompt, self._key(llm_string), return_val)

        def retrieve(self, question: str, k: int, fetch):
            """Retrieval cũng được record/replay (khoá = câu hỏi, k, seed): Chroma/HNSW có thể trả top-k khác nhau giữa các
            tiến trình nên prompt (và khoá cache LLM) sẽ lệch. Replay mà chưa có bản ghi -> CacheMiss (không truy hồi trực tiếp, không ghi gì)."""
            from langchain_core.documents import Document

            key = hashlib.sha256(json.dumps([question, k, self._seed], ensure_ascii=False).encode("utf-8")).hexdigest()
            if mode == "replay":
                row = None
                if Path(path).exists():
                    con = _open_ro(path)
                    try:
                        row = con.execute("SELECT docs FROM retrieval WHERE key=?", (key,)).fetchone()
                    except sqlite3.OperationalError:       # chưa có bảng retrieval
                        pass
                    finally:
                        con.close()
                if row is None:
                    raise CacheMiss("retrieval not in cache")
                return [Document(page_content=d["page_content"], metadata=d["metadata"]) for d in json.loads(row[0])]
            con = sqlite3.connect(str(path), timeout=60)
            try:
                con.execute(_RETRIEVAL_DDL)
                row = con.execute("SELECT docs FROM retrieval WHERE key=?", (key,)).fetchone()
                if row:
                    return [Document(page_content=d["page_content"], metadata=d["metadata"]) for d in json.loads(row[0])]
                docs = fetch()
                payload = json.dumps([{"page_content": d.page_content, "metadata": d.metadata} for d in docs],
                                     ensure_ascii=False, default=str)
                con.execute("INSERT OR REPLACE INTO retrieval VALUES (?, ?)", (key, payload))
                con.commit()
                return docs
            finally:
                con.close()

    return SeededCache(str(path))


class LazyVectorStore:
    """Chroma + embedder chỉ được nạp khi thật sự truy hồi (replay không cần chỉ mục)."""

    def __init__(self, factory=None):
        self._factory, self._vs = factory or rag_core.get_vectorstore, None

    def as_retriever(self, **kw):
        if self._vs is None:
            self._vs = self._factory()
        return self._vs.as_retriever(**kw)


# ------------------------------------------------------------------------ main
def answer_request(req: dict, vectorstore, llm, cache=None, limiter=None) -> str:
    t0 = time.time()
    if cache is not None:
        cache.set_seed(req["seed"])
    try:
        r = _ask(req, vectorstore, llm, limiter, cache)
        return format_response(req["id"], r["answer"], sources_from_docs(r["docs"]), r["usage"], time.time() - t0)
    except CacheMiss:
        return format_response(req["id"], "", [], {"in": 0, "out": 0}, time.time() - t0, error="cache_miss")
    except Exception as exc:  # the harness decides what each label means: fatal aborts, infra is excluded, error counts
        log(f"{req['id']}: {type(exc).__name__}: {str(exc)[:200]}")
        label = classify_exception(exc)
        detail = f"{type(exc).__name__} status={getattr(exc, 'status_code', None)}: {str(exc)[:200]}"
        return format_response(req["id"], "", [], {"in": 0, "out": 0}, time.time() - t0, error=f"{label}:{detail}")


def _ask(req: dict, vectorstore, llm, limiter=None, cache=None) -> dict:
    """Retrieve with the CURRENT question only; the prompt's QUESTION block carries the folded history."""
    from langchain_core.prompts import PromptTemplate

    fetch = lambda: vectorstore.as_retriever(search_kwargs={"k": config.RETRIEVE_K}).invoke(req["question"])
    docs = cache.retrieve(req["question"], config.RETRIEVE_K, fetch) if cache is not None else fetch()
    prompt = PromptTemplate.from_template(rag_core.PROMPT_TEMPLATE)
    inputs = {"context": rag_core.format_docs(docs), "question": compose_question(req["question"], req["history"])}
    out = call_with_retry(lambda: (prompt | llm).invoke(inputs), limiter=limiter)
    text, usage = rag_core.split_message(out)
    return {"answer": text, "docs": docs, "usage": usage}


def main() -> int:
    out = sys.stdout
    sys.stdout = sys.stderr  # nothing but protocol lines may reach the real stdout

    mode = os.getenv("LLM_CACHE", "").strip().lower()
    if mode not in ("", "off", "record", "replay"):
        log(f"unknown LLM_CACHE={mode!r}")
        return 2
    if mode != "replay" and not config.CHROMA_DIR.exists():       # replay chỉ cần cache, không cần chỉ mục
        log("no index: run ingest.py first")
        return 2
    cache, startup_error = None, None
    if mode in ("record", "replay"):
        from langchain_core.globals import set_llm_cache

        count = chroma_count()                       # None: không có chỉ mục -> replay tin dấu vân tay đã lưu
        if mode == "record" and count is None:
            log("no usable index: run ingest.py first")
            return 2
        try:
            cache = make_cache(mode, os.getenv("LLM_CACHE_PATH") or DEFAULT_CACHE_PATH,
                               index_fingerprint(count) if count is not None else None)
            set_llm_cache(cache)
        except IndexMismatch as exc:                 # mọi request sau đó trả 'fatal:' để harness dừng cả lượt chạy với thông báo rõ
            startup_error = f"fatal:{exc}"
            log(startup_error)
    log(f"loading vector store (cache={mode or 'off'}, device={config.EMBED_DEVICE}) ...")
    os.environ.setdefault("LLM_MAX_RETRIES", "0")        # call_with_retry điều tiết + retry; SDK không được tự retry ngoài bộ giới hạn
    limiter = _limiter() if mode != "replay" else None
    vectorstore = LazyVectorStore() if mode == "replay" else rag_core.get_vectorstore()
    llm = rag_core.get_llm()
    log("ready")

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = parse_request(line)
        except ValueError as exc:
            print(format_response(None, "", [], {"in": 0, "out": 0}, 0.0, error=f"bad_request: {exc}"),
                  file=out, flush=True)
            continue
        if startup_error:
            print(format_response(req["id"], "", [], {"in": 0, "out": 0}, 0.0, error=startup_error), file=out, flush=True)
            continue
        print(answer_request(req, vectorstore, llm, cache, limiter), file=out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
