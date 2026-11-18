"""Lớp đọc corpus dùng chung: manifest, text từng trang, outline (bookmark) PDF."""
import pytest

from ingestion import pdfdocs

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


def test_manifest_lists_the_real_documents_and_flags_the_missing_pdf():
    m = {e["doc_id"]: e for e in pdfdocs.load_manifest()}
    assert {"ESP32_TRM", "STM32G474_RM0440", "nRF52840_PS", "FreeRTOS_Ref_Manual"} <= set(m)
    assert pdfdocs.doc_pdf("STM32G474_RM0440").is_file()
    assert pdfdocs.doc_pdf("ESP32_Low_Power_AppNote") is None
    assert m["FreeRTOS_Ref_Manual"]["version"] == "V8.2.1"


def test_load_pages_is_one_based_and_matches_page_text():
    pages = pdfdocs.load_pages("STM32G474_RM0440")
    assert len(pages) == 2140
    assert "RTC wakeup timer register (RTC_WUTR)" in pages[1593]


def test_load_pages_rejects_a_cache_that_does_not_match_the_manifest_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfdocs, "PAGES_DIR", tmp_path)
    (tmp_path / "STM32G474_RM0440.jsonl").write_text('{"page_1based": 1, "text": "x"}\n')
    (tmp_path / "STM32G474_RM0440.sha256").write_text("0" * 64)
    with pytest.raises(RuntimeError, match="sha256"):
        pdfdocs.load_pages("STM32G474_RM0440")


def test_outline_entries_carry_page_level_and_ancestors():
    ol = pdfdocs.load_outline("STM32G474_RM0440")
    e = next(x for x in ol if x.title.startswith("37.6.6 RTC wakeup timer register"))
    assert e.page == 1593 and e.level >= 2
    assert any("Real-time clock" in a for a in e.path)


def test_outline_is_empty_for_pdf_without_bookmarks():
    assert pdfdocs.load_outline("FreeRTOS_Ref_Manual") == []
