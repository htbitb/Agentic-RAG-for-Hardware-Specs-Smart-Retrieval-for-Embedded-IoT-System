"""Đo Recall truy hồi: biến thể 'chỉ trang đầu của chunk' (cùng đơn vị với S1) khác 'cả khoảng trang' (khoảng rộng hơn)."""
from eval.schema import Task
from eval.tools import retrieval_recall as RR


class FakeCtx:
    def __init__(self, pages):
        self.pages = pages

    def page_text(self, doc, page):
        return self.pages.get((doc, page))


class FakeIndex:
    def __init__(self, hits):
        self.hits = hits

    def search(self, q, k=4, mode="hybrid", pool=40, **kw):
        return self.hits[:k]


def task():
    return Task(id="C2-001", category="C2", split="dev", turns=[{"user": "q"}], graders=["keyfacts"],
                expected={"cite_values": ["MAGICVALUE"]})


def test_value_only_on_the_second_page_of_a_chunk_counts_for_the_range_variant_but_not_for_first_page_or_chunk_text():
    ctx = FakeCtx({("D", 10): "nothing here", ("D", 11): "the MAGICVALUE lives here"})
    idx = FakeIndex([{"doc": "D", "page_start": 10, "page_end": 11, "text": "chunk text without the value"}])
    res = RR.measure(idx, ctx, [task()], ks=(4,), modes=("hybrid",))
    r = res["hybrid"][4]
    assert r["page"]["C2-001"] is True and r["first_page"]["C2-001"] is False and r["chunk"]["C2-001"] is False


def test_value_on_the_first_page_counts_for_all_page_variants():
    ctx = FakeCtx({("D", 10): "the MAGICVALUE lives here", ("D", 11): "x"})
    idx = FakeIndex([{"doc": "D", "page_start": 10, "page_end": 11, "text": "t"}])
    r = RR.measure(idx, ctx, [task()], ks=(4,), modes=("hybrid",))["hybrid"][4]
    assert r["page"]["C2-001"] is True and r["first_page"]["C2-001"] is True


def test_summary_reports_the_first_page_variant():
    ctx = FakeCtx({("D", 10): "the MAGICVALUE lives here"})
    idx = FakeIndex([{"doc": "D", "page_start": 10, "page_end": 10, "text": "t"}])
    t = task()
    s = RR.summarize(RR.measure(idx, ctx, [t], ks=(4,), modes=("hybrid",)), [t])
    assert s["hybrid"][4]["first_page"]["all"] == 1.0 and s["hybrid"][4]["first_page"]["C2"] == 1.0
