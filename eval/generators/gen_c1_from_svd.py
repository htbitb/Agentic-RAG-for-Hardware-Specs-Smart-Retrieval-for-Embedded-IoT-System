"""Sinh task C1 (tra cứu sự kiện) từ CMSIS-SVD, có seed, ground truth lấy thẳng từ SVD.

    python -m eval.generators.gen_c1_from_svd --seed 20261021 --out eval/tasks/C1

Loại câu hỏi: địa chỉ tuyệt đối, offset, reset value, vị trí bitfield, kiểu truy cập (tiếng Anh).
Ground truth đã tính đúng derivedFrom/dim/cluster (xem eval/generators/svd.py). Tất cả task ở
review_status=auto và split=test; `eval/generators/assign_splits.py` chia dev/test sau.
"""
from __future__ import annotations

import argparse
import random
import re
from pathlib import Path

import yaml

from eval.generators.svd import parse_svd
from eval.graders.common import norm_text
from eval.textnorm import hex_tokens

CHIPS = {
    "stm32g474": {"file": "STM32G474xx.svd", "doc": "STM32G474_RM0440", "display": "STM32G474",
                  "plan": {"address": 5, "offset": 3, "reset": 3, "bits": 3, "access": 1}},
    "nrf52840": {"file": "nrf52840.svd", "doc": "nRF52840_PS", "display": "nRF52840",
                 "plan": {"address": 2, "offset": 1, "reset": 1, "bits": 1, "access": 0}},
    "esp32": {"file": "esp32.svd", "doc": "ESP32_TRM", "display": "ESP32",
              "plan": {"address": 2, "offset": 0, "reset": 1, "bits": 1, "access": 1}},
}
TEMPLATES = {
    "address": [
        "What is the absolute memory-mapped address of {full} on the {chip}?",
        "On the {chip}, at which address is the {reg} register of {periph} located?",
        "I need the final address of {full} ({chip}) for a bare-metal driver. What is it?",
        "Give the 32-bit address of the {reg} register in the {periph} block of the {chip}.",
    ],
    "offset": [
        "What is the address offset of {reg} within the {periph} peripheral of the {chip}?",
        "How far from the {periph} base address is the {reg} register on the {chip}?",
        "For the {chip}, what offset do I add to the {periph} base address to reach {reg}?",
    ],
    "reset": [
        "What is the reset value of {full} on the {chip}?",
        "After a reset, what value does the {reg} register of {periph} hold on the {chip}?",
        "What is the default (power-on reset) value of {full} on the {chip}?",
    ],
    "bits": [
        "Which bits of {full} make up the {field} field on the {chip}?",
        "Where is the {field} bit field located inside the {reg} register of {periph} ({chip})?",
        "On the {chip}, give the bit position(s) of {field} in {full}.",
    ],
    "access": [
        "What is the access type of the {reg} register of {periph} on the {chip} (read-write, read-only or write-only)?",
        "Is {full} on the {chip} read-only, write-only or read-write?",
    ],
}
_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_BAD_FIELD = re.compile(r"^(RES|RESERVED|RSVD|UNUSED|REG\d*)", re.I)


def _names(chip: str, p, r) -> dict:
    """Cách gọi tên thanh ghi trong tài liệu từng chip."""
    if chip == "esp32":
        full = f"{p.name}_{r.name}_REG"
        return {"full": full, "reg": full, "cite": full}
    if chip == "nrf52840":
        return {"full": f"{p.name}->{r.name}", "reg": r.name, "cite": r.name}
    return {"full": f"{p.name}_{r.name}", "reg": r.name, "cite": r.name}


def _hex(v: int, width: int | None = None) -> str:
    return f"0x{v:0{width}X}" if width else f"0x{v:X}"


