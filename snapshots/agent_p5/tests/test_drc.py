"""DRC (W2): 8 luật xác định trên trạng thái Board State. Mỗi luật có ≥ 1 ca vi phạm và ≥ 1 ca hợp lệ SÁT BIÊN.

D19: giá trị kỳ vọng lấy từ datasheet/RM (số trang ở comment), KHÔNG sinh bằng chính code DRC. Dữ liệu chân/giới hạn đọc từ hw_specs.sqlite thật (P1)."""
import pytest

from hwmodel import board_state as B
from hwmodel import drc
from mcp_servers.hw_queries import HwStore


@pytest.fixture(scope="module")
def hw():
    return HwStore()


@pytest.fixture(scope="module")
def cat(hw):
    return drc.Catalog(hw)


def state(*pairs, project="t"):
    """Dựng trạng thái từ cặp (loại sự kiện, payload) — không qua server nên có thể tạo trạng thái 'xấu' để DRC bắt."""
    return B.fold(project, [{"version": i + 1, "ts": "t", "actor": "test", "type": t, "payload": p} for i, (t, p) in enumerate(pairs)])


def target(chip="stm32g474", package="LQFP64", vdd=3.3):
    return ("target_set", {"chip": chip, "package": package, "vdd": vdd})


def alloc(pin, signal, owner, af=None, peripheral="auto", mode=None, shared=False, chip="stm32g474"):
    if peripheral == "auto":
        peripheral = None if signal.startswith("GPIO") else signal.split("_")[0]
    return ("pin_allocated", {"pin": pin, "chip": chip, "signal": signal, "af": af, "peripheral": peripheral, "owner": owner, "mode": mode, "shared": shared})


def req(**kw):
    return ("requirements_set", {"requirements": [kw]})


def clock(cfg):
    ev = drc.evaluate_clock_config(cfg)
    return ("clock_configured", {"cfg": ev["cfg"], "derived": ev["derived"], "violations": ev["violations"]})


def codes(result, rule=None, severity=None):
    return sorted(v["code"] for v in result["violations"] if (rule is None or v["rule"] == rule) and (severity is None or v["severity"] == severity))


def run(st, hw, **kw):
    return drc.run_drc(st, hw, **kw)


# ============================================================================================ catalogue
def test_rules_table_matches_the_plan():
    assert list(drc.RULES) == ["DRC-PIN-01", "DRC-PIN-02", "DRC-PIN-03", "DRC-CLK-01", "DRC-CLK-02", "DRC-ELEC-01", "DRC-PWR-01", "DRC-REQ-01"]


def test_catalog_alternatives_for_i2c3_scl_follow_the_af_table(cat):
    """DS12288 Table 13 (p.73–79): I2C3_SCL = PA8 (AF2), PC8 (AF8), PF3 (AF4), PG7 (AF4). LQFP64 chỉ có PA8 (chân 42) và PC8 (chân 40) (Table 12)."""
    alts = cat.alternatives("stm32g474", "I2C3_SCL", package="LQFP64", taken={})
    assert [(a["pin"], a["af"]) for a in alts] == [("PA8", 2), ("PC8", 8)]
    assert cat.alternatives("stm32g474", "I2C3_SCL", package="LQFP64", taken={"PA8": {}}) == [a for a in alts if a["pin"] != "PA8"]
    assert [a["pin"] for a in cat.alternatives("stm32g474", "I2C3_SCL", package="LQFP128", taken={})] == ["PA8", "PC8", "PF3", "PG7"]
    assert [a["pin"] for a in cat.alternatives("stm32g474", "I2C3_SCL", package=None, taken={})] == ["PA8", "PC8", "PF3", "PG7"]


def test_signal_direction_heuristics():
    d = drc.signal_direction
    assert d("USART1_TX") == "out" and d("SPI1_MOSI") == "out" and d("USART1_RX") == "in" and d("SPI1_MISO") == "in"
    assert d("I2C3_SCL") == "inout" and d("I2C3_SDA") == "inout" and d("TIM1_CH1") is None and d("ADC1_IN1") == "in"
    assert d("GPIO_OUT") == "out" and d("GPIO_IN") == "in"
    assert d("USART1_RX", mode="AF_PP") == "out"            # mode tường minh thắng tên tín hiệu
    assert d("TIM1_CH1", mode="input") == "in"


# ============================================================================================ DRC-PIN-01
def test_pin_01_violation_requirement_claims_a_pin_owned_by_another(hw):
    """Kịch bản D2: PA8 đã cấp cho PWM (R1); yêu cầu I2C3 của R2 đặt SCL ở PA8 (DS12288 Table 13 p.73: PA8 AF2 = I2C3_SCL)."""
    st = state(target(), alloc("PA8", "TIM1_CH1", "R1-motor-pwm", af=6, peripheral="TIM1", mode="AF_PP"),
               req(id="R1", type="pwm", pin="PA8", signal="TIM1_CH1", status="satisfied", evidence="sim#1"),
               req(id="R2", type="i2c", instance="I2C3", scl_pin="PA8", status="satisfied", evidence="x"))
    r = run(st, hw)
    [v] = [v for v in r["violations"] if v["rule"] == "DRC-PIN-01"]
    assert v["code"] == "PIN_CONFLICT:PA8" and v["severity"] == "error" and not r["ok"]
    assert {c["claimant"] for c in v["claims"]} == {"R1", "R2"}


def test_pin_01_valid_when_the_second_requirement_uses_the_alternative_pin(hw):
    st = state(target(), alloc("PA8", "TIM1_CH1", "R1-motor-pwm", af=6, peripheral="TIM1", mode="AF_PP"),
               req(id="R1", type="pwm", pin="PA8", signal="TIM1_CH1", status="satisfied", evidence="x"),
               req(id="R2", type="i2c", instance="I2C3", scl_pin="PC8", status="satisfied", evidence="x"))
    assert codes(run(st, hw), "DRC-PIN-01") == []


def test_pin_01_same_owner_claiming_its_own_pin_is_not_a_conflict(hw):
    st = state(target(), alloc("PA8", "TIM1_CH1", "R1-motor-pwm", af=6, peripheral="TIM1"),
               req(id="R1", type="pwm", pin="PA8", signal="TIM1_CH1", status="satisfied", evidence="x"))
    assert codes(run(st, hw), "DRC-PIN-01") == []


