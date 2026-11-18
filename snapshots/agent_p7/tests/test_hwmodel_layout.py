"""hwmodel: các hằng số vị trí bit viết tay (trích từ RM0440, kèm số trang) phải KHỚP trường SVD trong DB; bảng cổng clock đủ & đúng;
giới hạn clock nạp từ DB khớp RM Table 9 (p.98) và DS12288 Table 46 (p.123).
Mục đích: bắt lỗi gõ nhầm hằng số — vì golden test dùng chính các vị trí bit này nên một hằng sai có thể "tự khớp" sai.
"""
import sqlite3

import pytest

from hwmodel import data
from hwmodel.clock_tree import (CR_HSEON, CR_HSERDY, CR_HSION, CR_HSIRDY, CR_PLLON, CR_PLLRDY, load_limits)
from hwmodel.periph import rcc, tim, usart, i2c
from hwmodel.regmap import load_regmap


@pytest.fixture(scope="module")
def rm():
    return load_regmap("stm32g474")


def where(rm, rid, field):
    reg = rm.get(rid)
    f = reg.field(field)
    assert f is not None, f"{rid}.{field}"
    return f.bit_offset, f.bit_width


@pytest.mark.parametrize("rid,field,pos", [
    ("RCC_CR", "HSION", (8, 1)), ("RCC_CR", "HSIRDY", (10, 1)), ("RCC_CR", "HSEON", (16, 1)), ("RCC_CR", "HSERDY", (17, 1)),
    ("RCC_CR", "PLLON", (24, 1)), ("RCC_CR", "PLLRDY", (25, 1)),
    ("RCC_CFGR", "SW", (0, 2)), ("RCC_CFGR", "SWS", (2, 2)), ("RCC_CFGR", "HPRE", (4, 4)), ("RCC_CFGR", "PPRE1", (8, 3)), ("RCC_CFGR", "PPRE2", (11, 3)),
    ("RCC_PLLCFGR", "PLLSRC", (0, 2)), ("RCC_PLLCFGR", "PLLM", (4, 4)), ("RCC_PLLCFGR", "PLLN", (8, 7)), ("RCC_PLLCFGR", "PLLR", (25, 2)),
    ("RCC_PLLCFGR", "PLLREN", (24, 1)), ("RCC_PLLCFGR", "PLLQ", (21, 2)), ("RCC_PLLCFGR", "PLLP", (17, 1)), ("RCC_PLLCFGR", "PLLPDIV", (27, 5)),
    ("PWR_CR1", "VOS", (9, 2)), ("PWR_CR5", "R1MODE", (8, 1)), ("FLASH_ACR", "LATENCY", (0, 4)),
    ("RCC_CCIPR", "USART1SEL", (0, 2)), ("RCC_CCIPR", "USART2SEL", (2, 2)), ("RCC_CCIPR", "USART3SEL", (4, 2)),
    ("RCC_CCIPR", "UART4SEL", (6, 2)), ("RCC_CCIPR", "UART5SEL", (8, 2)),
    ("RCC_CCIPR", "I2C1SEL", (12, 2)), ("RCC_CCIPR", "I2C2SEL", (14, 2)), ("RCC_CCIPR", "I2C3SEL", (16, 2)), ("RCC_CCIPR2", "I2C4SEL", (0, 2)),
])
def test_rcc_pwr_flash_constants_match_the_svd(rm, rid, field, pos):
    assert where(rm, rid, field) == pos


def test_clock_tree_bit_masks_match_the_svd(rm):
    for const, (field) in ((CR_HSION, "HSION"), (CR_HSIRDY, "HSIRDY"), (CR_HSEON, "HSEON"), (CR_HSERDY, "HSERDY"), (CR_PLLON, "PLLON"), (CR_PLLRDY, "PLLRDY")):
        assert const == 1 << where(rm, "RCC_CR", field)[0], field
    assert rcc.PLLREN == 1 << where(rm, "RCC_PLLCFGR", "PLLREN")[0]


@pytest.mark.parametrize("field,pos", [("CEN", (0, 1)), ("OPM", (3, 1)), ("DIR", (4, 1)), ("CMS", (5, 2)), ("ARPE", (7, 1)), ("DITHEN", (12, 1))])
def test_tim_cr1_constants(rm, field, pos):
    assert where(rm, "TIM1_CR1", field) == pos
    assert {"CEN": tim.CR1_CEN, "OPM": tim.CR1_OPM, "DIR": tim.CR1_DIR, "DITHEN": tim.CR1_DITHEN}.get(field, 1 << pos[0]) == 1 << pos[0]


