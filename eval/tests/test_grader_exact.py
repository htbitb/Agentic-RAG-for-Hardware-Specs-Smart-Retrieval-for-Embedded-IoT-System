import pytest

from eval.graders import exact
from eval.tests.helpers import mk_run, mk_task


def grade(answer, **exp):
    ex = {"attribute": "address", "kind": "hex", "value": "0x48000000"}
    ex.update(exp)
    return exact.grade(mk_task({"exact": ex}), mk_run(answer), ctx=None)


@pytest.mark.parametrize("answer", [
    "The address of GPIOA_MODER is 0x48000000.",
    "GPIOA_MODER is located at 0x4800_0000.",
    "It is at 0x4800 0000 (GPIOA base).",
    "Address: 0X48000000",
    "GPIOA_MODER = 1207959552 (decimal)",                  # 0x48000000 viết dạng thập phân
])
def test_address_correct_variants_pass(answer):
    r = grade(answer)
    assert r["pass"] is True and r["score"] == 1.0, r


@pytest.mark.parametrize("answer,reason", [
    ("The address is 0x48000400.", "wrong_value"),                       # sai giá trị
    ("I do not know.", "missing_value"),                                  # không nêu
    ("It is 0x48000000 on some boards but really 0x50000000.", "wrong_value"),  # mâu thuẫn cùng thuộc tính
])
def test_address_wrong_or_conflicting_fail(answer, reason):
    r = grade(answer)
    assert r["pass"] is False and any(x.startswith(reason) for x in r["reasons"]), r


def test_allowed_extra_hex_values_do_not_conflict():
    r = grade("GPIOA_MODER is at 0x48000000 (GPIOA base 0x48000000 + offset 0x00); reset 0xABFFFFFF.",
              allowed=["0x00", "0xABFFFFFF"])
    assert r["pass"] is True, r


def test_small_hex_in_address_answer_is_not_a_conflict():
    # offset nhỏ (< 0x1000) không bị coi là một địa chỉ khác
    assert grade("Address 0x48000000, offset 0x14.")["pass"] is True


def test_offset_uses_keyword_to_pick_the_claim():
    ok = grade("MODER offset is 0x00 and its reset value is 0xABFFFFFF.", attribute="offset", value="0x00")
    bad = grade("MODER offset is 0x14 and its reset value is 0xABFFFFFF.", attribute="offset", value="0x00")
    assert ok["pass"] is True and bad["pass"] is False


def test_reset_value_accepts_decimal_and_hex_equivalents():
    assert grade("Reset value: 0x0000 0003", attribute="reset", value="0x3")["pass"]
    assert grade("The reset value is 3.", attribute="reset", value="0x3")["pass"]
    assert not grade("The reset value is 0x0000 0004", attribute="reset", value="0x3")["pass"]


@pytest.mark.parametrize("answer,ok", [
    ("MODE is bits [1:0].", True), ("MODE occupies bits 0-1", True), ("bit 0..1", True), ("bits 1 to 0", True),
    ("MODE is bits [3:2].", False), ("MODE is bit 5", False),
])
def test_bit_range_normalisation(answer, ok):
    assert grade(answer, attribute="bits", kind="bits", value=[0, 1])["pass"] is ok


def test_bit_range_allowed_other_fields():
    r = grade("MODE0 is bits [1:0], MODE1 is bits [3:2].", attribute="bits", kind="bits", value=[0, 1], allowed=[[2, 3]])
    assert r["pass"] is True


@pytest.mark.parametrize("answer,ok", [("It is read/write.", True), ("Access: RW", True), ("read-only", False),
                                       ("It is read/write, but the bit is read-only", False)])
def test_access_kind(answer, ok):
    assert grade(answer, attribute="access", kind="access", value="rw")["pass"] is ok


def test_quantity_unit_conversion():
    assert grade("The max is 3600 mV.", attribute="vmax", kind="quantity", value=3.6, unit="V")["pass"]
    assert grade("The max is 3.6 V.", attribute="vmax", kind="quantity", value=3.6, unit="V")["pass"]
    assert not grade("The max is 3.3 V.", attribute="vmax", kind="quantity", value=3.6, unit="V")["pass"]