def test_pin_01_declared_shared_i2c_bus_is_allowed(hw):
    st = state(target(), alloc("PB7", "I2C1_SDA", "bus-i2c1", af=4, peripheral="I2C1", shared=True),
               alloc("PB7", "I2C1_SDA", "U3-sensor", af=4, peripheral="I2C1", shared=True))
    assert codes(run(st, hw), "DRC-PIN-01") == []
    st = state(target(), req(id="R1", type="i2c", instance="I2C1", sda_pin="PB7", shared=True, status="satisfied", evidence="x"),
               req(id="R2", type="i2c", instance="I2C1", sda_pin="PB7", shared=True, status="satisfied", evidence="x"))
    assert codes(run(st, hw), "DRC-PIN-01") == []


def test_pin_01_sharing_a_non_bus_signal_is_a_conflict(hw):
    st = state(target(), alloc("PA8", "TIM1_CH1", "R1", af=6, peripheral="TIM1", shared=True),
               alloc("PA8", "TIM1_CH1", "R2", af=6, peripheral="TIM1", shared=True))
    assert codes(run(st, hw), "DRC-PIN-01") == ["PIN_CONFLICT:PA8"]


def test_pin_01_two_requirements_on_one_pin_without_any_allocation(hw):
    st = state(target(), req(id="R1", type="pwm", pin="PA8", signal="TIM1_CH1", status="pending"), req(id="R2", type="uart", instance="USART1", tx_pin="PA8", status="pending"))
    assert codes(run(st, hw), "DRC-PIN-01") == ["PIN_CONFLICT:PA8"]


# ============================================================================================ DRC-PIN-02
def test_pin_02_signal_not_in_the_af_table_of_the_pin(hw):
    """DS12288 Table 13 p.73: PA9 carries I2C3_SMBA (AF2), I2C2_SCL (AF4), TIM1_CH2 (AF6), USART1_TX (AF7)... but NOT I2C3_SCL."""
    st = state(target(), alloc("PA9", "I2C3_SCL", "R2", peripheral="I2C3"))
    r = run(st, hw)
    [v] = [v for v in r["violations"] if v["rule"] == "DRC-PIN-02"]
    assert v["code"] == "NO_SUCH_AF:PA9" and [a["pin"] for a in v["alternatives"]] == ["PA8", "PC8"]


def test_pin_02_valid_boundary_every_listed_af_of_a_pin_is_accepted(hw):
    st = state(target(), alloc("PA8", "I2C3_SCL", "R2", af=2, peripheral="I2C3"))                    # AF2 (p.73)
    assert codes(run(st, hw), "DRC-PIN-02") == []
    st = state(target(), alloc("PA9", "USART1_TX", "R3", af=7, peripheral="USART1"))                 # AF7 (p.73)
    assert codes(run(st, hw), "DRC-PIN-02") == []
    st = state(target(), alloc("PA9", "GPIO_OUT", "R4", peripheral=None))                            # chân GPIO thường: luôn hợp lệ
    assert codes(run(st, hw), "DRC-PIN-02") == []


def test_pin_02_unknown_pin_and_pin_missing_from_the_package(hw):
    st = state(target(), alloc("PZ9", "GPIO_OUT", "R1", peripheral=None))
    assert codes(run(st, hw), "DRC-PIN-02") == ["NO_SUCH_PIN:PZ9"]
    # PF3 chỉ có ở UFBGA121 / LQFP128 (DS12288 Table 12): không có ở LQFP64
    st = state(target(package="LQFP64"), alloc("PF3", "I2C3_SCL", "R2", af=4, peripheral="I2C3"))
    assert codes(run(st, hw), "DRC-PIN-02") == ["PIN_NOT_IN_PACKAGE:PF3"]
    st = state(target(package="LQFP128"), alloc("PF3", "I2C3_SCL", "R2", af=4, peripheral="I2C3"))
    assert codes(run(st, hw), "DRC-PIN-02") == []


def test_pin_02_requirement_pin_that_cannot_carry_the_required_signal(hw):
    st = state(target(), req(id="R2", type="i2c", instance="I2C3", scl_pin="PA9", status="pending"))
    assert codes(run(st, hw), "DRC-PIN-02") == ["NO_SUCH_AF:PA9"]
    st = state(target(), req(id="R2", type="i2c", instance="I2C3", scl_pin="PC8", sda_pin="PC9", status="pending"))        # AF8 cả hai (p.75)
    assert codes(run(st, hw), "DRC-PIN-02") == []


# ============================================================================================ DRC-PIN-03
def test_pin_03_output_function_on_an_input_only_pin(hw):
    """ESP32 Datasheet p.61: 'GPIO pins 34-39 are input-only'."""
    st = state(target("esp32", None, 3.3), alloc("GPIO34", "GPIO_OUT", "R1", chip="esp32", peripheral=None))
    assert codes(run(st, hw), "DRC-PIN-03") == ["INPUT_ONLY:GPIO34"]
    st = state(target("esp32", None, 3.3), alloc("GPIO39", "GPIO", "R1", mode="output", chip="esp32", peripheral=None))
    assert codes(run(st, hw), "DRC-PIN-03") == ["INPUT_ONLY:GPIO39"]


def test_pin_03_bidirectional_functions_count_as_output(hw):
    """SCL/SDA là open-drain hai chiều: cần bộ đệm ngõ ra, nên cũng không đặt được lên chân input-only."""
    st = state(target("esp32", None, 3.3), alloc("GPIO34", "I2C0_SCL", "R1", chip="esp32", peripheral=None))
    assert codes(run(st, hw), "DRC-PIN-03") == ["INPUT_ONLY:GPIO34"]


def test_pin_03_valid_boundary_input_on_gpio34_and_output_on_gpio33(hw):
    st = state(target("esp32", None, 3.3), alloc("GPIO34", "GPIO_IN", "R1", chip="esp32", peripheral=None),
               alloc("GPIO35", "ADC1_CH7", "R2", chip="esp32", peripheral=None))
    assert codes(run(st, hw), "DRC-PIN-03") == []
    st = state(target("esp32", None, 3.3), alloc("GPIO33", "GPIO_OUT", "R1", chip="esp32", peripheral=None))               # GPIO33 không phải input-only
    assert codes(run(st, hw), "DRC-PIN-03") == []


def test_pin_03_unknown_direction_on_an_input_only_pin_is_reported_as_unknown_not_pass(hw):
    st = state(target("esp32", None, 3.3), alloc("GPIO34", "RTC_GPIO4", "R1", chip="esp32", peripheral=None, af=None))
    r = run(st, hw)
    assert codes(r, "DRC-PIN-03", "error") == [] and codes(r, "DRC-PIN-03", "unknown") == ["INPUT_ONLY_UNVERIFIED:GPIO34"]


