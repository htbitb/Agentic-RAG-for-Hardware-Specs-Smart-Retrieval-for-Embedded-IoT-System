"""Gắn trang RM0440 cho thanh ghi STM32G474. Giá trị kỳ vọng đã đối chiếu TAY với text trang RM (xem ledger P1).

Mỗi mục: (peripheral, register, trang RM kỳ vọng). Trang = trang có tiêu đề "<mục> ... (<TÊN_RM>)" + "Address offset".
"""
import pytest

from ingestion import pdfdocs
from ingestion.register_pages import ST_RM, locate_stm32, parse_offsets, parse_qualifier, stm32_blocks
from ingestion.svd_ingest import parse_svd

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")

GOLDEN = [
    ("RTC", "WUTR", 1593),          # 37.6.6 RTC wakeup timer register (RTC_WUTR), Address offset 0x14
    ("TIM1", "CR1", 1235),          # 29.6.1 (TIMx_CR1)(x = 1, 8, 20)
    ("TIM8", "CR1", 1235),          # peripheral dẫn xuất từ TIM1
    ("TIM2", "CR1", 1366),          # 30.5.1 (TIMx_CR1)(x = 2 to 5)
    ("TIM4", "CR1", 1366),
    ("TIM16", "CR1", 1484),         # 31.8.1 (x = 16 to 17)
    ("TIM6", "CR1", 1524),          # 32.4.1 (x = 6 to 7)
    ("RCC", "RCC_AHB2ENR", 306),    # 7.4.15 — SVD đã mang tiền tố RCC_
    ("GPIOA", "MODER", 355),        # 9.4.1 (GPIOx_MODER)(x = A to G)
    ("GPIOG", "AFRH", 360),
    ("USART1", "CR1", 1740),        # 40.8.1 (USART_CR1); bản [alternate] ở p.1743
    ("UART4", "CR1", 1740),         # SVD group USART -> RM dùng chung tên USART_CR1
    ("FLASH", "ACR", 130),          # G474 = Category 3 (RM Table 1, p.75) -> chương 3, không phải p.174/214
    ("ADC1", "CR", 681),            # 21.7.3 (ADC_CR) Address offset 0x08
    ("DMA1", "CCR1", 411),          # 12.6.3 (DMA_CCRx) Address offset 0x08 + 0x14 * (x - 1), (x = 1 to 8)
    ("DMA2", "CCR3", 411),
    ("I2C1", "TIMINGR", 1681),
    ("FDCAN1", "CCCR", 1987),       # (FDCAN_CCCR) Address offset 0x0018
    ("RCC", "RCC_CFGR", 289),
    ("PWR", "PWR_CR1", 253),
]


@pytest.fixture(scope="module")
def device():
    return parse_svd(pdfdocs.CORPUS / "svd" / "STM32G474xx.svd")


@pytest.fixture(scope="module")
def blocks():
    return stm32_blocks()


@pytest.mark.parametrize("periph,reg,page", GOLDEN)
def test_golden_register_pages(device, blocks, periph, reg, page):
    p = device.peripheral(periph)
    loc = locate_stm32("stm32g474", p, p.register(reg), blocks)
    assert loc is not None, f"{periph}.{reg} not located"
    assert (loc.doc, loc.page) == (ST_RM, page)
    assert loc.confidence == "high"          # tên + offset khớp


def test_alternate_description_pages_are_kept_separately(device, blocks):
    p = device.peripheral("TIM1")
    loc = locate_stm32("stm32g474", p, p.register("CCMR1_Output"), blocks) or locate_stm32("stm32g474", p, p.register("CCMR1_Input"), blocks)
    assert loc is not None and {loc.page, *loc.alt_pages} >= {1249, 1251}


def test_tim4_dtr2_is_not_in_the_reference_manual(device, blocks):
    """SVD của ST có TIM4_DTR2 @0x54 (derivedFrom TIM2) nhưng RM0440 chỉ mô tả DTR2 cho TIM1/8/20 (x = 1, 8, 20)."""
    p = device.peripheral("TIM4")
    assert locate_stm32("stm32g474", p, p.register("DTR2"), blocks) is None
    p1 = device.peripheral("TIM1")
    assert locate_stm32("stm32g474", p1, p1.register("DTR2"), blocks) is not None


