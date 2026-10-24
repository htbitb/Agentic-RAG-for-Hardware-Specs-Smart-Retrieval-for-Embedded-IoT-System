"""Runner: lập lịch (hệ x task x seed), chạy song song có giới hạn tốc độ, resume, timeout, ghi runs.jsonl + manifest.json.

    python -m eval.run --systems S0,S1,S2 --split dev --seeds 3 --workers 4 --cache record [--categories C1,C2] [--limit N]
    python -m eval.run --suite smoke --cache replay            # CI: chi phí 0 (cần cache đã record)
    python -m eval.run --resume eval/results/<timestamp> ...   # tiếp tục lượt chạy dở
    python -m eval.run --systems S3@P4 [--ablations A1,A3] ... # Agent v3 (cần snapshots/agent_p4); mỗi ablation là một biến thể riêng
    python -m eval.run --categories C5 --c5-oracle ...           # C5 (P5): người dùng mô phỏng trả lời interrupt / câu hỏi; thêm biến thể oracle-info

Sau khi chạy xong tự động chấm (eval.score) và sinh báo cáo (eval.report) trừ khi có --no-report.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from eval.adapters.agent_v3 import ABLATION_VARIANTS
from eval.adapters.base import FatalAdapterError
from eval.envload import LLMConfig
from eval.schema import RunResult, Task, is_hitl_task, load_tasks
from eval.sim_human import SimulatedHuman

ROOT = Path(__file__).resolve().parents[1]
CONFIRM_USD = 2.0
SYSTEMS_ALL = ["S0", "S1", "S2", "S2D", "S3@P4", "S3@P5"]
S3_SYSTEMS = ("S3@P4", "S3@P5")                      # hai thế hệ Agent v3 (mỗi thế hệ có snapshot và hàng kết quả riêng; hàng S3@P4 được giữ nguyên)
DEFAULT_SYSTEMS = ["S0", "S1", "S2", "S2D"]          # S3@P4/S3@P5 phải được yêu cầu rõ (--systems): cần snapshots/agent_p4 / agent_p5 và tốn nhiều lời gọi hơn hẳn
SNAPSHOT_P4 = ROOT / "snapshots" / "agent_p4"
SNAPSHOT_P5 = Path(os.environ.get("EVAL_SNAPSHOT_P5") or ROOT / "snapshots" / "agent_p5")      # EVAL_SNAPSHOT_P5 chỉ cho lượt PILOT trên bản chụp tạm; lượt chính thức dùng snapshots/agent_p5 (hash ghim trong manifest)
V3_MIN_TURN_TIMEOUT = 900.0                          # runtime v3 có ngân sách wall riêng bên dưới mức này; --timeout mặc định (180 s) sẽ cắt ngang nó

# Giả định để ước tính TRƯỚC khi chạy (số liệu đo thật từ eval/results/dev_baseline_v2, model ag/gemini-3.8-flash-medium qua gateway, 99 run/hệ, 1 lượt/run):
# "calls" = số lời gọi LLM mỗi lượt người dùng, "in"/"out" = token trung bình mỗi lời gọi (gateway cộng thêm ~2 000 token vào "in" mỗi lời gọi, D27).
ASSUMPTIONS = {"S0": {"calls": 1.0, "in": 3555, "out": 326}, "S1": {"calls": 1.0, "in": 3640, "out": 20},
               "S2": {"calls": 6.45, "in": 4190, "out": 35}, "S2D": {"calls": 4.06, "in": 7697, "out": 84},
               # S3@P4: số đo thật từ eval/results/pilot_p4_full + pilot_p4_round1 (38 run, 49 lượt, 1 seed: 662–685 lời gọi, 14,5 M token vào, 164 k ra); ghi lại khi đổi runtime/prompt
               "S3@P4": {"calls": 13.7, "in": 21600, "out": 240},
               # S3@P5: ước ban đầu = S3@P4 + schema ask_human (~+400 token/lời gọi) + lời mời hỏi/ask; hiệu chỉnh lại từ lượt đo thật đầu tiên của P5
               "S3@P5": {"calls": 14.5, "in": 22000, "out": 250}}
HISTORY_GROWTH = 0.25        # mỗi lượt thêm làm token đầu vào mỗi lời gọi tăng ~25 % (lịch sử hội thoại được gửi lại); chỉ áp cho task nhiều lượt
# C5 (P5): task có người dùng mô phỏng được tính thêm ~1 lượt người dùng (baseline hỏi lại rồi nhận câu trả lời / S3 chạy tiếp sau interrupt);
# giả định thô, chưa đo — ghi lại sau lượt chạy C5 đầu tiên
HITL_EXTRA_TURNS = 1.0
HITL_LOOP_MARGIN = 3         # số vòng resume tối đa mỗi lượt người dùng = max_answers + 3 (P5_interfaces §4, chống vòng lặp)


# ------------------------------------------------------------------ lập lịch
def parse_ablations(spec) -> list[str]:
    """'A1, a3' -> ['A1', 'A3'] (bỏ trùng, giữ thứ tự); mã lạ -> ValueError."""
    codes = list(dict.fromkeys(c.strip().upper() for c in (spec or "").split(",") if c.strip()))
    bad = [c for c in codes if c not in ABLATION_VARIANTS]
    if bad:
        raise ValueError(f"unknown ablation code(s) {bad}; valid: {', '.join(f'{c}={v}' for c, v in ABLATION_VARIANTS.items())}")
    return codes


def build_schedule(systems, tasks, seeds: int, ablations=()) -> list[tuple]:
    """(hệ, biến thể, task, seed). Với S3@P4, mỗi ablation là một biến thể riêng THAY CHO lượt chạy chính (chạy chính = không truyền --ablations;
    --resume bỏ qua phần đã xong). Hệ khác không bị ảnh hưởng."""
    variants = [ABLATION_VARIANTS[a] for a in ablations]
    return [(s, v, t.id, seed) for s in systems for v in (variants if s in S3_SYSTEMS and variants else [""])
            for t in sorted(tasks, key=lambda t: t.id) for seed in range(seeds)]


def load_done(path) -> set[tuple]:
    done: set[tuple] = set()
    p = Path(path)
    if not p.is_file():
        return done
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            done.add((d["system"], d["variant"], d["task_id"], d["seed"]))
        except (json.JSONDecodeError, KeyError):
            continue                                  # dòng cuối bị cắt khi tiến trình chết giữa chừng
    return done


def drop_infra_rows(path) -> int:
    """Chuyển các dòng run lỗi hạ tầng sang runs_infra_failed.jsonl để chúng trở thành 'chưa chạy' khi --resume --retry-infra."""
    p = Path(path)
    if not p.is_file():
        return 0
    keep, moved = [], []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        (moved if any(str(e).startswith("infra:") for e in d.get("errors", [])) else keep).append(line)
    if moved:
        with p.with_name("runs_infra_failed.jsonl").open("a", encoding="utf-8") as f:
            f.write("".join(l + "\n" for l in moved))
        p.write_text("".join(l + "\n" for l in keep), encoding="utf-8")
    return len(moved)


def ensure_trailing_newline(path) -> None:
    """Tiến trình chết giữa chừng có thể để lại dòng cụt không có dấu xuống dòng; thêm một dấu để dòng mới ghi tiếp không bị dính vào nó."""
    p = Path(path)
    if p.is_file() and p.stat().st_size:
        with p.open("rb+") as f:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                f.write(b"\n")


def set_aside_tail(path, n: int) -> None:
    """Chuyển n dòng cuối của runs.jsonl sang runs_infra_failed.jsonl để chúng trở thành 'chưa chạy' khi --resume."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines()
    keep, moved = lines[:-n], lines[-n:]
    with p.with_name("runs_infra_failed.jsonl").open("a", encoding="utf-8") as f:
        f.write("".join(l + "\n" for l in moved))
    p.write_text("".join(l + "\n" for l in keep), encoding="utf-8")