def test_pin_03_requirement_roles_tx_on_input_only_pin(hw):
    st = state(target("esp32", None, 3.3), req(id="R1", type="uart", instance="UART1", tx_pin="GPIO36", rx_pin="GPIO39", status="pending"))
    assert codes(run(st, hw), "DRC-PIN-03") == ["INPUT_ONLY:GPIO36"]


# ============================================================================================ DRC-CLK-01
HSI_PLL_170 = {"source": "HSI16", "pll": {"m": 4, "n": 85, "r": 2}}                      # 16/4 = 4 MHz x 85 = 340 MHz / 2 = 170 MHz (RM0440 §7.2.4)


def test_clock_derived_frequencies_for_the_reference_configurations():
    ev = drc.evaluate_clock_config(HSI_PLL_170)
    d = ev["derived"]
    assert (d["sysclk_hz"], d["hclk_hz"], d["pclk1_hz"], d["pclk2_hz"], d["tim_clk_apb2_hz"]) == (170_000_000,) * 5 and ev["violations"] == []
    assert d["pll"]["vco_hz"] == 340_000_000 and d["flash_latency"] == 4
    ev = drc.evaluate_clock_config({"source": "HSE", "hse_hz": 8_000_000, "pll": {"m": 2, "n": 85, "r": 2}, "apb2_div": 2})        # ví dụ của kế hoạch W2
    assert ev["derived"]["sysclk_hz"] == 170_000_000 and ev["derived"]["pclk2_hz"] == 85_000_000 and ev["derived"]["tim_clk_apb2_hz"] == 170_000_000
    assert ev["violations"] == []


def test_clk_01_sysclk_above_170_mhz_is_rejected_and_170_is_accepted(hw):
    """DS12288 Table 17 p.84: fHCLK, fPCLK1, fPCLK2 max 170 MHz; Table 46 p.123: VCO 96–344 MHz. N=86 -> VCO 344 MHz (đúng trần) nhưng SYSCLK 172 MHz > 170
    (bộ chia AHB/APB = 1 nên HCLK, PCLK1, PCLK2 cũng 172 MHz và cùng vượt trần của Table 17)."""
    over = drc.evaluate_clock_config({"source": "HSI16", "pll": {"m": 4, "n": 86, "r": 2}}, hw)
    assert sorted(v["code"] for v in over["violations"]) == ["CLOCK_LIMIT:PCLK1", "CLOCK_LIMIT:PCLK2", "CLOCK_LIMIT:SYSCLK"] and over["derived"]["sysclk_hz"] == 172_000_000
    div = drc.evaluate_clock_config({"source": "HSI16", "pll": {"m": 4, "n": 86, "r": 2}, "ahb_div": 2}, hw)           # HCLK 86 MHz: chỉ còn SYSCLK > 170 MHz
    assert [v["code"] for v in div["violations"]] == ["CLOCK_LIMIT:SYSCLK"]
    ok = drc.evaluate_clock_config(HSI_PLL_170, hw)
    assert ok["violations"] == []
    st = state(target(), clock({"source": "HSI16", "pll": {"m": 4, "n": 86, "r": 2}, "ahb_div": 2}))
    assert codes(run(st, hw), "DRC-CLK-01") == ["CLOCK_LIMIT:SYSCLK"]


def test_clk_01_vco_boundaries(hw):
    """Table 46 p.123, Range 1: fVCO_OUT 96–344 MHz. 4 MHz x 24 = 96 (ok) / x 23 = 92 (thấp); x 86 = 344 (ok) / x 87 = 348 (cao)."""
    def codes_for(n, r=8):
        return [v["code"] for v in drc.evaluate_clock_config({"source": "HSI16", "pll": {"m": 4, "n": n, "r": r}}, hw)["violations"]]
    assert codes_for(24) == [] and codes_for(23) == ["CLOCK_LIMIT:VCO"]
    assert codes_for(86, r=4) == [] and codes_for(87, r=4) == ["CLOCK_LIMIT:VCO"]


def test_clk_01_pll_input_boundaries(hw):
    """Table 46 p.123: fPLL_IN 2.66–16 MHz. HSE 8 MHz / 3 = 2.667 MHz (ok) / 4 = 2 MHz (thấp). HSE 32 MHz / 2 = 16 MHz (ok) / 1 = 32 MHz (cao)."""
    def codes_for(hse, m, n=64, r=8):
        return [v["code"] for v in drc.evaluate_clock_config({"source": "HSE", "hse_hz": hse, "pll": {"m": m, "n": n, "r": r}}, hw)["violations"]]
    assert codes_for(8_000_000, 3, n=48, r=4) == []
    assert "CLOCK_LIMIT:PLL_IN" in codes_for(8_000_000, 4, n=64)
    assert codes_for(32_000_000, 2, n=8, r=4) == []
    assert "CLOCK_LIMIT:PLL_IN" in codes_for(32_000_000, 1, n=8)


def test_clk_01_hse_crystal_range(hw):
    """Table 41 p.117: fOSC_IN 4–48 MHz."""
    assert drc.evaluate_clock_config({"source": "HSE", "hse_hz": 4_000_000}, hw)["violations"] == []
    assert [v["code"] for v in drc.evaluate_clock_config({"source": "HSE", "hse_hz": 3_990_000}, hw)["violations"]] == ["CLOCK_LIMIT:HSE"]
    assert drc.evaluate_clock_config({"source": "HSE", "hse_hz": 48_000_000}, hw)["violations"] == []
    assert [v["code"] for v in drc.evaluate_clock_config({"source": "HSE", "hse_hz": 48_000_001}, hw)["violations"]] == ["CLOCK_LIMIT:HSE"]


def test_clk_01_voltage_range_ceilings(hw):
    """RM0440 p.232–233 (Table 38) + DS12288 Table 46: Range 1 normal mode <= 150 MHz; Range 2 <= 26 MHz."""
    normal = drc.evaluate_clock_config({**HSI_PLL_170, "voltage_range": "range1_normal"}, hw)
    assert [v["code"] for v in normal["violations"]] == ["CLOCK_LIMIT:SYSCLK"]
    ok150 = drc.evaluate_clock_config({"source": "HSI16", "pll": {"m": 4, "n": 75, "r": 2}, "voltage_range": "range1_normal"}, hw)       # 4 x 75 / 2 = 150 MHz
    assert ok150["violations"] == [] and ok150["derived"]["sysclk_hz"] == 150_000_000
    r2 = drc.evaluate_clock_config({"source": "HSI16", "pll": {"m": 4, "n": 26, "r": 4}, "voltage_range": "range2"}, hw)                  # 4 x 26 / 4 = 26 MHz
    assert r2["violations"] == [] and r2["derived"]["sysclk_hz"] == 26_000_000
    r2b = drc.evaluate_clock_config({"source": "HSI16", "pll": {"m": 4, "n": 27, "r": 4}, "voltage_range": "range2"}, hw)                 # 27 MHz
    assert "CLOCK_LIMIT:SYSCLK" in [v["code"] for v in r2b["violations"]]