def test_cortex_core_peripherals_are_not_documented_in_rm0440(device, blocks):
    for name, reg in (("NVIC", "ISER0"), ("SCB", "CPUID"), ("STK", "CTRL"), ("MPU", "CTRL")):
        p = device.peripheral(name)
        assert locate_stm32("stm32g474", p, p.register(reg), blocks) is None


@pytest.mark.parametrize("expr,expected", [
    ("0x14", {0x14}), ("0x00.", {0}), ("0x0018", {0x18}), ("0x08 + 0x14 * (x - 1), (x = 1 to 8)", {0x08 + 0x14 * i for i in range(8)}),
    ("0x040 + 0x4 * x, (x = 0 to 7)", {0x40 + 4 * i for i in range(8)}),
    ("0x60 + 0x04 * (y -1), (y= 1 to 4)", {0x60, 0x64, 0x68, 0x6C}),
    ("Block A: 0x080", {0x80}), ("[USB_BTABLE] + n*8 + 2", None),
    ("0x00 to 0x1C", {0, 4, 8, 12, 16, 20, 24, 28}),
    ("Block A: 0x0BC Address offset: Block B: 0x13C", {0xBC, 0x13C}),
])
def test_parse_offsets(expr, expected):
    assert parse_offsets(expr) == expected


@pytest.mark.parametrize("title,expected", [
    ("(TIMx_CR1)(x = 1, 8, 20)", {"x": {"1", "8", "20"}}),
    ("(GPIOx_MODER) (x = A to G)", {"x": set("ABCDEFG")}),
    ("(ADCx_CSR) (x = 12 or 345)", {"x": {"12", "345"}}),
    ("(OPAMPx_TCMR) (x = 1...6)", {"x": {"1", "2", "3", "4", "5", "6"}}),
    ("(TIMx_CCR4)(x = 2, 5)", {"x": {"2", "5"}}),
    ("(RTC_CR)", {}),
])
def test_parse_qualifier(title, expected):
    assert parse_qualifier(title) == expected


# ---- bổ sung: nguồn text (tiêu đề không có trong outline), dự phòng theo offset, HRTIM base offset
GOLDEN2 = [
    ("FMC", "BCR1", 542, "high"),              # (FMC_BCRx), Address offset: 0x00 + 0x8 * (x - 1), (x = 1 to 4) — không có trong outline
    ("FMC", "BCR3", 542, "high"),
    ("USB_FS_device", "EP0R", 2040, "high"),   # "USB endpoint n register (USB_EPnR), n=[0..7]" Address offset: 0x00 to 0x1C (đọc tay p.2040)
    ("USB_FS_device", "EP5R", 2040, "high"),
    ("UCPD1", "CFG1", 2071, "offset"),         # SVD 'CFG1' vs RM 'UCPD_CFGR1', cùng offset 0x00 trong chương UCPD
    ("DBGMCU", "CR", 2108, "high"),            # "Address: 0xE004 2004" (địa chỉ tuyệt đối, đọc tay p.2108)
    ("HRTIM_TIMA", "TIMACR", 1006, "high"),    # RM in offset từ base HRTIM (0x80), SVD tính từ base timer A
    ("HRTIM_TIMC", "SETC1R", 1029, "high"),
    ("RCC", "RCC_APB1ENR1", 309, "high"),      # RCC in "Address: 0x58" = OFFSET (không phải địa chỉ tuyệt đối)
    ("DBGMCU", "IDCODE", 2095, "high"),        # "DBGMCU_IDCODE" đứng riêng một dòng + "Address: 0xE004 2000" (p.2095, đọc tay)
    ("DBGMCU", "APB1L_FZ", 2109, "offset"),    # SVD 'APB1L_FZ' vs RM 'DBGMCU_APB1FZR1', cùng địa chỉ 0xE0042008
]


@pytest.mark.parametrize("periph,reg,page,conf", GOLDEN2)
def test_text_sourced_and_fallback_locations(device, blocks, periph, reg, page, conf):
    from ingestion.register_pages import group_bases
    p = device.peripheral(periph)
    loc = locate_stm32("stm32g474", p, p.register(reg), blocks, group_bases(device))
    assert loc is not None, f"{periph}.{reg} not located"
    assert (loc.page, loc.confidence) == (page, conf)


