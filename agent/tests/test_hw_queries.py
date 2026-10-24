"""Lớp truy vấn dữ liệu phần cứng (đọc hw_specs.sqlite) dùng bởi MCP server hw-knowledge."""
import json

import pytest

from ingestion import hwdb, limits_curate, pdfdocs, pinout_extract, svd_ingest
from mcp_servers.hw_queries import HwStore

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


@pytest.fixture(scope="session")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("hwq") / "hw_specs.sqlite"
    assert svd_ingest.main(["--db", str(path)]) == 0
    assert pinout_extract.main(["--db", str(path)]) == 0
    assert limits_curate.main(["--db", str(path)]) == 0
    return HwStore(path)


# ---------------------------------------------------------------- registers
def test_register_lookup_returns_address_reset_fields_and_citation(store):
    r = store.get_register_bitfields("stm32g474", "TIM1", "CR1")
    assert r["count"] == 1
    reg = r["registers"][0]
    assert (reg["name"], reg["address"], reg["offset"], reg["reset_value"], reg["doc"], reg["page"]) == \
        ("TIM1_CR1", "0x40012C00", "0x00", "0x00000000", "STM32G474_RM0440", 1235)
    f = {x["name"]: x for x in reg["fields"]}
    assert f["ARPE"]["bits"] == "[7]" and f["CEN"]["bits"] == "[0]" and f["CKD"]["bits"] == "[9:8]"
    assert reg["access"] == "RW" and reg["reserved_mask"].startswith("0x")


@pytest.mark.parametrize("args", [
    dict(chip="stm32g474", peripheral="TIM1", register="TIM1_CR1"),
    dict(chip="stm32g474", peripheral=None, register="TIM1_CR1"),
    dict(chip="STM32G474", peripheral="tim1", register="cr1"),
    dict(chip="stm32", peripheral="TIM1", register="CR1"),
])
def test_register_name_forms_are_equivalent(store, args):
    r = store.get_register_bitfields(**args)
    assert r["count"] == 1 and r["registers"][0]["address"] == "0x40012C00"


def test_esp32_and_nrf_register_names_follow_the_vendor_documents(store):
    e = store.get_register_bitfields("esp32", "GPIO", "GPIO_OUT_REG")["registers"][0]
    assert (e["address"], e["address_alias"], e["manual_name"], e["doc"]) == ("0x3FF44004", "0x60004004", "GPIO_OUT_REG", "ESP32_TRM")
    n = store.get_register_bitfields("nrf52840", "TWIM0", "PSEL.SCL")["registers"][0]
    assert (n["address"], n["page"]) == ("0x40003508", 798) and {f["name"] for f in n["fields"]} == {"PIN", "PORT", "CONNECT"}


def test_peripheral_listing_is_paginated_and_reports_truncation(store):
    r = store.get_register_bitfields("esp32", "GPIO")
    assert r["total"] == 371 and r["count"] == 30 and r["truncated"] is True and r["next_offset"] == 30
    r2 = store.get_register_bitfields("esp32", "GPIO", offset=30, limit=10)
    assert r2["count"] == 10 and r2["registers"][0]["register"] != r["registers"][0]["register"]
    assert store.get_register_bitfields("stm32g474", "TIM6")["truncated"] is False


def test_svd_only_register_carries_a_warning_and_no_page(store):
    reg = store.get_register_bitfields("stm32g474", "TIM4", "DTR2")["registers"][0]
    assert (reg["doc"], reg["page"], reg["address"]) == ("STM32G474_SVD", None, "0x40000854")
    assert any("not found in the indexed manual" in w.lower() for w in reg["warnings"])


def test_svd_manual_reset_disagreement_is_reported_with_both_values(store):
    reg = store.get_register_bitfields("stm32g474", "FLASH", "ACR")["registers"][0]
    assert (reg["reset_value"], reg["manual_reset_value"]) == ("0x00000600", "0x00040601")
    assert any("0x00040601" in w and "0x00000600" in w for w in reg["warnings"])


def test_single_field_request_returns_all_enumerated_values(store):
    r = store.get_register_bitfields("nrf52840", "P0", "PIN_CNF[0]", field="PULL")["registers"][0]
    (f,) = r["fields"]
    assert f["name"] == "PULL" and f["bits"] == "[3:2]"
    assert [(e["name"], e["value"]) for e in f["enums"]] == [("Disabled", 0), ("Pulldown", 1), ("Pullup", 3)]


def test_response_size_is_bounded_and_flags_what_was_cut(store):
    full = store.get_register_bitfields("stm32g474", "TIM1", "CCMR1_Output")
    r = store.get_register_bitfields("stm32g474", "TIM1", "CCMR1_Output", max_chars=1200)
    assert len(json.dumps(r)) < len(json.dumps(full)) and len(json.dumps(r)) <= 2200
    assert r["registers"][0].get("fields_truncated") or r["registers"][0].get("enums_omitted")
    small = store.get_register_bitfields("stm32g474", "FLASH", "ACR", max_chars=900)["registers"][0]
    assert small.get("fields_truncated") and any("differs" in w for w in small["warnings"])   # cắt field nhưng giữ cảnh báo