# lỗi 4xx từ LLM client: S1 ghi 'status=400', S0/S2 ghi 'Error code: 404' hoặc tên lớp (BadRequestError...)
_CLIENT_4XX = re.compile(r"(?:status=|Error code: )4\d\d\b|\b(?:BadRequest|NotFound|UnprocessableEntity)Error\b")


def sole_llm_client_error(res: RunResult) -> str | None:
    """Thông điệp lỗi DUY NHẤT của run nếu đó là `error:` 4xx từ LLM client (sai model/endpoint/payload), ngược lại None."""
    errs = set(res.errors)
    if len(errs) != 1:
        return None
    (e,) = errs
    return e if e.startswith("error:") and _CLIENT_4XX.search(e) else None


class ManifestMismatch(RuntimeError):
    """--resume vào thư mục có manifest khác model/temperature/split/snapshot: kết quả sẽ không so sánh được."""


RESUME_MUST_MATCH = ("model", "temperature", "split", "snapshot_agent_v1_sha256", "snapshot_agent_p1_sha256",
                     "snapshot_agent_p1_data_sha256", "snapshot_agent_p4_sha256", "snapshot_agent_p4_data_sha256",
                     "snapshot_agent_p5_sha256", "snapshot_agent_p5_data_sha256")
RESUME_ENTRY_KEYS = ("cache_mode", "task_set_sha256", "corpus_manifest_sha256", "snapshot_agent_v1_sha256",
                     "snapshot_agent_p1_sha256", "snapshot_agent_p1_data_sha256", "snapshot_agent_p4_sha256", "snapshot_agent_p4_data_sha256",
                     "snapshot_agent_p5_sha256", "snapshot_agent_p5_data_sha256",
                     "native_rag_changelog_sha256", "hwmodel_vendor_sha256", "hwmodel_data_sha256")
# hwmodel_vendor_sha256 KHÔNG nằm trong RESUME_MUST_MATCH: chấm điểm đọc runs.jsonl SAU khi chạy nên đổi bản vendor giữa các lần resume là hợp lệ
# (khác snapshot agent, vốn quyết định output của hệ); mọi lần đổi phải được ghi vào post_run_changes.


