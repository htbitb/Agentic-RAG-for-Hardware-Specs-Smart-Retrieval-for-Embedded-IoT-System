"""Ghi chân/AF vào SQLite + kiểm tra chéo (mỗi chân đủ 16 khe AF, tiền tố tín hiệu ∈ SVD, AF ↔ pin definition)."""
import json

import pytest

from ingestion import hwdb, pdfdocs, pinout_extract, svd_ingest
from ingestion.pinout_extract import signal_peripheral

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")

SVD_NAMES = {"TIM2": "TIM", "USART2": "USART", "COMP": "COMP", "LPTIMER1": "LPTIM", "SAI": "SAI", "SPI3": "SPI", "SPI2": "SPI",
             "RCC": "RCC", "TIM16": "TIM", "USB_FS_device": "USB", "UART4": "USART", "HRTIM_Common": "HRTIM"}


@pytest.mark.parametrize("sig,expected", [
    ("TIM2_CH1", ("TIM2", None)), ("USART2_CTS", ("USART2", None)), ("UART4_TX", ("UART4", None)),
    ("COMP1_OUT", ("COMP", None)), ("LPTIM1_ETR", ("LPTIMER1", None)), ("SAI1_CK1", ("SAI", None)),
    ("I2S3_CK", ("SPI3", None)), ("MCO", ("RCC", None)), ("USB_CRS_SYNC", ("USB_FS_device", None)),
    ("HRTIM1_CHA1", ("HRTIM_Common", None)),
])
def test_signal_peripheral_maps_to_svd_peripheral(sig, expected):
    assert signal_peripheral(sig, SVD_NAMES) == expected


@pytest.mark.parametrize("sig", ["EVENTOUT", "SWDIO-JTMS", "JTDO-TRACESWO", "TRACECK", "TRACED2", "IR_OUT", "I2SCKIN"])
def test_signals_without_an_svd_peripheral_carry_a_reason(sig):
    per, reason = signal_peripheral(sig, SVD_NAMES)
    assert per is None and reason


def test_unknown_signal_prefix_is_reported_not_guessed():
    per, reason = signal_peripheral("FOOBAR_X", SVD_NAMES)
    assert per is None and reason.startswith("unknown")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("hw") / "hw_specs.sqlite"
    assert svd_ingest.main(["--db", str(path)]) == 0
    assert pinout_extract.main(["--db", str(path)]) == 0
    return hwdb.connect(path)


def test_stm32_pin_rows_and_alternate_functions(db):
    p = db.execute("select * from pins where chip='stm32g474' and pin='PA8'").fetchone()
    assert (p["io_structure"], p["is_5v_tolerant"], p["port"], p["number"], p["doc"]) == ("FT_a", 1, "A", 8, "STM32G474_Datasheet")
    assert json.loads(p["packages"])["LQFP128"] == "89"
    af = {r["af"]: (r["signal"], r["peripheral"], r["page"]) for r in
          db.execute("select * from pin_functions where chip='stm32g474' and pin='PA8' and kind='af'")}
    assert af[2] == ("I2C3_SCL", "I2C3", 73) and af[6] == ("TIM1_CH1", "TIM1", 73) and af[15][0] == "EVENTOUT"
    assert 1 not in af and 3 not in af                      # khe AF1/AF3 của PA8 là "-"


def test_stm32_every_gpio_has_all_sixteen_af_slots_recorded(db):
    n = db.execute("select count(*) from pins where chip='stm32g474'").fetchone()[0]
    assert n == 107
    per_pin = {r["pin"]: r["n"] for r in db.execute(
        "select pin, count(distinct af) n from pin_functions where chip='stm32g474' and kind='af' group by pin")}
    assert len(per_pin) == 107 and all(1 <= n <= 16 for n in per_pin.values())
    row = db.execute("select value from chip_notes where chip='stm32g474' and topic='af_slots_per_pin'").fetchone()
    assert row is not None and row["value"] == "16"


def test_stm32_additional_functions_are_recorded_separately(db):
    kinds = {r["kind"] for r in db.execute("select distinct kind from pin_functions where chip='stm32g474'")}
    assert {"af", "additional"} <= kinds


def test_stm32_datasheet_inconsistencies_become_anomalies(db):
    refs = {(r["kind"], r["ref"]) for r in db.execute("select kind, ref from data_anomalies where chip='stm32g474'")}
    assert ("af_vs_pindef", "PB3") in refs                   # AF3 = USB_CRS_SYNC (Table 13) vs UCPD1_CRS_SYNC (pin definition)


def test_esp32_pins_flags_and_functions(db):
    p = db.execute("select * from pins where chip='esp32' and pin='GPIO34'").fetchone()
    assert (p["input_only"], p["pad_name"], p["number"]) == (1, "VDET_1", 34)
    assert db.execute("select input_only from pins where chip='esp32' and pin='GPIO25'").fetchone()[0] == 0
    fl = {(r["pin"], r["kind"]) for r in db.execute("select pin, kind from pin_flags where chip='esp32'")}
    assert {("GPIO0", "strapping"), ("GPIO12", "strapping"), ("GPIO34", "input_only"), ("GPIO6", "flash")} <= fl
    q = db.execute("select * from pin_flags where chip='esp32' and pin='GPIO2' and kind='strapping'").fetchone()
    assert (q["doc"], q["page"], q["source"]) == ("ESP32_Datasheet", 22, "curated") and "GPIO2" in q["quote"]
    f = {r["af"]: r["signal"] for r in db.execute("select af, signal from pin_functions where chip='esp32' and pin='GPIO25' and kind='io_mux'")}
    assert f == {0: "GPIO25", 2: "GPIO25", 5: "EMAC_RXD0"}


def test_nrf_pins_fixed_functions_and_psel_note(db):
    assert db.execute("select count(*) from pins where chip='nrf52840'").fetchone()[0] == 48
    f = [r["signal"] for r in db.execute("select signal from pin_functions where chip='nrf52840' and pin='P0.31' and kind='fixed'")]
    assert f == ["AIN7"]
    note = db.execute("select * from chip_notes where chip='nrf52840' and topic='psel_routing'").fetchone()
    assert (note["doc"], note["page"]) == ("nRF52840_PS", 322) and "PSEL" in note["value"]
    lay = db.execute("select * from chip_notes where chip='nrf52840' and topic='psel_register_layout'").fetchone()
    assert (lay["doc"], lay["page"]) == ("nRF52840_PS", 798) and "CONNECT" in lay["value"]
    assert db.execute("select page from pins where chip='nrf52840' and pin='P1.15'").fetchone()[0] == 927