def test_missing_spec_is_an_error_not_a_silent_pass():
    with pytest.raises(ValueError):
        exact.grade(mk_task({}), mk_run("anything"), ctx=None)


def test_offset_answer_mentioning_base_address_is_not_a_conflict():
    ans = "The offset of MODER from the GPIOA base address 0x48000000 is 0x00."
    assert grade(ans, attribute="offset", value="0x00")["pass"]


def test_wrong_offset_after_base_mention_still_fails():
    ans = "The offset of MODER from the GPIOA base 0x48000000 is 0x14."
    assert not grade(ans, attribute="offset", value="0x00")["pass"]


def test_reset_value_answer_listing_other_attributes_passes():
    ans = "Reset value 0xABFFFFFF; address offset 0x00; absolute address 0x48000000."
    assert grade(ans, attribute="reset", value="0xABFFFFFF")["pass"]


# ---- review findings 1-3: cửa sổ từ khoá không được cắt literal hex / đếm số không liên quan -------------
def test_hex_literal_is_never_cut_by_the_keyword_window():
    assert grade("The reset value of SAI_BCR1 on the STM32G474 is 0x00000040.", attribute="reset", value="0x40")["pass"]


def test_register_number_in_a_parenthesis_is_not_a_reset_claim():
    ans = "The reset value of SAI_BCR1 (Block Configuration Register 1) on the STM32G474 is 0x0000 0040."
    assert grade(ans, attribute="reset", value="0x40")["pass"]


def test_trailing_field_width_remark_is_not_a_reset_claim():
    assert grade("The reset value is 0x0000FFFF (a 16-bit field).", attribute="reset", value="0xFFFF")["pass"]


def test_hex_claims_take_precedence_over_decimal_noise_but_wrong_hex_still_fails():
    assert not grade("The reset value of register 1 is 0x0000 0041.", attribute="reset", value="0x40")["pass"]


def test_address_answer_may_quote_the_reset_value_or_offset():
    ans = "FDCAN2_TXBTIE is at 0x400068DC. Its reset value is 0x0000FFFF and its mask is 0x00FF00FF."
    assert grade(ans, value="0x400068DC")["pass"]
    assert not grade("FDCAN2_TXBTIE is at 0x400064DC. Its reset value is 0x0000FFFF.", value="0x400068DC")["pass"]


def test_bits_ignore_ranges_of_other_fields_in_other_sentences():
    ans = "DTPE is bit 17. Bits 31:18 are reserved."
    assert grade(ans, attribute="bits", kind="bits", value=[17, 17], scope=["DTPE"])["pass"]
    assert not grade("DTPE is bits 31:18.", attribute="bits", kind="bits", value=[17, 17], scope=["DTPE"])["pass"]


def test_footnote_bracket_after_a_space_is_not_a_bit_reference():
    assert grade("DTPE is bit 17 [1].", attribute="bits", kind="bits", value=[17, 17], scope=["DTPE"])["pass"]
    assert grade("DTPE[17] enables it.", attribute="bits", kind="bits", value=[17, 17], scope=["DTPE"])["pass"]


def test_bit_position_phrase_is_understood():
    assert grade("DTPE sits at bit position 17.", attribute="bits", kind="bits", value=[17, 17], scope=["DTPE"])["pass"]


def test_access_is_scoped_to_the_clause_that_names_the_register():
    ans = "WUTR is read-write, but the WUTWF flag itself is read-only."
    assert grade(ans, attribute="access", kind="access", value="rw", scope=["WUTR"])["pass"]
    assert not grade("WUTR is read-only, but the WUTWF flag is read-write.", attribute="access", kind="access", value="rw", scope=["WUTR"])["pass"]


