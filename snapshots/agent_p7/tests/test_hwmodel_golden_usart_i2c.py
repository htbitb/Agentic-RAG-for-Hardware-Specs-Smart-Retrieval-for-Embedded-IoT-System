"""GOLDEN: USART (BRR/OVER8/nguồn clock) và I2C (TIMINGR) trên STM32G474 (brief P2 Bước 3, D19).

Kỳ vọng: ví dụ chính thức của RM0440 (p.1708 'How to derive USARTDIV…', Table 360 p.1657) hoặc phép tính tay ghi ở comment.
"""
import pytest

from hwmodel.sim import simulate_register_writes
from hwmodel_helpers import MOD, SET, W, errors, one_effect, warnings, without

CLK170 = "sysclk_170mhz_pll_hsi16_apb_div1"
USART1EN = SET("RCC_APB2ENR", 1 << 14)                    # bit 14 (RM p.313)
UE_TE_RE = 0b1101                                         # UE (bit 0) | RE (bit 2) | TE (bit 3), RM p.1743
OVER8 = 1 << 15                                           # CR1 bit 15 (RM p.1741)


def sim(ops, initial="reset"):
    return simulate_register_writes("stm32g474", ops, initial=initial)


def uart(res, instance="USART1"):
    return one_effect(res, kind="uart", instance=instance)


# ------------------------------------------------------------------ ví dụ trong RM (p.1708)
PCLK2_8MHZ = MOD("RCC_CFGR", 0b111 << 11, 0b100 << 11)     # reset: HSI16 16 MHz, APB2 /2 -> PCLK2 = 8 MHz (PPRE2 = 100, p.290)


def test_rm_example_1_9600_baud_at_8mhz_oversampling_16():
    # RM p.1708: usart_ker_ck_pres = 8 MHz, OVER8 = 0: USARTDIV = 8e6/9600 = 833.33 -> BRR = 833 = 0x0341
    res = sim([PCLK2_8MHZ, USART1EN, W("USART1_BRR", 0x0341), W("USART1_CR1", UE_TE_RE)])
    u = uart(res)
    assert u["kernel_clk_hz"] == 8_000_000 and u["over8"] == 0 and u["usartdiv"] == 833
    assert u["baud"] == pytest.approx(8e6 / 833, rel=1e-9)                # = 9603.8415...
    assert u["active"] is True and res["violations"] == []


def test_rm_example_1_9600_baud_at_8mhz_oversampling_8():
    # RM p.1708: OVER8 = 1: USARTDIV = 2*8e6/9600 = 1666.67 (0d1667 = 0x683) -> BRR[3:0] = 0x3 >> 1 = 0x1 -> BRR = 0x681
    # Phần cứng giải mã: USARTDIV = (0x68 << 4) | (0x1 << 1) = 0x682 = 1666 -> baud = 2*8e6/1666
    res = sim([PCLK2_8MHZ, USART1EN, W("USART1_BRR", 0x0681), W("USART1_CR1", OVER8 | UE_TE_RE)])
    u = uart(res)
    assert u["over8"] == 1 and u["usartdiv"] == 1666
    assert u["baud"] == pytest.approx(2 * 8e6 / 1666, rel=1e-9)


PLL48 = [MOD("FLASH_ACR", 0xF, 1),                                                    # 48 MHz, Range 1 normal: 1 WS (Table 9: <= 60 MHz)
         W("RCC_PLLCFGR", (1 << 24) | (0b01 << 25) | (24 << 8) | (0b0001 << 4) | 0b10),   # HSI16 / 2 = 8 MHz, x24 = 192 MHz, PLLR = /4 -> 48 MHz
         SET("RCC_CR", 1 << 24), MOD("RCC_CFGR", 0b11, 0b11)]


