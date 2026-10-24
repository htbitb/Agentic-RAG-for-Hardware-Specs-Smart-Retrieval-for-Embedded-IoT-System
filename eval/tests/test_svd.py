from pathlib import Path

import pytest

from eval.generators.svd import parse_svd

FIX = Path(__file__).parent / "fixtures" / "mini.svd"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dev():
    return parse_svd(FIX)


def reg(dev, periph, name):
    return next(r for p in dev.peripherals if p.name == periph for r in p.registers if r.name == name)


def test_absolute_address_and_offset(dev):
    r = reg(dev, "PA", "CTRL")
    assert (r.offset, r.address) == (0x0, 0x40000000)
    assert reg(dev, "PA", "STAT").address == 0x40000004


def test_inherits_device_defaults_and_register_overrides(dev):
    ctrl, stat = reg(dev, "PA", "CTRL"), reg(dev, "PA", "STAT")
    assert (ctrl.size, ctrl.access, ctrl.reset_value) == (32, "rw", 0x1234)
    assert (stat.size, stat.access, stat.reset_value) == (16, "ro", 0x0)


def test_field_bit_positions_from_offset_width_range_and_lsb_msb(dev):
    f = {x.name: (x.lsb, x.msb) for x in reg(dev, "PA", "CTRL").fields}
    assert f == {"EN": (0, 0), "MODE": (4, 6), "DIV": (8, 15)}
    assert {x.name: x.access for x in reg(dev, "PA", "CTRL").fields}["MODE"] == "ro"


def test_register_dim_array_expansion(dev):
    names = {r.name: r.address for p in dev.peripherals if p.name == "PA" for r in p.registers if r.name.startswith("DATA")}
    assert names == {"DATA0": 0x40000010, "DATA1": 0x40000014, "DATA2": 0x40000018}


def test_cluster_dim_expansion_prefixes_names(dev):
    cfg = {r.name: r.address for p in dev.peripherals if p.name == "PA" for r in p.registers if r.name.endswith("CFG")}
    assert cfg == {"CH0_CFG": 0x40000108, "CH1_CFG": 0x40000208}
    assert reg(dev, "PA", "CH0_CFG").reset_value == 0xFF


def test_derived_peripheral_gets_own_base_but_same_registers(dev):
    r = reg(dev, "PB", "CTRL")
    assert r.address == 0x40001000 and r.reset_value == 0x1234
    assert reg(dev, "PB", "STAT").address == 0x40001004


def test_derived_peripheral_register_override_wins(dev):
    assert reg(dev, "PC", "CTRL").reset_value == 0xABCD
    assert reg(dev, "PC", "STAT").address == 0x40002004          # phần còn lại vẫn kế thừa


def test_peripheral_dim_expansion(dev):
    assert reg(dev, "UART0", "TX").address == 0x50000000 and reg(dev, "UART1", "TX").address == 0x50001000


def test_real_stm32g474_svd_known_values():
    d = parse_svd(ROOT / "corpus" / "svd" / "STM32G474xx.svd")
    moder = reg(d, "GPIOA", "MODER")
    assert moder.address == 0x48000000 and moder.reset_value == 0xABFFFFFF and moder.size == 32
    assert reg(d, "GPIOB", "MODER").address == 0x48000400
    assert reg(d, "TIM1", "CR1").address == 0x40012C00
    assert {f.name: (f.lsb, f.msb) for f in reg(d, "TIM1", "CR1").fields}["CEN"] == (0, 0)


def test_real_esp32_and_nrf_svd_parse():
    esp = parse_svd(ROOT / "corpus" / "svd" / "esp32.svd")
    assert any(r.address == 0x3FF44004 for p in esp.peripherals for r in p.registers)      # GPIO_OUT_REG
    nrf = parse_svd(ROOT / "corpus" / "svd" / "nrf52840.svd")
    assert sum(len(p.registers) for p in nrf.peripherals) > 500
