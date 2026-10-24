"""Worker cho S2 (Agent v1 đóng băng). Chạy bằng `python -I` trong MỘT tiến trình riêng cho mỗi task, để:
  * tên module `config`, `agent`, `mcp_servers`... của snapshot không xung đột với nơi khác;
  * `config` (đọc env lúc import) trỏ MEMORY_DB / AUDIT_LOG / SANDBOX_DIR vào thư mục tạm của run -> bộ nhớ episodic sạch
    và không ghi bẩn agent/data.
Giao thức (JSONL):
  stdin  dòng 1 : {"snapshot","run_dir","task_id","seed","session_id","llm_cache":{"mode","path"}, "cache_module": đường dẫn eval/llm_cache.py}
  stdout dòng 1 : {"ready": true, "llm": ...}  hoặc {"fatal": "simulated_llm"} (exit 3)
  stdin  dòng n : {"user": "..."}   ->  stdout: kết quả một lượt (answer, status, agent_trace, observations, ...)
"""
import importlib.util
import json
import os
import sys
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
    if not run_dir.is_absolute():                # đường dẫn tương đối sẽ ghi bộ nhớ/log vào thư mục snapshot (config.py của snapshot hiểu nó theo ROOT của snapshot)
        emit({"fatal": f"bad_run_dir:{init.get('run_dir')!r} (must be an absolute path)"})
        return 4
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MEMORY_DB"] = str(run_dir / "memory.sqlite")
    os.environ["AUDIT_LOG"] = str(run_dir / "audit.jsonl")
    os.environ["SANDBOX_DIR"] = str(run_dir / "workspace_out")
    os.chdir(run_dir)
    sys.path.insert(0, str(init["snapshot"]))

    from agent.react_agent import HardwareAgent      # snapshot, không phải agent/ đang phát triển
    import config

    agent = HardwareAgent(transport="inproc", name="agent_v1")
    if getattr(agent.llm, "simulated", True):
        emit({"fatal": "simulated_llm"})
        return 3

    lc = load_cache_module(init["cache_module"])
    rl = load_cache_module(str(Path(init["cache_module"]).with_name("ratelimit.py")))
    cache = lc.LLMCache(init["llm_cache"]["path"], init["llm_cache"]["mode"], limiter=rl.from_env())
    cache.set_seed(init["seed"])
    # retry/pacing do LLMCache đảm nhiệm; tắt retry nội bộ của SDK để không có lời gọi nào vượt qua bộ giới hạn tốc độ
    agent.llm.client = agent.llm.client.with_options(max_retries=0)
    client = agent.llm.client
    lc.wrap_client(client, cache)
    inner = client.chat.completions.create
    state = {"calls": 0, "flags": []}

    def tracked(**kw):
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
    emit({"ready": True, "llm": agent.llm.name})

    sandbox = Path(os.environ["SANDBOX_DIR"])
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        state["calls"], state["flags"] = 0, []
        try:
            res = agent.ask(req["user"], session_id=init["session_id"], seed=init["seed"])
        except Exception as exc:                  # lỗi bất ngờ của chính agent -> lỗi hệ, không phải hạ tầng
            emit({"answer": "", "status": "error", "agent_trace": [], "observations": [], "pending_actions": [],
                  "metrics": {}, "llm_calls": state["calls"], "verification": None, "files": {},
                  "flags": [f"error:{type(exc).__name__}: {str(exc)[:200]}"], "traceback": traceback.format_exc()[-800:]})
            continue
        files = {p.name: p.read_text(encoding="utf-8", errors="replace")[:4000] for p in sandbox.glob("*") if p.is_file()}
        emit({"answer": res["answer"], "status": res["status"], "agent_trace": res["trace"],
              "verification": res["verification"], "observations": res["observations"],
              "pending_actions": res["pending_actions"], "metrics": res["metrics"], "llm_calls": state["calls"],
              "flags": state["flags"], "files": files})
    return 0


if __name__ == "__main__":
    sys.exit(main())
