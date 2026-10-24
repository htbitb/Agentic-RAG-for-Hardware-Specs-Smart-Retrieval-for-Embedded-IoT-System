"""hwmodel.regmap — lớp thanh ghi CHUNG (3 chip): memory map, reset (ưu tiên giá trị manual), access/W1C, reserved, địa chỉ lạ.

Giá trị kỳ vọng lấy từ RM0440 (số trang ghi cạnh từng assert) hoặc tính tay — KHÔNG lấy từ chính simulator (D19).
Trang = chỉ số trang PDF (manifest page_offset = 0).
"""
import pytest

from hwmodel.regmap import OpResult, Register, RegisterFile, RegMap, load_regmap


@pytest.fixture(scope="module")
def stm():
    return load_regmap("stm32g474")


@pytest.fixture()
def rf(stm):
    return RegisterFile(stm)


# ------------------------------------------------------------------ memory map (RM0440 Table 4, tr.84–86)
@pytest.mark.parametrize("name,addr", [
    ("TIM1_PSC", 0x4001_2C00 + 0x28),      # TIM1 0x4001 2C00 (p.85); PSC offset 0x028 (p.1262)
    ("GPIOA_MODER", 0x4800_0000 + 0x00),   # GPIOA 0x4800 0000 (p.84); MODER offset 0x00 (p.355)
    ("RCC_CR", 0x4002_1000 + 0x00),        # RCC 0x4002 1000 (p.85); CR offset 0x00 (p.287)
    ("RCC_PLLCFGR", 0x4002_1000 + 0x0C),   # PLLCFGR offset 0x0C (p.291)
    ("USART1_BRR", 0x4001_3800 + 0x0C),    # USART1 0x4001 3800 (p.85); BRR offset 0x0C
    ("I2C1_TIMINGR", 0x4000_5400 + 0x10),  # I2C1 0x4000 5400 (p.86); TIMINGR offset 0x10
])
def test_register_addresses_follow_the_reference_manual_memory_map(stm, name, addr):
    reg = stm.get(name)
    assert reg is not None, name
    assert reg.address == addr


def test_names_resolve_case_insensitively_and_by_address(stm):
    assert stm.get("tim1_psc") is stm.get("TIM1_PSC") is stm.get("TIM1.PSC")
    assert stm.by_address(0x4001_2C28) is stm.get("TIM1_PSC")
    assert stm.get("NOPE_X") is None
    assert stm.by_address(0x4001_2C80) is None            # TIM1 offset 0x80: trống trong RM (p.1286 register map)


def test_input_and_output_views_of_ccmr_are_one_physical_register(stm):
    out = stm.get("TIM1_CCMR1_Output")
    assert out is stm.get("TIM1_CCMR1_Input") is stm.get("TIM1_CCMR1")
    assert out.address == 0x4001_2C18                      # offset 0x18 (p.1253)
    names = {f.name for f in out.fields}
    assert {"OC1M", "OC1PE", "CC1S", "IC1F"} <= names     # đủ trường của cả hai cách nhìn


# ------------------------------------------------------------------ reset: ưu tiên giá trị manual khi SVD sai
@pytest.mark.parametrize("name,reset,page", [
    ("GPIOA_MODER", 0xABFF_FFFF, 355),     # RM p.355 "Reset value: 0xABFF FFFF (for port A)"
    ("GPIOB_MODER", 0xFFFF_FEBF, 355),     # "Reset value: 0xFFFF FEBF (for port B)"
    ("RCC_CR", 0x0000_0500, 287),          # SVD ghi 0x63 (sai); manual 0x0000 0500
    ("RCC_CFGR", 0x0000_0005, 289),        # SW = HSI16
    ("RCC_PLLCFGR", 0x0000_1000, 291),
    ("FLASH_ACR", 0x0004_0601, 130),       # SVD ghi 0x600 (sai)
    ("TIM1_ARR", 0x0000_FFFF, 1263),
    ("TIM3_ARR", 0x0000_FFFF, 1388),       # SVD derivedFrom TIM2 => 0xFFFFFFFF (sai)
    ("TIM2_ARR", 0xFFFF_FFFF, 1388),
    ("SPI2_CR1", 0x0000_0000, 1874),       # SVD đảo reset CR1/CR2 của SPI2/3/4
    ("SPI2_CR2", 0x0000_0700, 1876),
])
def test_reset_values_prefer_the_manual_over_the_svd(stm, rf, name, reset, page):
    reg = stm.get(name)
    assert reg.reset == reset, f"{name} (RM p.{page})"
    assert rf.value(reg) == reset