def test_clk_01_flash_latency_must_cover_hclk(hw):
    """RM0440 Table 9 p.98 (Range 1 boost): 0 WS <= 34 MHz, 1 WS <= 68, 2 WS <= 102, 3 WS <= 136, 4 WS <= 170."""
    low = drc.evaluate_clock_config({**HSI_PLL_170, "flash_latency": 3}, hw)
    assert [v["code"] for v in low["violations"]] == ["CLOCK_LIMIT:FLASH_WS"]
    assert drc.evaluate_clock_config({**HSI_PLL_170, "flash_latency": 4}, hw)["violations"] == []
    auto = lambda n, r: drc.evaluate_clock_config({"source": "HSI16", "pll": {"m": 4, "n": n, "r": r}}, hw)["derived"]["flash_latency"]       # noqa: E731
    assert auto(34, 4) == 0 and auto(36, 4) == 1                  # 34 MHz -> 0 WS ; 36 MHz -> 1 WS


def test_clk_01_invalid_configuration_is_an_error_not_a_guess():
    for bad in ({"source": "HSE"}, {"source": "HSI16", "pll": {"m": 0, "n": 85, "r": 2}}, {"source": "HSI16", "pll": {"m": 4, "n": 7, "r": 2}},
                {"source": "HSI16", "pll": {"m": 4, "n": 85, "r": 3}}, {"source": "HSI16", "apb1_div": 3}, {"source": "XTAL"}, {"source": "HSI16", "voltage_range": "x"}):
        with pytest.raises(drc.ClockConfigError):
            drc.evaluate_clock_config(bad)


def test_clk_01_without_a_clock_config_the_rule_reports_unknown(hw):
    r = run(state(target()), hw)
    assert codes(r, "DRC-CLK-01", "unknown") == ["CLOCK_NOT_CONFIGURED"] and r["ok"]


# ============================================================================================ DRC-CLK-02
def test_clk_02_used_peripheral_without_clock_enable(hw):
    """RM0440 §7.4: RCC_APB2ENR.TIM1EN (p.313) và RCC_AHB2ENR.GPIOAEN (p.308) phải = 1 trước khi truy cập TIM1 / GPIOA."""
    pins = [alloc("PA8", "TIM1_CH1", "R1", af=6, peripheral="TIM1")]
    st = state(target(), *pins, clock({**HSI_PLL_170, "enabled_peripherals": ["GPIOA"]}))
    assert codes(run(st, hw), "DRC-CLK-02", "error") == ["CLOCK_GATE:TIM1"]
    st = state(target(), *pins, clock({**HSI_PLL_170, "enabled_peripherals": ["TIM1"]}))
    assert codes(run(st, hw), "DRC-CLK-02", "error") == ["CLOCK_GATE:GPIOA"]                      # cổng GPIO cũng cần clock
    st = state(target(), *pins, clock({**HSI_PLL_170, "enabled_peripherals": ["TIM1", "GPIOA"]}))
    assert codes(run(st, hw), "DRC-CLK-02") == []


def test_clk_02_requirement_instances_count_as_used(hw):
    st = state(target(), req(id="R2", type="i2c", instance="I2C3", status="pending"), clock({**HSI_PLL_170, "enabled_peripherals": ["TIM1"]}))
    assert codes(run(st, hw), "DRC-CLK-02", "error") == ["CLOCK_GATE:I2C3"]


def test_clk_02_unknown_when_the_enable_list_is_not_declared(hw):
    st = state(target(), alloc("PA8", "TIM1_CH1", "R1", af=6, peripheral="TIM1"), clock(HSI_PLL_170))
    r = run(st, hw)
    assert codes(r, "DRC-CLK-02", "error") == [] and codes(r, "DRC-CLK-02", "unknown") == ["CLOCK_ENABLE_UNKNOWN:GPIOA", "CLOCK_ENABLE_UNKNOWN:TIM1"]


def test_clk_02_peripherals_without_a_rcc_gate_are_never_flagged(hw):
    st = state(target(), req(id="R9", type="other", instance="EXTI", status="pending"), clock({**HSI_PLL_170, "enabled_peripherals": []}))
    assert codes(run(st, hw), "DRC-CLK-02") == []                 # EXTI/IWDG/lõi Cortex-M4 không có bit ENR (RM0440 §7.4)


# ============================================================================================ DRC-ELEC-01
def dev(**kw):
    base = {"id": "U2", "part": "BME280", "vdd": 1.8, "interface": "I2C"}
    return ("device_added", {"device": {**base, **kw}})


def net(a, b, kind="bidirectional"):
    return ("net_connected", {"net": {"from": a, "to": b, "kind": kind}})


def test_elec_01_1v8_sensor_on_a_3v3_mcu_is_a_level_mismatch(hw):
    """MCU 3.3 V: VOH_max 3.3 V vs cảm biến 1.8 V (+0.3 V = 2.1 V tối đa) và VOH_min cảm biến 1.4 V < VIH_min MCU 2.31 V (DS12288 Table 54 p.128)."""
    st = state(target(), dev(), net("stm32g474.PB7", "U2.SDA"))
    r = run(st, hw)
    assert codes(r, "DRC-ELEC-01", "error") == ["LEVEL_MISMATCH:1.8V-3.3V"] and not r["ok"]


def test_elec_01_valid_boundaries_matched_domains(hw):
    st = state(target(), dev(vdd=3.3), net("stm32g474.PB7", "U2.SDA"))
    assert codes(run(st, hw), "DRC-ELEC-01") == []
    # 3.0 V: VOH_min MCU 2.9 V >= VIH_min cảm biến 0.7 x 3.0 = 2.1 V ; VOH_max 3.3 V <= 3.0 + 0.3 = 3.3 V (đúng biên) ; VOH_min cảm biến 2.6 V >= 2.31 V
    st = state(target(), dev(vdd=3.0), net("stm32g474.PB7", "U2.SDA"))
    assert codes(run(st, hw), "DRC-ELEC-01") == []
    # 2.9 V: VOH_max 3.3 V > 2.9 + 0.3 = 3.2 V -> quá áp
    st = state(target(), dev(vdd=2.9), net("stm32g474.PB7", "U2.SDA"))
    assert codes(run(st, hw), "DRC-ELEC-01") == ["LEVEL_MISMATCH:2.9V-3.3V"]


