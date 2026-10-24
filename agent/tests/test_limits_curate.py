"""Giới hạn điện & clock curate từ datasheet/RM: mỗi giá trị có doc + page + trích nguyên văn, script tự kiểm."""
import pytest

from ingestion import hwdb, pdfdocs, svd_ingest, limits_curate as lc

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


def row(**kw):
    base = dict(chip="stm32g474", parameter="Supply voltage VDD", category="absolute_max", field_type="supply_voltage",
                symbol="VDD-VSS", min="-0.3", typ=None, max="4.0", unit="V", condition="", applies_to="",
                doc="STM32G474_Datasheet", page=82,
                quote="VDD - VSS External main supply voltage (including VDD, VDDA, VBAT and VREF+) -0.3 4.0")
    base.update(kw)
    return base


def test_verify_row_accepts_a_correct_row():
    assert lc.verify_row(row()) == []


def test_verify_row_rejects_a_quote_that_is_not_on_the_page():
    problems = lc.verify_row(row(quote="VDD - VSS External main supply voltage -0.3 5.5"))
    assert any("quote not found" in p for p in problems)


def test_verify_row_rejects_a_value_that_the_quote_does_not_contain():
    problems = lc.verify_row(row(max="4.6"))
    assert any("'4.6'" in p for p in problems)


def test_verify_row_rejects_the_wrong_page():
    assert any("quote not found" in p for p in lc.verify_row(row(page=83)))


def test_verify_row_requires_known_category_and_unit():
    assert lc.verify_row(row(category="bogus"))
    assert lc.verify_row(row(unit=""))


def test_every_curated_electrical_and_clock_row_passes_automatic_verification():
    bad = {f"{r['chip']}/{r['parameter']}/{r.get('condition','')[:30]}": p
           for r in lc.ELECTRICAL + lc.CLOCK_ROWS() for p in [lc.verify_row(r)] if p}
    assert not bad, bad


def test_each_chip_has_absolute_max_recommended_and_logic_level_rows():
    for chip in ("stm32g474", "esp32", "nrf52840"):
        rows = [r for r in lc.ELECTRICAL if r["chip"] == chip]
        cats = {r["category"] for r in rows}
        types = {r["field_type"] for r in rows}
        assert {"absolute_max", "recommended_operating"} <= cats
        assert {"supply_voltage", "input_voltage_high", "input_voltage_low", "output_voltage_high", "output_voltage_low"} <= types


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("hw") / "hw_specs.sqlite"
    svd_ingest.main(["--db", str(path), "--chips", "stm32g474"])        # tạo schema; limits không phụ thuộc SVD
    assert lc.main(["--db", str(path)]) == 0
    return hwdb.connect(path)


def test_db_rows_are_all_verified_and_cited(db):
    for t in ("electrical_limits", "clock_limits"):
        n, bad = db.execute(f"select count(*), sum(verified=0 or page is null or doc is null or quote='') from {t}").fetchone()
        assert n > 30 and bad == 0, t


@pytest.mark.parametrize("chip,param,cat,max_,page", [
    ("stm32g474", "Supply voltage VDD", "absolute_max", "4.0", 82),          # Table 14
    ("stm32g474", "Supply voltage VDD", "recommended_operating", "3.6", 84), # Table 17
    ("esp32", "High-level input voltage VIH", "dc_characteristics", "VDD+0.3", 52),   # Table 5-3
    ("nrf52840", "Supply voltage VDD", "absolute_max", "3.9", 972),          # Table 101
])
def test_golden_limits(db, chip, param, cat, max_, page):
    r = db.execute("select * from electrical_limits where chip=? and parameter=? and category=?", (chip, param, cat)).fetchone()
    assert r is not None, (chip, param, cat)
    assert (r["max"], r["page"]) == (max_, page)


def test_flash_wait_state_table_from_rm0440(db):
    r = db.execute("select * from clock_limits where chip='stm32g474' and parameter like '%wait states%' "
                   "and condition like '%Range 1 boost%' and parameter like '%0 WS%'").fetchone()
    assert (r["max"], r["unit"], r["doc"], r["page"]) == ("34", "MHz", "STM32G474_RM0440", 98)
    n = db.execute("select count(*) from clock_limits where chip='stm32g474' and parameter like 'Flash wait states%'").fetchone()[0]
    assert n == 13                      # 5 mức WS x 3 dải VCORE, trừ 2 ô '-'


def test_esp32_power_consumption_rows_come_from_table_4_2(db):
    rows = {r["parameter"]: r for r in db.execute(
        "select * from electrical_limits where chip='esp32' and category='power_consumption'")}
    ds = rows["Deep-sleep current: RTC timer + RTC memory"]
    assert (ds["typ"], ds["unit"], ds["doc"], ds["page"]) == ("10", "µA", "ESP32_Datasheet", 30)
    assert rows["Hibernation current: RTC timer only"]["typ"] == "5"
    assert rows["Light-sleep current"]["typ"] == "0.8" and rows["Light-sleep current"]["unit"] == "mA"
    assert (rows["Modem-sleep current, 240 MHz dual-core"]["min"], rows["Modem-sleep current, 240 MHz dual-core"]["max"]) == ("30", "68")


def test_nrf_vih_upper_edge_is_not_exposed_as_a_hard_limit(db):
    """PS Table (6.9.3.1) VIH = 0.7×VDD .. VDD là dải logic-high; giới hạn hỏng nằm ở Table 101 (VDD+0.3 V). Nếu `max`=VDD thì guardrail
    (coi input_voltage_high là giới hạn) từ chối oan 3.4–3.6 V."""
    r = db.execute("select * from electrical_limits where chip='nrf52840' and field_type='input_voltage_high'").fetchone()
    assert r["min"] == "0.7*VDD" and r["max"] is None
    assert "upper edge" in r["condition"] and "VDD+0.3" in r["condition"] and r["page"] == 370