def test_unknown_names_return_errors_with_suggestions(store):
    r = store.get_register_bitfields("stm32g474", "TIM11", "CR1")
    assert "error" in r and "TIM1" in " ".join(r.get("suggestions", []))
    r = store.get_register_bitfields("stm32g474", "TIM1", "CR9")
    assert "error" in r and r["suggestions"]
    assert "error" in store.get_register_bitfields("avr128", "X", "Y")


def test_group_name_lists_the_matching_peripherals(store):
    r = store.get_register_bitfields("stm32g474", "TIM")
    assert "TIM1" in r["peripherals"] and r["count"] == 0


def test_search_registers_by_name_description_and_address(store):
    r = store.search_registers("stm32g474", "wakeup timer")
    assert r["results"][0]["register"] == "WUTR" and r["results"][0]["page"] == 1593
    r = store.search_registers("esp32", "uart clkdiv")        # SVD ESP32 không có mô tả -> tìm theo tên
    assert {"UART0", "UART1", "UART2"} <= {x["peripheral"] for x in r["results"] if x["register"] == "CLKDIV"}
    r = store.search_registers("stm32g474", "0x40012C00")
    assert r["results"][0]["name"] == "TIM1_CR1"
    assert len(store.search_registers("stm32g474", "register", limit=5)["results"]) == 5


# ---------------------------------------------------------------- pins
def test_pin_alternate_functions_for_stm32(store):
    r = store.query_pin_alternate_function("stm32g474", "pa8")
    af = {f["af"]: f["function"] for f in r["functions"] if f["af"] is not None}
    assert af[2] == "I2C3_SCL" and af[6] == "TIM1_CH1" and af[0] == "MCO"
    assert (r["pad_name"], r["io_structure"], r["is_5v_tolerant"], r["doc"], r["page"]) == ("PA8", "FT_a", True, "STM32G474_Datasheet", 66)
    assert {f["page"] for f in r["functions"] if f["kind"] == "af"} == {73}
    assert 1 in r["unused_af"] and 3 in r["unused_af"]
    assert all(f["doc"] and f["page"] for f in r["functions"])


@pytest.mark.parametrize("pin,expected", [("GPIO34", "GPIO34"), ("34", "GPIO34"), ("VDET_1", "GPIO34"), ("gpio34", "GPIO34")])
def test_esp32_pin_name_forms(store, pin, expected):
    r = store.query_pin_alternate_function("esp32", pin)
    assert r["pin"] == expected and r["input_only"] is True
    assert {f["kind"] for f in r["flags"]} == {"input_only"}


def test_esp32_strapping_and_flash_flags(store):
    assert {f["kind"] for f in store.query_pin_alternate_function("esp32", "GPIO12")["flags"]} == {"strapping"}
    assert "flash" in {f["kind"] for f in store.query_pin_alternate_function("esp32", "GPIO6")["flags"]}


def test_nrf_pin_forms_and_fixed_functions(store):
    r = store.query_pin_alternate_function("nrf52840", "P0.5")
    assert r["pin"] == "P0.05" and [f["function"] for f in r["functions"]] == ["AIN3"]
    assert "PSEL" in r["routing_note"]
    assert store.query_pin_alternate_function("nrf52840", "p1.15")["functions"] == []


def test_unknown_pin_returns_error(store):
    assert "error" in store.query_pin_alternate_function("stm32g474", "PZ9")


def test_find_pins_for_signal(store):
    r = store.find_pins_for_signal("stm32g474", "TIM1_CH1")
    assert {"pin": "PA8", "af": 6} in [{"pin": m["pin"], "af": m["af"]} for m in r["matches"]]
    r = store.find_pins_for_signal("stm32g474", "USART2")
    assert r["count"] > 5 and all(m["function"].startswith("USART2") for m in r["matches"])
    assert [m["pin"] for m in store.find_pins_for_signal("esp32", "U0TXD")["matches"]] == ["GPIO1"]
    assert [m["pin"] for m in store.find_pins_for_signal("nrf52840", "AIN7")["matches"]] == ["P0.31"]
    r = store.find_pins_for_signal("stm32g474", "TIM1", limit=3)
    assert r["count"] == 3 and r["truncated"] is True and r["total"] > 3