def test_elec_01_level_shifter_makes_each_side_consistent(hw):
    ls = ("device_added", {"device": {"id": "LS1", "part": "TXS0102", "vdd": 3.3, "interface": "level_shifter", "io_vdd": 3.3, "io_vdd_by_pin": {"B1": 1.8, "B2": 1.8}}})
    st = state(target(), dev(), ls, net("stm32g474.PB7", "LS1.A1"), net("LS1.B1", "U2.SDA"))
    assert codes(run(st, hw), "DRC-ELEC-01") == []
    st = state(target(), dev(), ls, net("stm32g474.PB7", "LS1.B1"))                          # nối nhầm phía 1.8 V vào MCU 3.3 V
    assert codes(run(st, hw), "DRC-ELEC-01", "error") == ["LEVEL_MISMATCH:1.8V-3.3V"]


def test_elec_01_5v_output_into_a_non_ft_pin(hw):
    """DS12288 Table 14 p.82: VIN max trên chân TT_xx = 4.0 V tuyệt đối (khuyến nghị VDD+0.3 V, Table 17 p.84). PA0 là TT_a; PB7 là FT_f (5.5 V)."""
    us = dev(id="US1", part="HC-SR04", vdd=5.0, interface="digital")
    assert codes(run(state(target(), us, net("US1.ECHO", "stm32g474.PA0", "digital")), hw), "DRC-ELEC-01", "error") == ["NOT_5V_TOLERANT:PA0"]
    assert codes(run(state(target(), us, net("US1.ECHO", "stm32g474.PB7", "digital")), hw), "DRC-ELEC-01") == []
    assert codes(run(state(target(), us, net("US1.ECHO", "stm32g474.PA0", "analog")), hw), "DRC-ELEC-01", "error") == ["NOT_5V_TOLERANT:PA0"]


def test_elec_01_ft_pin_limit_follows_vdd_formula(hw):
    """Table 17 p.84: VIN max = MIN(MIN(VDD, VDDA) + 3.6 V, 5.5 V). VDD = 1.9 V -> 5.5 V ; VDD = 1.8 V -> 5.4 V ; nguồn 5.5 V."""
    src = dev(id="X1", part="ext", vdd=5.5, interface="digital", voh_min=5.0, vol_max=0.4)
    assert codes(run(state(target(vdd=1.9), src, net("X1.OUT", "stm32g474.PB7", "digital")), hw), "DRC-ELEC-01", "error") == []
    assert codes(run(state(target(vdd=1.8), src, net("X1.OUT", "stm32g474.PB7", "digital")), hw), "DRC-ELEC-01", "error") == ["LEVEL_MISMATCH:1.8V-5.5V"]


def test_elec_01_assumptions_are_reported_when_device_thresholds_are_missing(hw):
    r = run(state(target(), dev(vdd=3.3), net("stm32g474.PB7", "U2.SDA")), hw)
    nets = r["nets"]
    assert nets[0]["status"] == "PASS" and any("assumed" in a for a in nets[0]["assumptions"])
    explicit = dev(vdd=3.3, vih_min=2.31, vil_max=0.99, voh_min=2.9, vol_max=0.4, vin_max=3.6)
    assert run(state(target(), explicit, net("stm32g474.PB7", "U2.SDA")), hw)["nets"][0]["assumptions"] == []


def test_elec_01_unknown_endpoint_is_reported_not_passed(hw):
    r = run(state(target(), net("stm32g474.PB7", "U9.SDA")), hw)
    assert codes(r, "DRC-ELEC-01", "unknown") == ["NET_ENDPOINT_UNKNOWN:U9.SDA"]


# ============================================================================================ DRC-PWR-01
def pdev(i, **by_mode):
    return ("device_added", {"device": {"id": i, "part": i, "vdd": 3.3, "interface": "x", "i_ua_by_mode": by_mode}})


def test_pwr_01_budget_arithmetic_and_boundary_with_a_chip_that_has_db_current_data(hw):
    """ESP32 Datasheet Table 4-2 p.30: Hibernation = 5 µA (một dòng duy nhất). Cảm biến: ngủ 0,1 µA (BME280, BST-BME280-DS002 Table 2) + 44,9 µA = đúng 50 µA (biên, đạt)."""
    t = target("esp32", None, 3.3)
    budget = req(id="R5", type="power", mode="hibernation", budget_ua=50, status="satisfied", evidence="x")
    r = run(state(t, budget, pdev("U1", hibernation=0.1), pdev("U2", hibernation=44.9)), hw)
    p = r["power"]["hibernation"]
    assert codes(r, "DRC-PWR-01") == [] and p["total_ua"] == pytest.approx(50.0) and p["status"] == "ok" and p["budget_ua"] == 50
    assert {c["id"] for c in p["contributors"]} == {"esp32", "U1", "U2"}
    r = run(state(t, budget, pdev("U1", hibernation=0.1), pdev("U2", hibernation=45.0)), hw)                        # 50.1 µA
    assert codes(r, "DRC-PWR-01", "error") == ["POWER_BUDGET:hibernation"] and r["power"]["hibernation"]["status"] == "exceeded"


def test_pwr_01_missing_current_data_is_unknown_never_pass(hw):
    """DB không có dòng tiêu thụ của STM32G474 (chỉ có IIO tuyệt đối, DS12288 Table 15 p.83) => không được coi là đạt."""
    r = run(state(target(), req(id="R5", type="power", mode="sleep", budget_ua=50, status="satisfied", evidence="x"), pdev("U1", sleep=0.1)), hw)
    assert codes(r, "DRC-PWR-01", "error") == [] and codes(r, "DRC-PWR-01", "unknown") == ["POWER_UNKNOWN:sleep"]
    p = r["power"]["sleep"]
    assert p["status"] == "unknown" and p["known_total_ua"] == pytest.approx(0.1) and "stm32g474" in p["unknown_contributors"]


