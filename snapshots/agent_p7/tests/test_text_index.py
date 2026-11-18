"""Text index hybrid: BM25 (SQLite FTS5) + embedding (numpy) + Reciprocal Rank Fusion, lọc theo chip/doc."""
import hashlib
import re

import numpy as np
import pytest

from ingestion.pdf_chunker import Chunk
from ingestion.text_index import TextIndex, build_index, rrf


def fake_embed(texts):
    """Bag-of-words băm vào 64 chiều (xác định, không cần mô hình)."""
    out = np.zeros((len(texts), 64), dtype=np.float32)
    for i, t in enumerate(texts):
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(n == 0, 1, n)


def mk(i, doc, chip, crumb, text, p0=1, p1=1):
    return Chunk(chunk_id=f"{doc}:{i:05d}", doc_id=doc, chip=chip, page_start=p0, page_end=p1, breadcrumb=crumb,
                 section=crumb.split(" > ")[-1], text=text, ord=i)


CHUNKS = [
    mk(0, "RM", "stm32g474", "RM > RCC > RCC_AHB2ENR", "Bit 0 GPIOAEN: IO port A clock enable. Set and cleared by software.", 306, 308),
    mk(1, "RM", "stm32g474", "RM > TIM > TIMx_CR1", "Bit 7 ARPE: auto-reload preload enable. Bit 0 CEN: counter enable.", 1235, 1236),
    mk(2, "RM", "stm32g474", "RM > TIM > TIMx_PSC", "The counter clock frequency is f_CK_PSC / (PSC[15:0] + 1) prescaler value.", 1240, 1240),
    mk(3, "TRM", "esp32", "TRM > GPIO > GPIO_ENABLE_REG", "GPIO0-31 output enable register. Writing 1 enables the output driver.", 139, 139),
    mk(4, "PS", "nrf52840", "PS > GPIO > PIN_CNF", "Configuration of GPIO pins: direction, input buffer, pull, drive and sense.", 349, 349),
    mk(5, "FR", "freertos", "FR > xTaskCreate()", "xTaskCreate creates a new task and returns pdPASS on success; heap memory is required.", 40, 41),
]


@pytest.fixture()
def idx(tmp_path):
    build_index(CHUNKS, tmp_path / "t.sqlite", tmp_path / "t.npy", embedder=fake_embed, meta={"model": "fake"})
    return TextIndex(tmp_path / "t.sqlite", tmp_path / "t.npy", embedder=fake_embed)


def test_exact_register_identifier_ranks_first_by_bm25(idx):
    r = idx.search("RCC_AHB2ENR clock enable", k=3, mode="bm25")
    assert r[0]["chunk_id"] == "RM:00000"


def test_results_expose_doc_page_range_and_breadcrumb_for_citation(idx):
    r = idx.search("auto-reload preload enable", k=1)[0]
    assert (r["doc"], r["page_start"], r["page_end"], r["page"]) == ("RM", 1235, 1236, 1235)
    assert r["breadcrumb"].endswith("TIMx_CR1") and "ARPE" in r["text"]


def test_filter_by_chip_and_doc(idx):
    assert {x["chip"] for x in idx.search("enable register", k=5, chip="esp32")} == {"esp32"}
    assert {x["doc"] for x in idx.search("enable register", k=5, doc="RM")} <= {"RM"}
    assert idx.search("enable register", k=5, chip="nonexistent") == []


def test_dense_only_finds_a_chunk_without_the_literal_query_words(tmp_path):
    chunks = [mk(0, "D", "c", "D > A", "alpha beta gamma delta epsilon"), mk(1, "D", "c", "D > B", "zeta eta theta iota kappa")]
    build_index(chunks, tmp_path / "a.sqlite", tmp_path / "a.npy", embedder=fake_embed, meta={})
    ix = TextIndex(tmp_path / "a.sqlite", tmp_path / "a.npy", embedder=fake_embed)
    assert ix.search("alpha beta", k=1, mode="dense")[0]["chunk_id"] == "D:00000"


