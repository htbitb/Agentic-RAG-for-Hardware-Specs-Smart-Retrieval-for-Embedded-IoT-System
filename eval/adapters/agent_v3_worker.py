"""Worker cho S3@P4 (Agent v3: runtime + Gate P4). Chạy bằng `python -I -B` trong MỘT tiến trình riêng cho mỗi task, để:
  * tên module `config`, `agent`, `mcp_servers`... của snapshot không xung đột với nơi khác;
  * memory / audit / sandbox / Board State / checkpoint / trace trỏ vào thư mục tạm của run (bộ nhớ sạch, không ghi bẩn agent/data).
Giao thức (JSONL; plan/P4_interfaces.md §3, §6):
  stdin  dòng 1 : {"snapshot","run_dir","task_id","seed","session_id","llm_cache":{"mode","path"},"cache_module","ablations":[...],"budgets":null|{...}}
  stdout dòng 1 : {"ready": true, "llm": ...}  hoặc {"fatal": "simulated_llm"} (exit 3) | {"fatal": "bad_run_dir:..."} (exit 4) | {"fatal": "build_runtime_failed:..."} (exit 5)
  stdin  dòng n : {"user": "..."}   ->  stdout: dict của `rt.ask(...)` + "llm_calls", "flags" (+ "files" gộp từ SANDBOX_DIR)
                  {"resume": {"run_id","interrupt_id","decision","payload"}} -> dict của `rt.resume(...)` (P5; interrupt sai/đã dùng => {"resume_error": "..."})
  Thời gian chờ hạ tầng (bộ giới hạn tốc độ + backoff của LLMCache) được cộng vào `llm.infra_wait_s` để runtime KHÔNG tính nó vào ngân sách wall_s (review P4 I2).
"""
import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path

REAL_STDOUT = sys.stdout


def emit(obj) -> None:
    REAL_STDOUT.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    REAL_STDOUT.flush()


