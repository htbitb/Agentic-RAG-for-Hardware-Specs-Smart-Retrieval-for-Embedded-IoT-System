"""Parser SVD của agent (độc lập với eval/generators — D05): kế thừa, derivedFrom, dim, cluster, enum, mask."""
import pytest

from ingestion.svd_ingest import parse_svd_text

DEVICE = """<?xml version="1.0"?>
<device><name>T</name><size>32</size><access>read-write</access>
<resetValue>0x00000000</resetValue><resetMask>0xFFFFFFFF</resetMask>
<peripherals>{body}</peripherals></device>"""


def dev(body: str):
    return parse_svd_text(DEVICE.format(body=body))


def periph(name, base, inner, extra="", attrs=""):
    return (f"<peripheral{attrs}><name>{name}</name><baseAddress>{base}</baseAddress>{extra}"
            f"<registers>{inner}</registers></peripheral>")


def reg(name, off, fields="", extra=""):
    return (f"<register><name>{name}</name><description>{name} reg</description>"
            f"<addressOffset>{off}</addressOffset>{extra}<fields>{fields}</fields></register>")


def fld(name, off, width, extra=""):
    return (f"<field><name>{name}</name><description>{name} fld</description>"
            f"<bitOffset>{off}</bitOffset><bitWidth>{width}</bitWidth>{extra}</field>")


# ---------------------------------------------------------------- defaults / inheritance
def test_register_inherits_size_access_reset_from_device():
    d = dev(periph("P", "0x40000000", reg("R", "0x4", fld("A", 0, 1))))
    r = d.peripheral("P").register("R")
    assert (r.size, r.access, r.reset_value, r.reset_mask) == (32, "RW", 0, 0xFFFFFFFF)
    assert r.address == 0x40000004 and r.offset == 4


def test_peripheral_level_defaults_override_device_and_register_overrides_peripheral():
    inner = reg("R1", "0x0", fld("A", 0, 1)) + reg("R2", "0x4", fld("A", 0, 1),
                                                   "<size>16</size><access>read-only</access><resetValue>0x5</resetValue>")
    d = dev(periph("P", "0x0", inner, "<size>8</size><access>write-only</access><resetValue>0xAB</resetValue>"))
    r1, r2 = d.peripheral("P").register("R1"), d.peripheral("P").register("R2")
    assert (r1.size, r1.access, r1.reset_value) == (8, "WO", 0xAB)
    assert (r2.size, r2.access, r2.reset_value) == (16, "RO", 5)


def test_field_access_inherits_from_register_and_can_override():
    r = dev(periph("P", "0x0", reg("R", "0x0", fld("A", 0, 1) + fld("B", 1, 1, "<access>read-only</access>"),
                                   "<access>write-only</access>"))).peripheral("P").register("R")
    assert {f.name: f.access for f in r.fields} == {"A": "WO", "B": "RO"}


# ---------------------------------------------------------------- number formats
@pytest.mark.parametrize("text,value", [("0x1F", 31), ("0X1f", 31), ("#101", 5), ("42", 42), ("0x0000_0010", 16)])
def test_numbers_accept_hex_binary_decimal(text, value):
    r = dev(periph("P", "0x0", reg("R", text, fld("A", 0, 1)))).peripheral("P").register("R")
    assert r.offset == value


# ---------------------------------------------------------------- derivedFrom
def test_derived_peripheral_gets_base_registers_at_its_own_base_address():
    body = (periph("A", "0x1000", reg("CR", "0x8", fld("EN", 0, 1))) +
            periph("B", "0x2000", "", attrs=' derivedFrom="A"'))
    d = dev(body)
    b = d.peripheral("B")
    assert b.derived_from == "A"
    assert b.register("CR").address == 0x2008
    assert [f.name for f in b.register("CR").fields] == ["EN"]
    assert d.peripheral("A").register("CR").address == 0x1008  # base untouched


def test_derived_peripheral_inherits_base_peripheral_defaults_and_can_override_registers():
    base = periph("A", "0x1000", reg("R1", "0x0", fld("X", 0, 1)) + reg("R2", "0x4", fld("Y", 0, 1)), "<size>16</size>")
    derived = periph("B", "0x2000", reg("R2", "0x10", fld("Z", 0, 1)), attrs=' derivedFrom="A"')
    b = dev(base + derived).peripheral("B")
    assert b.register("R1").size == 16                       # peripheral-level size inherited from base
    assert b.register("R2").offset == 0x10                   # own definition replaces the base register
    assert [f.name for f in b.register("R2").fields] == ["Z"]


def test_derived_peripheral_can_come_before_its_base_in_the_file():
    body = (periph("B", "0x2000", "", attrs=' derivedFrom="A"') + periph("A", "0x1000", reg("CR", "0x0", fld("E", 0, 1))))
    assert dev(body).peripheral("B").register("CR").address == 0x2000