def test_hybrid_contains_hits_from_both_rankers(tmp_path):
    chunks = [mk(0, "D", "c", "D > A", "register RCC_AHB2ENR enables clocks"),
              mk(1, "D", "c", "D > B", "completely unrelated prose about weather and rivers")]
    build_index(chunks, tmp_path / "h.sqlite", tmp_path / "h.npy", embedder=fake_embed, meta={})
    ix = TextIndex(tmp_path / "h.sqlite", tmp_path / "h.npy", embedder=fake_embed)
    hits = ix.search("RCC_AHB2ENR", k=2, mode="hybrid")
    assert hits[0]["chunk_id"] == "D:00000" and hits[0]["bm25_rank"] == 1


def test_rrf_fuses_ranked_lists_with_the_standard_formula():
    fused = rrf([["a", "b", "c"], ["b", "a", "d"]], k=60)
    assert [x for x, _ in fused[:2]] == ["a", "b"] or [x for x, _ in fused[:2]] == ["b", "a"]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)
    assert dict(fused)["c"] == pytest.approx(1 / 63) and dict(fused)["d"] == pytest.approx(1 / 63)


def test_special_characters_in_query_do_not_break_fts(idx):
    for q in ('TIM1_CH1 (PWM)?', 'a" OR "b', "NOT AND OR *", "'; DROP TABLE chunks; --", "[0..7] x:y"):
        idx.search(q, k=3)                       # không ném lỗi


def test_neighbors_are_returned_in_document_order(idx):
    n = idx.neighbors("RM:00001", window=1)
    assert [x["chunk_id"] for x in n] == ["RM:00000", "RM:00001", "RM:00002"]
    assert [x["chunk_id"] for x in idx.neighbors("RM:00000", window=1)] == ["RM:00000", "RM:00001"]
    assert idx.neighbors("nope") == []


def test_without_embeddings_the_index_falls_back_to_bm25_and_says_so(tmp_path):
    build_index(CHUNKS, tmp_path / "b.sqlite", tmp_path / "b.npy", embedder=fake_embed, meta={})
    ix = TextIndex(tmp_path / "b.sqlite", tmp_path / "missing.npy", embedder=None)
    r = ix.search("xTaskCreate", k=1)
    assert r[0]["chunk_id"] == "FR:00005" and ix.dense_available is False


def test_index_rejects_an_embedding_file_that_does_not_match_the_chunk_table(tmp_path):
    build_index(CHUNKS, tmp_path / "c.sqlite", tmp_path / "c.npy", embedder=fake_embed, meta={})
    np.save(tmp_path / "c.npy", np.zeros((3, 64), dtype=np.float32))
    with pytest.raises(ValueError, match="embeddings"):
        TextIndex(tmp_path / "c.sqlite", tmp_path / "c.npy", embedder=fake_embed)


def test_documents_listing_counts_chunks_and_pages(idx):
    docs = {d["doc"]: d for d in idx.documents()}
    assert docs["RM"]["chunks"] == 3 and docs["RM"]["chip"] == "stm32g474" and docs["RM"]["page_max"] == 1240


def test_manifest_docs_describe_every_pdf_entry_including_those_without_a_file():
    from ingestion import pdfdocs
    if not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file():
        pytest.skip("corpus not present")
    from ingestion.build_text_index import manifest_docs
    docs = {d["doc"]: d for d in manifest_docs()}
    assert docs["FreeRTOS_Ref_Manual"]["version"] == "V8.2.1" and docs["FreeRTOS_Ref_Manual"]["indexed"] is True
    assert docs["ESP32_Low_Power_AppNote"]["indexed"] is False and docs["ESP32_Low_Power_AppNote"]["pages"] is None
    assert docs["STM32G474_RM0440"]["pages"] == 2140 and "sha256" in docs["STM32G474_RM0440"]
    assert not any(d["doc"].endswith("_SVD") for d in docs.values())          # SVD không nằm trong text index