def _candidates(dev, qtype: str):
    out = []
    for p in dev.peripherals:
        if not _NAME.match(p.name):
            continue
        for r in p.registers:
            if not _NAME.match(r.name) or len(r.name) > 28:
                continue
            if qtype == "offset" and r.offset == 0:
                continue
            if qtype == "reset" and not r.reset_value:
                continue
            if qtype == "access" and r.access is None:
                continue
            if qtype == "bits":
                good = [f for f in r.fields if not _BAD_FIELD.match(f.name) and len(f.name) <= 12 and f.msb - f.lsb < 16]
                if len(good) < 2:
                    continue
                out += [(p, r, f) for f in good]
                continue
            out.append((p, r, None))
    out.sort(key=lambda t: (t[0].name, t[1].name, t[2].name if t[2] else ""))
    return out


def _build(chip: str, spec: dict, qtype: str, p, r, f, template_idx: int, tid: str, split: str) -> dict:
    n = _names(chip, p, r)
    q = TEMPLATES[qtype][template_idx].format(chip=spec["display"], periph=p.name, field=f.name if f else "", **{k: n[k] for k in ("full", "reg")})
    base = p.base
    neighbours = [_hex(base), _hex(r.offset), _hex(r.address, 8)]
    if r.reset_value is not None:
        neighbours.append(_hex(r.reset_value))
    if qtype == "address":
        exact = {"attribute": "address", "kind": "hex", "value": _hex(r.address, 8),
                 "allowed": [_hex(base)] + ([_hex(r.reset_value)] if r.reset_value else [])}
        cite = [_hex(r.address, 8), _hex(base), n["cite"]]
    elif qtype == "offset":
        exact = {"attribute": "offset", "kind": "hex", "value": _hex(r.offset),
                 "allowed": [_hex(base), _hex(r.address, 8)] + ([_hex(r.reset_value)] if r.reset_value else [])}
        cite = [n["cite"]]
    elif qtype == "reset":
        exact = {"attribute": "reset", "kind": "hex", "value": _hex(r.reset_value),
                 "allowed": [_hex(base), _hex(r.offset), _hex(r.address, 8)]}
        cite = [n["cite"], _hex(r.reset_value)]
    elif qtype == "bits":
        others = [[x.lsb, x.msb] for x in r.fields if x.name != f.name]
        exact = {"attribute": "bits", "kind": "bits", "value": [f.lsb, f.msb], "allowed": others}
        cite = [n["cite"], f.name]
    else:
        exact = {"attribute": "access", "kind": "access", "value": r.access}
        cite = [n["cite"]]
    prov = {"source": "svd", "svd": spec["file"], "peripheral": p.name, "register": r.name,
            "question_type": qtype, "template": f"{qtype}.{template_idx + 1}", "doc_hint": spec["doc"],
            "doc_name": n["cite"]}
    if f:
        prov["field"] = f.name
    return {
        "id": tid, "category": "C1", "split": split, "difficulty": "medium" if qtype in ("reset", "bits") else "easy",
        "chips": [chip], "tags": [f"register_{qtype}"], "turns": [{"user": q}],
        "expected": {"exact": exact, "numeric_support": neighbours, "cite_values": cite},
        "graders": ["exact", "numeric_claims", "citation"], "review_status": "auto", "provenance": prov, "version": 1,
    }



class CorpusIndex:
    """Chỉ mục trang của corpus để kiểm tra 'task có truy được trong tài liệu không' (answerable)."""

    def __init__(self, ctx):
        self.ctx = ctx
        self._docs: dict[str, tuple[list[str], list[set]]] = {}

    def _doc(self, doc: str):
        if doc not in self._docs:
            n = (self.ctx.entry(doc) or {}).get("pages") or 0
            texts = [self.ctx.page_text(doc, p) or "" for p in range(1, n + 1)]
            self._docs[doc] = ([norm_text(t) for t in texts], [set(hex_tokens(t)) for t in texts])
        return self._docs[doc]

    def name_pages(self, doc: str, name: str) -> set[int]:
        key = norm_text(name)
        return {i for i, t in enumerate(self._doc(doc)[0]) if key in t}

    def hex_pages(self, doc: str, value: int) -> set[int]:
        return {i for i, hs in enumerate(self._doc(doc)[1]) if value in hs}