def check_resume_compatible(old: dict, new: dict) -> None:
    for k in RESUME_MUST_MATCH:
        # mỗi snapshot có hash riêng: khoá chưa có (hoặc None) trong manifest cũ = hệ đó chưa từng chạy ở đây, nên không so (thêm S2D
        # vào dev_baseline không bị chặn bởi hash agent_v1); khi đã ghi thì phải khớp mãi mãi
        if old.get(k) is not None and old.get(k) != new.get(k):
            raise ManifestMismatch(f"--resume bị từ chối: {k} khác manifest hiện có ({old.get(k)!r} -> {new.get(k)!r}); "
                                   f"kết quả không còn so sánh được, hãy chạy vào thư mục --out mới")


def merge_manifest(old: dict, new: dict) -> dict:
    """Khi --resume: GIỮ giá trị gốc của lần chạy đầu (created_at, args, seeds, split, cache_mode, model, temperature, các hash);
    thông tin của lần resume này (args, thời gian, hash lúc đó) nằm trong `resumes[]`. Từ chối nếu model/temperature/split/snapshot đổi."""
    check_resume_compatible(old, new)
    merged = {**new, **old}
    merged["resumed_at"] = [*old.get("resumed_at", []), new.get("created_at")]
    # resume chỉ một hệ (vd chạy lại vài run S1) không được làm mất các hệ khác khỏi manifest
    merged["systems"] = sorted({*old.get("systems", []), *new.get("systems", [])})
    merged["resumes"] = [*old.get("resumes", []), {"args": new.get("args"), "started_at": new.get("created_at"), "status": "running",
                                                   **{k: new.get(k) for k in RESUME_ENTRY_KEYS}}]
    return merged


def finish_manifest(manifest: dict, wall_seconds: float, status: str, reason: str | None = None) -> None:
    """Ghi thời điểm kết thúc + trạng thái cho lần chạy hiện tại (lần resume cuối nếu có; nếu không thì lần chạy gốc), kể cả khi dừng vì lỗi."""
    target = manifest["resumes"][-1] if manifest.get("resumes") else manifest
    target.update(finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), wall_seconds=round(wall_seconds, 1), status=status)
    if reason:
        target["stop_reason"] = reason


def pending(schedule, done) -> list[tuple]:
    return [s for s in schedule if s not in done]


def select_limit(tasks: list[Task], n: int) -> list[Task]:
    """Lấy n task xoay vòng qua các nhóm để --limit nhỏ vẫn phủ nhiều nhóm."""
    by_cat: dict[str, list[Task]] = {}
    for t in sorted(tasks, key=lambda t: t.id):
        by_cat.setdefault(t.category, []).append(t)
    out: list[Task] = []
    while len(out) < n and any(by_cat.values()):
        for cat in sorted(by_cat):
            if by_cat[cat] and len(out) < n:
                out.append(by_cat[cat].pop(0))
    return out


# ------------------------------------------------------------- chi phí / manifest
def estimate_cost(systems, n_tasks: int, seeds: int, cfg: LLMConfig, n_turns: int | None = None) -> dict:
    """`n_turns` = tổng số lượt người dùng của các task (nhiều lượt như C4): số lời gọi tỉ lệ với số lượt, không phải số run. Mặc định 1 lượt/task.
    Token đầu vào mỗi lời gọi nhân thêm (1 + HISTORY_GROWTH x (số lượt TB mỗi task − 1)) vì lịch sử được gửi lại."""
    per, calls, tin, tout = {}, 0, 0, 0                  # `systems` có thể lặp một tên (mỗi biến thể ablation của S3@P4 là một mục): cộng dồn
    avg_turns = (n_turns / n_tasks) if (n_turns is not None and n_tasks) else 1.0
    grow = 1.0 + HISTORY_GROWTH * max(0.0, avg_turns - 1.0)
    for s in systems:
        a = ASSUMPTIONS[s]
        runs = n_tasks * seeds
        turn_runs = (n_turns if n_turns is not None else n_tasks) * seeds
        c, i, o = round(turn_runs * a["calls"]), round(turn_runs * a["calls"] * a["in"] * grow), round(turn_runs * a["calls"] * a["out"])
        p = per.setdefault(s, {"runs": 0, "llm_calls": 0, "tokens_in": 0, "tokens_out": 0})
        p["runs"], p["llm_calls"], p["tokens_in"], p["tokens_out"] = p["runs"] + runs, p["llm_calls"] + c, p["tokens_in"] + i, p["tokens_out"] + o
        calls, tin, tout = calls + c, tin + i, tout + o
    for p in per.values():
        p["usd"] = round(cfg.cost(p["tokens_in"], p["tokens_out"]), 4)
    return {"runs": n_tasks * seeds * len(systems), "llm_calls": calls, "tokens_in": tin, "tokens_out": tout,
            "usd": round(cfg.cost(tin, tout), 4), "per_system": per, "assumptions": ASSUMPTIONS}


def task_turns(task: Task) -> float:
    """Số lượt người dùng dùng để ước tính chi phí: lượt của task + HITL_EXTRA_TURNS nếu task có người dùng mô phỏng (C5)."""
    return len(task.turns) + (HITL_EXTRA_TURNS if is_hitl_task(task) else 0.0)


