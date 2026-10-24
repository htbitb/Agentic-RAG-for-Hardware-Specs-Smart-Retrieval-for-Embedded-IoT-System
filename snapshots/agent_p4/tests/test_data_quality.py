"""Báo cáo chất lượng dữ liệu: số liệu, spot-check ngẫu nhiên với các kiểm tra ĐỘC LẬP với extractor."""
import pytest

import config
from ingestion import data_quality as dq
from ingestion import hwdb, pdfdocs

ST_PAGE = """RM0440 Real-time clock (RTC)
37.6.6 RTC wakeup timer register (RTC_WUTR)
Address offset: 0x14
Backup domain reset value: 0x0000 FFFF
Bits 31:16 Reserved, must be kept at reset value.
Bits 15:0 WUT[15:0]: Wakeup auto-reload value bits
"""
NRF_PAGE = """6.9.2.4 IN
Address offset: 0x510
Read GPIO port
Reset 0x00000000 0 0 0
A RW PIN0 Pin 0
"""
ESP_PAGE = """Register 19.9. UART _CONF0_REG (0x20)
Reset
UART_BIT_NUM
"""


def reg(**kw):
    base = dict(chip="stm32g474", peripheral="RTC", name="WUTR", rm_name="RTC_WUTR", offset=0x14, address=0x40002814,
                reset_value=0xFFFF, rm_reset_value=None, size=32, page=1593, doc="STM32G474_RM0440", page_confidence="high")
    base.update(kw)
    return base


def test_register_check_confirms_offset_reset_and_field_from_the_page_text():
    r = dq.check_register(reg(), [{"name": "WUT", "bit_offset": 0, "bit_width": 16}], {1593: ST_PAGE})
    assert r["match"] is True and "0x14" in r["pdf"] and "0000FFFF" in r["pdf"].replace(" ", "").upper()


@pytest.mark.parametrize("override", [dict(offset=0x18), dict(reset_value=0x1234)])
def test_register_check_detects_a_wrong_offset_or_reset(override):
    r = dq.check_register(reg(**override), [{"name": "WUT", "bit_offset": 0, "bit_width": 16}], {1593: ST_PAGE})
    assert r["match"] is False


def test_register_check_detects_a_wrong_field_range():
    r = dq.check_register(reg(), [{"name": "WUT", "bit_offset": 4, "bit_width": 8}], {1593: ST_PAGE})
    assert r["match"] is False and "WUT" in r["pdf"]


def test_register_check_for_nrf_and_esp32_flavours():
    n = dq.check_register(reg(chip="nrf52840", peripheral="P0", name="IN", rm_name="IN", offset=0x510, address=0x50000510,
                              reset_value=0, page=326, doc="nRF52840_PS"), [{"name": "PIN0", "bit_offset": 0, "bit_width": 1}], {326: NRF_PAGE})
    assert n["match"] is True
    e = dq.check_register(reg(chip="esp32", peripheral="UART0", name="CONF0", rm_name="UART_CONF0_REG", offset=0x20,
                              address=0x3FF40020, reset_value=0x800001C, page=332, doc="ESP32_TRM"),
                          [{"name": "BIT_NUM", "bit_offset": 2, "bit_width": 2}], {332: ESP_PAGE})
    assert e["match"] is True
    bad = dq.check_register(reg(chip="esp32", peripheral="UART0", name="CONF0", rm_name="UART_CONF0_REG", offset=0x24,
                                address=0x3FF40024, reset_value=0, page=332, doc="ESP32_TRM"), [], {332: ESP_PAGE})
    assert bad["match"] is False


def test_svd_only_registers_are_never_sampled_as_page_checks():
    assert dq.check_register(reg(page=None), [], {})["match"] is None


def test_sampling_is_deterministic_and_stratified():
    rows = [{"chip": c, "i": i} for c in ("a", "b", "c") for i in range(50)]
    s1 = dq.sample_by_chip(rows, {"a": 7, "b": 7, "c": 6}, seed=1022)
    s2 = dq.sample_by_chip(rows, {"a": 7, "b": 7, "c": 6}, seed=1022)
    assert s1 == s2 and len(s1) == 20 and sum(1 for x in s1 if x["chip"] == "c") == 6
    assert s1 != dq.sample_by_chip(rows, {"a": 7, "b": 7, "c": 6}, seed=7)


pytestmark_real = pytest.mark.skipif(not (config.HW_DB.is_file() and config.TEXT_INDEX_DB.is_file() and
                                          pdfdocs.CORPUS.joinpath("manifest.yaml").is_file()), reason="data not built")


