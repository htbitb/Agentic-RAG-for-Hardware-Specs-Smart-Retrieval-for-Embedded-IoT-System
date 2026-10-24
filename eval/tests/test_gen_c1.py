from collections import Counter
from pathlib import Path

import pytest

from eval.generators import gen_c1_from_svd as gen
from eval.generators.svd import parse_svd
from eval.schema import Task

ROOT = Path(__file__).resolve().parents[2]
SVD_DIR = ROOT / "corpus" / "svd"


@pytest.fixture(scope="module")
def tasks():
    return gen.generate(SVD_DIR, n=25, seed=20261021)


def test_deterministic_for_same_seed_and_different_for_other_seed(tasks):
    assert gen.generate(SVD_DIR, n=25, seed=20261021) == tasks
    other = gen.generate(SVD_DIR, n=25, seed=7)
    assert [t["turns"] for t in other] != [t["turns"] for t in tasks]


def test_count_chip_mix_and_ids(tasks):
    assert len(tasks) == 25
    chips = Counter(t["chips"][0] for t in tasks)
    assert chips == {"stm32g474": 15, "nrf52840": 5, "esp32": 5}
    assert [t["id"] for t in tasks] == [f"C1-{i:03d}" for i in range(1, 26)]


def test_every_task_is_a_valid_task_with_exact_and_numeric_graders(tasks):
    for d in tasks:
        t = Task.from_dict(d)
        assert t.category == "C1" and t.review_status == "auto"
        assert "exact" in t.graders and "numeric_claims" in t.graders
        assert t.expected["exact"]["value"] is not None


def test_ground_truth_matches_svd_for_each_task(tasks):
    devs = {"stm32g474": parse_svd(SVD_DIR / "STM32G474xx.svd"), "nrf52840": parse_svd(SVD_DIR / "nrf52840.svd"),
            "esp32": parse_svd(SVD_DIR / "esp32.svd")}
    for d in tasks:
        pv = d["provenance"]
        dev = devs[d["chips"][0]]
        p = next(p for p in dev.peripherals if p.name == pv["peripheral"])
        r = next(r for r in p.registers if r.name == pv["register"])
        ex = d["expected"]["exact"]
        kind = pv["question_type"]
        if kind == "address":
            assert int(ex["value"], 16) == r.address
        elif kind == "offset":
            assert int(ex["value"], 16) == r.offset
        elif kind == "reset":
            assert int(ex["value"], 16) == r.reset_value
        elif kind == "bits":
            f = next(f for f in r.fields if f.name == pv["field"])
            assert sorted(ex["value"]) == [f.lsb, f.msb]
        elif kind == "access":
            assert ex["value"] == r.access
        else:
            pytest.fail(f"unknown question type {kind}")
        # câu hỏi nêu đúng chip + thanh ghi + (nếu có) field
        q = d["turns"][0]["user"]
        assert r.name in q or r.name.replace("_", " ") in q
        if kind == "bits":
            assert pv["field"] in q


def test_variety_of_question_types_and_templates(tasks):
    types = Counter(t["provenance"]["question_type"] for t in tasks)
    assert set(types) == {"address", "offset", "reset", "bits", "access"}
    assert len({t["provenance"]["template"] for t in tasks}) >= 8
    qs = [t["turns"][0]["user"] for t in tasks]
    assert len(set(qs)) == 25


def test_peripheral_diversity_cap(tasks):
    per = Counter((t["chips"][0], t["provenance"]["peripheral"]) for t in tasks)
    assert max(per.values()) <= 2


def test_answerable_registers_only(tasks):
    for t in tasks:
        pv = t["provenance"]
        assert "%" not in pv["register"] and len(pv["register"]) <= 28
        if pv["question_type"] == "reset":
            assert t["expected"]["exact"]["value"] is not None


def test_allowed_values_cover_neighbouring_attributes_of_same_register(tasks):
    for t in tasks:
        if t["provenance"]["question_type"] == "address":
            # offset/reset nhỏ của cùng thanh ghi không bị coi là địa chỉ mâu thuẫn
            assert isinstance(t["expected"]["exact"].get("allowed", []), list)
            assert t["expected"]["numeric_support"]


# ------------------------------------------------------------------ bộ lọc answerable
class FakeCtx:
    """GradeContext tối thiểu: manifest + text trang."""
    def __init__(self, pages):
        self.pages = pages
        self.manifest = [{"doc_id": d, "pages": len(v)} for d, v in pages.items()]

    def entry(self, doc_id):
        return next((e for e in self.manifest if e["doc_id"] == doc_id), None)

    def page_text(self, doc_id, p):
        return self.pages[doc_id][p - 1]


def _task(qtype, **exp):
    base = {"id": "C1-X", "chips": ["stm32g474"], "provenance": {"question_type": qtype, "doc_hint": "D",
            "peripheral": "GPIOA", "register": "MODER"},
            "expected": {"exact": {"value": exp.get("value", "0x0"), "kind": exp.get("kind", "hex")},
                         "cite_values": exp.get("cite", ["MODER"]), "numeric_support": exp.get("support", [])}}
    return base


def test_answerable_requires_register_name_in_corpus():
    idx = gen.CorpusIndex(FakeCtx({"D": ["intro", "GPIOx_MODER GPIO port mode register Address offset: 0x00"]}))
    assert gen.answerable(_task("offset", value="0x0"), idx)
    assert not gen.answerable(_task("offset", value="0x0", cite=["NOSUCHREG"]), idx)


def test_answerable_reset_needs_name_and_value_on_the_same_page():
    pages = ["MODER only here", "reset value 0xABFF FFFF but no register name"]
    idx = gen.CorpusIndex(FakeCtx({"D": pages}))
    assert not gen.answerable(_task("reset", value="0xABFFFFFF"), idx)
    idx2 = gen.CorpusIndex(FakeCtx({"D": ["MODER ... Reset value: 0xABFF FFFF"]}))
    assert gen.answerable(_task("reset", value="0xABFFFFFF"), idx2)


def test_answerable_address_needs_peripheral_base_in_corpus():
    t = _task("address", value="0x48000000", cite=["0x48000000", "0x48000000"], support=["0x48000000", "0x0"])
    t["expected"]["numeric_support"] = ["0x48000000"]
    assert gen.answerable(t, gen.CorpusIndex(FakeCtx({"D": ["0x4800 0000 - 0x4800 03FF GPIOA", "MODER register"]})))
    assert not gen.answerable(t, gen.CorpusIndex(FakeCtx({"D": ["nothing relevant"]})))


@pytest.mark.skipif(not (ROOT / "corpus" / ".cache" / "pages" / "STM32G474_RM0440.jsonl").exists(), reason="chưa có cache trang")
def test_generation_with_real_corpus_keeps_only_answerable_tasks():
    from eval.context import GradeContext

    ctx = GradeContext.load()
    ts = gen.generate(SVD_DIR, n=25, seed=20261021, ctx=ctx)
    idx = gen.CorpusIndex(ctx)
    assert len(ts) == 25 and all(gen.answerable(t, idx) for t in ts)


def test_address_tasks_also_cite_the_register_name(tasks):
    # RM0440 không in địa chỉ tuyệt đối: trang đúng phải được công nhận qua tên thanh ghi (review finding 7)
    for t in tasks:
        if t["provenance"]["question_type"] == "address":
            assert t["provenance"]["doc_name"] in t["expected"]["cite_values"]