def needs_confirmation(est: dict, threshold: float = CONFIRM_USD) -> bool:
    return est["usd"] > threshold


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def snapshot_checksum(snapshot: Path = ROOT / "snapshots" / "agent_v1") -> str:
    """Cùng công thức với SNAPSHOT.md: sha256 của `find . -name '*.py' | sort | xargs shasum -a 256` (đường dẫn dạng ./...)."""
    files = sorted(snapshot.rglob("*.py"), key=lambda p: "./" + p.relative_to(snapshot).as_posix())
    listing = "".join(f"{_sha256_file(p)}  ./{p.relative_to(snapshot).as_posix()}\n" for p in files)
    return hashlib.sha256(listing.encode()).hexdigest()


def snapshot_data_checksum(snapshot: Path) -> str | None:
    """sha256 của danh sách (sha256, đường dẫn) các file dữ liệu (*.sqlite, *.npy) của snapshot; None nếu không có.
    Với S2D dữ liệu chính là biến độc lập nên phải được ghim như mã (checksum .py không phủ chúng)."""
    files = sorted((p for p in snapshot.rglob("*") if p.is_file() and p.suffix in (".sqlite", ".npy")),
                   key=lambda p: "./" + p.relative_to(snapshot).as_posix())
    if not files:
        return None
    listing = "".join(f"{_sha256_file(p)}  ./{p.relative_to(snapshot).as_posix()}\n" for p in files)
    return hashlib.sha256(listing.encode()).hexdigest()


def _commit() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def build_manifest(cfg: LLMConfig, systems, tasks, seeds: int, split, cache_mode: str, args: dict) -> dict:
    from eval import sandbox

    task_blob = json.dumps(sorted((t.id, t.version, t.to_dict()) for t in tasks), sort_keys=True, ensure_ascii=False, default=str)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **{k: v for k, v in cfg.public_dict().items() if k != "api_key_set"},
        "api_key_set": bool(cfg.api_key),
        "corpus_manifest_sha256": _sha256_file(ROOT / "corpus" / "manifest.yaml"),
        "snapshot_agent_v1_sha256": snapshot_checksum(),
        "snapshot_agent_p1_sha256": snapshot_checksum(ROOT / "snapshots" / "agent_p1") if (ROOT / "snapshots" / "agent_p1").is_dir() else None,
        "snapshot_agent_p1_data_sha256": snapshot_data_checksum(ROOT / "snapshots" / "agent_p1") if (ROOT / "snapshots" / "agent_p1").is_dir() else None,
        "snapshot_agent_p4_sha256": snapshot_checksum(SNAPSHOT_P4) if SNAPSHOT_P4.is_dir() else None,
        "snapshot_agent_p4_data_sha256": snapshot_data_checksum(SNAPSHOT_P4) if SNAPSHOT_P4.is_dir() else None,
        "snapshot_agent_p5_sha256": snapshot_checksum(SNAPSHOT_P5) if SNAPSHOT_P5.is_dir() else None,
        "snapshot_agent_p5_data_sha256": snapshot_data_checksum(SNAPSHOT_P5) if SNAPSHOT_P5.is_dir() else None,
        "native_rag_changelog_sha256": _sha256_file(ROOT / "native-RAG" / "CHANGELOG_EVAL.md"),
        **sandbox.vendor_hashes(),                    # hwmodel đóng băng dùng cho grader functional_sim/compile (D19)
        "commit": _commit(), "seeds": seeds, "systems": list(systems), "split": split, "cache_mode": cache_mode,
        "n_tasks": len(tasks), "task_set_sha256": hashlib.sha256(task_blob.encode()).hexdigest(),
        "python": sys.version.split()[0], "platform": platform.platform(), "args": args,
        "known_issues": [
            "Agent v1 trích dẫn 'FreeRTOS v10.5.0' trong khi PDF corpus là FreeRTOS V8.2.1 (không sửa trong P0).",
            "Dữ liệu Agent v1 là hằng số mô phỏng (3 chân, 11 thanh ghi, 8 đoạn văn); điểm thấp trên task sinh từ SVD là baseline hợp lệ.",
            "Gemini bỏ qua `seed` và API có thể không xác định ngay cả ở temperature 0; mỗi seed được ghi nhận độc lập trong cache.",
            "Task C1 review_status=auto; C2/C6/C7/C8 chưa có người duyệt độc lập.",
            "S2D = vòng lặp/verifier/guardrail của Agent v1 (byte-identical) + dữ liệu thật của P1 (snapshots/agent_p1); S2→S2D đo đóng góp của DỮ LIỆU.",
            "S2D: guardrail.evaluate_hw (không đổi, D10) lấy MIN trên mọi hàng input_voltage nên 5 V vào chân STM32 FT cũng bị từ chối; không chặn 'VDDH' của nRF.",
            "S2D: 779 thanh ghi chỉ có trong SVD (page=null; ESP32 661, STM32 101, nRF 17) không thể qua verifier V3 ⇒ trả lời 'Insufficient evidence'.",
        ],
    }


# ------------------------------------------------------------------- thực thi
class RateLimiter:
    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps and rps > 0 else 0.0
        self.lock = threading.Lock()
        self.next = 0.0

    def acquire(self) -> None:
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            wait = max(0.0, self.next - now)
            self.next = max(now, self.next) + self.interval
        if wait:
            time.sleep(wait)