def test_scope_falls_back_to_provenance_of_generated_tasks():
    from eval.graders import exact
    from eval.tests.helpers import mk_run, mk_task

    t = mk_task({"exact": {"attribute": "bits", "kind": "bits", "value": [17, 17]}}, provenance={"field": "DTPE", "register": "TIM4_DTR2"})
    assert exact.grade(t, mk_run("DTPE is bit 17. Bits 31:18 are reserved."), None)["pass"]


# ---- review G-4: claim offset/reset chỉ lấy từ mệnh đề thuộc đối tượng được hỏi -------------------------------------
def grade_prov(answer, prov, **exp):
    t = mk_task({"exact": exp}, provenance=prov)
    return exact.grade(t, mk_run(answer), ctx=None)


OFF = dict(attribute="offset", kind="hex", value="0x10", allowed=["0x50000000", "0x50000010"])
CFGR2 = {"register": "CFGR2", "doc_name": "CFGR2", "peripheral": "ADC1"}


@pytest.mark.parametrize("answer", [
    "CFGR2 sits at offset 0x10 from the ADC1 base 0x50000000, i.e. address 0x50000010.",
    "The CFGR2 register is at offset 0x10.",
    "Offset 0x0C (ADC_CFGR is at 0x0C, CFGR2 is 0x10).",
    "ADC_CFGR is at offset 0x0C, CFGR2 is at offset 0x10.",                     # offset của thanh ghi KHÁC đứng trước
    "ADC_CFGR is at offset 0x0C; ADC1_CFGR2 is at offset 0x10.",
    "Register: CFGR2. Offset: 0x10.",
])
def test_offset_of_a_neighbouring_register_is_not_a_conflicting_claim(answer):
    r = grade_prov(answer, CFGR2, **OFF)
    assert r["pass"] is True, r


@pytest.mark.parametrize("answer", [
    "The offset is 0x14.",
    "CFGR2 is at 0x50000010.",                          # địa chỉ tuyệt đối chứ không phải offset
    "ADC_CFGR is at offset 0x0C, CFGR2 is at offset 0x14.",
    "ADC1_CFGR2 is at offset 0x14, see also CFGR 0x10.",   # bí danh của CHÍNH thanh ghi được hỏi mang giá trị sai
])
def test_a_wrong_offset_for_the_asked_register_still_fails(answer):
    assert grade_prov(answer, CFGR2, **OFF)["pass"] is False


def test_reset_claim_of_a_neighbour_register_is_ignored_too():
    prov = {"register": "BCR1", "doc_name": "SAI_BCR1"}
    assert grade_prov("SAI_ACR1 reset value is 0x0; SAI_BCR1 reset value is 0x0000 0040.", prov, attribute="reset", value="0x40")["pass"]
    assert not grade_prov("SAI_ACR1 reset value is 0x40; SAI_BCR1 reset value is 0x0.", prov, attribute="reset", value="0x40")["pass"]


# ---- review G-5: dải bit 'Reserved' không phải là mâu thuẫn ------------------------------------------------------
BITS = dict(attribute="bits", kind="bits", value=[17, 17], allowed=[[16, 16], [0, 7]])


@pytest.mark.parametrize("answer", [
    "Bit 17 DTPE: Deadtime preload enable (bits 31:18 are reserved, DTAE is bit 16, DTGF[7:0]).",
    "DTPE is bit 17 of TIM1_DTR2; bits 31:18 reserved.",
    "DTPE is bit 17 of TIM1_DTR2; Reserved: bits 31:18.",
    "DTPE is bit 17. Bits 31:18 Reserved, must be kept at reset value.",
    "DTPE is bit 17 (bits [31:18] are reserved).",
    "DTPE is bit 17 and bits 31 to 18 are reserved.",
    "DTPE is bit 17; bits 20..18 (reserved).",
])
def test_reserved_ranges_are_not_conflicting_bit_claims(answer):
    r = grade_prov(answer, {"field": "DTPE"}, **BITS)
    assert r["pass"] is True, r


@pytest.mark.parametrize("answer", [
    "DTPE is bits 31:18.",
    "DTPE is bit 17 and bit 20 (bits 31:21 reserved).",
    "DTPE is bit 18 (bits 31:19 reserved).",
])
def test_reserved_filter_does_not_hide_a_wrong_claim(answer):
    assert grade_prov(answer, {"field": "DTPE"}, **BITS)["pass"] is False


