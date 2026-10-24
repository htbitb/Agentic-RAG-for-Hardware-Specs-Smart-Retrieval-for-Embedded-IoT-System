"""Kiểm thử các thay đổi native-RAG phục vụ eval (xem native-RAG/CHANGELOG_EVAL.md)."""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RAG = ROOT / "native-RAG"


@pytest.fixture()
def rag_modules(monkeypatch):
    """Import config/rag_core của native-RAG (import nhẹ, không kéo torch/chroma)."""
    monkeypatch.syspath_prepend(str(RAG))
    for name in ("config", "rag_core", "eval_adapter"):
        sys.modules.pop(name, None)
    monkeypatch.delenv("RAG_PDF_DIR", raising=False)
    config = importlib.import_module("config")
    rag_core = importlib.import_module("rag_core")
    yield config, rag_core
    for name in ("config", "rag_core", "eval_adapter"):
        sys.modules.pop(name, None)


def test_pdf_dir_defaults_to_shared_corpus(rag_modules):
    config, _ = rag_modules
    assert Path(config.PDF_DIR).resolve() == (ROOT / "corpus" / "pdfs").resolve()


def test_pdf_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(RAG))
    sys.modules.pop("config", None)
    monkeypatch.setenv("RAG_PDF_DIR", str(tmp_path))
    config = importlib.import_module("config")
    try:
        assert Path(config.PDF_DIR) == tmp_path
    finally:
        sys.modules.pop("config", None)


def test_chunking_parameters_are_unchanged(rag_modules):
    config, _ = rag_modules
    assert (config.CHUNK_SIZE, config.CHUNK_OVERLAP, config.RETRIEVE_K) == (1000, 150, 4)
    assert config.EMBEDDING_MODEL_NAME == "sentence-transformers/all-MiniLM-L6-v2"


def test_embed_device_defaults_to_cpu(rag_modules, monkeypatch):
    config, _ = rag_modules
    assert config.EMBED_DEVICE == "cpu"


def test_doc_index_maps_file_names_to_doc_ids(rag_modules):
    _, rag_core = rag_modules
    idx = rag_core.load_doc_index()
    assert idx["esp32_datasheet_en.pdf"] == "ESP32_Datasheet"
    assert idx["rm0440-stm32g4-series-advanced-armbased-32bit-mcus-stmicroelectronics.pdf"] == "STM32G474_RM0440"
    assert idx["nRF52840_PS.pdf"] == "nRF52840_PS"
    assert idx["FreeRTOS_Reference_Manual_V8.2.1.pdf"] == "FreeRTOS_Ref_Manual"
    assert None not in idx and all(v for v in idx.values())   # doc không có PDF (file: null) bị bỏ qua


def test_prompt_is_generalised_and_keeps_abstain_sentence(rag_modules):
    _, rag_core = rag_modules
    p = rag_core.PROMPT_TEMPLATE
    for chip in ("ESP32", "STM32G474", "nRF52840", "FreeRTOS"):
        assert chip in p
    assert "I could not find this in the documents." in p
    assert "{context}" in p and "{question}" in p


def test_ingest_metadata_adds_page_1based_and_doc_id(rag_modules):
    _, rag_core = rag_modules
    meta = rag_core.enrich_metadata({"source": "/x/data/esp32_datasheet_en.pdf", "page": 0},
                                    rag_core.load_doc_index())
    assert meta["page"] == 0                       # giữ nguyên 0-based gốc
    assert meta["page_1based"] == 1
    assert meta["doc_id"] == "ESP32_Datasheet"


def test_enrich_metadata_unknown_file_gets_stem_doc_id(rag_modules):
    _, rag_core = rag_modules
    meta = rag_core.enrich_metadata({"source": "/x/unknown_manual.pdf", "page": 6}, {})
    assert meta["page_1based"] == 7
    assert meta["doc_id"] == "unknown_manual"


def test_usage_extraction_from_ai_message(rag_modules):
    _, rag_core = rag_modules

    class Msg:
        content = "answer text"
        usage_metadata = {"input_tokens": 120, "output_tokens": 7, "total_tokens": 127}

    text, usage = rag_core.split_message(Msg())
    assert text == "answer text"
    assert usage == {"in": 120, "out": 7}


def test_usage_extraction_when_missing(rag_modules):
    _, rag_core = rag_modules

    class Msg:
        content = "x"
        usage_metadata = None

    assert rag_core.split_message(Msg())[1] == {"in": 0, "out": 0}
