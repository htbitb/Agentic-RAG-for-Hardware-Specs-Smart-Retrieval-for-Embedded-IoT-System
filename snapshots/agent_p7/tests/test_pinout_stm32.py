"""Trích bảng Alternate Function (Table 13) và Pin definition (Table 12) của STM32G474 từ datasheet bằng pdfplumber.
Golden = đọc TAY text trang datasheet (DS12288 Rev 6): AF p.73–79, pin definition p.56–72."""
import pytest

from ingestion import pdfdocs
from ingestion.pinout_extract import ST_DS, normalize_cell, stm32_af_rows, stm32_pin_definitions

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


@pytest.mark.parametrize("raw,expected", [
    ("USART2_\nCTS", ["USART2_CTS"]), ("EVENT\nOUT", ["EVENTOUT"]), ("-", []), ("", []), (None, []),
    ("SPI3_NSS/\nI2S3_WS", ["SPI3_NSS", "I2S3_WS"]), ("SWDIO-JTMS", ["SWDIO-JTMS"]), ("TIM8_\nBKIN", ["TIM8_BKIN"]),
    ("QUADSPI1_\nBK1_NCS", ["QUADSPI1_BK1_NCS"]), ("--", []),
])
def test_normalize_cell(raw, expected):
    assert normalize_cell(raw) == expected


@pytest.fixture(scope="module")
def af():
    return {r.pin: r for r in stm32_af_rows()}


@pytest.fixture(scope="module")
def pindefs():
    return stm32_pin_definitions()


GOLDEN_AF = {
    # đọc tay: "PA8 MCO - I2C3_SCL - I2C2_SDA I2S2_MCK TIM1_CH1 USART1_CK COMP7_OUT - TIM4_ETR FDCAN3_RX SAI1_CK2 HRTIM1_CHA1 SAI1_SCK_A EVENTOUT"
    "PA8": (73, {0: ["MCO"], 2: ["I2C3_SCL"], 4: ["I2C2_SDA"], 5: ["I2S2_MCK"], 6: ["TIM1_CH1"], 7: ["USART1_CK"],
                 8: ["COMP7_OUT"], 10: ["TIM4_ETR"], 11: ["FDCAN3_RX"], 12: ["SAI1_CK2"], 13: ["HRTIM1_CHA1"],
                 14: ["SAI1_SCK_A"], 15: ["EVENTOUT"]}),
    "PB6": (74, {1: ["TIM16_CH1N"], 2: ["TIM4_CH1"], 5: ["TIM8_CH1"], 6: ["TIM8_ETR"], 7: ["USART1_TX"], 8: ["COMP4_OUT"],
                 9: ["FDCAN2_TX"], 10: ["TIM8_BKIN2"], 11: ["LPTIM1_ETR"], 12: ["HRTIM1_SCIN"], 13: ["HRTIM1_EEV4"],
                 14: ["SAI1_FS_B"], 15: ["EVENTOUT"]}),
    "PA13": (73, {0: ["SWDIO-JTMS"], 1: ["TIM16_CH1N"], 3: ["I2C4_SCL"], 4: ["I2C1_SCL"], 5: ["IR_OUT"], 7: ["USART3_CTS"],
                  10: ["TIM4_CH3"], 13: ["SAI1_SD_B"], 15: ["EVENTOUT"]}),
    "PC13": (75, {2: ["TIM1_BKIN"], 4: ["TIM1_CH1N"], 6: ["TIM8_CH4N"], 15: ["EVENTOUT"]}),
    "PA0": (73, {1: ["TIM2_CH1"], 2: ["TIM5_CH1"], 7: ["USART2_CTS"], 8: ["COMP1_OUT"], 9: ["TIM8_BKIN"], 10: ["TIM8_ETR"],
                 14: ["TIM2_ETR"], 15: ["EVENTOUT"]}),
}


@pytest.mark.parametrize("pin", list(GOLDEN_AF))
def test_af_golden_rows(af, pin):
    page, slots = GOLDEN_AF[pin]
    row = af[pin]
    assert row.page == page
    assert {k: v for k, v in row.slots.items() if v} == slots


def test_every_pin_has_all_sixteen_af_slots_ae0_to_af15(af):
    assert len(af) >= 100
    for pin, row in af.items():
        assert sorted(row.slots) == list(range(16)), pin


def test_af_table_covers_every_gpio_of_the_largest_package(af, pindefs):
    """Gói lớn nhất = LQFP128 (128 chân): mọi chân GPIO ở cột LQFP128 của bảng pin definition phải có hàng AF."""
    lqfp128 = {n for n, d in pindefs.items() if d.is_gpio and d.packages.get("LQFP128", "-") not in ("-", "")}
    assert len(lqfp128) >= 100
    missing = sorted(lqfp128 - set(af))
    assert not missing, missing


@pytest.mark.parametrize("pin,io,ball128,five_v", [
    ("PA8", "FT_a", "89", True),        # p.66: "D1 30 30 42 56 E10 69 E7 89 PA8 I/O FT_a"
    ("PB6", "FT_c", "121", True),       # p.71
    ("PA13", "FT_f", "96", True),       # p.67
    ("PC13", "FT", "7", True),          # p.57
])
def test_pin_definition_golden(pindefs, pin, io, ball128, five_v):
    d = pindefs[pin]
    assert (d.io_structure, d.packages["LQFP128"], d.is_5v_tolerant) == (io, ball128, five_v)
    assert d.doc == ST_DS and d.page >= 56


def test_tt_pins_are_not_5v_tolerant(pindefs):
    tt = [d for d in pindefs.values() if d.io_structure.startswith("TT")]
    assert tt and all(not d.is_5v_tolerant for d in tt)