class RepeatedClientError(FatalAdapterError):
    """N run liên tiếp cùng một lỗi 4xx từ LLM client: n dòng cuối của runs.jsonl bị đưa sang runs_infra_failed.jsonl."""

    def __init__(self, msg: str, n: int):
        super().__init__(f"{n} consecutive runs failed with the same LLM client error ({msg[:200]}) - likely a wrong model/endpoint/"
                         f"payload, not a system result; those {n} rows were moved to runs_infra_failed.jsonl, fix and rerun with --resume")
        self.n = n


class HitlStop(Exception):
    """Hội thoại của run dừng sớm (vượt giới hạn vòng interrupt hoặc resume lỗi); lỗi đã nằm trong HumanLoop.errors."""


class HumanLoop:
    """Vòng người–hệ của MỘT run (plan/P5_interfaces.md §4), dùng SimulatedHuman theo `human_policy`/`hidden_info` của task.

    * Adapter có `resume` (S3 có HITL): mỗi lần `send`/`resume` trả `status == "interrupted"` ⇒ SimulatedHuman trả lời interrupt, runner ghi `human_reply`
      rồi gọi `adapter.resume(interrupt_id, decision, payload)` và ghi `resume_result`. Quá `max_answers + 3` vòng trong một lượt ⇒ sự kiện `hitl_loop`,
      lỗi `error:hitl_loop` (lỗi của HỆ) và dừng hội thoại. Resume ném lỗi ⇒ `error:resume:...`, dừng hội thoại (trace vẫn được giữ).
      Hệ có HITL KHÔNG bị áp quy tắc câu hỏi văn bản.
    * Adapter không có `resume` (baseline) trên task có người dùng mô phỏng (`is_hitl_task`): nếu câu trả lời chứa câu hỏi hướng tới người dùng
      (`detect_question`) ⇒ gửi câu trả lời của SimulatedHuman như lượt người dùng KẾ TIẾP (tối đa `max_answers` lượt bổ sung cho cả run; lượt này nằm
      trong `RunResult.turns` nhưng không phải lượt của task) và ghi `human_reply` source=baseline_text. Task cũ (C1–C4, C6–C8) không đổi hành vi.
    Sự kiện mang `turn` = chỉ số lượt người dùng đã gửi (0-based, kể cả lượt bổ sung) và được nối vào cuối `RunResult.trace` khi run kết thúc.
    """

    def __init__(self, task: Task):
        self.human = SimulatedHuman(task.human_policy, task.hidden_info)
        self.text_rule = is_hitl_task(task)
        self.limit = self.human.max_answers + HITL_LOOP_MARGIN
        self.events: list[dict] = []
        self.errors: list[str] = []
        self.sent = 0                 # số lượt người dùng đã gửi (chỉ số `turn` của sự kiện)
        self.extra = 0                # số lượt bổ sung của baseline đã dùng

    def turn(self, adapter, user_msg: str):
        result = self._send(adapter, user_msg)
        if hasattr(adapter, "resume") or not self.text_rule:
            return result
        while self.extra < self.human.max_answers and getattr(result, "status", None) != "error":
            reply = self.human.reply_to_text(getattr(result, "answer", "") or "")
            if reply is None:
                break
            self._log(reply, self.sent - 1)
            self.extra += 1
            result = self._send(adapter, reply.payload["answer"])
        return result

    def _send(self, adapter, msg: str):
        idx = self.sent
        self.sent += 1
        result = adapter.send(msg)
        rounds = 0
        while getattr(result, "status", None) == "interrupted" and hasattr(adapter, "resume"):
            intr = getattr(result, "interrupt", None) or {}
            if rounds >= self.limit:
                self.events.append({"type": "hitl_loop", "turn": idx, "interrupt_id": intr.get("id"), "rounds": rounds})
                self.errors.append(f"error:hitl_loop: still interrupted after {rounds} resume rounds (limit = max_answers + {HITL_LOOP_MARGIN})")
                raise HitlStop
            reply = self.human.respond(intr)
            self._log(reply, idx, interrupt_id=intr.get("id"))
            try:
                result = adapter.resume(intr.get("id"), reply.decision, reply.payload)
            except FatalAdapterError:
                raise
            except Exception as exc:          # ResumeError... của hệ: ghi lại, dừng hội thoại, vẫn lấy trace qua finish()
                msg = f"{type(exc).__name__}: {str(exc)[:200]}"
                self.events.append({"type": "resume_result", "turn": idx, "interrupt_id": intr.get("id"), "status": "error", "error": msg})
                self.errors.append(f"error:resume:{msg}")
                raise HitlStop from exc
            self.events.append({"type": "resume_result", "turn": idx, "interrupt_id": intr.get("id"), "status": getattr(result, "status", None)})
            rounds += 1
        return result

    def _log(self, reply, turn: int, **extra) -> None:
        r = reply.record
        self.events.append({"type": "human_reply", "turn": turn, "kind": r["kind"], "question": r["question"][:2000], "matched": list(r["matched"]),
                            "necessary": r["necessary"], "answered": r["answered"], "decision": r["decision"], "source": r["source"],
                            "index": r["index"], "answer": r["answer"][:2000], **extra})

    def attach(self, result: RunResult) -> RunResult:
        result.trace = [*(result.trace or []), *self.events]
        result.errors = [*result.errors, *(e for e in self.errors if e not in result.errors)]
        return result


