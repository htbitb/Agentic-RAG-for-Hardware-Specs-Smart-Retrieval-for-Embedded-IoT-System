"""Golden test trên `hw_specs.sqlite` dựng từ SVD thật: mỗi chip >= 10 thanh ghi đối chiếu TAY với text trang PDF
(địa chỉ = base + offset in trên trang; reset value; bit field; trang mô tả). Nguồn đọc tay ghi cạnh từng dòng."""
import pytest

from ingestion import hwdb, pdfdocs, svd_ingest

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("hw") / "hw_specs.sqlite"
    assert svd_ingest.main(["--db", str(path)]) == 0
    return hwdb.connect(path)


def reg(db, chip, per, name):
    r = db.execute("select * from registers where chip=? and peripheral=? and name=?", (chip, per, name)).fetchone()
    assert r is not None, f"{chip} {per}.{name} missing"
    return r


def field(db, r, name):
    f = db.execute("select * from fields where register_id=? and name=?", (r["id"], name)).fetchone()
    assert f is not None, f"field {name} of {r['name']} missing"
    return f["bit_offset"], f["bit_width"]


# (peripheral, register, address, reset, {field: (bit_offset, width)}, page)  — RM0440 (STM32G474)
ST = [
    ("RTC", "WUTR", 0x40002814, 0x0000FFFF, {"WUT": (0, 16)}, 1593),            # p.1593: "Address offset: 0x14", "reset value: 0x0000 FFFF"
    ("TIM1", "CR1", 0x40012C00, 0x0, {"ARPE": (7, 1), "CEN": (0, 1)}, 1235),     # p.1235 "Bit 7 ARPE", p.1236 "Bit 0 CEN"
    ("RCC", "RCC_AHB2ENR", 0x4002104C, 0x0, {"GPIOAEN": (0, 1)}, 306),            # p.306 offset 0x4C; "Bit 0 GPIOAEN" (p.308)
    ("GPIOA", "MODER", 0x48000000, 0xABFFFFFF, {}, 355),                           # p.355 "reset value: 0xABFF FFFF (for port A)"
    ("GPIOB", "MODER", 0x48000400, 0xFFFFFEBF, {}, 355),                           # "0xFFFF FEBF (for port B)"
    ("GPIOC", "MODER", 0x48000800, 0xFFFFFFFF, {}, 355),                           # "0xFFFF FFFF (for ports C..G)"
    ("GPIOA", "AFRH", 0x48000024, 0x0, {"AFRH8": (0, 4)}, 360),                     # p.360 offset 0x24; RM gọi AFSEL8[3:0] (cuối dãy), SVD gọi AFRH8
    ("USART1", "CR1", 0x40013800, 0x0, {"UE": (0, 1)}, 1740),                      # p.1740 offset 0x00; "Bit 0 UE" (p.1743)
    ("FLASH", "ACR", 0x40022000, 0x00000600, {"LATENCY": (0, 4)}, 130),            # p.130 offset 0x00; "Bits 3:0 LATENCY[3:0]" (p.131). SVD reset 0x600 ≠ RM 0x0004 0601 (xem test dưới)
    ("ADC1", "CR", 0x50000008, 0x20000000, {"ADEN": (0, 1)}, 681),                 # p.681 offset 0x08, reset 0x2000 0000; "Bit 0 ADEN" (p.683)
    ("I2C1", "TIMINGR", 0x40005410, 0x0, {"PRESC": (28, 4)}, 1681),                # p.1681 offset 0x10; "Bits 31:28 PRESC[3:0]"
    ("FDCAN1", "CCCR", 0x40006418, 0x1, {"INIT": (0, 1)}, 1987),                   # p.1987 offset 0x0018, reset 0x0000 0001; "Bit 0 INIT" (p.1988)
    ("PWR", "PWR_CR1", 0x40007000, 0x200, {"VOS": (9, 2), "LPR": (14, 1)}, 253),   # p.253 offset 0x00, reset 0x0000 0200; "Bits 10:9 VOS", "Bit 14 LPR"
    ("RCC", "RCC_CFGR", 0x40021008, 0x5, {}, 289),                                 # p.289 offset 0x08, reset 0x0000 0005
    ("DMA1", "CCR2", 0x4002001C, 0x0, {}, 411),                                    # p.411 offset 0x08 + 0x14*(x-1), x=2 -> 0x1C
]