def test_pwr_01_device_without_a_number_for_the_mode_is_also_unknown(hw):
    t = target("esp32", None, 3.3)
    r = run(state(t, req(id="R5", type="power", mode="hibernation", budget_ua=50, status="pending"), pdev("U1", active=3.6)), hw)
    assert codes(r, "DRC-PWR-01", "unknown") == ["POWER_UNKNOWN:hibernation"] and "U1" in r["power"]["hibernation"]["unknown_contributors"]


def test_pwr_01_known_sum_already_above_budget_is_exceeded_even_with_unknown_parts(hw):
    r = run(state(target(), req(id="R5", type="power", mode="sleep", budget_ua=50, status="satisfied", evidence="x"), pdev("U1", sleep=60.0)), hw)
    assert codes(r, "DRC-PWR-01", "error") == ["POWER_BUDGET:sleep"] and r["power"]["sleep"]["status"] == "exceeded"


def test_pwr_01_ambiguous_database_rows_are_unknown(hw):
    """Table 4-2 p.30 có ba dòng Deep-sleep (150 / 100 / 10 µA) và ba dòng Modem-sleep => không chọn bừa."""
    t = target("esp32", None, 3.3)
    r = run(state(t, req(id="R5", type="power", mode="deep sleep", budget_ua=500, status="pending")), hw)
    assert codes(r, "DRC-PWR-01", "unknown") == ["POWER_UNKNOWN:deep sleep"]
    r = run(state(t, req(id="R5", type="power", mode="hibernation", budget_ua=4.9, status="pending")), hw)
    assert codes(r, "DRC-PWR-01", "error") == ["POWER_BUDGET:hibernation"]


def test_pwr_01_get_power_budget_for_a_mode_without_a_budget_requirement(hw):
    p = drc.power_budget(state(target("esp32", None, 3.3), pdev("U1", hibernation=2.0)), "hibernation", drc.Catalog(hw))
    assert p["budget_ua"] is None and p["status"] == "no_budget" and p["total_ua"] == pytest.approx(7.0)


def test_pwr_01_no_budget_requirement_means_nothing_to_check(hw):
    assert codes(run(state(target()), hw), "DRC-PWR-01") == []


# ============================================================================================ DRC-REQ-01
def test_req_01_open_requirements_block_and_waivers_need_a_reason(hw):
    st = state(target(), req(id="R1", type="pwm", pin="PA8", status="pending"), req(id="R2", type="pwm", pin="PA9", status="satisfied", evidence="sim#1"),
               req(id="R3", type="pwm", pin="PA10", status="waived", waiver_reason="khách hàng bỏ yêu cầu"), req(id="R4", type="pwm", pin="PA11", status="waived"),
               req(id="R5", type="pwm", pin="PA12", status="bogus"))
    r = run(st, hw)
    assert codes(r, "DRC-REQ-01", "error") == ["REQ_OPEN:R1", "REQ_STATUS_INVALID:R5", "REQ_WAIVER_REASON:R4"]


def test_req_01_satisfied_without_evidence_is_a_warning_and_all_satisfied_is_clean(hw):
    st = state(target(), req(id="R1", type="pwm", pin="PA8", status="satisfied"))
    r = run(st, hw)
    assert codes(r, "DRC-REQ-01", "error") == [] and codes(r, "DRC-REQ-01", "warning") == ["REQ_NO_EVIDENCE:R1"]
    st = state(target(), req(id="R1", type="pwm", pin="PA8", status="satisfied", evidence="sim#12"), req(id="R2", type="pwm", pin="PA9", status="waived", waiver_reason="x"))
    assert codes(run(st, hw), "DRC-REQ-01") == []


# ============================================================================================ run_drc tổng hợp
def test_run_drc_summary_has_one_entry_per_rule_and_ok_ignores_warnings_and_unknowns(hw):
    r = run(state(target(), req(id="R1", type="pwm", pin="PA8", status="satisfied", evidence="e")), hw)
    assert list(r["summary"]) == list(drc.RULES)
    assert r["ok"] is True and r["summary"]["DRC-CLK-01"]["status"] == "unknown" and r["summary"]["DRC-PIN-01"]["status"] == "pass"
    assert r["complete"] is False and r["version"] == 2
    bad = run(state(target(), req(id="R1", type="pwm", pin="PA8", status="pending")), hw)
    assert bad["ok"] is False and bad["summary"]["DRC-REQ-01"]["status"] == "fail" and bad["summary"]["DRC-REQ-01"]["count"] == 1



# ============================================================================================ sửa sau review mã
# --- mục 1: yêu cầu power thiếu / sai kiểu budget_ua không được làm run_drc ném
@pytest.mark.parametrize("budget", [None, "", "x", [], {}, float("nan"), float("inf"), -5.0, True])
def test_pwr_01_power_requirement_without_a_usable_budget_is_unknown_not_a_crash(hw, budget):
    extra = {} if budget is None else {"budget_ua": budget}
    for tgt in (target(), target("esp32", None, 3.3)):                                       # G474: DB không có dòng dòng-điện; ESP32: có
        r = run(state(tgt, req(id="R5", type="power", mode="sleep", **extra)), hw)
        assert "POWER_BUDGET_MISSING:sleep" in codes(r, "DRC-PWR-01", "unknown"), codes(r, "DRC-PWR-01")
        assert not any(v["severity"] == "error" for v in r["violations"] if v["rule"] == "DRC-PWR-01") and r["complete"] is False
    assert drc.power_budget(state(target(), req(id="R5", type="power", mode="sleep", **extra)), "sleep", drc.Catalog(hw))["budget_ua"] is None


def test_pwr_01_a_valid_budget_next_to_a_broken_one_is_still_used(hw):
    st = state(target("esp32", None, 3.3), req(id="R5", type="power", mode="hibernation", budget_ua="oops"), req(id="R6", type="power", mode="hibernation", budget_ua=2.0),
               pdev("U1", hibernation=5.0))
    r = run(st, hw)
    assert "POWER_BUDGET:hibernation" in codes(r, "DRC-PWR-01", "error")                       # 5 + MCU > 2 µA vẫn bị bắt
    assert "REQ_INVALID:R5" in codes(r, "DRC-REQ-01", "unknown")


# --- mục 2: dữ liệu xấu trong log cũ không làm DRC ném
BAD_REQS = [
    dict(id="R1", type="gpio_out", pin=["PA8"]), dict(id="R1", type="gpio_out", pin=5), dict(id="R1", type="gpio_out", pins="PA8,PA9"),
    dict(id="R1", type="gpio_out", pins=[1, None, "PA8"]), dict(id="R1", type="uart", instance="USART1", tx_pin={"a": 1}, rx_pin=7),
    dict(id="R1", type="pwm", pin="PA8", signal=["TIM1_CH1"], freq_hz=None, tol_pct=None), dict(id="R1", type="pwm", mode=["x"], budget_ua=[1]),
]