def test_register_derived_from_sibling_copies_fields_but_not_name_or_offset():
    r2 = ('<register derivedFrom="R1"><name>R2</name><addressOffset>0x10</addressOffset></register>')
    d = dev(periph("P", "0x0", reg("R1", "0x0", fld("A", 0, 4)) + r2))
    r = d.peripheral("P").register("R2")
    assert r.offset == 0x10 and [(f.name, f.bit_width) for f in r.fields] == [("A", 4)]


def test_register_derived_from_qualified_path_in_other_peripheral():
    r2 = ('<register derivedFrom="Q.R1"><name>R2</name><addressOffset>0x10</addressOffset></register>')
    d = dev(periph("Q", "0x100", reg("R1", "0x0", fld("A", 0, 4))) + periph("P", "0x0", r2))
    assert [f.name for f in d.peripheral("P").register("R2").fields] == ["A"]


# ---------------------------------------------------------------- dim
def test_register_array_with_bracket_pattern_expands_with_increment():
    r = reg("KEY[%s]", "0x10", fld("K", 0, 8), "<dim>3</dim><dimIncrement>0x4</dimIncrement>")
    p = dev(periph("P", "0x1000", r)).peripheral("P")
    assert [x.name for x in p.registers] == ["KEY[0]", "KEY[1]", "KEY[2]"]
    assert [x.address for x in p.registers] == [0x1010, 0x1014, 0x1018]
    assert p.registers[1].array_base == "KEY" and p.registers[1].array_index == "1"


def test_register_array_with_dimindex_range_and_list():
    rng = reg("T%s", "0x0", fld("K", 0, 8), "<dim>4</dim><dimIncrement>4</dimIncrement><dimIndex>1-4</dimIndex>")
    lst = reg("U%s", "0x20", fld("K", 0, 8), "<dim>3</dim><dimIncrement>4</dimIncrement><dimIndex>A,B,C</dimIndex>")
    p = dev(periph("P", "0x0", rng + lst)).peripheral("P")
    assert [x.name for x in p.registers] == ["T1", "T2", "T3", "T4", "UA", "UB", "UC"]
    assert p.register("T4").offset == 12 and p.register("UC").offset == 0x28


def test_dimindex_letter_range():
    r = reg("G%s", "0x0", fld("K", 0, 1), "<dim>3</dim><dimIncrement>4</dimIncrement><dimIndex>A-C</dimIndex>")
    assert [x.name for x in dev(periph("P", "0x0", r)).peripheral("P").registers] == ["GA", "GB", "GC"]


def test_peripheral_array_expands_base_address_and_name():
    body = ("<peripheral><name>GPIO%s</name><baseAddress>0x1000</baseAddress><dim>2</dim>"
            "<dimIncrement>0x400</dimIncrement><dimIndex>A,B</dimIndex><registers>" + reg("ODR", "0x14", fld("O", 0, 1)) +
            "</registers></peripheral>")
    d = dev(body)
    assert d.peripheral("GPIOA").base_address == 0x1000 and d.peripheral("GPIOB").register("ODR").address == 0x1414


def test_field_array_expands_bit_offsets():
    f = ("<field><name>MODE%s</name><description>m</description><bitOffset>0</bitOffset><bitWidth>2</bitWidth>"
         "<dim>3</dim><dimIncrement>2</dimIncrement></field>")
    r = dev(periph("P", "0x0", reg("R", "0x0", f))).peripheral("P").register("R")
    assert [(x.name, x.bit_offset) for x in r.fields] == [("MODE0", 0), ("MODE1", 2), ("MODE2", 4)]


# ---------------------------------------------------------------- cluster
def test_cluster_adds_offset_and_qualifies_register_name():
    cluster = ("<cluster><name>PSEL</name><addressOffset>0x508</addressOffset>" + reg("SCK", "0x0", fld("P", 0, 5)) +
               reg("MOSI", "0x4", fld("P", 0, 5)) + "</cluster>")
    p = dev(periph("SPIM0", "0x40003000", cluster)).peripheral("SPIM0")
    r = p.register("PSEL.MOSI")
    assert r.address == 0x40003000 + 0x508 + 4 and r.offset == 0x50C and r.cluster_path == "PSEL"
    assert p.register("MOSI") is r                                   # lookup by short name works too


def test_cluster_array_and_cluster_level_defaults():
    cluster = ("<cluster><name>CH[%s]</name><dim>2</dim><dimIncrement>0x10</dimIncrement><addressOffset>0x100</addressOffset>"
               "<access>read-only</access>" + reg("CFG", "0x4", fld("P", 0, 5)) + "</cluster>")
    p = dev(periph("X", "0x0", cluster)).peripheral("X")
    assert [(r.name, r.offset, r.access) for r in p.registers] == [("CH[0].CFG", 0x104, "RO"), ("CH[1].CFG", 0x114, "RO")]


