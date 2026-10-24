import pytest

from eval.textnorm import bit_ranges, canonical_access, hex_tokens, number_tokens, quantities


@pytest.mark.parametrize("text,expected", [
    ("address 0x4800_0000", [0x48000000]),
    ("address 0x48000000", [0x48000000]),
    ("address 0x4800 0000.", [0x48000000]),          # ST in nhóm 4 chữ số cách nhau bởi khoảng trắng
    ("0X1F and 0x0010", [0x1F, 0x10]),
    ("offset 0x10 dead end", [0x10]),                 # 'dead' là từ, không phải nhóm hex
    ("Reset value: 0xABFF FFFF", [0xABFFFFFF]),       # nhóm toàn chữ HOA (FFFF) vẫn là hex
    ("reset 0x0000 30D0.", [0x30D0]),
    ("no hex here 1234", []),
])
def test_hex_tokens(text, expected):
    assert hex_tokens(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("bits [6:4]", {(4, 6)}),
    ("bits [4:6]", {(4, 6)}),
    ("bit 4..6", {(4, 6)}),
    ("bits 4-6", {(4, 6)}),
    ("bits 6 to 4", {(4, 6)}),
    ("at bit 5", {(5, 5)}),
    ("MODE[1:0] and OTYPE[3]", {(0, 1), (3, 3)}),
    ("nothing", set()),
])
def test_bit_ranges_normalised_to_lo_hi(text, expected):
    assert bit_ranges(text) == expected


def test_number_tokens_ignore_hex_digits_and_citations():
    toks = number_tokens("reset value is 16 (0x10); see [RM0440 p.1277]")
    assert 16.0 in toks and 1277.0 not in toks and 0.0 not in toks


@pytest.mark.parametrize("text,si,base", [
    ("3.3 V", 3.3, "V"), ("3300 mV", 3.3, "V"), ("170 MHz", 1.7e8, "Hz"), ("20 µA", 2e-5, "A"), ("0.02 mA", 2e-5, "A"),
])
def test_quantities_to_si(text, si, base):
    (val, unit, got_si, got_base), = quantities(text)
    assert got_base == base and got_si == pytest.approx(si)


@pytest.mark.parametrize("text,cls", [
    ("read/write", "rw"), ("Read-Write register", "rw"), ("RW", "rw"), ("read-only", "ro"), ("read only", "ro"),
    ("write-only", "wo"), ("reserved", None),
])
def test_canonical_access(text, cls):
    assert canonical_access(text) == ({cls} if cls else set())


def test_article_a_is_not_the_ampere_unit():
    assert quantities("see section 3 a register map") == []
    assert len(quantities("draws 3 A")) == 1 and len(quantities("draws 3 mA")) == 1


# ---- review D12: khoảng giá trị / danh sách có đơn vị ở số cuối -------------------------------------------------
@pytest.mark.parametrize("text,vals,base", [
    ("2.3-3.6 V", [2.3, 3.6], "V"),                          # gạch nối ASCII
    ("2.3–3.6 V", [2.3, 3.6], "V"),                          # en-dash
    ("2.3 – 3.6 V", [2.3, 3.6], "V"),
    ("1.7 to 3.6 V", [1.7, 3.6], "V"),
    ("between 2.3 and 3.6 V", [2.3, 3.6], "V"),
    ("80/160/240 MHz", [80e6, 160e6, 240e6], "Hz"),
    ("80 MHz/160 MHz/240 MHz", [80e6, 160e6, 240e6], "Hz"),
    ("80 MHz, 160 MHz or 240 MHz", [80e6, 160e6, 240e6], "Hz"),
    ("VDD 1.7-3.6 V, VDDH 2.5-5.5 V", [1.7, 3.6, 2.5, 5.5], "V"),
    ("-0.3 to 3.9 V", [-0.3, 3.9], "V"),
])
def test_quantity_ranges_and_lists_yield_every_value_with_the_unit(text, vals, base):
    got = quantities(text)
    assert sorted(q[2] for q in got) == pytest.approx(sorted(vals))
    assert {q[3] for q in got} == {base}