@pytest.mark.parametrize("brr,cr1,div", [(0x34, UE_TE_RE, 52), (0x64, OVER8 | UE_TE_RE, 104)])
def test_rm_example_2_921600_baud_at_48mhz(brr, cr1, div):
    # RM p.1708: OVER8=0: USARTDIV = 48e6/921600 = 52 -> BRR = 0x34; OVER8=1: USARTDIV = 104 -> BRR[3:0] = 0x8 >> 1 = 0x4 -> BRR = 0x64
    res = sim(PLL48 + [USART1EN, W("USART1_BRR", brr), W("USART1_CR1", cr1)])
    assert res["clocks"]["sysclk_hz"] == 48_000_000
    u = uart(res)
    assert u["usartdiv"] == div
    expected = (48e6 if cr1 & OVER8 == 0 else 96e6) / div                              # = 923076.92 cho cả hai
    assert u["baud"] == pytest.approx(expected, rel=1e-9)


# ------------------------------------------------------------------ 115200 baud ở 170 MHz — TÍNH TAY
def test_115200_baud_at_170mhz_oversampling_16():
    # USARTDIV = 170e6 / 115200 = 1475.694 -> làm tròn BRR = 1476 -> baud thực = 170e6 / 1476 = 115176.15
    # sai số = (115176.15 - 115200) / 115200 = -0.0207 %
    res = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", UE_TE_RE)], initial=CLK170)
    u = uart(res)
    assert u["baud"] == pytest.approx(115176.15, abs=0.01)
    assert abs(u["baud"] - 115200) / 115200 * 100 == pytest.approx(0.0207, abs=0.0005)


def test_115200_baud_at_170mhz_oversampling_8():
    # USARTDIV = 2*170e6/115200 = 2951.39 -> 2951 = 0xB87; BRR[15:4] = 0xB8, BRR[2:0] = 0x7 >> 1 = 3 -> BRR = 0xB83
    # Giải mã ngược: USARTDIV = (0xB8 << 4) | (3 << 1) = 2950 -> baud = 2*170e6 / 2950 = 115254.24
    res = sim([USART1EN, W("USART1_BRR", 0xB83), W("USART1_CR1", OVER8 | UE_TE_RE)], initial=CLK170)
    assert uart(res)["baud"] == pytest.approx(115254.24, abs=0.01)


def test_brr_with_bit3_set_in_oversampling_8_is_flagged():
    # RM p.1708: 'BRR[3] must be kept cleared' khi OVER8 = 1
    res = sim([USART1EN, W("USART1_BRR", 0xB8B), W("USART1_CR1", OVER8 | UE_TE_RE)], initial=CLK170)
    assert "SIM-USART-BRR" in errors(res)