def test_tim_bdtr_constants(rm):
    assert tim.BDTR_MOE == 1 << where(rm, "TIM1_BDTR", "MOE")[0]
    assert tim.BDTR_AOE == 1 << where(rm, "TIM1_BDTR", "AOE")[0]
    assert where(rm, "TIM1_BDTR", "DTG") == (0, 8)


@pytest.mark.parametrize("ch", [1, 2, 3, 4])
def test_tim_channel_field_positions_match_the_svd(rm, ch):
    f = tim.channel_fields(ch)
    ccmr = f"TIM1_{f['ccmr']}"
    assert where(rm, ccmr, f"OC{ch}M") == (f["ocm_lo"], 3)
    assert where(rm, ccmr, f"OC{ch}M_3") == (f["ocm_hi"], 1)
    assert where(rm, ccmr, f"CC{ch}S") == (f["ccs_lo"], 2)
    assert where(rm, ccmr, f"OC{ch}PE") == (f["ocpe"], 1)
    assert where(rm, "TIM1_CCER", f"CC{ch}E")[0] == f["cce"]
    assert where(rm, "TIM1_CCER", f"CC{ch}P")[0] == f["ccp"]
    assert where(rm, "TIM1_CCER", f"CC{ch}NE")[0] == f["ccne"]
    assert where(rm, "TIM1_CCER", f"CC{ch}NP")[0] == f["ccnp"]


def test_usart_and_i2c_constants(rm):
    assert usart.CR1_UE == 1 << where(rm, "USART1_CR1", "UE")[0]
    assert usart.CR1_RE == 1 << where(rm, "USART1_CR1", "RE")[0]
    assert usart.CR1_TE == 1 << where(rm, "USART1_CR1", "TE")[0]
    assert usart.CR1_OVER8 == 1 << where(rm, "USART1_CR1", "OVER8")[0]
    assert where(rm, "USART1_BRR", "DIV_Mantissa") == (4, 12) and where(rm, "USART1_BRR", "DIV_Fraction") == (0, 4)
    assert where(rm, "USART1_PRESC", "PRESCALER") == (0, 4)
    for inst, (_bus, lo) in usart.USARTS.items():
        assert where(rm, "RCC_CCIPR", f"{inst}SEL")[0] == lo, inst
    for fld, pos in (("PRESC", (28, 4)), ("SCLDEL", (20, 4)), ("SDADEL", (16, 4)), ("SCLH", (8, 8)), ("SCLL", (0, 8))):
        assert where(rm, "I2C1_TIMINGR", fld) == pos
    assert where(rm, "I2C1_CR1", "PE") == (0, 1) and where(rm, "I2C1_CR1", "DNF") == (8, 4)
    for inst, (selreg, lo) in i2c.I2CS.items():
        assert where(rm, selreg, f"{inst}SEL")[0] == lo, inst


def test_gpio_mode_and_af_field_positions(rm):
    # MODERy ở bit 2y (p.355), AFSELy ở nibble 4*(y mod 8) của AFRL (y<8) / AFRH (y>=8)
    for n in range(16):
        assert where(rm, "GPIOA_MODER", f"MODER{n}") == (2 * n, 2)
        assert where(rm, "GPIOA_AFRL" if n < 8 else "GPIOA_AFRH", f"AFR{'L' if n < 8 else 'H'}{n}") == (4 * (n % 8), 4)


# ------------------------------------------------------------------ cổng clock
def test_every_gate_names_a_real_enable_bit(rm):
    for per, (enr, fld) in rcc.GATES.items():
        assert rm.get(enr) is not None and rm.get(enr).field(fld) is not None, (per, enr, fld)
    seen = {r.peripheral for r in rm.registers}
    assert set(rcc.GATES) <= seen, set(rcc.GATES) - seen


def test_every_peripheral_in_the_db_is_either_gated_or_declared_ungated(rm):
    con = sqlite3.connect(f"file:{data.default_db()}?mode=ro", uri=True)
    names = {r[0] for r in con.execute("SELECT name FROM peripherals WHERE chip='stm32g474'")}
    con.close()
    missing = names - set(rcc.GATES) - rcc.UNGATED
    assert not missing, f"peripheral(s) without a clock-gate decision: {sorted(missing)}"