def test_reset_source_is_reported(stm):
    assert stm.get("FLASH_ACR").reset_source == "manual"
    assert stm.get("TIM1_PSC").reset_source in ("svd", "manual")        # cả hai nguồn trùng nhau


# ------------------------------------------------------------------ errata: độ rộng ARR theo RM (p.1263, p.1388)
@pytest.mark.parametrize("name,mask", [
    ("TIM1_ARR", 0x000F_FFFF), ("TIM8_ARR", 0x000F_FFFF), ("TIM3_ARR", 0x000F_FFFF), ("TIM4_ARR", 0x000F_FFFF),
    ("TIM2_ARR", 0xFFFF_FFFF), ("TIM5_ARR", 0xFFFF_FFFF),
])
def test_arr_write_mask_follows_the_manual_not_the_svd(stm, name, mask):
    assert stm.get(name).rw_mask == mask


# ------------------------------------------------------------------ ghi: reserved / RO / địa chỉ lạ / svd_only
def test_plain_write_changes_value_without_violations(stm, rf):
    res = rf.apply({"op": "write", "reg": "TIM1_PSC", "value": 0x1234}, at_op=0)
    assert isinstance(res, OpResult)
    assert res.applied and res.new == 0x1234 and not res.violations
    assert rf.value(stm.get("TIM1_PSC")) == 0x1234


def test_write_to_reserved_bits_warns_and_keeps_reset_value(stm, rf):
    # TIM1_CR1: bit 31:13 và bit 10 reserved (p.1245); chỉ bit 12, 11, 9:0 ghi được (rw_mask 0x1BFF)
    res = rf.apply({"op": "write", "reg": "TIM1_CR1", "value": 0xFFFF_FFFF}, at_op=3)
    assert res.new == 0x0000_1BFF
    [v] = res.violations
    assert (v["code"], v["severity"], v["at_op"]) == ("SIM-RESERVED", "warning", 3)
    assert v["reg"] == "TIM1_CR1"


def test_write_that_leaves_reserved_bits_at_reset_value_is_clean(rf):
    res = rf.apply({"op": "write", "reg": "TIM1_CR1", "value": 0x0000_0081}, at_op=0)     # CEN | ARPE
    assert res.new == 0x81 and not res.violations


def test_write_to_read_only_register_warns_and_does_not_change(stm, rf):
    res = rf.apply({"op": "write", "reg": "GPIOA_IDR", "value": 0xFFFF}, at_op=1)
    assert not res.applied and res.new == rf.value(stm.get("GPIOA_IDR")) == 0
    assert [v["code"] for v in res.violations] == ["SIM-RO"] and res.violations[0]["severity"] == "warning"


def test_read_only_bits_inside_a_writable_register_are_not_changed(stm, rf):
    # RCC_CR.HSIRDY (bit 10) là RO: ghi 0 vào cả thanh ghi không xoá cờ RDY và không cảnh báo (RMW kinh điển)
    before = rf.value(stm.get("RCC_CR"))
    assert before & (1 << 10)
    res = rf.apply({"op": "write", "reg": "RCC_CR", "value": 0}, at_op=0)
    assert res.new & (1 << 10) and not [v for v in res.violations if v["code"] == "SIM-RO"]


def test_write_to_unknown_address_is_an_error_and_ignored(rf):
    res = rf.apply({"op": "write", "addr": 0x4001_2C80, "value": 1}, at_op=2)
    assert not res.applied and res.reg is None
    [v] = res.violations
    assert (v["code"], v["severity"], v["at_op"]) == ("SIM-BADADDR", "error", 2)
    assert "0x40012C80" in v["msg"]


