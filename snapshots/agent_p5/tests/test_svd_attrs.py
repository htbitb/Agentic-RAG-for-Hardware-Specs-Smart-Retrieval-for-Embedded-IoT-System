"""ingestion.svd_attrs — sidecar `data/svd_attrs.json`: modifiedWriteValues / readAction ở mức THANH GHI và TRƯỜNG.

Lý do: DB P1 chỉ lưu `modifiedWriteValues` ở mức trường nên mất W1C/oneToSet của thanh ghi nRF (P0.OUTSET...).
Đổi lược đồ DB sẽ buộc dựng lại cả DB (gắn trang PDF), nên P2 thêm sidecar nhỏ, có sha256 của SVD nguồn.
"""
import hashlib
import json
from pathlib import Path

import pytest

from ingestion import hwdb, svd_attrs
from ingestion.svd_ingest import parse_svd_text

CORPUS = Path(__file__).resolve().parents[2] / "corpus"

SVD = """<?xml version="1.0"?><device><name>T</name><peripherals>
<peripheral><name>P</name><baseAddress>0x1000</baseAddress><registers>
  <register><name>A</name><addressOffset>0</addressOffset><size>32</size><access>read-write</access>
    <modifiedWriteValues>oneToClear</modifiedWriteValues></register>
  <register><name>B</name><addressOffset>4</addressOffset><size>32</size><access>read-only</access>
    <readAction>clear</readAction>
    <fields><field><name>F</name><bitOffset>0</bitOffset><bitWidth>1</bitWidth><access>read-only</access></field></fields></register>
  <register><name>C</name><addressOffset>8</addressOffset><size>32</size><access>read-write</access>
    <fields><field><name>G</name><bitOffset>3</bitOffset><bitWidth>2</bitWidth><modifiedWriteValues>oneToSet</modifiedWriteValues></field></fields></register>
  <register><name>D</name><addressOffset>12</addressOffset><size>32</size><access>read-write</access></register>
</registers></peripheral></peripherals></device>"""


def test_register_level_attributes_are_extracted_from_svd_text():
    got = svd_attrs.extract(parse_svd_text(SVD))
    assert got["P.A"] == {"modified_write": "oneToClear"}
    assert got["P.B"] == {"read_action": "clear"}
    assert got["P.C"] == {"fields": {"G": {"modified_write": "oneToSet"}}}
    assert "P.D" not in got                      # không có thuộc tính => không ghi (giữ sidecar nhỏ)


def test_sidecar_is_built_for_all_chips_and_matches_the_svd_sources():
    path = hwdb.ROOT / "data" / "svd_attrs.json"
    assert path.is_file(), "chạy `python -m ingestion.svd_attrs` để dựng data/svd_attrs.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["chips"]) == {"stm32g474", "esp32", "nrf52840"}
    for chip, entry in data["chips"].items():
        svd_file = CORPUS / "svd" / Path(entry["svd_file"]).name
        assert hashlib.sha256(svd_file.read_bytes()).hexdigest() == entry["svd_sha256"], chip


def test_nrf_gpio_set_clear_registers_are_in_the_sidecar():
    data = json.loads((hwdb.ROOT / "data" / "svd_attrs.json").read_text(encoding="utf-8"))["chips"]["nrf52840"]["registers"]
    assert data["P0.OUTSET"]["modified_write"] == "oneToSet"
    assert data["P0.OUTCLR"]["modified_write"] == "oneToClear"
    assert data["P0.DIRSET"]["modified_write"] == "oneToSet"
    assert data["P0.DIRCLR"]["modified_write"] == "oneToClear"


def test_stm32_svd_has_no_write_side_effect_attributes():
    # SVD của ST không khai báo modifiedWriteValues (cờ TIMx_SR là rc_w0 chỉ có trong RM) => sidecar rỗng cho STM32
    data = json.loads((hwdb.ROOT / "data" / "svd_attrs.json").read_text(encoding="utf-8"))["chips"]["stm32g474"]["registers"]
    assert data == {}


def test_main_refuses_to_run_when_a_chip_svd_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        svd_attrs.build(corpus=tmp_path)


def test_interrupt_numbers_are_extracted_for_the_nvic_enum():
    # RM0440 Table 100 (p.438): TIM1_BRK/TIM15 = 24, TIM1_UP/TIM16 = 25, TIM2 = 28, I2C1_EV = 31, USART1 = 37
    data = json.loads((hwdb.ROOT / "data" / "svd_attrs.json").read_text(encoding="utf-8"))["chips"]["stm32g474"]["interrupts"]
    assert data["TIM1_UP_TIM16"] == 25 and data["TIM1_BRK_TIM15"] == 24 and data["TIM2"] == 28
    assert data["I2C1_EV"] == 31 and data["USART1"] == 37


def test_extract_interrupts_reads_name_and_value():
    xml = """<device><peripherals><peripheral><name>P</name><baseAddress>0</baseAddress>
      <interrupt><name>FOO</name><value>7</value></interrupt><interrupt><name>BAR</name><value>9</value></interrupt>
      </peripheral></peripherals></device>"""
    assert svd_attrs.extract_interrupts(xml.encode()) == {"FOO": 7, "BAR": 9}