@pytestmark_real
def test_stm32_af_cell_read_by_word_positions_agrees_with_the_database():
    conn = hwdb.connect(config.HW_DB, readonly=True)
    pdf_cells = dq.stm32_af_by_words("PA8")
    db = {r["af"]: r["signal"] for r in conn.execute("select af, signal from pin_functions where chip='stm32g474' and pin='PA8' and kind='af'")}
    assert pdf_cells[2] == "I2C3_SCL" and pdf_cells[6] == "TIM1_CH1" and pdf_cells[0] == "MCO"
    assert {k: v for k, v in pdf_cells.items() if v} == db


@pytestmark_real
def test_esp32_function_names_in_the_datasheet_io_mux_table_agree_with_the_trm_based_rows():
    ds = dq.esp32_datasheet_functions()
    assert ds[25][5] == "EMAC_RXD0" and ds[25][0] == "GPIO25" and ds[34][2] == "GPIO34"


@pytestmark_real
def test_collect_stats_counts_and_page_coverage_are_consistent():
    s = dq.collect_stats(hwdb.connect(config.HW_DB, readonly=True), config.TEXT_INDEX_DB)
    st = s["registers"]["stm32g474"]
    assert (st["peripherals"], st["registers"]) == (91, 1585) and st["with_page"] + st["svd_only"] == st["registers"]
    assert sum(st["by_confidence"].values()) == st["with_page"]
    assert s["pins"]["stm32g474"] == 107 and s["chunks"]["total"] == 9583
    assert 0 < s["page_coverage"]["registers"]["all"] <= 1


def test_stm32_field_check_accepts_any_documented_variant_of_the_bit_range():
    page = ("37.6.6 RTC wakeup timer register (RTC_WUTR)\nAddress offset: 0x14\nReset value: 0x0000 0000\n"
            "Bits 19:4 ARR[15:0]: dithering variant\nBits 15:0 ARR[15:0]: Auto-reload value\n")
    r = dq.check_register(reg(rm_name="RTC_WUTR", reset_value=0), [{"name": "ARR", "bit_offset": 0, "bit_width": 16}], {1593: page})
    assert r["match"] is True
    r = dq.check_register(reg(rm_name="RTC_WUTR", reset_value=0), [{"name": "ARR", "bit_offset": 0, "bit_width": 8}], {1593: page})
    assert r["match"] is False


def test_esp32_array_register_is_checked_against_the_pattern_heading_and_formula():
    page = "Register 6.15. GPIO_FUNCy_IN_SEL_CFG_REG (y: 0-255) (0x130+0x4*y)\nGPIO_FUNCy_IN_SEL_CFG_REG ...\n"
    ok = dq.check_register(reg(chip="esp32", peripheral="GPIO", name="FUNC33_IN_SEL_CFG", rm_name="GPIO_FUNC33_IN_SEL_CFG_REG",
                               offset=0x130 + 4 * 33, address=0x3FF441B4, reset_value=0, page=139, doc="ESP32_TRM"), [], {139: page})
    assert ok["match"] is True
    bad = dq.check_register(reg(chip="esp32", peripheral="GPIO", name="FUNC33_IN_SEL_CFG", rm_name="GPIO_FUNC33_IN_SEL_CFG_REG",
                                offset=0x131, address=0x3FF44131, reset_value=0, page=139, doc="ESP32_TRM"), [], {139: page})
    assert bad["match"] is False                       # offset không thuộc dãy 0x130 + 4*y


@pytestmark_real
def test_af_word_reader_ignores_page_header_and_footer_words():
    cells = dq.stm32_af_by_words("PA13")               # hàng cuối của một trang: trước đây hút cả chữ chân trang
    assert cells[15] == "EVENTOUT" and cells[0] == "SWDIO-JTMS"


def test_esp32_array_formula_with_a_decimal_stride_is_recognised():
    page = "Register 21.21. I2C_COMDn_REG (n: 0-15) (0x58+4* n)\nI2C_COMDn_REG ...\n"
    mk = lambda off: dq.check_register(reg(chip="esp32", peripheral="I2C1", name="COMD9", rm_name="I2C_COMD9_REG", offset=off,  # noqa: E731
                                            address=0x3FF67000 + off, reset_value=0, page=414, doc="ESP32_TRM"), [], {414: page})
    assert mk(0x58 + 4 * 9)["match"] is True            # 0x7C
    assert mk(0x58 + 4 * 9 + 2)["match"] is False       # không nằm trên dãy 0x58 + 4*n