def test_wrong_kernel_clock_assumption_changes_the_baud():
    # APB2 /2: PCLK2 = 85 MHz. Người tính BRR theo 170 MHz (1476) nhưng nguồn mặc định là PCLK2 (USART1SEL = 00) -> 85e6/1476 = 57588.08
    res = simulate_register_writes("stm32g474", [USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", UE_TE_RE)],
                                   initial="sysclk_170mhz_pll_hsi16_apb2_div2")
    assert uart(res)["baud"] == pytest.approx(85e6 / 1476, rel=1e-9)
    assert uart(res)["kernel_clk_hz"] == 85_000_000


@pytest.mark.parametrize("sel,kclk", [(0b00, 85_000_000), (0b01, 170_000_000), (0b10, 16_000_000)])
def test_usart1_kernel_clock_source_selection(sel, kclk):
    # RCC_CCIPR.USART1SEL [1:0]: 00 PCLK2, 01 SYSCLK, 10 HSI16 (RM p.324)
    res = simulate_register_writes("stm32g474", [MOD("RCC_CCIPR", 0b11, sel), USART1EN, W("USART1_BRR", 1000), W("USART1_CR1", UE_TE_RE)],
                                   initial="sysclk_170mhz_pll_hsi16_apb2_div2")
    assert uart(res)["kernel_clk_hz"] == kclk
    assert uart(res)["baud"] == pytest.approx(kclk / 1000, rel=1e-9)


def test_usart2_is_on_apb1():
    res = simulate_register_writes("stm32g474", [SET("RCC_APB1ENR1", 1 << 17), W("USART2_BRR", 1476), W("USART2_CR1", UE_TE_RE)],
                                   initial="sysclk_170mhz_pll_hsi16_apb1_div2")
    assert uart(res, "USART2")["kernel_clk_hz"] == 85_000_000                  # USART2EN = APB1ENR1 bit 17 (RM p.310)


def test_prescaler_register_divides_the_kernel_clock():
    # USART_PRESC [3:0] = 0001 -> /2 (RM p.1766 'PRESCALER'): 170e6 / 2 / 1476... -> USARTDIV tính trên 85 MHz
    res = sim([USART1EN, W("USART1_PRESC", 0b0001), W("USART1_BRR", 738), W("USART1_CR1", UE_TE_RE)], initial=CLK170)
    assert uart(res)["baud"] == pytest.approx(85e6 / 738, rel=1e-9)            # = 115176.15


# ------------------------------------------------------------------ lỗi
def test_uart_not_enabled_is_reported():
    res = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", 0b1100)], initial=CLK170)          # TE | RE nhưng UE = 0
    assert uart(res)["active"] is False and uart(res)["reason"] == "SIM-USART-UE"
    assert errors(res) == ["SIM-USART-UE"]


def test_uart_without_te_and_re_is_reported():
    res = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", 0b0001)], initial=CLK170)           # chỉ UE
    assert uart(res)["reason"] == "SIM-USART-TXRX"


def test_forgetting_the_usart_clock_is_caught():
    res = sim([W("USART1_BRR", 1476), W("USART1_CR1", UE_TE_RE)], initial=CLK170)
    assert [v["peripheral"] for v in res["violations"] if v["code"] == "SIM-CLK-GATE"] == ["USART1"]
    assert uart(res)["active"] is False and uart(res)["reason"] == "SIM-CLK-GATE"


def test_brr_below_16_is_invalid():
    # RM p.1708: 'USARTDIV must be greater than or equal to 16'
    res = sim([USART1EN, W("USART1_BRR", 8), W("USART1_CR1", UE_TE_RE)], initial=CLK170)
    assert "SIM-USART-BRR" in errors(res) and uart(res)["reason"] == "SIM-USART-BRR"


def test_writing_brr_while_the_usart_is_enabled_is_an_error_and_the_write_is_ignored():
    # RM p.1755: 'This register can only be written when the USART is disabled (UE = 0)'
    res = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", UE_TE_RE), W("USART1_BRR", 738)], initial=CLK170)
    bad = [v for v in res["violations"] if v["code"] == "SIM-WRITE-LOCKED"]
    assert len(bad) == 1 and bad[0]["severity"] == "error" and bad[0]["at_op"] == 3 and bad[0]["reg"] == "USART1_BRR"
    assert uart(res)["brr"] == 1476 and uart(res)["baud"] == pytest.approx(170e6 / 1476)


@pytest.mark.parametrize("field,mask", [("OVER8", OVER8), ("M0", 1 << 12), ("M1", 1 << 28), ("PS", 1 << 9)])
def test_cr1_word_format_bits_are_locked_while_enabled(field, mask):
    # RM p.1741–1742: OVER8, M1, M0, PS 'can only be written when the USART is disabled (UE = 0)'
    res = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", UE_TE_RE), SET("USART1_CR1", mask)], initial=CLK170)
    assert [v["code"] for v in res["violations"] if v["severity"] == "error"] == ["SIM-WRITE-LOCKED"]
    assert uart(res)["over8"] == 0 and uart(res)["data_bits"] == 8


def test_prescaler_is_write_locked_while_enabled():
    # RM p.1772: USART_PRESC 'can only be written when the USART is disabled (UE = 0)'
    res = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", UE_TE_RE), W("USART1_PRESC", 1)], initial=CLK170)
    assert [v["code"] for v in res["violations"] if v["severity"] == "error"] == ["SIM-WRITE-LOCKED"] and uart(res)["presc_div"] == 1


@pytest.mark.parametrize("bit,name", [(15, "SWAP"), (16, "RXINV"), (17, "TXINV"), (14, "LINEN"), (11, "CLKEN")])
def test_cr2_features_that_are_not_modelled_are_reported_not_ignored(bit, name):
    # RM p.1749: SWAP exchanges the TX/RX pin functions, TXINV/RXINV invert the levels — the pin check would be wrong if silently ignored
    res = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR2", 1 << bit), W("USART1_CR1", UE_TE_RE)], initial=CLK170)
    assert any(name in u for u in res["unmodeled"]) and uart(res)["modeled"] is False


def test_te_and_re_may_be_changed_while_enabled_and_a_single_cr1_write_may_set_ue_with_the_format():
    res = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", OVER8 | 0b0001), SET("USART1_CR1", 0b1100)], initial=CLK170)
    assert res["violations"] == [] and uart(res)["over8"] == 1


def test_cr2_stop_bits_are_locked_while_enabled_and_reported():
    # RM p.1749: STOP[13:12] 00 = 1 stop bit, 10 = 2 stop bits; 'can only be written when the USART is disabled'
    ok = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR2", 0b10 << 12), W("USART1_CR1", UE_TE_RE)], initial=CLK170)
    assert uart(ok)["stop_bits"] == 2 and ok["violations"] == []
    late = sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", UE_TE_RE), W("USART1_CR2", 0b10 << 12)], initial=CLK170)
    assert uart(late)["stop_bits"] == 1 and [v["code"] for v in late["violations"]] == ["SIM-WRITE-LOCKED"]


@pytest.mark.parametrize("cr1,bits,parity", [
    (UE_TE_RE, 8, "none"), (UE_TE_RE | (1 << 12), 9, "none"), (UE_TE_RE | (1 << 28), 7, "none"),
    (UE_TE_RE | (1 << 10), 7, "even"), (UE_TE_RE | (1 << 10) | (1 << 9), 7, "odd"), (UE_TE_RE | (1 << 12) | (1 << 10), 8, "even"),
])
def test_frame_format_is_reported(cr1, bits, parity):
    # M[1:0]: 00 = 8 data bits, 01 = 9, 10 = 7 (p.1741); with PCE the parity bit takes the MSB position of the word (p.1742)
    u = uart(sim([USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", cr1)], initial=CLK170))
    assert (u["data_bits"], u["parity"], u["stop_bits"]) == (bits, parity, 1)


def test_usart_pins_are_reported_when_routed():
    # PA9 AF7 = USART1_TX, PA10 AF7 = USART1_RX (DS12288 Table 13 p.73)
    ops = [SET("RCC_AHB2ENR", 1), MOD("GPIOA_MODER", 0xF << 18, 0b1010 << 18), MOD("GPIOA_AFRH", 0xFF << 4, 0x77 << 4),
           USART1EN, W("USART1_BRR", 1476), W("USART1_CR1", UE_TE_RE)]
    u = uart(sim(ops, initial=CLK170))
    assert u["tx_pin"] == "PA9" and u["rx_pin"] == "PA10"
    assert uart(sim(ops[3:], initial=CLK170))["tx_pin"] is None


# ------------------------------------------------------------------ I2C: TIMINGR (RM Table 360 p.1657, fI2CCLK = 16 MHz)
I2C1EN = SET("RCC_APB1ENR1", 1 << 21)                     # bit 21 (RM p.310)


def timingr(presc, scll, sclh, sdadel, scldel):
    return (presc << 28) | (scldel << 20) | (sdadel << 16) | (sclh << 8) | scll              # RM p.1672


def i2c(res, instance="I2C1"):
    return one_effect(res, kind="i2c", instance=instance)


@pytest.mark.parametrize("name,regs,scll_ns,sclh_ns,scl_hz", [
    # Sm 100 kHz: PRESC 0x3, SCLL 0x13, SCLH 0xF, SDADEL 0x2, SCLDEL 0x4: tSCLL = 20 x 250 ns = 5.0 µs, tSCLH = 16 x 250 ns = 4.0 µs
    #   tSCL = 5.0 + 4.0 + tSYNC(min 4 x tI2CCLK = 250 ns) = 9.25 µs -> 108108 Hz (RM in ~10 µs với tSYNC = 1000 ns)
    ("Sm-100k", (0x3, 0x13, 0xF, 0x2, 0x4), 5000.0, 4000.0, 1 / 9.25e-6),
    # Fm 400 kHz: PRESC 0x1, SCLL 0x9, SCLH 0x3, SDADEL 0x2, SCLDEL 0x3: 10 x 125 ns = 1250 ns; 4 x 125 ns = 500 ns; tSCL = 1750 + 250 = 2 µs
    ("Fm-400k", (0x1, 0x9, 0x3, 0x2, 0x3), 1250.0, 500.0, 1 / 2.0e-6),
    # Fm+ 1 MHz: PRESC 0x0, SCLL 0x4, SCLH 0x2, SDADEL 0x0, SCLDEL 0x2: 5 x 62.5 = 312.5 ns; 3 x 62.5 = 187.5 ns; tSCL = 500 + 250 = 750 ns
    ("Fm+-1M", (0x0, 0x4, 0x2, 0x0, 0x2), 312.5, 187.5, 1 / 750e-9),
])
def test_rm_table_360_timings_at_16mhz(name, regs, scll_ns, sclh_ns, scl_hz):
    res = sim([I2C1EN, W("I2C1_TIMINGR", timingr(*regs)), W("I2C1_CR1", 1)])
    e = i2c(res)
    assert e["i2cclk_hz"] == 16_000_000
    assert e["t_scll_ns"] == pytest.approx(scll_ns, rel=1e-9) and e["t_sclh_ns"] == pytest.approx(sclh_ns, rel=1e-9)
    assert e["scl_hz"] == pytest.approx(scl_hz, rel=1e-9), name
    assert e["active"] is True and res["violations"] == []


def test_timingr_encoding_matches_the_manual_example():
    assert timingr(0x3, 0x13, 0xF, 0x2, 0x4) == 0x30420F13


def test_the_effect_states_its_approximation():
    e = i2c(sim([I2C1EN, W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", 1)]))
    assert e["approximation"] == "tSYNC1+tSYNC2 = 4 x tI2CCLK (RM minimum); rise/fall time and analog filter delay ignored"
    assert e["scl_hz_upper_bound"] == pytest.approx(1 / 9e-6, rel=1e-9)         # không có tSYNC


def test_digital_noise_filter_lengthens_the_clock_period():
    # RM p.1645: tSYNC1 và tSYNC2 mỗi cái cộng DNF x tI2CCLK. DNF = 2 (CR1[11:8]): thêm 2 x 2 x 62.5 ns = 250 ns => tSCL = 9.5 µs
    e = i2c(sim([I2C1EN, W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", (2 << 8) | 1)]))
    assert e["scl_hz"] == pytest.approx(1 / 9.5e-6, rel=1e-9)


@pytest.mark.parametrize("sel,clk", [(0b00, 85_000_000), (0b01, 170_000_000), (0b10, 16_000_000)])
def test_i2c1_kernel_clock_selection(sel, clk):
    # RCC_CCIPR.I2C1SEL [13:12]: 00 PCLK1, 01 SYSCLK, 10 HSI16 (RM p.324)
    res = simulate_register_writes("stm32g474", [MOD("RCC_CCIPR", 0b11 << 12, sel << 12), I2C1EN, W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", 1)],
                                   initial="sysclk_170mhz_pll_hsi16_apb1_div2")
    assert i2c(res)["i2cclk_hz"] == clk


def test_bus_timing_estimates_are_reported():
    # tLOW ~ tSCLL + tSYNC1, tHIGH ~ tSCLH + tSYNC2 with tSYNC1 = tSYNC2 = 2 x tI2CCLK (half of the RM minimum 4 x tI2CCLK) + DNF x tI2CCLK each
    # RM Table 360 Sm 100 kHz @ 16 MHz: tSCLL = 5000 ns, tSCLH = 4000 ns, tI2CCLK = 62.5 ns
    e = i2c(sim([I2C1EN, W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", 1)]))
    assert e["t_low_ns"] == pytest.approx(5000 + 125) and e["t_high_ns"] == pytest.approx(4000 + 125)
    d = i2c(sim([I2C1EN, W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", (2 << 8) | 1)]))            # DNF = 2 => +2 x 62.5 ns on each side
    assert d["t_low_ns"] == pytest.approx(5000 + 250) and d["t_high_ns"] == pytest.approx(4000 + 250)


def test_timingr_is_locked_while_the_peripheral_is_enabled():
    # RM p.1681: 'This register must be configured when the I2C peripheral is disabled (PE = 0)'
    res = sim([I2C1EN, W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", 1), W("I2C1_TIMINGR", 0x10320309)])
    assert [v["code"] for v in res["violations"] if v["severity"] == "error"] == ["SIM-WRITE-LOCKED"]
    assert i2c(res)["timingr"] == 0x30420F13


def test_the_slow_bound_uses_tsync_up_to_the_largest_value_in_the_manual_examples():
    # RM Table 359/360 notes: examples with tSYNC1 + tSYNC2 up to 1000 ns. 100 kHz example: 1 / (9.0 us + 1.0 us) = 100 kHz exactly
    e = i2c(sim([I2C1EN, W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", 1)]))
    assert e["scl_hz_slow"] == pytest.approx(100_000.0, rel=1e-9) and e["scl_hz"] == pytest.approx(1 / 9.25e-6, rel=1e-9)
    f = i2c(sim([I2C1EN, W("I2C1_TIMINGR", 0x10320309), W("I2C1_CR1", 1)]))             # Fm example: 1 / (1.75 us + 1.0 us) = 363.6 kHz
    assert f["scl_hz_slow"] == pytest.approx(1 / 2.75e-6, rel=1e-9)


def test_i2c_not_enabled_is_reported():
    res = sim([I2C1EN, W("I2C1_TIMINGR", 0x30420F13)])
    assert i2c(res)["active"] is False and i2c(res)["reason"] == "SIM-I2C-PE"
    assert errors(res) == ["SIM-I2C-PE"]


def test_forgetting_the_i2c_clock_is_caught():
    res = sim([W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", 1)])
    assert i2c(res)["reason"] == "SIM-CLK-GATE" and "SIM-CLK-GATE" in errors(res)


def test_i2c_timingr_never_programmed_is_reported():
    res = sim([I2C1EN, W("I2C1_CR1", 1)])
    assert i2c(res)["reason"] == "SIM-I2C-TIMING"


def test_i2c_pins_are_reported_when_routed():
    # PB8 AF4 = I2C1_SCL, PB9 AF4 = I2C1_SDA (DS12288 Table 13 p.73)
    ops = [SET("RCC_AHB2ENR", 1 << 1), MOD("GPIOB_MODER", 0xF << 16, 0b1010 << 16), MOD("GPIOB_AFRH", 0xFF, 0x44),
           MOD("GPIOB_OTYPER", 0b11 << 8, 0b11 << 8), I2C1EN, W("I2C1_TIMINGR", 0x30420F13), W("I2C1_CR1", 1)]
    e = i2c(sim(ops))
    assert e["scl_pin"] == "PB8" and e["sda_pin"] == "PB9"
    assert e["open_drain"] == {"PB8": True, "PB9": True}
    assert i2c(sim(without(ops, 3)))["open_drain"] == {"PB8": False, "PB9": False}