class Runner:
    def __init__(self, out_dir, factories: dict, workers: int = 4, rps: float = 4.0, max_consecutive_infra: int = 12,
                 max_consecutive_same_error: int = 8, log=lambda m: print(m, file=sys.stderr, flush=True)):
        self.out_dir, self.factories, self.workers, self.log = Path(out_dir), factories, workers, log
        self.max_consecutive_infra = max_consecutive_infra
        self.max_consecutive_same_error = max_consecutive_same_error
        self._streak = 0
        self._err_msg, self._err_streak = None, 0
        self.cache_misses = 0                          # số run kết thúc bằng infra:cache_miss trong lần chạy này
        self.limiter = RateLimiter(rps)
        self._local = threading.local()
        self._adapters: list = []
        self._lock = threading.Lock()
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _adapter(self, system: str, variant: str = ""):
        """Một adapter cho mỗi (hệ, biến thể) trên mỗi luồng. Biến thể ablation cần factory khoá `(hệ, biến thể)`; hệ chính dùng khoá `hệ`."""
        cache = getattr(self._local, "cache", None)
        if cache is None:
            cache = self._local.cache = {}
        key = (system, variant)
        if key not in cache:
            cache[key] = self.factories[key if variant else system]()
            with self._lock:
                self._adapters.append(cache[key])
        return cache[key]

    def _execute(self, key: tuple, task: Task) -> RunResult:
        system, variant, _, seed = key
        self.limiter.acquire()
        adapter = self._adapter(system, variant)
        t0 = time.time()
        try:
            adapter.start(task, seed)
            loop = HumanLoop(task)
            try:
                for turn in task.turns:
                    loop.turn(adapter, turn["user"])
            except HitlStop:
                pass                          # lỗi đã ghi; không gửi lượt nào nữa cho hệ đang kẹt
            return loop.attach(adapter.finish())
        except FatalAdapterError:
            raise
        except Exception as exc:          # lỗi bất ngờ trong adapter -> lỗi của HỆ (tính vào TSR), không làm sập cả lượt chạy
            try:
                adapter.close()
            except Exception:
                pass
            return RunResult(system=system, variant=variant, task_id=task.id, seed=seed,
                             errors=[f"error:{type(exc).__name__}: {str(exc)[:300]}"], latency_s=round(time.time() - t0, 3))

    def run(self, schedule, tasks_by_id: dict) -> int:
        runs_path = self.out_dir / "runs.jsonl"
        ensure_trailing_newline(runs_path)
        write_lock = threading.Lock()
        done = 0
        try:
            with runs_path.open("a", encoding="utf-8") as out, cf.ThreadPoolExecutor(max_workers=self.workers) as ex:
                futs = {ex.submit(self._execute, key, tasks_by_id[key[2]]): key for key in schedule}
                order = {fut: i for i, fut in enumerate(futs)}
                pending = set(futs)

                def completed():
                    """Các future xong theo THỨ TỰ LỊCH (không phải thứ tự tuỳ ý của tập): bộ ngắt 'N lỗi liên tiếp' và dòng ghi ra không phụ thuộc máy tải."""
                    nonlocal pending
                    while pending:
                        ready, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
                        yield from sorted(ready, key=order.__getitem__)

                try:
                    for fut in completed():
                        res = fut.result()            # FatalAdapterError được ném lại ở đây
                        with write_lock:
                            out.write(json.dumps(res.to_dict(), ensure_ascii=False) + "\n")
                            out.flush()
                        done += 1
                        self._streak = self._streak + 1 if res.has_infra_error() else 0
                        self.cache_misses += "infra:cache_miss" in res.errors
                        msg = sole_llm_client_error(res)
                        self._err_streak = self._err_streak + 1 if msg and msg == self._err_msg else (1 if msg else 0)
                        self._err_msg = msg
                        if self.max_consecutive_infra and self._streak >= self.max_consecutive_infra:
                            raise FatalAdapterError(f"{self._streak} consecutive runs failed with infra errors "
                                                    f"(API quota/outage?) - stopping; progress is saved, rerun with --resume")
                        if self.max_consecutive_same_error and self._err_streak >= self.max_consecutive_same_error:
                            raise RepeatedClientError(msg, self._err_streak)
                        if done % 10 == 0 or done == len(schedule):
                            infra = "infra" if res.has_infra_error() else "ok"
                            self.log(f"[{done}/{len(schedule)}] {res.system} {res.task_id} seed={res.seed} ({infra})")
                except BaseException:
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise
                finally:
                    for a in self._adapters:
                        try:
                            a.close()
                        except Exception:
                            pass
        except RepeatedClientError as exc:
            set_aside_tail(runs_path, exc.n)          # file đã đóng; các dòng này không phải kết quả của hệ nên phải chạy lại khi --resume
            raise
        return done