@pytest.mark.parametrize("bad", BAD_REQS)
def test_run_drc_never_raises_on_malformed_requirements_already_in_the_log(hw, bad):
    st = state(target(), ("pin_allocated", {"pin": "PA9", "chip": "stm32g474", "signal": "TIM1_CH2", "af": 6, "peripheral": "TIM1", "owner": "R2", "mode": None, "shared": False}),
               req(**bad))
    r = run(st, hw)                                                                           # không ném
    assert r["complete"] is False and "REQ_INVALID:R1" in codes(r, "DRC-REQ-01", "unknown")
    assert not [c for c in codes(r) if c.startswith("NO_SUCH_PIN:")]                          # không duyệt từng ký tự của chuỗi "PA8,PA9"


def test_validate_requirement_reports_each_problem():
    ok = dict(id="R1", type="pwm", pin="PA8", signal="TIM1_CH1", freq_hz=20000, duty_pct=25, tol_pct=1.0)
    assert drc.validate_requirement(ok) == []
    assert drc.validate_requirement(dict(id="R1", type="power", mode="sleep", budget_ua=50)) == []
    for bad, needle in ((dict(ok, freq_hz=float("nan")), "freq_hz"), (dict(ok, duty_pct=120), "duty_pct"), (dict(ok, pin=5), "pin"), (dict(ok, pins="PA8"), "pins"),
                        (dict(ok, tol_pct=None, freq_hz=True), "freq_hz"), (dict(id="R1", type="power", mode="sleep"), "budget_ua"), (dict(id="R1", type="power", budget_ua=5), "mode"),
                        (dict(ok, type="warp"), "type"), (dict(ok, shared="yes"), "shared"), (dict(ok, baud=0), "baud")):
        problems = drc.validate_requirement(bad)
        assert problems and any(needle in p for p in problems), (bad, problems)


def test_run_drc_turns_an_unexpected_rule_failure_into_an_unknown_item_never_a_pass(hw, monkeypatch):
    monkeypatch.setattr(drc, "rule_pin_03", lambda state, cat: 1 / 0)
    r = run(state(target()), hw)
    assert "DRC_INTERNAL_ERROR:DRC-PIN-03" in codes(r, "DRC-PIN-03", "unknown") and r["summary"]["DRC-PIN-03"]["status"] == "unknown" and r["complete"] is False


# --- mục 10: tên chân của requirement được chuẩn hoá trước khi so chủ
@pytest.mark.parametrize("name", ["pa8", " PA8 ", "stm32g474.PA8", "STM32G474.pa8", "Pa8"])
def test_pin_01_requirement_pin_names_are_normalised_before_comparing_owners(hw, name):
    st = state(target(), alloc("PA8", "TIM1_CH1", "R1-motor-pwm", af=6, peripheral="TIM1"),
               req(id="R1", type="pwm", pin="PA8", signal="TIM1_CH1"), req(id="R2", type="i2c", instance="I2C3", scl_pin=name))
    r = run(st, hw)
    assert codes(r, "DRC-PIN-01") == ["PIN_CONFLICT:PA8"]
    assert not [c for c in codes(r, "DRC-PIN-02") if c.startswith("NO_SUCH_PIN")]


def test_pin_name_normalisation_only_strips_a_known_chip_prefix(hw):
    st = state(target(), req(id="R1", type="gpio_out", pin="foo.PA8"))
    assert codes(run(st, hw), "DRC-PIN-02") == ["NO_SUCH_PIN:FOO.PA8"]                          # tiền tố lạ không bị cắt âm thầm


# --- mục 4: Flash wait state không bị báo sai ở trạng thái chuyển tiếp
def test_clk_01_range2_low_frequency_with_automatic_latency_is_clean():
    """RM0440 Table 9 p.98: Range 2 chạy 0 WS tới 12 MHz (1 WS tới 24 MHz, 2 WS tới 26 MHz). HSE 8 MHz ⇒ latency tự chọn = 0, không vi phạm."""
    ev = drc.evaluate_clock_config({"source": "HSE", "hse_hz": 8_000_000, "voltage_range": "range2"})
    assert ev["violations"] == [] and ev["derived"]["flash_latency"] == 0 and ev["derived"]["hclk_hz"] == 8_000_000
    ev = drc.evaluate_clock_config({"source": "HSE", "hse_hz": 8_000_000, "voltage_range": "range2", "flash_latency": 0})
    assert ev["violations"] == []                                                                # latency 0 tường minh cũng đúng ở 8 MHz


@pytest.mark.parametrize("div, latency", [(1, 1), (2, 0), (4, 0)])
def test_clk_01_hsi16_in_range2_with_ahb_divider(div, latency):
    """HSI16 = 16 MHz: Range 2 cần 1 WS (12 < 16 ≤ 24); chia 2 ⇒ 8 MHz ⇒ 0 WS."""
    ev = drc.evaluate_clock_config({"source": "HSI16", "ahb_div": div, "voltage_range": "range2"})
    assert ev["violations"] == [] and ev["derived"]["flash_latency"] == latency


def test_clk_01_range2_boundaries_of_the_flash_table():
    assert drc.evaluate_clock_config({"source": "HSE", "hse_hz": 12_000_000, "voltage_range": "range2"})["derived"]["flash_latency"] == 0       # 12 MHz: biên của 0 WS
    ev = drc.evaluate_clock_config({"source": "HSE", "hse_hz": 12_000_001, "voltage_range": "range2"})
    assert ev["derived"]["flash_latency"] == 1 and ev["violations"] == []
    ev = drc.evaluate_clock_config({"source": "HSE", "hse_hz": 24_000_000, "voltage_range": "range2", "flash_latency": 0})
    assert [v["code"] for v in ev["violations"]] == ["CLOCK_LIMIT:FLASH_WS"]                    # latency quá thấp so với HCLK CUỐI vẫn bị bắt
    assert [v["code"] for v in drc.evaluate_clock_config({**HSI_PLL_170, "flash_latency": 2})["violations"]] == ["CLOCK_LIMIT:FLASH_WS"]
    assert drc.evaluate_clock_config({**HSI_PLL_170, "flash_latency": 5})["violations"] == []