@pytest.mark.parametrize("per,enr,fld,bit", [
    ("GPIOA", "RCC_AHB2ENR", "GPIOAEN", 0), ("TIM1", "RCC_APB2ENR", "TIM1EN", 11), ("USART1", "RCC_APB2ENR", "USART1EN", 14),
    ("TIM2", "RCC_APB1ENR1", "TIM2EN", 0), ("USART2", "RCC_APB1ENR1", "USART2EN", 17), ("I2C1", "RCC_APB1ENR1", "I2C1EN", 21),
    ("PWR", "RCC_APB1ENR1", "PWREN", 28), ("DMA1", "RCC_AHB1ENR", "DMA1EN", 0), ("FLASH", "RCC_AHB1ENR", "FLASHEN", 8),
])
def test_clock_enable_bits_follow_the_manual(rm, per, enr, fld, bit):
    # vị trí bit đọc trực tiếp từ trang RM0440 (p.306–313)
    assert rcc.GATES[per] == (enr, fld) and where(rm, enr, fld) == (bit, 1)


def test_modeled_register_names_exist_in_the_db(rm):
    for tmr in ("TIM1", "TIM2", "TIM15"):
        for r in tim.MODELED_REGS:
            if rm.get(f"{tmr}_{r}") is None:
                assert tmr in ("TIM2", "TIM15"), (tmr, r)          # TIM2 không có BDTR/RCR..., TIM15 không có CCR3/4: hợp lệ


# ------------------------------------------------------------------ giới hạn từ DB (RM Table 9 p.98, DS Table 46 p.123, Table 17 p.84)
def test_limits_match_the_documents():
    lim = load_limits("stm32g474")
    assert lim.hclk_max == 170e6
    assert lim.pll_in == (2.66e6, 16e6)
    assert lim.vco == {"range1": (96e6, 344e6), "range2": (96e6, 128e6)}
    # RM0440 Table 9 (category 3): ngưỡng HCLK tối đa của 0..4 WS
    assert dict(lim.flash_ws["boost"]) == {0: 34e6, 1: 68e6, 2: 102e6, 3: 136e6, 4: 170e6}
    assert dict(lim.flash_ws["normal"]) == {0: 30e6, 1: 60e6, 2: 90e6, 3: 120e6, 4: 150e6}
    assert dict(lim.flash_ws["range2"]) == {0: 12e6, 1: 24e6, 2: 26e6}


@pytest.mark.parametrize("hclk,mode,ws", [(16e6, "normal", 0), (30e6, "normal", 0), (30.1e6, "normal", 1), (80e6, "boost", 2), (170e6, "boost", 4),
                                          (150e6, "normal", 4), (26e6, "range2", 2), (170e6, "normal", None)])
def test_needed_wait_states(hclk, mode, ws):
    from hwmodel.clock_tree import Limits
    assert load_limits("stm32g474").needed_ws(hclk, mode) == ws
    assert Limits.mode(0b10, 0) == "range2" and Limits.mode(0b01, 1) == "normal" and Limits.mode(0b01, 0) == "boost"


def test_write_lock_masks_match_the_svd_fields(rm):
    from hwmodel.periph import i2c as i2c_mod, usart as usart_mod
    cr1 = usart_mod.WRITE_LOCKED["CR1"]
    for name in ("FIFOEN", "M1", "OVER8", "M0", "WAKE", "PS"):
        off, w = where(rm, "USART1_CR1", name)
        assert cr1 & (((1 << w) - 1) << off) == ((1 << w) - 1) << off, name
    for name in ("TE", "RE", "UE", "PCE", "IDLEIE"):                 # không bị khoá: TE/RE đổi được khi đang chạy; PCE không có câu 'only be written when disabled'
        off, w = where(rm, "USART1_CR1", name)
        assert not cr1 & (((1 << w) - 1) << off), name
    assert usart_mod.WRITE_LOCKED["CR2"] & (0b11 << 12) == 0b11 << 12 and where(rm, "USART1_CR2", "STOP") == (12, 2)
    assert usart_mod.WRITE_LOCKED["BRR"] == 0xFFFF and i2c_mod.WRITE_LOCKED["TIMINGR"] == 0xFFFF_FFFF
    assert where(rm, "USART1_CR1", "PS") == (9, 1) and where(rm, "USART1_CR1", "PCE") == (10, 1)