def load_cache_module(path):
    spec = importlib.util.spec_from_file_location("eval_llm_cache", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    sys.stdout = sys.stderr                      # thư viện in gì cũng không làm bẩn kênh giao thức
    init = json.loads(sys.stdin.readline())
    run_dir = Path(str(init.get("run_dir")))
    if not run_dir.is_absolute():                # đường dẫn tương đối sẽ ghi bộ nhớ/log vào thư mục snapshot
        emit({"fatal": f"bad_run_dir:{init.get('run_dir')!r} (must be an absolute path)"})
        return 4
    run_dir.mkdir(parents=True, exist_ok=True)
    ablations = [str(a) for a in init.get("ablations") or []]
    budgets = init.get("budgets")
    checkpoint_db, trace_dir = run_dir / "checkpoints.sqlite", run_dir / "trace"
    os.environ["MEMORY_DB"] = str(run_dir / "memory.sqlite")
    os.environ["AUDIT_LOG"] = str(run_dir / "audit.jsonl")
    os.environ["SANDBOX_DIR"] = str(run_dir / "workspace_out")
    os.environ["BOARD_STATE_DB"] = str(run_dir / "board_state.sqlite")
    os.environ.pop("BOARD_STATE_PROJECT", None)  # runtime tự truyền project_id
    os.environ["AGENT_CHECKPOINT_DB"] = str(checkpoint_db)
    os.environ["AGENT_TRACE_DIR"] = str(trace_dir)
    os.environ["AGENT_ABLATIONS"] = ",".join(ablations)
    os.chdir(run_dir)
    sys.path.insert(0, str(init["snapshot"]))

    try:
        from agent.runtime.factory import build_runtime      # snapshot, không phải agent/ đang phát triển

        rt = build_runtime(transport="inproc", ablations=tuple(ablations), budgets=budgets, checkpoint_db=str(checkpoint_db), trace_dir=str(trace_dir))
    except Exception as exc:                      # snapshot thiếu/hỏng: dừng cả lượt chạy ngay thay vì để 12 run liên tiếp lỗi hạ tầng
        emit({"fatal": f"build_runtime_failed:{type(exc).__name__}: {str(exc)[:300]}"})
        return 5
    llm = rt.llm
    if getattr(llm, "simulated", True):
        emit({"fatal": "simulated_llm"})
        return 3

    lc = load_cache_module(init["cache_module"])
    rl = load_cache_module(str(Path(init["cache_module"]).with_name("ratelimit.py")))
    cache = lc.LLMCache(init["llm_cache"]["path"], init["llm_cache"]["mode"], limiter=rl.from_env())
    cache.set_seed(init["seed"])
    waited = {"s": 0.0}

    class TimedLimiter:
        def __init__(self, inner):
            self.inner = inner

        def acquire(self):
            t0 = time.monotonic()
            try:
                self.inner.acquire()
            finally:
                waited["s"] += time.monotonic() - t0

    if cache.limiter is not None:
        cache.limiter = TimedLimiter(cache.limiter)
    real_sleep = cache.sleep

    def timed_sleep(sec):
        t0 = time.monotonic()
        try:
            real_sleep(sec)
        finally:
            waited["s"] += time.monotonic() - t0

    cache.sleep = timed_sleep
    llm.infra_wait_s = 0.0
    # retry/pacing do LLMCache đảm nhiệm; tắt retry nội bộ của SDK để không có lời gọi nào vượt qua bộ giới hạn tốc độ
    llm.client = llm.client.with_options(max_retries=0)
    client = llm.client
    raw_create = client.chat.completions.create

    def timed_attempt(**kw):
        """Một tentative gọi API. Tentative THẤT BẠI (timeout/5xx/429 rồi LLMCache retry) là thời gian hạ tầng: cộng vào `waited` để runtime không tính nó vào wall_s
        (pilot P5: 3 run mất ~600 s ở MỘT lời gọi bị treo rồi retry thành công và bị xử là hết ngân sách wall_s)."""
        t0 = time.monotonic()
        try:
            return raw_create(**kw)
        except BaseException:
            waited["s"] += time.monotonic() - t0
            raise

    client.chat.completions.create = timed_attempt
    lc.wrap_client(client, cache)
    inner = client.chat.completions.create
    state = {"calls": 0, "flags": []}

    def tracked(**kw):
        try:
            return _tracked(**kw)
        finally:
            llm.infra_wait_s = waited["s"]

    def _tracked(**kw):
        try:
            resp = inner(**kw)
            state["calls"] += 1
            return resp
        except lc.CacheMiss:
            state["flags"].append("infra:cache_miss")
            raise
        except lc.FatalLLMError as exc:
            state["flags"].append(f"fatal:{exc}")
            raise
        except lc.InfraError as exc:
            state["flags"].append(f"infra:{exc}")
            raise
        except Exception as exc:
            state["flags"].append(f"error:{type(exc).__name__}: {str(exc)[:200]}")
            raise

    client.chat.completions.create = tracked
    emit({"ready": True, "llm": getattr(llm, "name", None)})

    sandbox = Path(os.environ["SANDBOX_DIR"])
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        state["calls"], state["flags"] = 0, []
        try:
            if "resume" in req:
                r = req["resume"]
                try:
                    res = rt.resume(r["run_id"], r["interrupt_id"], r["decision"], r.get("payload") or {})
                except ValueError as exc:                    # ResumeError: interrupt sai/đã dùng/quyết định không hợp lệ — không chạy gì
                    emit({"resume_error": str(exc), "answer": "", "status": "error", "events": [], "usage": {}, "llm_calls": 0, "flags": []})
                    continue
            else:
                res = rt.ask(req["user"], session_id=init["session_id"], seed=init["seed"])
        except Exception as exc:                  # lỗi bất ngờ của chính runtime -> lỗi hệ, không phải hạ tầng (cờ hạ tầng của wrapper vẫn được giữ)
            flags = list(dict.fromkeys([*state["flags"], f"error:{type(exc).__name__}: {str(exc)[:200]}"]))
            emit({"answer": "", "status": "error", "events": [], "usage": {}, "plan": [], "board_state": None, "gate": None, "escalation": None,
                  "files": {}, "errors": [], "llm_calls": state["calls"], "flags": flags, "traceback": traceback.format_exc()[-800:]})
            continue
        files = {p.name: p.read_text(encoding="utf-8", errors="replace")[:4000] for p in sandbox.glob("*") if p.is_file()} if sandbox.is_dir() else {}
        files.update(res.get("files") or {})
        emit({**res, "files": files, "llm_calls": state["calls"], "flags": state["flags"]})
    try:
        rt.close()
    except Exception:
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