# --- mục 12: cấu hình clock sai kiểu là ClockConfigError có thông báo, không phải TypeError/ValueError lạ
BAD_CLOCK = [
    {"source": "HSE", "hse_hz": float("nan")}, {"source": "HSE", "hse_hz": float("inf")}, {"source": "HSE", "hse_hz": -1}, {"source": "HSE", "hse_hz": "8e6"},
    {"source": "PLL", "pll": "x"}, {"source": "PLL", "pll": [1, 2]}, {"source": "PLL", "pll": {"m": "a", "n": 85, "r": 2}}, {"source": "PLL", "pll": {"m": float("nan"), "n": 85, "r": 2}},
    {"source": "HSI16", "ahb_div": [1]}, {"source": "HSI16", "ahb_div": {"a": 1}}, {"source": "HSI16", "apb1_div": True}, {"source": "HSI16", "apb2_div": None, "voltage_range": ["range2"]},
    {"source": "HSI16", "voltage_range": {"a": 1}}, {"source": "HSI16", "enabled_peripherals": 5}, {"source": "HSI16", "enabled_peripherals": [["GPIOA"]]},
    {"source": ["HSI16"]}, {"source": "HSI16", "sysclk_source": ["PLL"]}, {"source": "HSI16", "flash_latency": float("inf")}, {"source": "HSI16", "flash_latency": [1]},
]


@pytest.mark.parametrize("cfg", BAD_CLOCK)
def test_clock_config_errors_are_clock_config_errors(cfg):
    with pytest.raises(drc.ClockConfigError):
        drc.evaluate_clock_config(cfg)


# --- mục 9: loại chân "other pins" (NRST) và FT_c
def test_elec_01_other_pins_input_limit_and_ft_c_five_volt(hw):
    """DS12288 Table 14 p.82: 'other pins' (NRST) VIN max 4.0 V ; Table 17 p.84: FT_c 5.0 V. PG10 là NRST (không TT/FT, không chịu 5 V)."""
    lv = hw.chip_logic_levels("stm32g474", 3.3, "NRST(4)")
    assert lv["in_max"] == 4.0 and lv["in_max_source"]["page"] == 82
    assert hw.chip_logic_levels("stm32g474", 3.3, "FT_c")["in_max"] == 5.0
    us = dev(id="US1", part="HC-SR04", vdd=5.0, interface="digital")
    assert codes(run(state(target(), us, net("US1.ECHO", "stm32g474.PG10", "digital")), hw), "DRC-ELEC-01", "error") == ["NOT_5V_TOLERANT:PG10"]
    assert codes(run(state(target(), us, net("US1.ECHO", "stm32g474.PB4", "digital")), hw), "DRC-ELEC-01", "error") == []                      # PB4 = FT_c: 5.0 V ≥ 5.0 V
    src55 = dev(id="X1", part="ext", vdd=5.5, interface="digital", voh_min=5.0, vol_max=0.4)
    assert codes(run(state(target(), src55, net("X1.OUT", "stm32g474.PB4", "digital")), hw), "DRC-ELEC-01", "error") == ["LEVEL_MISMATCH:3.3V-5.5V"]  # PB4 chịu 5 V nhưng 5.5 V > 5.0 V của FT_c


def test_elec_01_missing_input_maximum_is_unknown_never_pass(hw, monkeypatch):
    real = hw.chip_logic_levels
    monkeypatch.setattr(hw, "chip_logic_levels", lambda chip, vdd=3.3, io=None: {**real(chip, vdd, io), "in_max": None, "in_max_source": None})
    c2 = drc.Catalog(hw)
    us = dev(id="US1", part="HC-SR04", vdd=5.0, interface="digital")
    r = run(state(target(), us, net("US1.ECHO", "stm32g474.PB7", "digital")), c2)
    assert codes(r, "DRC-ELEC-01", "unknown") == ["NET_INPUT_MAX_UNKNOWN:stm32g474.PB7"] and r["nets"][0]["status"] == "UNKNOWN" and r["complete"] is False


# --- mục 16: kết nối analog tới chân có kênh ADC; chú thích 3 Table 17
def test_elec_01_analog_input_range_of_an_adc_pin(hw):
    """DS12288 Table 17 p.84: VDDA 1.62–3.6 V ⇒ VREF+ ≤ 3.6 V. PA2 (FT_a, ADC1_IN3) chịu 5 V về điện nhưng một tín hiệu analog 5 V vượt dải ADC."""
    s5 = dev(id="S5", part="sensor", vdd=5.0, interface="analog")
    r = run(state(target(), s5, net("S5.OUT", "stm32g474.PA2", "analog")), hw)
    assert codes(r, "DRC-ELEC-01", "error") == ["ADC_RANGE:PA2"]
    s33 = dev(id="S3", part="sensor", vdd=3.3, interface="analog")
    r = run(state(target(), s33, net("S3.OUT", "stm32g474.PA2", "analog")), hw)
    assert codes(r, "DRC-ELEC-01") == [] and any("VDDA" in a for a in r["nets"][0]["assumptions"])                  # VDDA/VREF+ giả định = VDD, nói rõ
    s34 = dev(id="S4", part="sensor", vdd=3.4, interface="analog")
    r = run(state(target(), s34, net("S4.OUT", "stm32g474.PA2", "analog")), hw)
    assert codes(r, "DRC-ELEC-01", "unknown") == ["ADC_RANGE_UNVERIFIED:PA2"] and r["complete"] is False
    assert codes(run(state(target(), s5, net("S5.OUT", "stm32g474.PA2", "digital")), hw), "DRC-ELEC-01") == []     # digital: chỉ giới hạn chân (FT chịu 5 V)
    s5b = dev(id="S6", part="sensor", vdd=5.0, interface="analog")
    assert codes(run(state(target(), s5b, net("S6.OUT", "stm32g474.PB7", "analog")), hw), "DRC-ELEC-01") == []     # PB7 không có kênh ADC


def test_elec_01_ft_pin_above_vdd_plus_0v3_notes_the_pull_resistor_footnote(hw):
    us = dev(id="US1", part="HC-SR04", vdd=5.0, interface="digital")
    r = run(state(target(), us, net("US1.ECHO", "stm32g474.PB7", "digital")), hw)
    assert codes(r, "DRC-ELEC-01") == [] and any("pull-up" in n and "Table 17" in n for n in r["nets"][0]["notes"])
    ok33 = dev(id="U3", part="x", vdd=3.3, interface="digital")
    assert not run(state(target(), ok33, net("U3.OUT", "stm32g474.PB7", "digital")), hw)["nets"][0]["notes"]