# ---------------------------------------------------------------- electrical / clock / compatibility
def test_electrical_results_keep_the_structure_the_guardrail_reads(store):
    r = store.get_electrical_specs("stm32g474", "supply voltage VDD")
    for row in r["results"]:
        assert {"category", "field_type", "min", "max", "unit", "parameter", "doc", "page"} <= set(row)
    top = [x for x in r["results"] if x["field_type"] == "supply_voltage"]
    assert {(x["category"], x["max"], x["page"]) for x in top} == {("absolute_max", "4.0", 82), ("recommended_operating", "3.6", 84)}


def test_electrical_evaluates_vdd_expressions(store):
    r = store.get_electrical_specs("esp32", "input voltage VIH pin", vdd=3.3)
    vih = next(x for x in r["results"] if x["field_type"] == "input_voltage_high")
    assert vih["evaluated_at_vdd"]["max"] == pytest.approx(3.6) and vih["evaluated_at_vdd"]["min"] == pytest.approx(2.475)


def test_electrical_category_filter_and_limit(store):
    r = store.get_electrical_specs("nrf52840", "", category="absolute_max", limit=3)
    assert r["truncated"] is True and {x["category"] for x in r["results"]} == {"absolute_max"} and len(r["results"]) == 3


def test_clock_limits_for_flash_wait_states_and_pll(store):
    r = store.get_clock_limits("stm32g474", "flash wait states")
    assert any(x["max"] == "34" and "Range 1 boost" in x["condition"] and x["page"] == 98 for x in r["results"])
    r = store.get_clock_limits("stm32g474", "PLL VCO")
    assert any(x["symbol"] == "fVCO_OUT" and x["max"] == "344" for x in r["results"])
    assert any(x["max"] == "240" for x in store.get_clock_limits("esp32", "CPU frequency")["results"])


def test_logic_level_check_esp32_to_nrf(store):
    ok = store.check_logic_level_compatibility("esp32", "nrf52840", 3.3, 3.0)
    assert ok["verdict"] == "compatible"
    bad = store.check_logic_level_compatibility("esp32", "nrf52840", 3.3, 1.8)
    assert bad["verdict"].startswith("incompatible") and any(c["status"] == "FAIL" for c in bad["checks"])
    assert ok["evidence"] and all("doc" in e and "page" in e for e in ok["evidence"])


def test_logic_level_check_handles_chips_where_vih_has_no_upper_bound(store):
    r = store.check_logic_level_compatibility("nrf52840", "stm32g474", 3.0, 3.3)
    assert "checks" in r and "error" not in r


def test_chip_logic_levels_stm32g474_from_the_datasheet_tables(store):
    """DS12288 Table 54 p.128 (VIL <= 0.3 VDD, VIH >= 0.7 VDD), Table 55 p.130 (VOL <= 0.4 V, VOH >= VDD-0.4 V for VDD >= 2.7 V),
    Table 17 p.84 (VIN max: TT_xx = VDD+0.3 V, FT_xxx = 5.5 V), Table 14 p.82 (absolute max: TT 4.0 V, FT = VDD+4.0 V)."""
    ft = store.chip_logic_levels("stm32g474", 3.3, "FT_f")
    assert (ft["vih_min"], ft["vil_max"], ft["voh_min"], ft["vol_max"], ft["voh_max"]) == pytest.approx((2.31, 0.99, 2.9, 0.4, 3.3))
    assert ft["in_max"] == 5.5 and ft["in_max_source"]["page"] == 84
    tt = store.chip_logic_levels("stm32g474", 3.3, "TT_a")
    assert tt["in_max"] == pytest.approx(3.6) and tt["in_max_source"]["page"] == 84
    assert store.chip_logic_levels("stm32g474", 3.3)["in_max"] == pytest.approx(3.6)          # kiểu chân chưa biết: lấy giới hạn chặt nhất
    assert {e["page"] for e in ft["evidence"]} >= {128, 130, 84}
    assert "error" in store.chip_logic_levels("avr", 3.3)


def test_chip_logic_levels_flags_vdd_below_the_row_validity(store):
    r = store.chip_logic_levels("stm32g474", 1.8, "FT_f")
    assert r["voh_min"] == pytest.approx(1.4) and any("2.7" in n for n in r["notes"])
    assert store.chip_logic_levels("stm32g474", 3.3)["notes"] == []


def test_check_logic_level_compatibility_is_unchanged_by_the_refactor(store):
    r = store.check_logic_level_compatibility("esp32", "stm32g474", 3.3, 3.3, dst_io_structure="FT_f")
    assert r["verdict"] == "compatible" and [c["status"] for c in r["checks"]] == ["PASS", "PASS", "PASS"]
    assert r["checks"][0]["detail"].startswith("src VOH_min = ") and "dst max input voltage = 5.5 V" in r["checks"][2]["detail"]


def test_list_chips_reports_sizes(store):
    r = store.list_chips()
    assert set(r["chips"]) == {"esp32", "stm32g474", "nrf52840"}
    assert r["details"]["stm32g474"]["registers"] == 1585 and r["details"]["esp32"]["pins"] == 34