def answerable(task: dict, idx: CorpusIndex) -> bool:
    """Ground truth từ SVD chỉ được giữ nếu tài liệu corpus thực sự nói về thanh ghi/giá trị đó."""
    pv, ex = task["provenance"], task["expected"]
    doc, qtype = pv["doc_hint"], pv["question_type"]
    name = pv.get("doc_name") or next((c for c in ex.get("cite_values", []) if not str(c).lower().startswith("0x")), pv["register"])
    names = idx.name_pages(doc, name)
    if not names:
        return False
    if qtype in ("offset", "reset"):
        return bool(names & idx.hex_pages(doc, int(ex["exact"]["value"], 16)))
    if qtype == "bits":
        return bool(names & idx.name_pages(doc, pv["field"]))
    if qtype == "address":
        if names & idx.hex_pages(doc, int(ex["exact"]["value"], 16)):
            return True
        base = int(ex["cite_values"][1], 16)
        return bool(idx.hex_pages(doc, base) & idx.name_pages(doc, pv["peripheral"]))
    return True        # access: chỉ cần tên thanh ghi xuất hiện


def generate(svd_dir, n: int = 25, seed: int = 20261021, split: str = "test", ctx=None) -> list[dict]:
    """ctx (GradeContext) -> chỉ giữ task mà tài liệu corpus thật sự đề cập (answerable)."""
    if n != 25:
        raise ValueError("kế hoạch phân bổ hiện cố định ở 25 task (xem CHIPS[...]['plan'])")
    rng = random.Random(seed)
    index = CorpusIndex(ctx) if ctx is not None else None
    chosen: list[dict] = []
    seen_q: set[str] = set()
    for chip, spec in CHIPS.items():
        dev = parse_svd(Path(svd_dir) / spec["file"])
        per_periph: dict[str, int] = {}
        used_regs: set[tuple] = set()
        for qtype, count in spec["plan"].items():
            pool = _candidates(dev, qtype)
            rng.shuffle(pool)
            taken = 0
            for p, r, f in pool:
                if taken == count:
                    break
                key = (p.name, r.name)
                if per_periph.get(p.name, 0) >= 2 or key in used_regs:
                    continue
                tidx = rng.randrange(len(TEMPLATES[qtype]))
                task = _build(chip, spec, qtype, p, r, f, tidx, "C1-000", split)
                if task["turns"][0]["user"] in seen_q:
                    continue
                if index is not None and not answerable(task, index):
                    continue
                seen_q.add(task["turns"][0]["user"])
                per_periph[p.name] = per_periph.get(p.name, 0) + 1
                used_regs.add(key)
                chosen.append(task)
                taken += 1
            if taken < count:
                raise RuntimeError(f"không đủ ứng viên {chip}/{qtype}: {taken}/{count}")
    rng.shuffle(chosen)
    for i, t in enumerate(chosen, start=1):
        t["id"] = f"C1-{i:03d}"
    return chosen


def write_yaml(tasks: list[dict], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for t in tasks:
        (out / f"{t['id']}.yaml").write_text(yaml.safe_dump(t, sort_keys=False, allow_unicode=True, width=200), encoding="utf-8")


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--svd-dir", type=Path, default=root / "corpus" / "svd")
    ap.add_argument("--out", type=Path, default=root / "eval" / "tasks" / "C1")
    ap.add_argument("--n", type=int, default=25)
    a = ap.parse_args()
    from eval.context import GradeContext

    tasks = generate(a.svd_dir, a.n, a.seed, ctx=GradeContext.load())
    write_yaml(tasks, a.out)
    print(f"đã ghi {len(tasks)} task C1 vào {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
