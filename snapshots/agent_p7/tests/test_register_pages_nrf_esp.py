"""Gắn trang cho nRF52840 (PS) và ESP32 (TRM). Giá trị kỳ vọng đã đối chiếu TAY với text trang."""
import pytest

from ingestion import pdfdocs
from ingestion.register_pages import (ESP_TRM, NRF_PS, dport_window, esp32_index, locate_esp32, locate_nrf,
                                      nrf_blocks)
from ingestion.svd_ingest import parse_svd

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")

NRF_GOLDEN = [
    # (peripheral, register, trang PS, offset trên trang)
    ("P0", "OUT", 326, 0x504),               # 6.9.2.1 OUT, Address offset: 0x504
    ("P0", "IN", 335, 0x510),                # 6.9.2.4 IN
    ("P0", "PIN_CNF[0]", 349, 0x700),        # 6.9.2.10 PIN_CNF[0]
    ("P1", "OUT", 326, 0x504),               # P1 derivedFrom P0 -> cùng chương GPIO
    ("TWIM0", "PSEL.SCL", 798, 0x508),       # 6.31.7.19 PSEL.SCL
    ("TWIM0", "INTENCLR", 796, 0x308),       # 6.31.7.16 INTENCLR (cũng có ở SPIM/TWIS... -> phải chọn đúng chương TWIM)
    ("TIMER0", "CC[0]", 784, 0x540),         # 6.30.5.24 CC[0] (RTC cũng có CC[0] ở p.674)
    ("TIMER0", "PRESCALER", 783, 0x510),     # 6.30.5.23
    ("UARTE0", "BAUDRATE", 846, 0x524),      # 6.34.9.27 (UARTE; chương 6.33 là UART legacy: p.830)
    ("UARTE0", "PSEL.RXD", 846, 0x514),      # 6.34.9.26
    ("FICR", "DEVICEADDR[0]", 36, 0x0A4),    # 4.4.1.14
    ("RTC0", "CC[0]", 674, 0x540),           # 6.22.10.18
]


@pytest.fixture(scope="module")
def nrf():
    return parse_svd(pdfdocs.CORPUS / "svd" / "nrf52840.svd"), nrf_blocks()


@pytest.mark.parametrize("periph,reg,page,offset", NRF_GOLDEN)
def test_nrf_golden_pages(nrf, periph, reg, page, offset):
    dev, blocks = nrf
    p = dev.peripheral(periph)
    r = p.register(reg)
    assert r.offset == offset                 # SVD đúng với offset in trên trang
    loc = locate_nrf(p, r, blocks)
    assert loc is not None, f"{periph}.{reg}"
    assert (loc.doc, loc.page, loc.confidence) == (NRF_PS, page, "high")


def test_nrf_cluster_member_without_own_heading_falls_back_to_cluster_page(nrf):
    dev, blocks = nrf
    p = dev.peripheral("TWIM0")
    r = p.register("RXD.PTR")
    loc = locate_nrf(p, r, blocks)
    assert loc is not None and loc.page in (799, 800)   # "6.31.7.22 RXD" bắt đầu ở p.799


ESP_GOLDEN = [
    # (peripheral, register, tên trong TRM, trang bảng tóm tắt đã đọc tay)
    ("UART0", "FIFO", "UART_FIFO_REG", 320),
    ("UART2", "FIFO", "UART_FIFO_REG", 320),              # cùng hàng, cột địa chỉ thứ ba (0x3FF6E000)
    ("SPI2", "CTRL", "SPI_CTRL_REG", 363),                # địa chỉ in không có tiền tố 0x: 3FF64008
    ("MCPWM0", "TIMER0_CFG0", "PWM_TIMER0_CFG0_REG", 677),
    ("RTC_I2C", "CTRL", "RTC_I2C_CTRL_REG", 45),
    ("GPIO", "OUT", "GPIO_OUT_REG", 134),
    ("GPIO", "OUT_W1TS", "GPIO_OUT_W1TS_REG", 135),
]