def test_range_expansion_keeps_the_original_boundaries():
    assert quantities("VDD-0.3 V") == []                      # 'VDD-0.3' là tên + số, không phải khoảng
    assert [q[2] for q in quantities("Table 5-2 lists 3.3 V")] == [3.3]
    assert quantities("pins 34-39") == []                     # không có đơn vị
    assert quantities("section 3-4 a register") == []         # 'a' là mạo từ, không phải ampere


# P1 review (D18): ký hiệu bit trong markdown / dạng 'bit offset N, bit width W' (C1-010 S2D seed 1-2 bị chấm sai)
@pytest.mark.parametrize("text, want", [
    ("located at bit **[17]** (bit offset 17, bit width 1)", {(17, 17)}),
    ("* **Bit:** `[17]` (bit offset 17, bit width 1)", {(17, 17)}),
    ("OTYPE is bit offset 4, bit width 3", {(4, 6)}),
    ("**bits [6:4]**", {(4, 6)}),
    ("the reset value is 0x0 [1]", set()),                       # chú thích kiểu ' [1]' vẫn không phải bit
    ("see `[1]` in the footnotes", set()),
])
def test_bit_ranges_markdown_and_offset_width(text, want):
    from eval.textnorm import bit_ranges
    assert bit_ranges(text) == want


# ---------------------------------------------------------------- D18 (P4): ô số trong hàng bảng markdown mang đơn vị của ô "đơn vị" cùng hàng
def _q(text):
    return [(v, u) for v, u, _, _ in quantities(text)]


def test_numbers_in_a_table_row_take_the_unit_cell_of_the_same_row():
    row = "| **VDD** | $V_{VDD}$ | **1.7** | **3.0** | **3.6** | V | independent of DC/DC |"
    assert _q(row) == [(1.7, "V"), (3.0, "V"), (3.6, "V")]


def test_row_unit_carry_over_leaves_ambiguous_or_unitless_rows_alone():
    assert _q("| tSCLL | 1.25 | µs | 3 | V |") == []                       # hai ô đơn vị: không đoán
    assert _q("| Port | 6 | TIM1_CH1 |") == []
    assert _q("| Min | Typ | Max | Unit |") == []
    assert _q("| PRESC | 3 | A |") == []                                  # 'A' đơn lẻ có thể là chữ cái, không phải ampere
    assert _q("| VDD | 3.3 V | V |") == [(3.3, "V")]                    # số đã có đơn vị: không nhân đôi


def test_text_outside_tables_is_unchanged():
    assert _q("The supply is 3.6 V and the clock 170 MHz.") == [(3.6, "V"), (170.0, "MHz")]
    assert _q("a | 5 | V") == []


# ---------------------------------------------------------------- D34 (P5): vị trí của đại lượng / hex để gán giá trị cho thuộc tính gần nhất
def test_quantities_at_gives_the_span_of_each_match_and_the_same_values_as_quantities():
    from eval.textnorm import carry_row_units, quantities_at
    text = "Industrial temperature range, -40 to 85 °C (105 °C junction); supply 3.3 V"
    got = quantities_at(text)
    assert [q for _, _, q in got] == quantities(text)
    (s0, e0, _), (s1, e1, _), (s2, e2, _), (s3, e3, _) = got
    assert text[s0:e0] == "-40 to 85 °C" and (s1, e1) == (s0, e0)          # cả khoảng là một cụm
    assert text[s2:e2] == "105 °C" and text[s3:e3] == "3.3 V"
    row = "| VDD | 1.7 | 3.6 | V |"
    t = carry_row_units(row)
    assert carry_row_units(t) == t                                             # luỹ đẳng: vị trí tính trên văn bản đã chuyển
    assert [t[s:e] for s, e, _ in quantities_at(row)] == ["1.7 V", "3.6 V"]


def test_hex_tokens_at_gives_spans_and_the_same_values_as_hex_tokens():
    from eval.textnorm import hex_tokens_at
    text = "stride of `0x14` (20 bytes); LSCH7 at 0x3FF5_912C and 0x4800 0000"
    got = hex_tokens_at(text)
    assert [h for _, _, h in got] == hex_tokens(text) == [0x14, 0x3FF5912C, 0x48000000]
    assert [text[s:e] for s, e, _ in got] == ["0x14", "0x3FF5_912C", "0x4800 0000"]
