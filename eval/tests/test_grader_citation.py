import pytest

from eval.context import GradeContext
from eval.graders import citation
from eval.tests.helpers import mk_run, mk_task

MANIFEST = [
    {"doc_id": "ESP32_TRM", "kind": "pdf", "aliases": ["ESP32 TRM"], "file": "pdfs/trm.pdf", "pages": 3, "page_offset": 0},
    {"doc_id": "STM32G474_RM0440", "kind": "pdf", "aliases": ["RM0440", "rm0440.pdf"], "file": "pdfs/rm.pdf", "pages": 4, "page_offset": 2},
    {"doc_id": "ESP32_Low_Power_AppNote", "kind": "pdf", "aliases": [], "file": None, "pages": None, "page_offset": None},
]
PAGES = {
    "ESP32_TRM": ["intro text", "GPIO_OUT_REG address 0x3FF44004 is the output register", "unrelated"],
    "STM32G474_RM0440": ["p1", "p2", "TIM1_CR1 offset 0x00 reset value 0x0000 0000", "p4"],
}
TASK = mk_task({"exact": {"attribute": "address", "kind": "hex", "value": "0x3FF44004"}}, graders=("exact", "citation"))
CTX = GradeContext(manifest=MANIFEST, pages=PAGES)


def grade(answer, task=TASK, **run_kw):
    return citation.grade(task, mk_run(answer, **run_kw), CTX)


def test_valid_citation_when_page_contains_expected_value():
    r = grade("GPIO_OUT_REG is at 0x3FF44004 [ESP32_TRM p.2].")
    assert r["details"]["valid"] == 1 and r["details"]["invalid"] == 0 and r["pass"]


def test_invalid_when_page_lacks_the_value():
    r = grade("It is 0x3FF44004 [ESP32_TRM p.3].")
    assert r["details"]["invalid"] == 1 and not r["pass"] and any(x.startswith("citation_unsupported") for x in r["reasons"])


def test_unknown_document_is_invalid():
    r = grade("See [FooBar_Manual p.2].")
    assert r["details"]["invalid"] == 1 and any("unknown_doc" in x for x in r["reasons"])


def test_page_out_of_range_is_invalid():
    assert grade("See [ESP32_TRM p.99].")["details"]["invalid"] == 1


def test_document_without_real_pdf_is_unverifiable_not_invalid():
    r = grade("Per [ESP32_Low_Power_AppNote p.4] deep sleep is low.")
    assert r["details"]["unverifiable"] == 1 and r["details"]["invalid"] == 0 and r["details"]["precision"] is None


def test_alias_and_page_offset():
    t = mk_task({"exact": {"attribute": "offset", "kind": "hex", "value": "0x0"}}, graders=("exact", "citation"))
    r = citation.grade(t, mk_run("TIM1_CR1 offset is 0x00 (RM0440 p.1)."), CTX)   # in 1 + offset 2 = pdf trang 3
    assert r["details"]["valid"] == 1


def test_page_range_valid_if_any_page_supports():
    assert grade("[ESP32_TRM p.1-2] says 0x3FF44004")["details"]["valid"] == 1


def test_multiple_citations_in_one_bracket():
    r = grade("[ESP32_TRM p.2; STM32G474_RM0440 p.1]")
    assert r["details"]["valid"] == 1 and r["details"]["invalid"] == 1 and r["details"]["precision"] == 0.5


def test_non_document_parentheses_are_ignored():
    assert grade("(see Table 5, p.12) and (e.g. p.4)")["details"]["n_citations"] == 0


def test_no_citation_fails_but_does_not_crash():
    r = grade("The address is 0x3FF44004.")
    assert r["details"]["n_citations"] == 0 and not r["pass"] and r["details"]["precision"] is None


def test_s1_uses_sources_metadata_and_flags_retrieval_miss():
    good = grade("ans", system="S1", sources=[{"doc_id": "ESP32_TRM", "file": "trm.pdf", "page": 2},
                                               {"doc_id": "ESP32_TRM", "file": "trm.pdf", "page": 3}])
    assert good["details"]["valid"] == 1 and good["details"]["invalid"] == 1 and good["details"]["retrieval_hit"]
    miss = grade("ans", system="S1", sources=[{"doc_id": "ESP32_TRM", "file": "trm.pdf", "page": 3}])
    assert not miss["details"]["retrieval_hit"] and any(x.startswith("retrieval_miss") for x in miss["reasons"])


def test_explicit_cite_values_override_derived_facts():
    t = mk_task({"cite_values": ["output register"]}, graders=("exact", "citation"))
    r = citation.grade(t, mk_run("x [ESP32_TRM p.2]"), CTX)
    assert r["details"]["valid"] == 1


# ---- review finding 6: trích dẫn theo kiểu tự nhiên của LLM -----------------------------------------------
def test_natural_style_citations_resolve_through_manifest_aliases():
    real = GradeContext.load()
    cases = {"[ESP32 Technical Reference Manual, p. 58]": "ESP32_TRM",
             "[RM0440 Reference Manual, p. 774]": "STM32G474_RM0440",
             "[nRF52840 Product Specification v1.8, p. 439-440]": "nRF52840_PS",
             "[STM32G474xx Datasheet, DS12297 p. 132]": "STM32G474_Datasheet",
             "(ESP32 Series Datasheet, p. 51)": "ESP32_Datasheet",
             "[FreeRTOS Reference Manual V8.2.1, p. 40]": "FreeRTOS_Ref_Manual"}
    for text, doc in cases.items():
        cites = citation.extract_citations(text, real)
        assert [c["doc_id"] for c in cites] == [doc], text


def test_unknown_multiword_sources_are_still_ignored():
    assert citation.extract_citations("[Some Random Book, p. 3]", GradeContext.load()) == []
