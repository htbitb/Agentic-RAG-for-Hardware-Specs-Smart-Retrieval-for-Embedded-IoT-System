"""Chunk theo cấu trúc (outline -> breadcrumb), giữ số trang, không cắt ngang bảng, loại header/footer."""
import pytest

from ingestion import pdfdocs
from ingestion.pdf_chunker import chunk_document, chunk_pages
from ingestion.pdfdocs import OutlineEntry as O

OUT = [O(0, "1 Chapter", 1, ()), O(1, "1.1 Alpha", 1, ("1 Chapter",)), O(0, "2 Beta", 1, ())]


def chunks(pages, outline=OUT, **kw):
    kw.setdefault("min_section_chars", 0)
    return chunk_pages(pages, outline, doc_id="DOC", chip="chipx", doc_title="Doc", **kw)


def test_headings_inside_a_page_split_the_text_and_build_breadcrumbs():
    pages = {1: "intro line\n1.1 Alpha\ntext a1\n2 Beta\ntext b"}
    cs = chunks(pages)
    by = {c.breadcrumb: c.text for c in cs}
    assert by["Doc > 1 Chapter"].strip() == "intro line"
    assert "text a1" in by["Doc > 1 Chapter > 1.1 Alpha"] and "text b" not in by["Doc > 1 Chapter > 1.1 Alpha"]
    assert "text b" in by["Doc > 2 Beta"]


def test_long_section_is_split_with_page_range_overlap_and_unique_ids():
    body1 = "\n".join(f"sentence number {i} about the timer prescaler." for i in range(30))
    body2 = "\n".join(f"second page sentence {i} describing the counter." for i in range(30))
    cs = chunks({1: "1 Chapter\n" + body1, 2: body2}, [O(0, "1 Chapter", 1, ())], max_chars=500, overlap=100)
    assert len(cs) >= 4
    assert all(len(c.text) <= 650 for c in cs)
    assert cs[0].page_start == 1 and cs[-1].page_end == 2
    assert any(c.page_start == 1 and c.page_end == 2 for c in cs)              # một chunk nằm vắt qua hai trang
    assert len({c.chunk_id for c in cs}) == len(cs) and [c.ord for c in cs] == list(range(len(cs)))
    tail = cs[0].text.strip().splitlines()[-1]
    assert tail in cs[1].text                                                  # overlap


def test_a_table_is_not_cut_between_its_rows_when_it_can_be_avoided():
    prose = "\n".join(f"This paragraph line {i} explains the register in plain words." for i in range(6))
    table = "\n".join(f"0x{i:02X} REG_{i} 0x0000 0000 rw {i} {i + 1} {i + 2}" for i in range(14))
    cs = chunks({1: "1 Chapter\n" + prose + "\n" + table + "\nclosing sentence of the section."},
                [O(0, "1 Chapter", 1, ())], max_chars=420, overlap=0)
    rows = [f"REG_{i}" for i in range(14)]
    homes = [{r for r in rows if r in c.text} for c in cs]
    assert any(len(h) == 14 for h in homes), "the 14 table rows should stay in one chunk"


def test_page_headers_and_footers_are_removed():
    page = "1 Chapter\nreal content here\nRM0440 Rev 9 1593/2140\nEspressif Systems 47\nSubmit Documentation Feedback\n4413_417 v1.11 796"
    text = " ".join(c.text for c in chunks({1: page}, [O(0, "1 Chapter", 1, ())]))
    assert "real content here" in text
    for noise in ("Rev 9", "Espressif Systems", "Submit Documentation", "4413_417"):
        assert noise not in text


def test_table_of_contents_dot_leaders_are_dropped():
    page = "1 Chapter\n1.1 Alpha . . . . . . . . . . . . . . . 12\n2 Beta ..................... 40\nreal sentence stays here."
    text = " ".join(c.text for c in chunks({1: page}, [O(0, "1 Chapter", 1, ())]))
    assert "real sentence stays here" in text and ". . . ." not in text and "....." not in text


def test_tiny_sections_are_carried_into_the_next_section():
    pages = {1: "1 Chapter\n1.1 Tiny\nshort\n1.2 Real\n" + "real body sentence. " * 30}
    out = [O(0, "1 Chapter", 1, ()), O(1, "1.1 Tiny", 1, ("1 Chapter",)), O(1, "1.2 Real", 1, ("1 Chapter",))]
    cs = chunk_pages(pages, out, doc_id="D", chip="c", doc_title="Doc", min_section_chars=80)
    assert len(cs) == 1 and cs[0].breadcrumb == "Doc > 1 Chapter > 1.2 Real"
    assert "1.1 Tiny" in cs[0].text and "short" in cs[0].text                 # nội dung mục nhỏ không bị mất


def test_every_chunk_has_nonempty_text_and_valid_pages():
    pages = {p: f"1 Chapter\nline {p}\n" * 1 + "words " * 40 for p in (1, 2, 3)}
    for c in chunks(pages, [O(0, "1 Chapter", 1, ())], max_chars=200):
        assert c.text.strip() and 1 <= c.page_start <= c.page_end <= 3 and c.chip == "chipx" and c.doc_id == "DOC"


pytestmark_real = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


@pytestmark_real
def test_rm0440_register_section_gets_its_own_breadcrumb_and_page():
    cs = chunk_document("STM32G474_RM0440")
    c = next(c for c in cs if "RTC wakeup timer register (RTC_WUTR)" in c.breadcrumb)
    assert c.page_start <= 1593 <= c.page_end and "Real-time clock" in c.breadcrumb
    assert "Address offset: 0x14" in c.text or "Address offset: 0x14" in " ".join(
        x.text for x in cs if x.breadcrumb == c.breadcrumb)
    assert 3000 < len(cs) < 30000


@pytestmark_real
def test_freertos_without_bookmarks_gets_headings_from_numbered_titles():
    cs = chunk_document("FreeRTOS_Ref_Manual")
    assert any("2.13 taskEXIT_CRITICAL()" in c.breadcrumb for c in cs)