@pytest.fixture(scope="module")
def esp():
    return parse_svd(pdfdocs.CORPUS / "svd" / "esp32.svd"), esp32_index()


@pytest.mark.parametrize("periph,reg,trm_name,summary_page", ESP_GOLDEN)
def test_esp32_golden_pages(esp, periph, reg, trm_name, summary_page):
    dev, idx = esp
    p = dev.peripheral(periph)
    loc = locate_esp32(p, p.register(reg), idx)
    assert loc is not None, f"{periph}.{reg}"
    assert loc.doc == ESP_TRM and loc.rm_name == trm_name
    assert summary_page in {loc.page, *loc.alt_pages}


def test_esp32_dport_and_ahb_windows_are_the_same_register():
    """TRM p.73: (0x3FF40000 + n) và (0x60000000 + n) truy cập cùng nội dung, n = 0..0x3FFFF."""
    assert dport_window(0x60019100) == 0x3FF59100
    assert dport_window(0x3FF59100) == 0x3FF59100
    assert dport_window(0x50000000) == 0x50000000          # ngoài hai cửa sổ -> giữ nguyên


def test_esp32_registers_absent_from_the_trm_are_not_invented(esp):
    dev, idx = esp
    p = dev.peripheral("GPIO")
    assert locate_esp32(p, p.register("BT_SELECT"), idx) is None      # SVD-only, TRM không liệt kê


def test_esp32_array_register_resolves_to_the_pattern_description(esp):
    dev, idx = esp
    p = dev.peripheral("GPIO")
    loc = locate_esp32(p, p.register("PIN7"), idx) if "PIN7" in {r.name for r in p.registers} else None
    assert loc is not None and loc.rm_name.startswith("GPIO_PIN")


def test_nrf_block_exposes_the_reset_value_from_the_register_table(nrf):
    dev, blocks = nrf
    p = dev.peripheral("P0")
    assert locate_nrf(p, p.register("PIN_CNF[0]"), blocks).rm_reset == 0x00000002      # PS p.349 "Reset 0x00000002"
    assert locate_nrf(p, p.register("OUT"), blocks).rm_reset == 0x0


# ---- review fix: khoảng chỉ số của mẫu mảng trong tiêu đề TRM phải được áp dụng (không gán trang cho thanh ghi không tồn tại)
@pytest.mark.parametrize("spec,expected", [
    ("0-19, 21-23, 25-27 , 32-39", set(range(0, 20)) | {21, 22, 23, 25, 26, 27} | set(range(32, 40))),
    ("0-255", set(range(256))), ("8, 9", {8, 9}), ("0-19, 20 1, 21-23", set(range(0, 24))),
])
def test_array_index_ranges_are_parsed(spec, expected):
    from ingestion.register_pages import parse_index_ranges
    assert parse_index_ranges(spec) == expected


@pytest.mark.parametrize("reg,page", [("PIN19", 146), ("PIN39", 146), ("FUNC27_OUT_SEL_CFG", 147), ("FUNC33_OUT_SEL_CFG", 147),
                                      ("FUNC200_IN_SEL_CFG", 146)])
def test_esp32_array_register_inside_the_documented_range_keeps_its_pattern_page(esp, reg, page):
    dev, idx = esp
    p = dev.peripheral("GPIO")
    loc = locate_esp32(p, p.register(reg), idx)
    assert loc is not None and loc.page == page


@pytest.mark.parametrize("reg", ["PIN20", "PIN24", "PIN28", "PIN31", "FUNC20_OUT_SEL_CFG", "FUNC28_OUT_SEL_CFG", "FUNC34_OUT_SEL_CFG",
                                 "FUNC39_OUT_SEL_CFG"])
def test_esp32_array_register_outside_the_documented_range_gets_no_manual_page(esp, reg):
    """TRM: 'GPIO_PINn_REG (n: 0-19, 21-23, 25-27, 32-39)' — GPIO20/24/28-31 không tồn tại; '..._OUT_SEL_CFG (n: ..., 32-33)'."""
    dev, idx = esp
    p = dev.peripheral("GPIO")
    assert locate_esp32(p, p.register(reg), idx) is None