# ---- D15: alias địa chỉ ESP32 (DPORT 0x3FF4xxxx == AHB 0x6000xxxx, TRM p.73) -----------------------------------
LEDC = dict(attribute="address", kind="hex", value="0x3FF59100", allowed=["0x3FF59000", "0x60019000"], equivalent=["0x60019100"])


@pytest.mark.parametrize("answer", [
    "LEDC_LSCH4_DUTY_R_REG is at 0x3FF59100.",
    "LEDC_LSCH4_DUTY_R_REG is at 0x60019100 (AHB address).",
    "LEDC_LSCH4_DUTY_R_REG = 0x3FF59100 (DPORT), also reachable via the AHB alias 0x60019100.",
    "Base 0x60019000 + 0x100 = 0x60019100.",
])
def test_equivalent_alias_address_is_accepted(answer):
    assert grade(answer, **LEDC)["pass"] is True


def test_other_addresses_still_fail_when_an_alias_is_configured():
    assert not grade("It is at 0x3FF59104.", **LEDC)["pass"]
    assert not grade("It is at 0x60019104.", **LEDC)["pass"]
    assert not grade("It is at 0x3FF59100 or maybe 0x3FF5A100.", **LEDC)["pass"]


# D18: mệnh đề nhắc field kết thúc bằng ':' -> các dòng liệt kê ngay sau đó là phần tiếp theo của cùng claim (C1-010 S2D seed 1)
def test_scoped_clause_ending_with_colon_includes_following_list():
    ans = ("the **DTPE** field of the **TIM1_DTR2** register consists of:\n\n"
           "* **Bit:** `[17]` (bit offset 17, bit width 1) [STM32G474_RM0440 p. 1274].")
    assert grade(ans, attribute="bits", kind="bits", value=[17, 17], scope=["DTPE"])["pass"] is True
    wrong = ans.replace("[17]", "[16]").replace("offset 17", "offset 16")
    assert grade(wrong, attribute="bits", kind="bits", value=[17, 17], scope=["DTPE"])["pass"] is False


def test_scoped_list_after_colon_stops_at_next_non_list_line():
    ans = "DTPE is described below:\n- bit 17\nThe DTGF field is bit 16."
    assert grade(ans, attribute="bits", kind="bits", value=[17, 17], scope=["DTPE"])["pass"] is True


# ---------------------------------------------------------------- D18 (P4): lời giải thích mức bit không phải claim về giá trị reset của cả thanh ghi
BIT_LEVEL = ("The reset value of **SAI_BCR1** is **`0x00000040`**.\n- **Reset value:** `0x00000040`\n"
             "In this register, bit 6 is set to 1 at reset (within `DS[2:0]`, bits [7:5] = `010b`).\n"
             "* All other bits reset to `0`.\nThe reset value of `DS[2:0]` is `010`.")


def test_bit_level_reset_remarks_do_not_count_as_conflicting_register_reset_claims():
    r = grade(BIT_LEVEL, attribute="reset", value="0x40", allowed=["0x24"])
    assert r["pass"] is True, r


@pytest.mark.parametrize("answer", [
    "The reset value of SAI_BCR1 is 0x20.",                                            # giá trị sai ở câu nói về cả thanh ghi vẫn trượt
    "The reset value of SAI_BCR1 is 0x40. Actually the reset value is 0x00000020.",
])
def test_a_wrong_register_level_reset_value_still_fails(answer):
    r = grade(answer, attribute="reset", value="0x40")
    assert r["pass"] is False and any(x.startswith("wrong_value") for x in r["reasons"]), r


def test_only_the_bit_level_value_present_is_not_enough():
    r = grade("All other bits reset to 0, and the field DS[2:0] resets to 010.", attribute="reset", value="0x40")
    assert r["pass"] is False and any(x.startswith("missing_value") for x in r["reasons"]), r