def test_write_to_unknown_register_name_is_badaddr_too(rf):
    res = rf.apply({"op": "write", "reg": "TIM1_NOPE", "value": 1}, at_op=0)
    assert [v["code"] for v in res.violations] == ["SIM-BADADDR"]


def test_svd_only_register_still_simulates_but_warns(stm, rf):
    reg = stm.get("TIM4_DTR2")                 # RM0440 p.1403: offset 0x44–0x54 của TIM2/3/4/5 là Reserved => lỗi SVD
    assert reg is not None and reg.svd_only
    res = rf.apply({"op": "write", "reg": "TIM4_DTR2", "value": 1}, at_op=0)
    assert res.applied and "SIM-SVDONLY" in [v["code"] for v in res.violations]
    assert [v for v in res.violations if v["code"] == "SIM-SVDONLY"][0]["severity"] == "warning"


# ------------------------------------------------------------------ ops: set_bits / clear_bits / modify / read
def test_set_bits_is_a_read_modify_write(stm, rf):
    rf.apply({"op": "write", "reg": "GPIOA_AFRH", "value": 0x0000_00F0})
    res = rf.apply({"op": "set_bits", "reg": "GPIOA_AFRH", "mask": 0x6})
    assert res.new == 0xF6


def test_clear_bits_and_modify(stm, rf):
    rf.apply({"op": "write", "reg": "GPIOA_AFRH", "value": 0xFFFF_FFFF})
    assert rf.apply({"op": "clear_bits", "reg": "GPIOA_AFRH", "mask": 0xF}).new == 0xFFFF_FFF0
    assert rf.apply({"op": "modify", "reg": "GPIOA_AFRH", "mask": 0xF, "value": 0x6}).new == 0xFFFF_FFF6


def test_modify_ignores_value_bits_outside_the_mask(rf):
    rf.apply({"op": "write", "reg": "GPIOA_AFRH", "value": 0})
    assert rf.apply({"op": "modify", "reg": "GPIOA_AFRH", "mask": 0xF, "value": 0x16}).new == 0x6


def test_field_form_modify_uses_the_svd_field_position(rf):
    # RCC_APB2ENR.TIM1EN = bit 11 (p.313)
    res = rf.apply({"op": "modify", "reg": "RCC_APB2ENR", "field": "TIM1EN", "value": 1})
    assert res.new == 1 << 11


def test_toggle_bits_is_a_read_modify_write_xor(rf):
    rf.apply({"op": "write", "reg": "GPIOA_ODR", "value": 0b0110})
    assert rf.apply({"op": "toggle_bits", "reg": "GPIOA_ODR", "mask": 0b0011}).new == 0b0101


def test_rmw_is_one_write_of_a_general_bitwise_function_of_the_old_value(rf):
    rf.apply({"op": "write", "reg": "GPIOA_ODR", "value": 0x00F0})
    # ((old & 0xFF) | 0x0F) ^ 0x3C  với old = 0xF0:  (0xF0 | 0x0F) ^ 0x3C = 0xFF ^ 0x3C = 0xC3  — một lệnh ghi duy nhất
    assert rf.apply({"op": "rmw", "reg": "GPIOA_ODR", "and": 0xFF, "or": 0x0F, "xor": 0x3C}).new == 0xC3


def test_hex_strings_are_accepted_for_values_and_masks(rf):
    assert rf.apply({"op": "write", "reg": "TIM1_ARR", "value": "0x2133"}).new == 0x2133
    assert rf.apply({"op": "set_bits", "reg": "TIM1_ARR", "mask": "0x1"}).new == 0x2133


def test_read_op_does_not_change_state_and_returns_the_value(stm, rf):
    res = rf.apply({"op": "read", "reg": "RCC_CR"})
    assert res.new == res.old == 0x500 and not res.violations and res.applied is False


def test_read_of_write_only_register_returns_zero(stm, rf):
    assert stm.get("GPIOA_BSRR").access == "WO"
    assert rf.apply({"op": "read", "reg": "GPIOA_BSRR"}).new == 0