# ------------------------------------------------------------------------ CLI
def make_factories(cfg: LLMConfig, cache_mode: str, timeout: float) -> dict:
    from eval import ratelimit
    from eval.adapters.agent_v1 import WORKER, AgentV1Adapter
    from eval.adapters.agent_v3 import WORKER as WORKER_V3, AgentV3Adapter
    from eval.adapters.direct_llm import DirectLLMAdapter
    from eval.adapters.native_rag import NativeRAGAdapter
    from eval.llm_cache import LLMCache

    llm_db = ROOT / "eval" / ".cache" / "llm_cache.sqlite"
    rag_db = ROOT / "eval" / ".cache" / "native_rag_llm.sqlite"

    def v3(name="S3@P4", snapshot=SNAPSHOT_P4, **kw):
        # S3@P4/S3@P5: snapshot tương ứng trên interpreter của agent/.venv; timeout mỗi lượt không thấp hơn 600 s (runtime tự có ngân sách wall bên dưới)
        return AgentV3Adapter(cfg, cache_mode=cache_mode, cache_path=llm_db, timeout=max(timeout, V3_MIN_TURN_TIMEOUT), snapshot=snapshot, name=name,
                              cmd=[str(ROOT / "agent" / ".venv" / "bin" / "python"), "-I", "-B", str(WORKER_V3)], **kw)

    return {
        "S0": lambda: DirectLLMAdapter(cfg, cache=LLMCache(llm_db, cache_mode, limiter=ratelimit.from_env())),
        "S1": lambda: NativeRAGAdapter(cfg, cache_mode=cache_mode, cache_path=rag_db, timeout=timeout),
        "S2": lambda: AgentV1Adapter(cfg, cache_mode=cache_mode, cache_path=llm_db, timeout=timeout),
        # S2D = vòng lặp v1 + dữ liệu P1: snapshot agent_p1, chạy bằng interpreter của agent/.venv (cần numpy/sentence-transformers)
        "S2D": lambda: AgentV1Adapter(cfg, cache_mode=cache_mode, cache_path=llm_db, timeout=timeout, name="S2D",
                                      snapshot=ROOT / "snapshots" / "agent_p1",
                                      cmd=[str(ROOT / "agent" / ".venv" / "bin" / "python"), "-I", "-B", str(WORKER)]),
        "S3@P4": v3,
        "S3@P5": lambda: v3(name="S3@P5", snapshot=SNAPSHOT_P5),
        # biến thể ablation: khoá (hệ, biến thể); mỗi mục một adapter riêng mang nhãn biến thể và cờ ablation của nó
        **{("S3@P4", variant): (lambda code=code, variant=variant: v3(ablations=[code], variant=variant)) for code, variant in ABLATION_VARIANTS.items()},
        **{("S3@P5", variant): (lambda code=code, variant=variant: v3(name="S3@P5", snapshot=SNAPSHOT_P5, ablations=[code], variant=variant)) for code, variant in ABLATION_VARIANTS.items()},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default=",".join(DEFAULT_SYSTEMS), help=f"mặc định {','.join(DEFAULT_SYSTEMS)}; thêm S3@P4 để đo Agent v3")
    ap.add_argument("--ablations", default="", help="chỉ với S3@P4/S3@P5: A1=-Planner, A2=-BoardState, A3=-Sandbox, A4=-Reflection, A6=-HITL (phân tách bằng dấu phẩy); "
                    "mỗi ablation là một biến thể riêng THAY CHO lượt chạy chính của S3@P4")
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--categories")
    ap.add_argument("--suite")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--seeds", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", default="record", choices=["off", "record", "replay"])
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--rps", type=float, default=4.0, help="tốc độ KHỞI ĐỘNG run (không phải tốc độ gọi API)")
    ap.add_argument("--llm-rpm", type=float, default=12.0,
                    help="giới hạn số lời gọi LLM THẬT mỗi phút, dùng chung mọi hệ/tiến trình (free tier Gemini: 15 RPM); 0 = không giới hạn")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--resume", type=Path)
    ap.add_argument("--yes", action="store_true", help="chấp nhận chi phí ước tính > 2 USD (sau khi người dùng đã xác nhận)")
    ap.add_argument("--retry-infra", action="store_true", help="với --resume: chạy lại các run đã bị lỗi hạ tầng (chuyển dòng cũ sang runs_infra_failed.jsonl)")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in lịch chạy + ước tính chi phí")
    ap.add_argument("--c5-oracle", action="store_true", help="P5: xếp lịch thêm biến thể oracle-info (C5-xxx-O: thông tin ẩn đưa sẵn ở lượt đầu) của mọi task có hidden_info")
    a = ap.parse_args(argv)

    systems = [s.strip() for s in a.systems.split(",") if s.strip()]
    unknown = set(systems) - set(SYSTEMS_ALL)
    if unknown:
        ap.error(f"hệ không hỗ trợ trong P0: {sorted(unknown)}")
    try:
        ablations = parse_ablations(a.ablations)
    except ValueError as exc:
        ap.error(str(exc))
    if ablations and not set(S3_SYSTEMS) & set(systems):
        ap.error("--ablations chỉ áp dụng cho hệ S3 (thêm S3@P4 hoặc S3@P5 vào --systems)")
    seeds = a.seeds if a.seeds is not None else (1 if a.suite else 3)
    cfg = LLMConfig.load()
    if a.cache != "replay" and not cfg.api_key:
        print("Thiếu LLM_API_KEY (agent/.env hoặc môi trường): không thể chạy S0/S1/S2 với model thật.", file=sys.stderr)
        return 2
    if a.cache == "replay" and not cfg.api_key:
        cfg = replace(cfg, api_key="replay-only-no-network")

    tasks = load_tasks(ROOT / "eval" / "tasks", split=None if a.suite else a.split,
                       categories=a.categories.split(",") if a.categories else None, suite=a.suite, oracle=a.c5_oracle)
    if a.limit:
        tasks = select_limit(tasks, a.limit)
    if not tasks:
        print("Không có task nào khớp bộ lọc.", file=sys.stderr)
        return 2

    out_dir = a.resume or a.out or ROOT / "eval" / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")
    schedule = build_schedule(systems, tasks, seeds, ablations)
    manifest = build_manifest(cfg, systems, tasks, seeds, None if a.suite else a.split, a.cache,
                              {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()})
    manifest["suite"] = a.suite
    old_path = out_dir / "manifest.json"
    old = json.loads(old_path.read_text(encoding="utf-8")) if a.resume and old_path.exists() else None
    if old is not None:                                # kiểm tra TRƯỚC khi đụng vào bất kỳ file nào (kể cả --retry-infra)
        try:
            check_resume_compatible(old, manifest)
        except ManifestMismatch as exc:
            print(f"DỪNG: {exc}", file=sys.stderr)
            return 2
    if a.retry_infra and not a.dry_run:
        n_moved = drop_infra_rows(out_dir / "runs.jsonl")
        print(f"--retry-infra: {n_moved} run lỗi hạ tầng được đưa sang runs_infra_failed.jsonl để chạy lại", file=sys.stderr)
    todo = pending(schedule, load_done(out_dir / "runs.jsonl"))
    todo_ids = {s[2] for s in todo}
    est_systems = [s for s, _ in dict.fromkeys((e[0], e[1]) for e in schedule)]          # một mục cho mỗi (hệ, biến thể)
    est = (estimate_cost(est_systems, len(todo_ids), seeds, cfg, n_turns=sum(task_turns(t) for t in tasks if t.id in todo_ids))
           if todo else {"usd": 0.0, "runs": 0, "llm_calls": 0})
    live = a.cache != "replay"
    print(f"Lịch chạy: {len(schedule)} run, còn lại {len(todo)} | hệ={systems} task={len(tasks)} seeds={seeds} cache={a.cache}"
          + (f" ablations={ablations}" if ablations else ""), file=sys.stderr)
    if live and a.llm_rpm:
        print(f"Giới hạn {a.llm_rpm:g} lời gọi LLM thật/phút -> tối thiểu ~{est['llm_calls'] / a.llm_rpm:.0f} phút cho phần chưa có cache", file=sys.stderr)
    print(f"Ước tính (chỉ khi gọi API thật): ~{est['llm_calls']} LLM call, ~${est['usd']:.3f}"
          f" (giá {cfg.price_in}/{cfg.price_out} USD/1M token in/out; cache hit thì chi phí thấp hơn)", file=sys.stderr)
    if a.dry_run:
        return 0
    if live and needs_confirmation(est) and not a.yes:
        print(f"Chi phí ước tính ${est['usd']:.2f} > ${CONFIRM_USD:.2f}: cần người dùng xác nhận, chạy lại với --yes.", file=sys.stderr)
        return 2
    if not todo:
        print("Không còn gì để chạy.", file=sys.stderr)
    out_dir.mkdir(parents=True, exist_ok=True)
    if old is not None:
        manifest = merge_manifest(old, manifest)
    (manifest["resumes"][-1] if old is not None else manifest).update(estimate=est, status="running")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    os.environ["EVAL_LLM_RPM"] = str(a.llm_rpm if live else 0)           # tiến trình con kế thừa
    os.environ["EVAL_RATE_FILE"] = str(ROOT / "eval" / ".cache" / "llm_rate.lock")
    runner = Runner(out_dir, make_factories(cfg, a.cache, a.timeout), workers=a.workers, rps=a.rps)
    t0 = time.time()

    def close_manifest(status: str, reason: str | None = None) -> None:
        finish_manifest(manifest, time.time() - t0, status, reason)
        (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def miss_note() -> str:
        return (f"REPLAY: {runner.cache_misses} run kết thúc bằng infra:cache_miss (cache thiếu bản ghi cho lời gọi/truy hồi đó; "
                f"chạy replay không hoàn chỉnh)") if a.cache == "replay" and runner.cache_misses else ""

    try:
        n = runner.run(todo, {t.id: t for t in tasks})
    except FatalAdapterError as exc:
        close_manifest("stopped_fatal", str(exc)[:500])
        print(f"DỪNG: {exc}", file=sys.stderr)
        if miss_note():
            print(miss_note(), file=sys.stderr)
        return 3
    except BaseException as exc:                      # Ctrl-C hoặc lỗi bất ngờ: vẫn ghi thời điểm kết thúc
        close_manifest("interrupted", type(exc).__name__)
        raise
    close_manifest("completed")
    target = manifest["resumes"][-1] if old is not None else manifest
    print(f"Đã chạy {n} run trong {target['wall_seconds']}s -> {out_dir}", file=sys.stderr)
    if not a.no_report:
        from eval import report, score

        score.main(["--run", str(out_dir)])
        report.main(["--run", str(out_dir)])
    if miss_note():
        print(miss_note(), file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