# ---------------------------------------------------------------- fields & enums
def test_field_position_variants_bitrange_and_lsb_msb():
    f1 = "<field><name>A</name><bitRange>[7:4]</bitRange></field>"
    f2 = "<field><name>B</name><lsb>8</lsb><msb>11</msb></field>"
    r = dev(periph("P", "0x0", reg("R", "0x0", f1 + f2))).peripheral("P").register("R")
    assert [(f.name, f.bit_offset, f.bit_width) for f in r.fields] == [("A", 4, 4), ("B", 8, 4)]


def test_enumerated_values_with_formats_and_default():
    enums = ("<enumeratedValues><usage>read-write</usage>"
             "<enumeratedValue><name>OFF</name><description>off</description><value>0</value></enumeratedValue>"
             "<enumeratedValue><name>ON</name><description>on</description><value>0x1</value></enumeratedValue>"
             "<enumeratedValue><name>BIN</name><value>#10</value></enumeratedValue>"
             "<enumeratedValue><name>DC</name><value>#1x0</value></enumeratedValue>"
             "<enumeratedValue><name>OTHER</name><isDefault>true</isDefault></enumeratedValue></enumeratedValues>")
    f = dev(periph("P", "0x0", reg("R", "0x0", fld("A", 0, 2, enums)))).peripheral("P").register("R").fields[0]
    got = {e.name: (e.value, e.is_default) for e in f.enums}
    assert got == {"OFF": (0, False), "ON": (1, False), "BIN": (2, False), "DC": (None, False), "OTHER": (None, True)}
    assert next(e for e in f.enums if e.name == "DC").value_raw == "#1x0"


def test_enumerated_values_derived_from_other_field():
    base = ("<enumeratedValues><name>E1</name><enumeratedValue><name>A</name><value>0</value></enumeratedValue>"
            "<enumeratedValue><name>B</name><value>1</value></enumeratedValue></enumeratedValues>")
    ref = '<enumeratedValues derivedFrom="P.R.A.E1"/>'
    d = dev(periph("P", "0x0", reg("R", "0x0", fld("A", 0, 1, base) + fld("B", 1, 1, ref))))
    assert [e.name for e in d.peripheral("P").register("R").fields[1].enums] == ["A", "B"]


def test_write_constraint_range_and_flags():
    wc = "<writeConstraint><range><minimum>1</minimum><maximum>14</maximum></range></writeConstraint>"
    wc2 = "<writeConstraint><useEnumeratedValues>true</useEnumeratedValues></writeConstraint>"
    r = dev(periph("P", "0x0", reg("R", "0x0", fld("A", 0, 4, wc) + fld("B", 4, 1, wc2)))).peripheral("P").register("R")
    assert r.fields[0].write_constraint == "range 1..14" and r.fields[1].write_constraint == "enumerated values only"


# ---------------------------------------------------------------- masks
def test_reserved_and_rw_masks_from_field_complement():
    fields = fld("A", 0, 4) + fld("B", 8, 4, "<access>read-only</access>") + fld("C", 31, 1)
    r = dev(periph("P", "0x0", reg("R", "0x0", fields))).peripheral("P").register("R")
    assert r.reserved_mask == 0x7FFFF0F0
    assert r.rw_mask == 0x8000000F                       # A (rw) + C (rw); B is read-only


def test_register_without_fields_has_no_reserved_bits_and_uses_register_access_for_rw_mask():
    r = dev(periph("P", "0x0", reg("R", "0x0", "", "<access>read-only</access>"))).peripheral("P").register("R")
    assert (r.reserved_mask, r.rw_mask, r.has_fields) == (0, 0, False)
    r2 = dev(periph("P", "0x0", reg("R", "0x0", ""))).peripheral("P").register("R")
    assert (r2.rw_mask, r2.has_fields) == (0xFFFFFFFF, False)


def test_overlapping_fields_are_reported():
    r = dev(periph("P", "0x0", reg("R", "0x0", fld("A", 0, 4) + fld("B", 2, 4)))).peripheral("P").register("R")
    assert r.overlapping_fields == [("A", "B")]


# ---------------------------------------------------------------- alternates / misc
def test_alternate_peripheral_and_alternate_register_are_recorded():
    body = ("<peripheral><name>SPIM0</name><baseAddress>0x4000</baseAddress><alternatePeripheral>SPI0</alternatePeripheral>"
            "<groupName>SPI</groupName><description>spi master</description><registers>" +
            reg("A", "0x0", fld("X", 0, 1)) +
            "<register><name>B</name><addressOffset>0x0</addressOffset><alternateRegister>A</alternateRegister></register>"
            "</registers></peripheral>")
    p = dev(body).peripheral("SPIM0")
    assert p.alternate_peripheral == "SPI0" and p.group == "SPI" and p.description == "spi master"
    assert p.register("B").alternate_register == "A"


def test_unknown_derived_from_raises_clear_error():
    with pytest.raises(ValueError, match="derivedFrom"):
        dev(periph("B", "0x0", "", attrs=' derivedFrom="NOPE"'))