def test_set_bits_on_write_only_register_does_not_resurrect_old_bits(rf):
    # |= trên thanh ghi WO: phần cứng đọc về 0 rồi ghi (0 | mask) — không "nhớ" lần ghi trước
    rf.apply({"op": "write", "reg": "TIM1_EGR", "value": 0b11})
    res = rf.apply({"op": "set_bits", "reg": "TIM1_EGR", "mask": 0b100})
    assert res.written == 0b100


def test_unknown_op_is_rejected_with_a_clear_error(rf):
    with pytest.raises(ValueError, match="unknown op"):
        rf.apply({"op": "toggle", "reg": "TIM1_PSC", "value": 1})


def test_values_wider_than_the_register_are_truncated_like_a_32_bit_store(rf):
    res = rf.apply({"op": "write", "reg": "TIM1_PSC", "value": 0x1_0000_0001})
    assert res.new == 0x1 and res.written == 0x1


# ------------------------------------------------------------------ W1C / oneToSet … (tổng quát; dữ liệu nRF có thật ở test_svd_attrs)
def _toy_map(modified):
    reg = Register(chip="toy", peripheral="P", name="SR", rid="P_SR", address=0x1000, size=32, access="RW", reset=0b1011,
                   reset_source="svd", rw_mask=0xFF, reserved_mask=0xFFFF_FF00, svd_only=False, page=None, doc="toy",
                   fields=[], views=["SR"], modified_write=modified)
    return RegMap("toy", [reg])


def test_one_to_clear_register_clears_only_the_bits_written_as_one():
    rm = _toy_map("oneToClear")
    rf = RegisterFile(rm)
    assert rf.apply({"op": "write", "reg": "P_SR", "value": 0b0010}).new == 0b1001


def test_set_bits_on_a_one_to_clear_register_clears_every_pending_flag():
    # lỗi kinh điển: SR |= X  đọc cờ đang bật rồi ghi lại 1 => xoá hết cờ
    rm = _toy_map("oneToClear")
    rf = RegisterFile(rm)
    assert rf.apply({"op": "set_bits", "reg": "P_SR", "mask": 0b0100}).new == 0


def test_one_to_set_register_sets_only_the_bits_written_as_one():
    rm = _toy_map("oneToSet")
    rf = RegisterFile(rm)
    assert rf.apply({"op": "write", "reg": "P_SR", "value": 0b0100}).new == 0b1111


def test_zero_to_clear_register_clears_the_bits_written_as_zero():
    rm = _toy_map("zeroToClear")
    rf = RegisterFile(rm)
    assert rf.apply({"op": "write", "reg": "P_SR", "value": 0b1110}).new == 0b1010


# ------------------------------------------------------------------ 3 chip
def test_all_three_chips_load_and_expose_registers():
    for chip, probe in (("esp32", None), ("nrf52840", None)):
        rm = load_regmap(chip)
        assert len(rm.registers) > 1000
    assert load_regmap("stm32g474").get("TIM1_PSC") is not None


def test_nrf52840_svd_attributes_are_loaded_from_the_sidecar():
    # nRF SVD có modifiedWriteValues ở mức thanh ghi (P0.OUTSET/OUTCLR/DIRSET/DIRCLR, ERRORSRC...); DB P1 không lưu => sidecar svd_attrs.json
    rm = load_regmap("nrf52840")
    assert rm.get("P0_OUTSET").modified_write == "oneToSet"
    assert rm.get("P0_OUTCLR").modified_write == "oneToClear"
    assert rm.get("P0_DIRSET").modified_write == "oneToSet"
    assert rm.get("P0_DIRCLR").modified_write == "oneToClear"
    assert rm.get("P0_OUT").modified_write is None


def test_esp32_alias_address_resolves_to_the_same_register():
    rm = load_regmap("esp32")
    regs = [r for r in rm.registers if r.address_alias]
    assert regs, "ESP32 phải có thanh ghi với địa chỉ alias (TRM p.73)"
    r = regs[0]
    assert rm.by_address(r.address) is r and rm.by_address(r.address_alias) is r


def test_unknown_chip_raises():
    with pytest.raises(KeyError):
        load_regmap("avr")