@pytest.mark.parametrize("per,name,addr,reset,fields,page", ST)
def test_stm32g474_golden(db, per, name, addr, reset, fields, page):
    r = reg(db, "stm32g474", per, name)
    assert (r["address"], r["reset_value"], r["doc"], r["page"]) == (addr, reset, "STM32G474_RM0440", page)
    assert r["svd_only"] == 0
    for f, pos in fields.items():
        assert field(db, r, f) == pos


def test_stm32g474_flash_acr_reset_differs_between_svd_and_manual(db):
    """SVD ST: 0x00000600; RM0440 p.130: 'Reset value: 0x0004 0601'. DB giữ giá trị SVD, lưu giá trị RM và ghi bất thường."""
    r = reg(db, "stm32g474", "FLASH", "ACR")
    assert (r["reset_value"], r["rm_reset_value"]) == (0x600, 0x40601)
    kinds = [a["kind"] for a in db.execute("select kind from data_anomalies where chip='stm32g474' and ref='FLASH.ACR'")]
    assert "reset_mismatch" in kinds


def test_stm32g474_tim4_dtr2_is_svd_only(db):
    """Lỗi SVD ST: TIM4 (derivedFrom TIM2) có DTR2 @0x54 nhưng RM0440 không mô tả (TIM2/3/4/5 map: 0x44-0x54 reserved)."""
    r = reg(db, "stm32g474", "TIM4", "DTR2")
    assert (r["svd_only"], r["page"], r["doc"], r["address"]) == (1, None, "STM32G474_SVD", 0x40000854)


def test_stm32g474_usart1_cr1_keeps_the_alternate_description_page(db):
    import json
    assert json.loads(reg(db, "stm32g474", "USART1", "CR1")["alt_pages"]) == [1743]


# --- nRF52840 (PS v1.11)
NRF = [
    ("P0", "OUT", 0x50000504, 0x0, {}, 326),                                       # p.326 "6.9.2.1 OUT Address offset: 0x504"
    ("P1", "OUT", 0x50000804, 0x0, {}, 326),                                       # P1 base 0x50000300 (derivedFrom P0) + 0x504
    ("P0", "PIN_CNF[0]", 0x50000700, 0x2, {"DIR": (0, 1), "INPUT": (1, 1), "PULL": (2, 2), "DRIVE": (8, 3), "SENSE": (16, 2)}, 349),
    ("TWIM0", "PSEL.SCL", 0x40003508, 0xFFFFFFFF, {"PIN": (0, 5), "PORT": (5, 1), "CONNECT": (31, 1)}, 798),
    ("TWIM0", "INTENCLR", 0x40003308, 0x0, {}, 796),
    ("TIMER0", "PRESCALER", 0x40008510, 0x4, {}, 783),
    ("TIMER0", "CC[0]", 0x40008540, 0x0, {}, 784),
    ("UARTE0", "BAUDRATE", 0x40002524, 0x04000000, {}, 846),
    ("FICR", "DEVICEADDR[0]", 0x100000A4, 0xFFFFFFFF, {}, 36),
    ("RTC0", "CC[0]", 0x4000B540, 0x0, {}, 674),
    ("SPIM0", "FREQUENCY", 0x40003524, 0x04000000, {}, 734),
]


@pytest.mark.parametrize("per,name,addr,reset,fields,page", NRF)
def test_nrf52840_golden(db, per, name, addr, reset, fields, page):
    r = reg(db, "nrf52840", per, name)
    assert (r["address"], r["reset_value"], r["doc"], r["page"]) == (addr, reset, "nRF52840_PS", page)
    for f, pos in fields.items():
        assert field(db, r, f) == pos


