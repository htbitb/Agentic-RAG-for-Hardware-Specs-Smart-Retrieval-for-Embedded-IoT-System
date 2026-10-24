"""Ghi mô hình thanh ghi vào SQLite: cột, cờ svd_only, alias địa chỉ ESP32, đếm khớp parser."""
import json
import sqlite3

import pytest

from ingestion import hwdb
from ingestion.register_pages import PageRef
from ingestion.svd_ingest import ingest_device, parse_svd_text

SVD = """<device><name>T</name><size>32</size><access>read-write</access><resetValue>0x0</resetValue><resetMask>0xFFFFFFFF</resetMask>
<peripherals>
<peripheral><name>P</name><baseAddress>0x60019000</baseAddress><groupName>G</groupName><description>periph P</description><registers>
 <register><name>CR</name><description>control</description><addressOffset>0x100</addressOffset><resetValue>0x5</resetValue><fields>
  <field><name>EN</name><description>enable</description><bitOffset>0</bitOffset><bitWidth>1</bitWidth>
   <enumeratedValues><enumeratedValue><name>OFF</name><value>0</value></enumeratedValue><enumeratedValue><name>ON</name><value>1</value></enumeratedValue></enumeratedValues>
  </field>
  <field><name>MODE</name><description>mode</description><bitOffset>4</bitOffset><bitWidth>2</bitWidth><access>read-only</access></field>
 </fields></register>
 <register><name>GHOST</name><addressOffset>0x104</addressOffset></register>
</registers></peripheral></peripherals></device>"""


def locate(p, r):
    if r.short_name == "CR":
        return PageRef("DOC_RM", 42, "high", alt_pages=[43], rm_name="P_CR")
    return None


@pytest.fixture()
def conn(tmp_path):
    c = hwdb.connect(tmp_path / "t.sqlite")
    hwdb.init_schema(c)
    ingest_device(c, "chipx", parse_svd_text(SVD), locate, alias_fn=lambda a: 0x3FF59100 if a == 0x60019100 else None)
    return c


def test_register_row_carries_masks_page_and_alias(conn):
    r = conn.execute("select * from registers where chip='chipx' and name='CR'").fetchone()
    assert (r["peripheral"], r["address"], r["address_alias"], r["offset"]) == ("P", 0x60019100, 0x3FF59100, 0x100)
    assert (r["reset_value"], r["reset_mask"], r["size"], r["access"]) == (5, 0xFFFFFFFF, 32, "RW")
    assert (r["reserved_mask"], r["rw_mask"]) == (0xFFFFFFFF & ~0x31, 0x1)
    assert (r["doc"], r["page"], r["page_confidence"], r["svd_only"]) == ("DOC_RM", 42, "high", 0)
    assert json.loads(r["alt_pages"]) == [43]


def test_register_not_found_in_manual_is_flagged_svd_only(conn):
    r = conn.execute("select * from registers where name='GHOST'").fetchone()
    assert (r["doc"], r["page"], r["svd_only"]) == ("chipx_SVD", None, 1)
    assert r["note"]
    an = conn.execute("select kind from data_anomalies where chip='chipx' and ref like '%GHOST%'").fetchall()
    assert [a["kind"] for a in an] == ["svd_only_register"]


def test_fields_and_enums_are_linked_to_their_register(conn):
    rows = conn.execute("""select f.name, f.bit_offset, f.bit_width, f.access, e.name as en, e.value
                           from fields f left join enum_values e on e.field_id = f.id
                           join registers r on r.id = f.register_id where r.name='CR' order by f.bit_offset, e.value""").fetchall()
    assert [(x["name"], x["bit_offset"], x["bit_width"], x["access"], x["en"], x["value"]) for x in rows] == [
        ("EN", 0, 1, "RW", "OFF", 0), ("EN", 0, 1, "RW", "ON", 1), ("MODE", 4, 2, "RO", None, None)]


def test_peripheral_row_and_counts(conn):
    p = conn.execute("select * from peripherals where chip='chipx'").fetchone()
    assert (p["name"], p["base_address"], p["group_name"], p["description"]) == ("P", 0x60019000, "G", "periph P")
    assert conn.execute("select count(*) from registers").fetchone()[0] == 2


def test_reingest_replaces_the_chip_instead_of_duplicating(conn):
    ingest_device(conn, "chipx", parse_svd_text(SVD), locate)
    assert conn.execute("select count(*) from registers where chip='chipx'").fetchone()[0] == 2
    assert conn.execute("select count(*) from fields where chip='chipx'").fetchone()[0] == 2


def test_reset_mismatch_between_svd_and_manual_is_recorded(tmp_path):
    c = hwdb.connect(tmp_path / "m.sqlite")
    hwdb.init_schema(c)

    def loc(p, r):
        return PageRef("DOC_RM", 7, "high", rm_name="P_CR", rm_reset=0x40601 if r.short_name == "CR" else None)

    ingest_device(c, "chipx", parse_svd_text(SVD), loc)
    row = c.execute("select reset_value, rm_reset_value from registers where name='CR'").fetchone()
    assert (row["reset_value"], row["rm_reset_value"]) == (5, 0x40601)
    kinds = [a["kind"] for a in c.execute("select kind from data_anomalies where ref like '%CR'")]
    assert kinds == ["reset_mismatch"]


def test_matching_reset_is_not_an_anomaly(tmp_path):
    c = hwdb.connect(tmp_path / "m.sqlite")
    hwdb.init_schema(c)
    ingest_device(c, "chipx", parse_svd_text(SVD), lambda p, r: PageRef("DOC_RM", 7, "high", rm_reset=r.reset_value))
    assert c.execute("select count(*) from data_anomalies where kind='reset_mismatch'").fetchone()[0] == 0


def test_init_schema_rebuilds_a_database_with_an_older_schema_version(tmp_path):
    c = hwdb.connect(tmp_path / "old.sqlite")
    c.execute("CREATE TABLE registers(id INTEGER PRIMARY KEY, chip TEXT)")        # schema cũ, thiếu cột
    c.execute("INSERT INTO registers(chip) VALUES ('stale')")
    c.commit()
    hwdb.init_schema(c)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(registers)")}
    assert "rm_reset_value" in cols and c.execute("select count(*) from registers").fetchone()[0] == 0
    assert c.execute("PRAGMA user_version").fetchone()[0] == hwdb.SCHEMA_VERSION


def test_init_schema_keeps_data_when_version_is_current(tmp_path):
    c = hwdb.connect(tmp_path / "cur.sqlite")
    hwdb.init_schema(c)
    c.execute("INSERT INTO chips(chip) VALUES ('keep')")
    c.commit()
    hwdb.init_schema(c)
    assert c.execute("select count(*) from chips").fetchone()[0] == 1
