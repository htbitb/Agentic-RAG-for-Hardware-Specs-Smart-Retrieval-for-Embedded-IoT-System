"""ESP32 IO_MUX (TRM Table 6.10-1, tr.133 + datasheet Appendix A.4, tr.69), cờ chân; nRF52840 ball assignment (PS tr.927–929).
Golden = đọc TAY text trang."""
import pytest

from ingestion import pdfdocs
from ingestion.pinout_extract import (ESP_DS, ESP_TRM, NRF_PS, esp32_io_mux, esp32_pin_flags, nrf_fixed_functions,
                                      verify_quote)

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


@pytest.fixture(scope="module")
def mux():
    return {r.gpio: r for r in esp32_io_mux()}


# TRM p.133: "25 GPIO25 GPIO25 - GPIO25 - - EMAC_RXD0 0 R"  (GPIO, tên chân, Function0..5, Reset, Notes)
ESP_GOLDEN = {
    0: ("GPIO0", {0: "GPIO0", 1: "CLK_OUT1", 2: "GPIO0", 5: "EMAC_TX_CLK"}),
    1: ("U0TXD", {0: "U0TXD", 1: "CLK_OUT3", 2: "GPIO1", 5: "EMAC_RXD2"}),
    2: ("GPIO2", {0: "GPIO2", 1: "HSPIWP", 2: "GPIO2", 3: "HS2_DATA0", 4: "SD_DATA0"}),
    12: ("MTDI", {0: "MTDI", 1: "HSPIQ", 2: "GPIO12", 3: "HS2_DATA2", 4: "SD_DATA2", 5: "EMAC_TXD3"}),
    16: ("GPIO16", {0: "GPIO16", 2: "GPIO16", 3: "HS1_DATA4", 4: "U2RXD", 5: "EMAC_CLK_OUT"}),
    25: ("GPIO25", {0: "GPIO25", 2: "GPIO25", 5: "EMAC_RXD0"}),
    34: ("VDET_1", {0: "GPIO34", 2: "GPIO34"}),
}


@pytest.mark.parametrize("gpio", list(ESP_GOLDEN))
def test_esp32_io_mux_golden(mux, gpio):
    pad, funcs = ESP_GOLDEN[gpio]
    r = mux[gpio]
    assert r.pad_name == pad
    assert {k: v for k, v in r.functions.items() if v} == funcs
    assert r.doc == ESP_TRM and r.page == 133


def test_esp32_has_every_gpio_the_trm_lists(mux):
    assert sorted(mux) == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27,
                           32, 33, 34, 35, 36, 37, 38, 39]               # 34 GPIO (không có 20, 24, 28–31)
    for r in mux.values():
        assert sorted(r.functions) == list(range(6))


def test_esp32_input_only_pins_are_gpio34_to_39_from_the_trm_notes_column(mux):
    assert sorted(g for g, r in mux.items() if r.input_only) == [34, 35, 36, 37, 38, 39]
    assert all(r.rtc_capable for g, r in mux.items() if g in (25, 26, 27, 32, 33, 34, 0, 2, 4, 12, 13, 14, 15))
    assert not mux[18].rtc_capable


def test_esp32_datasheet_io_mux_adds_power_domain_analog_and_type(mux):
    r = mux[25]
    assert r.power_domain == "VDD3P3_RTC" and r.package_pin == 14                 # datasheet p.69: "14 GPIO25 VDD3P3_RTC DAC_1 ADC2_CH8 RTC_GPIO6"
    assert set(r.analog) == {"DAC_1", "ADC2_CH8"} and r.rtc_funcs == ["RTC_GPIO6"]
    assert mux[16].power_domain == "VDD_SDIO" and mux[16].package_pin == 25
    assert mux[36].package_pin == 5 and mux[36].pad_name == "SENSOR_VP"


def test_esp32_flags_have_page_and_quote_that_exist_in_the_page_text():
    flags = esp32_pin_flags()
    assert {f.gpio for f in flags if f.kind == "strapping"} == {0, 2, 5, 12, 15}
    assert {f.gpio for f in flags if f.kind == "input_only"} == {34, 35, 36, 37, 38, 39}
    assert {f.gpio for f in flags if f.kind == "flash"} >= {6, 7, 8, 9, 10, 11}
    for f in flags:
        assert verify_quote(f.doc, f.page, f.quote), (f.gpio, f.kind, f.quote)


def test_verify_quote_ignores_whitespace_and_case_but_not_content():
    assert verify_quote(ESP_DS, 22, "GPIO0 Pull-up 1")
    assert not verify_quote(ESP_DS, 22, "GPIO0 Pull-up 0")


@pytest.fixture(scope="module")
def nrf():
    return {r.pin: r for r in nrf_fixed_functions()}


NRF_GOLDEN = {
    # PS p.927–929 (Table 61: aQFN73 ball assignments), đọc tay
    "P0.31": ("A8", ["AIN7"]), "P0.29": ("A10", ["AIN5"]), "P0.02": ("A12", ["AIN0"]), "P0.03": ("B13", ["AIN1"]),
    "P0.30": ("B9", ["AIN6"]), "P0.28": ("B11", ["AIN4"]), "P0.04": ("J1", ["AIN2"]), "P0.05": ("K2", ["AIN3"]),
    "P0.00": ("D2", ["XL1"]), "P0.01": ("F2", ["XL2"]), "P0.09": ("L24", ["NFC1"]), "P0.10": ("J24", ["NFC2"]),
    "P0.07": ("M2", ["TRACECLK"]), "P1.09": ("R1", ["TRACEDATA3"]), "P0.11": ("T2", ["TRACEDATA2"]),
    "P0.12": ("U1", ["TRACEDATA1"]), "P1.00": ("AD22", ["TRACEDATA0", "SWO"]), "P0.18": ("AC13", ["nRESET"]),
}


@pytest.mark.parametrize("pin", list(NRF_GOLDEN))
def test_nrf_fixed_function_golden(nrf, pin):
    ball, funcs = NRF_GOLDEN[pin]
    r = nrf[pin]
    assert (r.ball, sorted(r.functions)) == (ball, sorted(funcs))
    assert r.doc == NRF_PS and r.page in (927, 928, 929)


def test_nrf_plain_gpio_has_no_fixed_function_and_low_frequency_hint_is_kept(nrf):
    assert nrf["P1.15"].functions == [] and nrf["P1.15"].low_frequency_only         # "Standard drive, low frequency I/O only"
    assert not nrf["P0.26"].low_frequency_only


def test_nrf_lists_every_gpio_of_the_aqfn73_package(nrf):
    assert sorted(nrf) == sorted([f"P0.{i:02d}" for i in range(32)] + [f"P1.{i:02d}" for i in range(16)])