def test_nrf52840_pull_enum_matches_the_manual_table(db):
    """PS p.349: PULL: Disabled 0, Pulldown 1, Pullup 3."""
    rows = db.execute("""select e.name, e.value from enum_values e join fields f on f.id=e.field_id join registers r on r.id=f.register_id
                         where r.chip='nrf52840' and r.peripheral='P0' and r.name='PIN_CNF[0]' and f.name='PULL' order by e.value""").fetchall()
    assert [(x["name"], x["value"]) for x in rows] == [("Disabled", 0), ("Pulldown", 1), ("Pullup", 3)]


# --- ESP32 (TRM v5.8); địa chỉ trong SVD ở cửa sổ DPORT, `address_alias` ở cửa sổ AHB (TRM p.73)
ESP = [
    ("UART0", "CONF0", 0x3FF40020, 0x60000020, 0x0800001C, {"BIT_NUM": (2, 2), "STOP_BIT_NUM": (4, 2)}, 332),
    ("UART1", "CONF0", 0x3FF50020, 0x60010020, 0x0800001C, {"BIT_NUM": (2, 2)}, 332),                    # cùng mô tả UART_CONF0_REG
    ("GPIO", "ENABLE", 0x3FF44020, 0x60004020, None, {}, 139),                                            # reset 'x' trong TRM (không xác định)
    ("I2C0", "CTR", 0x3FF53004, 0x60013004, 0x3, {"MS_MODE": (4, 1), "TRANS_START": (5, 1), "RX_LSB_FIRST": (7, 1)}, 403),
    ("I2C1", "CTR", 0x3FF67004, 0x60027004, 0x3, {}, 403),
]


@pytest.mark.parametrize("per,name,addr,alias,reset,fields,page", ESP)
def test_esp32_golden(db, per, name, addr, alias, reset, fields, page):
    r = reg(db, "esp32", per, name)
    assert (r["address"], r["address_alias"], r["doc"], r["page"]) == (addr, alias, "ESP32_TRM", page)
    if reset is not None:
        assert r["reset_value"] == reset
    for f, pos in fields.items():
        assert field(db, r, f) == pos


def test_esp32_summary_only_registers_cite_the_summary_page(db):
    r = reg(db, "esp32", "RTC_I2C", "CTRL")                      # TRM p.45 summary: RTC_I2C_CTRL_REG 0x3FF48C04
    assert (r["address"], r["doc"]) == (0x3FF48C04, "ESP32_TRM") and r["page"] is not None


def test_esp32_ahb_aliased_peripheral_keeps_both_addresses(db):
    r = reg(db, "esp32", "RNG", "DATA")                          # SVD dùng cửa sổ AHB; TRM p.73 in RNG ở 0x3FF7_5000
    assert (r["address"], r["address_alias"]) == (0x60035144, 0x3FF75144)


def test_esp32_registers_missing_from_the_trm_are_svd_only(db):
    r = reg(db, "esp32", "GPIO", "BT_SELECT")
    assert (r["svd_only"], r["page"], r["doc"]) == (1, None, "ESP32_SVD")


# --- đếm toàn bộ khớp parser
def test_db_counts_match_the_parser(db):
    from ingestion.svd_ingest import SVD_CHIPS, parse_svd
    for chip, doc in SVD_CHIPS.items():
        dev = parse_svd(pdfdocs.CORPUS / pdfdocs.manifest_entry(doc)["file"])
        regs = sum(len(p.registers) for p in dev.peripherals)
        flds = sum(len(r.fields) for p in dev.peripherals for r in p.registers)
        assert db.execute("select count(*) from peripherals where chip=?", (chip,)).fetchone()[0] == len(dev.peripherals)
        assert db.execute("select count(*) from registers where chip=?", (chip,)).fetchone()[0] == regs
        assert db.execute("select count(*) from fields where chip=?", (chip,)).fetchone()[0] == flds