def _tiny(reg_name, offset):
    from ingestion.svd_ingest import parse_svd_text
    xml = ("<device><name>T</name><size>32</size><access>read-write</access><resetValue>0</resetValue><resetMask>0xFFFFFFFF</resetMask>"
           "<peripherals><peripheral><name>UCPD1</name><baseAddress>0x1000</baseAddress><groupName>UCPD</groupName><registers>"
           f"<register><name>{reg_name}</name><addressOffset>{offset}</addressOffset></register></registers></peripheral></peripherals></device>")
    p = parse_svd_text(xml).peripheral("UCPD1")
    return p, p.registers[0]


def _ucpd_block():
    from ingestion.register_pages import Block
    return Block(doc=ST_RM, page=2071, title="46.8.1 UCPD configuration register 1 (UCPD_CFGR1)", names=["UCPD_CFGR1"],
                 var_sets={}, offsets={0}, chapter="46 USB Type-C / USB Power Delivery interface (UCPD)",
                 path=("46 USB Type-C / USB Power Delivery interface (UCPD)", "46.8 UCPD registers"))


def test_offset_fallback_accepts_similar_name_with_same_offset_in_the_peripheral_chapter():
    p, r = _tiny("CFG1", "0x0")
    loc = locate_stm32("stm32g474", p, r, [_ucpd_block()])
    assert (loc.page, loc.confidence) == (2071, "offset")


def test_offset_fallback_refuses_when_the_name_is_not_similar_enough():
    p, r = _tiny("QWERTYUIOP", "0x0")
    assert locate_stm32("stm32g474", p, r, [_ucpd_block()]) is None


def test_offset_fallback_refuses_when_two_blocks_share_the_offset_and_are_equally_similar():
    from dataclasses import replace
    b1 = _ucpd_block()
    b2 = replace(b1, page=2073, names=["UCPD_CFGR2"], title="46.8.2 UCPD configuration register 2 (UCPD_CFGR2)")
    p, r = _tiny("CFG", "0x0")
    assert locate_stm32("stm32g474", p, r, [b1, b2]) is None


# ---- reset value in the manual (SVD <-> RM discrepancy check)
@pytest.mark.parametrize("text,expected", [
    ("0x0004 0601", 0x40601), ("0x0000 0000", 0), ("0x2000 0000", 0x20000000), ("0x0000", 0), ("0x0000 FFFF.", 0xFFFF),
    ("0xABFF FFFF (for port A)", None), ("0x0000 30DB, 0x0000 30D2, 0x0000 30D2", None), ("0x0000 xxxx", None),
])
def test_parse_reset_text(text, expected):
    from ingestion.register_pages import parse_reset_text
    assert parse_reset_text(text) == expected


def test_stm32_block_exposes_the_reset_value_printed_in_the_manual(blocks):
    from ingestion.register_pages import ST_RM  # noqa: F401
    b = next(b for b in blocks if "FLASH_ACR" in b.names and b.page == 130)
    assert b.reset == 0x00040601
    wutr = next(b for b in blocks if "RTC_WUTR" in b.names)
    assert wutr.reset == 0xFFFF                      # "Backup domain reset value: 0x0000 FFFF"
    assert next(b for b in blocks if "GPIOx_MODER" in b.names).reset is None      # ba giá trị theo cổng -> không chọn


def test_located_register_carries_the_manual_reset(device, blocks):
    p = device.peripheral("FLASH")
    loc = locate_stm32("stm32g474", p, p.register("ACR"), blocks)
    assert loc.rm_reset == 0x00040601


def test_reset_equal_to_any_documented_variant_is_not_a_mismatch(device, blocks):
    """LPUART_ISR có hai mô tả (FIFO bật: 0x0080 00C0; FIFO tắt: 0x0000 00C0). SVD = 0xC0 khớp biến thể thứ hai."""
    p = device.peripheral("LPUART1")
    r = p.register("ISR")
    loc = locate_stm32("stm32g474", p, r, blocks)
    assert r.reset_value == 0xC0 and loc.rm_reset == 0xC0


def test_reset_mismatch_is_kept_when_no_variant_matches(device, blocks):
    p = device.peripheral("SPI2")
    loc = locate_stm32("stm32g474", p, p.register("CR1"), blocks)      # SVD 0x700 (đảo với CR2); RM SPIx_CR1 = 0x0
    assert loc.rm_reset == 0x0 and p.register("CR1").reset_value == 0x700
