"""MCP server hw-knowledge / text-manual: tên tool, mô tả, tham số, quyền, và gọi qua ToolHub (inproc)."""
import asyncio
import json

import pytest

import config
from ingestion import hwdb, limits_curate, pdfdocs, pinout_extract, svd_ingest
from ingestion.pdf_chunker import Chunk
from ingestion.text_index import build_index

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


@pytest.fixture(scope="module")
def servers(tmp_path_factory):
    d = tmp_path_factory.mktemp("srv")
    db = d / "hw_specs.sqlite"
    svd_ingest.main(["--db", str(db)]); pinout_extract.main(["--db", str(db)]); limits_curate.main(["--db", str(db)])
    import hashlib
    import numpy as np
    chunks = [Chunk("RM:00000", "STM32G474_RM0440", "stm32g474", 306, 308, "RM0440 > RCC > RCC_AHB2ENR", "RCC_AHB2ENR",
                    "Bit 0 GPIOAEN: IO port A clock enable", 0),
              Chunk("RM:00001", "STM32G474_RM0440", "stm32g474", 1235, 1236, "RM0440 > TIM > TIMx_CR1", "TIMx_CR1",
                    "Bit 7 ARPE auto-reload preload enable", 1),
              Chunk("FR:00000", "FreeRTOS_Ref_Manual", "freertos", 40, 41, "FreeRTOS Reference Manual > xTaskCreate()", "xTaskCreate()",
                    "xTaskCreate returns pdPASS if the task was created successfully", 0)]

    def emb(texts):
        out = np.zeros((len(texts), 32), dtype=np.float32)
        for i, t in enumerate(texts):
            out[i, int(hashlib.md5(t.split()[0].encode()).hexdigest(), 16) % 32] = 1.0
        return out

    docs = [{"doc": "STM32G474_RM0440", "title": "RM0440 Reference manual STM32G4 series", "version": "Rev 9", "chip": "stm32g474",
             "pages": 2140, "indexed": True},
            {"doc": "FreeRTOS_Ref_Manual", "title": "The FreeRTOS Reference Manual", "version": "V8.2.1", "chip": "freertos", "pages": 302, "indexed": True},
            {"doc": "ESP32_Low_Power_AppNote", "title": "ESP32 low-power application note", "version": None, "chip": "esp32", "pages": None,
             "indexed": False, "note": "no PDF in the corpus"}]
    build_index(chunks, d / "ti.sqlite", d / "ti.npy", embedder=emb, meta={"docs": docs})
    config.HW_DB, config.TEXT_INDEX_DB, config.TEXT_INDEX_EMB = db, d / "ti.sqlite", d / "ti.npy"
    from mcp_servers import hw_knowledge_server as hk, text_manual_server as tm
    hk._reset(); tm._reset(embedder=emb)
    return hk, tm


def tools_of(mod):
    return {t.name: t for t in asyncio.run(mod.mcp.list_tools())}


def test_hw_knowledge_exposes_old_and_new_tools_with_documented_parameters(servers):
    hk, _ = servers
    t = tools_of(hk)
    assert {"list_chips", "query_pin_alternate_function", "get_register_bitfields", "get_electrical_specs",
            "check_logic_level_compatibility", "find_pins_for_signal", "get_clock_limits", "search_registers"} <= set(t)
    props = t["get_register_bitfields"].inputSchema["properties"]
    assert {"chip", "peripheral", "register", "field", "limit", "offset"} <= set(props) and "max_chars" not in props
    assert all(len(t[n].description) > 60 for n in t)


def test_text_manual_exposes_search_context_and_documents(servers):
    _, tm = servers
    assert {"search_manual", "naive_search", "get_chunk_context", "list_documents"} <= set(tools_of(tm))


def test_hw_tool_functions_return_json_serialisable_data(servers):
    hk, _ = servers
    for out in (hk.list_chips(), hk.get_register_bitfields("stm32g474", "TIM1", "CR1"),
                hk.query_pin_alternate_function("stm32g474", "PA8"), hk.find_pins_for_signal("stm32g474", "TIM1_CH1"),
                hk.get_electrical_specs("esp32", "supply voltage VDD"), hk.get_clock_limits("stm32g474", "HSE"),
                hk.search_registers("stm32g474", "wakeup timer"), hk.check_logic_level_compatibility("esp32", "stm32g474")):
        json.dumps(out)


def test_search_manual_returns_citable_chunks_and_filters(servers):
    _, tm = servers
    r = tm.search_manual("GPIOAEN clock enable", chip="stm32g474", k=2)
    assert r["results"][0]["doc"] == "STM32G474_RM0440" and r["results"][0]["page_start"] == 306 and "GPIOAEN" in r["results"][0]["text"]
    assert tm.search_manual("xTaskCreate", doc="FreeRTOS_Ref_Manual")["results"][0]["chunk_id"] == "FR:00000"
    assert tm.search_manual("anything", chip="nonexistent")["results"] == []


def test_chunk_context_and_document_listing(servers):
    _, tm = servers
    assert [c["chunk_id"] for c in tm.get_chunk_context("RM:00001", window=1)["results"]] == ["RM:00000", "RM:00001"]
    assert "error" in tm.get_chunk_context("nope")
    docs = {d["doc"]: d for d in tm.list_documents()["documents"]}
    assert docs["FreeRTOS_Ref_Manual"]["version"] == "V8.2.1" and docs["ESP32_Low_Power_AppNote"]["indexed"] is False
    assert "v10" not in json.dumps(tm.list_documents()).lower()


def test_tool_hub_registers_the_new_servers_and_permissions(servers):
    from agent.tools import PERMISSIONS, SERVERS, ToolHub
    assert set(SERVERS) == {"text-manual", "hw-knowledge", "hw-sandbox", "board-state"}
    hub = ToolHub(transport="inproc", disabled_servers=("hw-sandbox", "board-state"))
    try:
        names = set(hub.tool_names())
        assert {"get_register_bitfields", "find_pins_for_signal", "get_clock_limits", "search_registers", "search_manual"} <= names
        assert "naive_search" not in names                              # baseline-only vẫn ẩn
        assert all(PERMISSIONS[n] == "read-only" for n in names - {"write_config_file"})
        assert hub.owner["get_clock_limits"] == "hw-knowledge"
        res = hub.call("get_register_bitfields", {"chip": "stm32g474", "peripheral": "TIM1", "register": "CR1"})
        assert res["registers"][0]["address"] == "0x40012C00"
    finally:
        hub.close()
