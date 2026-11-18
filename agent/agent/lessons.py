"""Lesson memory (P7, plan §4 W6, D48): bộ nhớ DÀI HẠN kiểu Reflexion, xác định (không gọi LLM để tóm tắt).

Chính sách GHI (_learn trong runtime, sau khi finish được Gate chấp nhận):
  * chỉ khi bản được chấp nhận qua G2 = "pass" (simulator XÁC NHẬN; skipped/na không tính) và run KHÔNG nhận observation bị gắn cờ injection (chống đầu độc bộ nhớ);
  * mỗi mã lỗi G2 (gate G2, severity error, trừ mã hạ tầng/không sửa được bằng code) xuất hiện ở một bản nháp TRƯỚC và KHÔNG còn ở bản được chấp nhận
    => một lesson {chip, peripheral, error_code, trigger_pattern, fix, evidence_run_id}; fix = các dòng C thêm/bớt giữa bản lỗi và bản đúng (bỏ chú thích, tối đa 14 dòng / 700 ký tự);
  * không có thay đổi mã, không xác định được chip hoặc ngoại vi, hoặc văn bản lesson bị bộ lọc injection gắn cờ => không ghi. Trùng (chip, họ ngoại vi, mã, fix) => không ghi lại.
Chính sách ĐỌC (INTAKE): chip của lượt + họ ngoại vi nêu trong mục tiêu (TIM1 và TIM8 cùng họ "TIM-ADV": bộ định thời nâng cao, RM0440) => tối đa 3 lesson, đưa vào ngữ cảnh như GỢI Ý
chưa kiểm chứng (system message), không phải tài liệu: agent vẫn phải mô phỏng.
Cô lập (D05): mỗi run của eval có LESSONS_DB riêng (thư mục run, trống); snapshot không mang theo lessons.sqlite; học từ dev không được lọt vào test.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import sqlite3
import threading
import time

from agent import guardrail
from agent.gate import codeblocks

EXCLUDED_CODES = {"G2-TOOL-ERROR", "G2-SKIPPED", "G2-UNMODELED", "G2-UNSUPPORTED", "G2-START-MISMATCH", "G2-NO-CODE"}
MAX_FIX_LINES, MAX_FIX_CHARS, MAX_LESSONS, MAX_CONTEXT_CHARS = 14, 700, 3, 1800
_PERIPH = re.compile(r"\b(TIM\d{1,2}|LPTIM\d|LPUART\d|USART\d|UART\d|I2C\d|SPI\d|ADC\d|DAC\d|FDCAN\d|DMA\d|GPIO[A-G]|RCC|PWR|FLASH|CRS|IWDG|WWDG|RTC)\b")
_FAMILY_TIM = {"TIM1": "TIM-ADV", "TIM8": "TIM-ADV", "TIM20": "TIM-ADV",                      # RM0440: bộ định thời điều khiển nâng cao (BDTR.MOE, dead time, break)
               "TIM2": "TIM-GP", "TIM3": "TIM-GP", "TIM4": "TIM-GP", "TIM5": "TIM-GP",
               "TIM6": "TIM-BASIC", "TIM7": "TIM-BASIC", "TIM15": "TIM-GP2", "TIM16": "TIM-GP2", "TIM17": "TIM-GP2"}
_COMMENT = re.compile(r"/\*.*?\*/|//.*$")


def extract_peripherals(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) for m in _PERIPH.finditer(text or "")))


def family(peripheral: str) -> str:
    """Họ của một ngoại vi (TIM1 -> TIM-ADV, USART3 -> USART). Nhận cả nhãn họ có sẵn (idempotent)."""
    p = (peripheral or "").upper()
    return p if p in set(_FAMILY_TIM.values()) else (_FAMILY_TIM.get(p) or re.sub(r"\d+$", "", p))


def code_diff(old: str, new: str) -> str:
    """Các dòng C thêm (+) / bớt (-) giữa hai bản mã, bỏ chú thích và dòng trống, gọn."""
    def norm(code: str) -> list[str]:
        return [re.sub(r"\s+", " ", _COMMENT.sub("", ln)).strip() for ln in (code or "").splitlines() if _COMMENT.sub("", ln).strip()]
    out = [ln for ln in difflib.unified_diff(norm(old), norm(new), lineterm="", n=0) if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    text = "\n".join(out[:MAX_FIX_LINES])
    return text[:MAX_FIX_CHARS]


class LessonStore:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        with self._lock, self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS lessons (id TEXT PRIMARY KEY, chip TEXT NOT NULL, peripheral TEXT NOT NULL, family TEXT NOT NULL, error_code TEXT NOT NULL, "
                      "trigger_pattern TEXT NOT NULL, fix TEXT NOT NULL, evidence_run_id TEXT NOT NULL, created REAL NOT NULL, uses INTEGER NOT NULL DEFAULT 0)")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, *, chip: str, peripheral: str, error_code: str, trigger_pattern: str, fix: str, evidence_run_id: str) -> dict | None:
        """Ghi một lesson; trả bản ghi nếu MỚI, None nếu trùng (cùng chip, họ ngoại vi, mã lỗi, fix)."""
        fam = family(peripheral)
        lid = "L-" + hashlib.sha256(f"{chip}|{fam}|{error_code}|{fix}".encode()).hexdigest()[:8]
        row = {"id": lid, "chip": chip.lower(), "peripheral": peripheral.upper(), "family": fam, "error_code": error_code, "trigger_pattern": trigger_pattern,
               "fix": fix, "evidence_run_id": evidence_run_id, "created": time.time(), "uses": 0}
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO lessons VALUES (:id,:chip,:peripheral,:family,:error_code,:trigger_pattern,:fix,:evidence_run_id,:created,:uses)", row)
            return row if cur.rowcount else None

    def search(self, chip: str, families, error_code: str | None = None, k: int = MAX_LESSONS) -> list[dict]:
        fams = sorted({family(f) for f in families})
        if not chip or not fams:
            return []
        q = f"SELECT * FROM lessons WHERE chip=? AND family IN ({','.join('?' * len(fams))})"
        args: list = [chip.lower(), *fams]
        if error_code:
            q += " AND error_code=?"
            args.append(error_code)
        q += " ORDER BY uses DESC, created DESC LIMIT ?"
        with self._lock, self._conn() as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(q, [*args, k])]

    def mark_used(self, ids) -> None:
        with self._lock, self._conn() as c:
            c.executemany("UPDATE lessons SET uses = uses + 1 WHERE id = ?", [(i,) for i in ids])

    def all(self) -> list[dict]:
        with self._lock, self._conn() as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM lessons ORDER BY created")]


def lessons_from_run(artifacts: list[dict], chip: str | None, run_id: str) -> list[dict]:
    """Các lesson (chưa ghi) rút từ chuỗi bản nháp của một run: mỗi mã lỗi G2 ở bản nháp trước mà bản được chấp nhận (cuối) không còn, kèm diff mã. Bản cuối phải qua G2."""
    if not artifacts or not chip:
        return []
    final = artifacts[-1]
    gate = final.get("gate") or {}
    if not final.get("passed") or (gate.get("gates") or {}).get("G2") != "pass":
        return []
    still = {f.get("code") for f in gate.get("findings") or []}
    new_code = codeblocks.extract_c_code(final.get("text", ""))
    out, seen = [], set()
    for art in artifacts[:-1]:
        old_code = codeblocks.extract_c_code(art.get("text", ""))
        for f in (art.get("gate") or {}).get("findings") or []:
            code = f.get("code")
            if f.get("gate") != "G2" or f.get("severity") != "error" or code in EXCLUDED_CODES or code in still or code in seen:
                continue
            fix = code_diff(old_code, new_code)
            added = "\n".join(ln[1:] for ln in fix.splitlines() if ln.startswith("+"))
            periph = (extract_peripherals(added) or extract_peripherals(fix) or extract_peripherals(str(f.get("where", ""))) or [None])[0]
            trigger = f"{code}: expected {str(f.get('expected', ''))[:90]}; observed {str(f.get('actual', ''))[:90]}"
            if not fix or not periph or guardrail.scan_injection(fix + " " + trigger):
                continue
            seen.add(code)
            out.append({"chip": chip, "peripheral": periph, "error_code": code, "trigger_pattern": trigger, "fix": fix, "evidence_run_id": run_id})
    return out


def render(lessons: list[dict]) -> str | None:
    if not lessons:
        return None
    lines = ["LESSONS from earlier verified fixes on this hardware (hints, NOT documentation: they came from past runs where the simulator confirmed the fix; "
             "verify with the simulator before relying on them):"]
    for l in lessons:
        lines.append(f"- [{l['id']}] {l['chip']} {l['peripheral']} (family {l['family']}), when the gate reported {l['trigger_pattern']} the verified fix was these C changes "
                     f"(- removed, + added):\n" + "\n".join("    " + ln for ln in l["fix"].splitlines()))
    return "\n".join(lines)[:MAX_CONTEXT_CHARS]
