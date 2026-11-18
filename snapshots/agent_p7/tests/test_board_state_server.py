"""MCP server board-state (W2): 13 tool, lỗi có MÃ + PHƯƠNG ÁN THAY THẾ, chạy inproc + stdio, kịch bản D2 end-to-end.
Quyền: tool ghi = `state-mutating`, tool chỉ đọc = `read-only`; server nằm trong SERVERS của agent từ P4 (S2D là snapshot P1 nên không có)."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from agent import tools as hub_mod
from hwmodel import board_state as B

AGENT_DIR = Path(__file__).resolve().parents[1]
TOOLS = ["get_board_state", "set_target", "set_requirements", "allocate_pin", "release_pin", "set_clock_config", "add_device", "connect", "get_power_budget",
         "run_drc", "record_decision", "diff", "rollback"]
MUTATING = {"set_target", "set_requirements", "allocate_pin", "release_pin", "set_clock_config", "add_device", "connect", "record_decision", "rollback"}


@pytest.fixture()
def bs(monkeypatch, tmp_path):
    monkeypatch.setenv("BOARD_STATE_DB", str(tmp_path / "bs.sqlite"))
    monkeypatch.setenv("BOARD_STATE_PROJECT", "demo")
    from mcp_servers import board_state_server as srv
    return srv


def tools(srv):
    return {t.name: t for t in asyncio.run(srv.mcp.list_tools())}


def codes(items):
    return [i["code"] for i in items]


def setup_d1(bs, package="LQFP64"):
    assert bs.set_target("stm32g474", package, 3.3)["ok"]
    assert bs.set_requirements([{"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1.0}])["ok"]
    return bs.allocate_pin("PA8", "TIM1_CH1", "R1-motor-pwm")


# ------------------------------------------------------------------------------------------------ giao diện
def test_server_exposes_exactly_the_thirteen_tools_with_documented_parameters(bs):
    t = tools(bs)
    assert sorted(t) == sorted(TOOLS)
    assert all(len(x.description) > 80 for x in t.values())
    props = lambda n: set(t[n].inputSchema["properties"])                         # noqa: E731
    assert {"chip", "package", "vdd"} <= props("set_target") and "requirements" in props("set_requirements")
    assert {"pin", "signal", "owner"} <= props("allocate_pin") and "pin" in props("release_pin") and "cfg" in props("set_clock_config")
    assert {"from_ref", "to_ref", "kind"} <= props("connect") and "mode" in props("get_power_budget") and {"v1", "v2"} <= props("diff")
    assert {"question", "options", "chosen", "by", "rationale"} <= props("record_decision") and "version" in props("rollback") and "section" in props("get_board_state")
    assert all("project_id" in props(n) for n in TOOLS)


def test_permissions_state_mutating_for_writers_read_only_for_queries_and_registered_from_p4():
    for name in TOOLS:
        assert hub_mod.PERMISSIONS[name] == ("state-mutating" if name in MUTATING else "read-only"), name
    assert "board-state" in hub_mod.SERVERS                          # P4 (D32)
    hub = hub_mod.ToolHub(transport="inproc", session_id="t")
    assert set(TOOLS) <= set(hub.tool_names())
    assert not set(TOOLS) & set(hub_mod.ToolHub(transport="inproc", disabled_servers=("board-state",)).tool_names())


# ------------------------------------------------------------------------------------------------ set_target / get_board_state
def test_set_target_and_get_board_state(bs):
    r = bs.set_target("stm32g474", "LQFP64", 3.3)
    assert r["ok"] and r["version"] == 1 and r["warnings"] == []
    s = bs.get_board_state()
    assert s["ok"] and s["version"] == 1 and s["state"]["targets"] == [{"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3}] and s["head"] == 1
    assert bs.get_board_state("pins")["data"] == {} and bs.get_board_state("targets")["data"][0]["chip"] == "stm32g474"
    assert bs.get_board_state("nope")["error"]["code"] == "NO_SUCH_SECTION" and "pins" in bs.get_board_state("nope")["error"]["sections"]
    assert bs.get_board_state(version=0)["state"]["targets"] == []
    assert bs.get_board_state(version=9)["error"]["code"] == "NO_SUCH_VERSION"


def test_set_target_warns_about_vdd_outside_the_recommended_range(bs):
    """DS12288 Table 17 p.84: VDD 1.71–3.6 V ; Table 14 p.82: tuyệt đối tối đa 4.0 V."""
    assert bs.set_target("stm32g474", "LQFP64", 1.71)["warnings"] == [] and bs.set_target("stm32g474", "LQFP64", 3.6)["warnings"] == []
    low = bs.set_target("stm32g474", "LQFP64", 1.70)
    assert codes(low["warnings"]) == ["VDD_OUT_OF_RANGE"] and low["ok"]
    assert codes(bs.set_target("stm32g474", "LQFP64", 3.61)["warnings"]) == ["VDD_OUT_OF_RANGE"]
    assert codes(bs.set_target("stm32g474", "LQFP64", 5.0)["warnings"]) == ["VDD_OUT_OF_RANGE"]
    assert bs.get_board_state()["state"]["targets"][0]["vdd"] == 5.0                                  # cảnh báo, không từ chối


def test_set_target_unknown_chip_and_package(bs):
    r = bs.set_target("atmega328", "DIP28", 5.0)
    assert not r["ok"] and r["error"]["code"] == "UNKNOWN_CHIP" and "stm32g474" in r["error"]["chips"] and bs.get_board_state()["head"] == 0
    r = bs.set_target("stm32g474", "LQFP999", 3.3)
    assert r["ok"] and codes(r["warnings"]) == ["UNKNOWN_PACKAGE"] and "LQFP64" in r["warnings"][0]["known_packages"]


# ------------------------------------------------------------------------------------------------ allocate_pin
def test_allocate_pin_success_records_af_from_the_table(bs):
    r = setup_d1(bs)
    assert r["ok"] and r["af"] == 6 and r["peripheral"] == "TIM1" and r["mode"] == "AF_PP" and r["package_pin"] == "42" and r["warnings"] == []
    pin = bs.get_board_state("pins")["data"]["PA8"]
    assert pin["signal"] == "TIM1_CH1" and pin["owner"] == "R1-motor-pwm" and pin["af"] == 6
    assert bs.get_board_state("peripherals")["data"]["TIM1"]["owners"] == ["R1-motor-pwm"]


def test_allocate_pin_is_idempotent_for_the_same_owner_and_signal(bs):
    setup_d1(bs)
    head = bs.get_board_state()["head"]
    r = bs.allocate_pin("pa8", "tim1_ch1", "R1-motor-pwm")
    assert r["ok"] and r["unchanged"] is True and bs.get_board_state()["head"] == head


def test_d2_conflict_lists_alternatives_from_the_af_table(bs):
    """Kịch bản D2: PA8 đã cấp cho PWM (R1); xin I2C3_SCL ở PA8 => CONFLICT + chân thay thế theo DS12288 Table 13 (p.73-79):
    I2C3_SCL = PA8 (AF2), PC8 (AF8), PF3 (AF4), PG7 (AF4); gói LQFP64 chỉ có PA8 và PC8."""
    setup_d1(bs)
    head = bs.get_board_state()["head"]
    r = bs.allocate_pin("PA8", "I2C3_SCL", "R2-bme280-i2c")
    e = r["error"]
    assert not r["ok"] and e["code"] == "CONFLICT" and e["pin"] == "PA8"
    assert e["current"] == {"signal": "TIM1_CH1", "owner": "R1-motor-pwm", "af": 6}
    assert e["requested"] == {"signal": "I2C3_SCL", "owner": "R2-bme280-i2c"}
    assert [(a["pin"], a["af"]) for a in e["alternatives"]] == [("PC8", 8)] and all(a["free"] for a in e["alternatives"])
    assert bs.get_board_state()["head"] == head                                         # bị từ chối: không ghi sự kiện
    bs.set_target("stm32g474", "LQFP128", 3.3)
    e = bs.allocate_pin("PA8", "I2C3_SCL", "R2")["error"]
    assert [(a["pin"], a["af"]) for a in e["alternatives"]] == [("PC8", 8), ("PF3", 4), ("PG7", 4)]


def test_conflict_with_a_different_signal_of_the_same_owner_is_still_a_conflict(bs):
    setup_d1(bs)
    e = bs.allocate_pin("PA8", "USART1_CK", "R1-motor-pwm")["error"]
    assert e["code"] == "CONFLICT" and "release_pin" in e["message"]


def test_no_such_af_lists_the_pins_that_carry_the_signal(bs):
    """DS12288 Table 13 p.73: PA9 không mang I2C3_SCL."""
    bs.set_target("stm32g474", "LQFP64", 3.3)
    r = bs.allocate_pin("PA9", "I2C3_SCL", "R2")
    e = r["error"]
    assert not r["ok"] and e["code"] == "NO_SUCH_AF" and [a["pin"] for a in e["alternatives"]] == ["PA8", "PC8"]
    assert [p["pin"] for p in e["pins_with_signal"]] == ["PA8", "PC8", "PF3", "PG7"]
    assert bs.allocate_pin("PA9", "NOT_A_SIGNAL", "R2")["error"]["code"] == "NO_SUCH_AF"
    assert bs.allocate_pin("PA9", "NOT_A_SIGNAL", "R2")["error"]["alternatives"] == []


def test_no_such_pin_and_pin_missing_from_the_package(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    e = bs.allocate_pin("PZ9", "GPIO_OUT", "R1")["error"]
    assert e["code"] == "NO_SUCH_PIN" and isinstance(e["suggestions"], list)
    e = bs.allocate_pin("PF3", "I2C3_SCL", "R2")["error"]                               # PF3 không có ở LQFP64 (DS12288 Table 12)
    assert e["code"] == "PIN_NOT_IN_PACKAGE" and [a["pin"] for a in e["alternatives"]] == ["PA8", "PC8"]


def test_allocate_requires_a_target(bs):
    assert bs.allocate_pin("PA8", "TIM1_CH1", "R1")["error"]["code"] == "NO_TARGET"


def test_input_only_pin_rejects_output_functions_and_offers_output_capable_pins(bs):
    """ESP32 Datasheet p.61: 'GPIO pins 34-39 are input-only'."""
    bs.set_target("esp32", None, 3.3)
    r = bs.allocate_pin("GPIO34", "GPIO_OUT", "R1")
    e = r["error"]
    assert not r["ok"] and e["code"] == "INPUT_ONLY" and e["pin"] == "GPIO34"
    assert e["alternatives"] and all(a["pin"] not in {f"GPIO{n}" for n in range(34, 40)} for a in e["alternatives"])
    assert bs.allocate_pin("GPIO34", "GPIO_IN", "R1")["ok"]                                # nhập thì được
    assert bs.allocate_pin("GPIO35", "GPIO", "R2", mode="output")["error"]["code"] == "INPUT_ONLY"
    assert bs.allocate_pin("GPIO33", "GPIO_OUT", "R3")["ok"]                               # biên: GPIO33 không phải input-only


def test_shared_bus_requires_a_bus_signal_and_same_signal(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    assert bs.allocate_pin("PB7", "I2C1_SDA", "bus-i2c1", shared=True)["ok"]
    r = bs.allocate_pin("PB7", "I2C1_SDA", "U3-sensor", shared=True)
    assert r["ok"] and bs.get_board_state("pins")["data"]["PB7"]["shared_with"] == ["U3-sensor"]
    assert bs.allocate_pin("PB7", "I2C1_SDA", "U4", shared=False)["error"]["code"] == "CONFLICT"
    assert bs.allocate_pin("PA8", "TIM1_CH1", "R1", shared=True)["error"]["code"] == "SHARED_NOT_BUS"


def test_two_owners_on_one_timer_get_a_peripheral_shared_warning(bs):
    setup_d1(bs)
    r = bs.allocate_pin("PA9", "TIM1_CH2", "R3-fan-pwm")
    assert r["ok"] and codes(r["warnings"]) == ["PERIPHERAL_SHARED"] and r["warnings"][0]["peripheral"] == "TIM1"
    assert r["warnings"][0]["owners"] == ["R1-motor-pwm"] and "frequency" in r["warnings"][0]["message"]


def test_strapping_pin_warning(bs):
    bs.set_target("esp32", None, 3.3)
    r = bs.allocate_pin("GPIO0", "GPIO_OUT", "R1")                                          # ESP32 Datasheet Table 3-1 p.22: GPIO0 là strapping pin
    assert r["ok"] and codes(r["warnings"]) == ["PIN_FLAG:strapping"]


def test_release_pin(bs):
    setup_d1(bs)
    r = bs.release_pin("PA8")
    assert r["ok"] and bs.get_board_state("pins")["data"] == {} and bs.get_board_state("peripherals")["data"] == {}
    assert bs.release_pin("PA8")["error"]["code"] == "NOT_ALLOCATED"


# ------------------------------------------------------------------------------------------------ set_requirements
def test_requirements_upsert_status_default_and_validation(bs):
    r = bs.set_requirements([{"id": "R1", "type": "pwm", "pin": "PA8", "freq_hz": 20000}])
    assert r["ok"] and r["requirements"][0]["status"] == "pending" and r["contradictions"] == []
    r = bs.set_requirements([{"id": "R1", "type": "pwm", "pin": "PA8", "freq_hz": 20000, "status": "satisfied", "evidence": "sim#12"}])
    assert [x["status"] for x in r["requirements"]] == ["satisfied"] and len(r["requirements"]) == 1
    assert bs.set_requirements([{"type": "pwm"}])["error"]["code"] == "INVALID_REQUIREMENT"
    assert bs.set_requirements([{"id": "R2", "type": "pwm", "status": "done"}])["error"]["code"] == "INVALID_REQUIREMENT"
    assert bs.set_requirements(json.dumps([{"id": "R3", "type": "gpio_out", "pin": "PB0"}]))["ok"]
    assert bs.set_requirements("not json")["error"]["code"] == "INVALID_REQUIREMENT"


def test_requirements_report_contradictions(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    bs.set_requirements([{"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000}])
    r = bs.set_requirements([{"id": "R2", "type": "i2c", "instance": "I2C3", "scl_pin": "PA8"}])
    assert [c["code"] for c in r["contradictions"]] == ["PIN_CONFLICT:PA8"]
    r = bs.set_requirements([{"id": "R3", "type": "pwm", "pin": "PA9", "signal": "TIM1_CH2", "freq_hz": 1000}])
    assert "TIMER_SHARED:TIM1" in [c["code"] for c in r["contradictions"]]                      # hai kênh của TIM1 dùng chung PSC/ARR => một tần số
    r = bs.set_requirements([{"id": "R3", "type": "pwm", "pin": "PA9", "signal": "TIM1_CH2", "freq_hz": 20000}])
    assert "TIMER_SHARED:TIM1" not in [c["code"] for c in r["contradictions"]]                  # cùng tần số: không mâu thuẫn


# ------------------------------------------------------------------------------------------------ set_clock_config
def test_set_clock_config_returns_derived_frequencies(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    r = bs.set_clock_config({"source": "HSE", "hse_hz": 8_000_000, "pll": {"m": 2, "n": 85, "r": 2}, "enabled_peripherals": ["GPIOA", "TIM1"]})
    assert r["ok"] and r["recorded"] and r["violations"] == []
    assert r["derived"]["sysclk_hz"] == 170_000_000 and r["derived"]["tim_clk_apb2_hz"] == 170_000_000
    clk = bs.get_board_state("clock")["data"]
    assert clk["derived"]["hclk_hz"] == 170_000_000 and clk["enabled_peripherals"] == ["GPIOA", "TIM1"]


def test_set_clock_config_reports_violations_with_codes_and_records_them(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    r = bs.set_clock_config({"source": "HSI16", "pll": {"m": 4, "n": 87, "r": 2}, "ahb_div": 2})                # VCO 348 MHz > 344 ; SYSCLK 174 MHz > 170
    assert not r["ok"] and r["recorded"] and sorted(codes(r["violations"])) == ["CLOCK_LIMIT:SYSCLK", "CLOCK_LIMIT:VCO"]
    assert bs.get_board_state("clock")["data"]["violations"]
    r = bs.set_clock_config({"source": "HSI16", "pll": {"m": 4, "n": 85, "r": 2}})
    assert r["ok"] and bs.get_board_state("clock")["data"]["violations"] == []
    assert bs.run_drc()["summary"]["DRC-CLK-01"]["status"] == "pass"


def test_set_clock_config_invalid_input_is_an_error_without_recording(bs):
    r = bs.set_clock_config({"source": "HSE"})
    assert not r["ok"] and r["error"]["code"] == "INVALID_CLOCK_CONFIG" and "hse_hz" in r["error"]["message"] and bs.get_board_state()["head"] == 0
    assert bs.set_clock_config("[1]")["error"]["code"] == "INVALID_CLOCK_CONFIG"


# ------------------------------------------------------------------------------------------------ devices / connect
def test_add_device_and_connect_level_check(bs):
    """D2: BME280 ở 1.8 V (cảm biến), MCU 3.3 V => LEVEL_MISMATCH:1.8V-3.3V kèm gợi ý level shifter; kết nối bị từ chối (không ghi sự kiện)."""
    bs.set_target("stm32g474", "LQFP64", 3.3)
    d = bs.add_device("U2", "BME280", 1.8, "I2C", i_typ_ua=3.6)
    assert d["ok"] and d["device"]["id"] == "U2" and d["device"]["i_typ_ua"] == 3.6
    head = bs.get_board_state()["head"]
    r = bs.connect("stm32g474.PC8", "U2.SCL", "i2c")
    assert not r["ok"] and not r["recorded"] and r["error"]["code"] == "LEVEL_MISMATCH:1.8V-3.3V"
    assert any(s["action"] == "add_level_shifter" for s in r["error"]["suggestions"])
    assert r["level_check"]["status"] == "FAIL" and r["level_check"]["assumptions"]
    assert bs.get_board_state("nets")["data"] == [] and bs.get_board_state()["head"] == head


def test_a_net_that_becomes_invalid_later_is_caught_by_the_drc(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    bs.add_device("U2", "BME280", 3.3, "I2C")
    assert bs.connect("stm32g474.PC8", "U2.SCL", "i2c")["ok"]
    assert bs.run_drc()["summary"]["DRC-ELEC-01"]["status"] == "pass"
    bs.add_device("U2", "BME280", 1.8, "I2C")                                    # đổi thiết kế: cảm biến nay là bản 1.8 V
    r = bs.run_drc()
    assert r["summary"]["DRC-ELEC-01"]["status"] == "fail" and [v["code"] for v in r["violations"] if v["rule"] == "DRC-ELEC-01"] == ["LEVEL_MISMATCH:1.8V-3.3V"]


def test_connect_matching_domains_passes_and_unknown_endpoint_is_refused(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    bs.add_device("U2", "BME280", 3.3, "I2C")
    r = bs.connect("stm32g474.PC8", "U2.SCL", "bidirectional")
    assert r["ok"] and r["level_check"]["status"] == "PASS"
    r = bs.connect("stm32g474.PC8", "U9.SCL", "digital")
    assert not r["ok"] and r["error"]["code"] == "UNKNOWN_ENDPOINT" and not r["recorded"]
    assert bs.connect("stm32g474.PC8", "U2.SCL", "wireless")["error"]["code"] == "INVALID_KIND"
    assert bs.connect("stm32g474.PC8", "stm32g474.PC9", "digital")["ok"]                     # MCU-MCU cùng miền 3.3 V


def test_5v_output_into_a_non_ft_pin_is_blocked_with_the_pin_in_the_code(bs):
    """D3: cảm biến siêu âm 5 V vào PA0 (TT_a, không chịu 5 V)."""
    bs.set_target("stm32g474", "LQFP64", 3.3)
    bs.add_device("US1", "HC-SR04", 5.0, "digital")
    r = bs.connect("US1.ECHO", "stm32g474.PA0", "digital")
    assert not r["ok"] and not r["recorded"] and r["error"]["code"] == "NOT_5V_TOLERANT:PA0" and r["error"]["suggestions"]
    assert bs.connect("US1.ECHO", "stm32g474.PB7", "digital")["ok"]


def test_add_device_validation(bs):
    assert bs.add_device("", "x", 3.3, "I2C")["error"]["code"] == "INVALID_DEVICE"
    assert bs.add_device("U1", "x", -1, "I2C")["error"]["code"] == "INVALID_DEVICE"
    d = bs.add_device("LS1", "TXS0102", 3.3, "level_shifter", io_vdd=3.3, io_vdd_by_pin={"B1": 1.8})
    assert d["ok"] and d["device"]["io_vdd_by_pin"] == {"B1": 1.8}
    assert bs.add_device("LS1", "TXS0102", 3.3, "level_shifter")["ok"] and len(bs.get_board_state("devices")["data"]) == 1             # cập nhật theo id


# ------------------------------------------------------------------------------------------------ power / decisions / drc
def test_get_power_budget_reports_unknown_for_missing_chip_data(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    bs.add_device("U2", "BME280", 3.3, "I2C", i_ua_by_mode={"sleep": 0.1})
    bs.set_requirements([{"id": "R5", "type": "power", "mode": "sleep", "budget_ua": 50}])
    p = bs.get_power_budget("sleep")
    assert p["ok"] and p["status"] == "unknown" and p["known_total_ua"] == pytest.approx(0.1) and "stm32g474" in p["unknown_contributors"] and p["budget_ua"] == 50
    assert bs.get_power_budget("active")["status"] == "unknown"


def test_record_decision_assigns_ids_and_validates(bs):
    r = bs.record_decision("I2C3_SCL đặt ở chân nào?", ["PC8", "PF3"], "PC8", "human", "PA8 đã dùng cho PWM")
    assert r["ok"] and r["decision"]["id"] == "D1" and r["decision"]["by"] == "human"
    r = bs.record_decision("Có dùng level shifter?", json.dumps(["có", "không"]), "có", "agent", "cảm biến 1.8 V")
    assert r["decision"]["id"] == "D2" and r["decision"]["options"] == ["có", "không"]
    assert bs.record_decision("", [], "x", "agent", "y")["error"]["code"] == "INVALID_DECISION"
    assert bs.record_decision("q", ["a"], "z", "agent", "y")["error"]["code"] == "INVALID_DECISION"             # chosen phải nằm trong options
    assert bs.record_decision("q", ["a"], "a", "robot", "y")["error"]["code"] == "INVALID_DECISION"
    assert [d["id"] for d in bs.get_board_state("decisions")["data"]] == ["D1", "D2"]


def test_run_drc_on_the_server_returns_the_structured_result(bs):
    setup_d1(bs)
    r = bs.run_drc()
    assert r["ok"] is False and r["summary"]["DRC-REQ-01"]["status"] == "fail" and any(v["code"] == "REQ_OPEN:R1" for v in r["violations"])
    assert list(r["summary"]) == ["DRC-PIN-01", "DRC-PIN-02", "DRC-PIN-03", "DRC-CLK-01", "DRC-CLK-02", "DRC-ELEC-01", "DRC-PWR-01", "DRC-REQ-01"]
    json.dumps(r)


# ------------------------------------------------------------------------------------------------ diff / rollback
def test_diff_and_rollback_through_the_server(bs):
    setup_d1(bs)                                                             # versions: target 1, requirements 2, pin 3
    bs.allocate_pin("PC8", "I2C3_SCL", "R2")                                 # 4
    bs.allocate_pin("PC9", "I2C3_SDA", "R2")                                 # 5
    d = bs.diff(3, 5)
    assert d["ok"] and d["from"] == 3 and d["to"] == 5
    assert [(c["section"], c["op"], c["key"]) for c in d["changes"] if c["section"] == "pins"] == [("pins", "added", "PC8"), ("pins", "added", "PC9")]
    assert d["summary"]["pins"] == 2
    r = bs.rollback(3)
    assert r["ok"] and r["version"] == 6 and r["restored_from"] == 3 and set(bs.get_board_state("pins")["data"]) == {"PA8"}
    assert [c["op"] for c in r["changes"] if c["section"] == "pins"] == ["removed", "removed"]
    assert bs.get_board_state(version=5)["state"]["pins"].keys() >= {"PC8", "PC9"}               # lịch sử còn nguyên
    assert bs.diff(1, 99)["error"]["code"] == "NO_SUCH_VERSION" and bs.rollback(99)["error"]["code"] == "NO_SUCH_VERSION"


# ------------------------------------------------------------------------------------------------ D2 end-to-end
def test_scenario_d2_end_to_end_inproc(bs):
    # Lượt 1: PWM 20 kHz duty 25 % ở PA8
    assert bs.set_target("stm32g474", "LQFP64", 3.3)["ok"]
    assert bs.set_requirements([{"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1.0}])["ok"]
    assert bs.allocate_pin("PA8", "TIM1_CH1", "R1-motor-pwm")["ok"]
    clk = bs.set_clock_config({"source": "HSE", "hse_hz": 8_000_000, "pll": {"m": 2, "n": 85, "r": 2}, "enabled_peripherals": ["GPIOA", "TIM1", "GPIOC", "I2C3"]})
    assert clk["ok"] and clk["derived"]["sysclk_hz"] == 170_000_000
    v_before = bs.get_board_state()["head"]
    # Lượt 2: thêm BME280 qua I2C3 — agent tự phát hiện PA8 đã thuộc R1
    assert bs.add_device("U2", "BME280", 1.8, "I2C", i_typ_ua=3.6)["ok"]
    assert bs.set_requirements([{"id": "R2", "type": "i2c", "instance": "I2C3", "scl_pin": "PA8", "sda_pin": "PC9", "device": "U2"}])["contradictions"][0]["code"] == "PIN_CONFLICT:PA8"
    conflict = bs.allocate_pin("PA8", "I2C3_SCL", "R2-bme280-i2c")
    assert conflict["error"]["code"] == "CONFLICT" and conflict["error"]["current"]["owner"] == "R1-motor-pwm"
    assert [a["pin"] for a in conflict["error"]["alternatives"]] == ["PC8"]
    # đổi sang chân thay thế (PC8/PC9 đều AF8, DS12288 p.75) và ghi quyết định
    assert bs.set_requirements([{"id": "R2", "type": "i2c", "instance": "I2C3", "scl_pin": "PC8", "sda_pin": "PC9", "device": "U2"}])["contradictions"] == []
    assert bs.allocate_pin("PC8", "I2C3_SCL", "R2-bme280-i2c")["ok"] and bs.allocate_pin("PC9", "I2C3_SDA", "R2-bme280-i2c")["ok"]
    assert bs.record_decision("I2C3_SCL đặt ở chân nào?", ["PC8", "PF3"], "PC8", "agent", "PA8 đã dùng cho PWM (R1)")["ok"]
    # connect trực tiếp: 1.8 V vs 3.3 V => bị từ chối kèm gợi ý
    bad = bs.connect("stm32g474.PC8", "U2.SCL", "i2c")
    assert bad["error"]["code"] == "LEVEL_MISMATCH:1.8V-3.3V" and not bad["recorded"]
    # thêm level shifter và nối qua nó
    assert bs.add_device("LS1", "TXS0102", 3.3, "level_shifter", io_vdd=3.3, io_vdd_by_pin={"B1": 1.8, "B2": 1.8})["ok"]
    nets = [("stm32g474.PC8", "LS1.A1"), ("LS1.B1", "U2.SCL"), ("stm32g474.PC9", "LS1.A2"), ("LS1.B2", "U2.SDA")]
    assert all(bs.connect(a, b, "i2c")["ok"] for a, b in nets)
    drc = bs.run_drc()
    assert drc["summary"]["DRC-ELEC-01"]["status"] == "pass" and all(n["status"] == "PASS" for n in drc["nets"]) and len(drc["nets"]) == 4
    assert drc["summary"]["DRC-PIN-01"]["status"] == "pass" and drc["summary"]["DRC-PIN-02"]["status"] == "pass" and drc["summary"]["DRC-CLK-02"]["status"] == "pass"
    # diff giữa phiên bản trước lượt 2 và hiện tại
    d = bs.diff(v_before, bs.get_board_state()["head"])
    sections = {c["section"] for c in d["changes"]}
    assert {"devices", "pins", "nets", "requirements", "decisions", "peripherals"} <= sections
    assert {c["key"] for c in d["changes"] if c["section"] == "pins"} == {"PC8", "PC9"}


# ------------------------------------------------------------------------------------------------ project / bền vững
def test_projects_are_isolated_and_state_survives_a_new_import(bs, monkeypatch):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    assert bs.set_target("esp32", None, 3.3, project_id="other")["ok"]
    assert [t["chip"] for t in bs.get_board_state("targets")["data"]] == ["stm32g474"]
    assert [t["chip"] for t in bs.get_board_state("targets", project_id="other")["data"]] == ["esp32"]
    store = B.EventStore(os.environ["BOARD_STATE_DB"])
    assert sorted(store.projects()) == ["demo", "other"]


def test_results_are_json_serialisable_and_errors_are_values_not_exceptions(bs):
    json.dumps(setup_d1(bs))
    json.dumps(bs.run_drc())
    for call in (lambda: bs.allocate_pin("PA8", "I2C3_SCL", "R2"), lambda: bs.rollback(-1), lambda: bs.diff("a", 2), lambda: bs.get_power_budget(""),
                 lambda: bs.set_requirements(None), lambda: bs.connect("", "", "digital")):
        out = call()
        assert out["ok"] is False and "code" in out["error"]


# ------------------------------------------------------------------------------------------------ stdio
def test_stdio_transport_serves_the_same_tools_and_the_d2_conflict(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        env = {"AGENT_DOTENV": "0", "LLM_API_KEY": "", "PATH": os.environ.get("PATH", ""), "BOARD_STATE_DB": str(tmp_path / "stdio.sqlite"),
               "BOARD_STATE_PROJECT": "stdio-demo"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_servers.board_state_server"], cwd=str(AGENT_DIR), env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                call = lambda n, a: s.call_tool(n, arguments=a)                      # noqa: E731
                load = lambda res: json.loads(res.content[0].text)                   # noqa: E731
                await call("set_target", {"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3})
                ok = load(await call("allocate_pin", {"pin": "PA8", "signal": "TIM1_CH1", "owner": "R1-motor-pwm"}))
                conflict = load(await call("allocate_pin", {"pin": "PA8", "signal": "I2C3_SCL", "owner": "R2"}))
                drc = load(await call("run_drc", {}))
                return names, ok, conflict, drc

    names, ok, conflict, drc = asyncio.run(asyncio.wait_for(go(), 120))
    assert names == set(TOOLS)
    assert ok["ok"] and ok["af"] == 6
    assert conflict["error"]["code"] == "CONFLICT" and [a["pin"] for a in conflict["error"]["alternatives"]] == ["PC8"]
    assert drc["summary"]["DRC-PIN-01"]["status"] == "pass"
    ev = B.EventStore(tmp_path / "stdio.sqlite").events("stdio-demo")
    assert [e["type"] for e in ev] == ["target_set", "pin_allocated"]                    # sự kiện được ghi bền ngoài tiến trình server


# ------------------------------------------------------------------------------------------------ sửa sau review mã
def head(bs, project_id=None):
    return bs.get_board_state(project_id=project_id)["head"]


# --- mục 1, 2: set_requirements kiểm kiểu trường lồng; từ chối cả lời gọi, không ghi nửa chừng
GOOD = {"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1.0}
BAD_REQUIREMENTS = [
    {"id": "R5", "type": "power", "mode": "sleep"}, {"id": "R5", "type": "power", "mode": "sleep", "budget_ua": None}, {"id": "R5", "type": "power", "mode": "sleep", "budget_ua": "50"},
    {"id": "R5", "type": "power", "mode": "sleep", "budget_ua": 0}, {"id": "R5", "type": "power", "mode": "sleep", "max_ua": 50}, {"id": "R5", "type": "power", "budget_ua": 50},
    {"id": "R5", "type": "power", "mode": "sleep", "budget_ua": float("nan")}, {"id": "R5", "type": "power", "mode": "sleep", "budget_ua": [1]},
    {**GOOD, "pin": ["PA8"]}, {**GOOD, "pin": 5}, {**GOOD, "pins": "PA8,PA9"}, {**GOOD, "pins": ["PA8", 7]}, {**GOOD, "tol_pct": None, "freq_hz": float("inf")},
    {**GOOD, "freq_hz": True}, {**GOOD, "freq_hz": "20k"}, {**GOOD, "freq_hz": -1}, {**GOOD, "duty_pct": 101}, {**GOOD, "signal": ["TIM1_CH1"]}, {**GOOD, "type": "warp-drive"},
    {**GOOD, "shared": "yes"}, {**GOOD, "id": 7}, {**GOOD, "id": "  "}, {**GOOD, "scl_pin": {"a": 1}}, {**GOOD, "evidence": 5}, {**GOOD, "baud": 0},
]


@pytest.mark.parametrize("bad", BAD_REQUIREMENTS)
def test_set_requirements_rejects_wrongly_typed_fields_and_writes_nothing(bs, bad):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    h = head(bs)
    r = bs.set_requirements([{**GOOD, "id": "R0"}, bad])                                      # phần tử đầu hợp lệ: cũng không được ghi (cả lời gọi bị từ chối)
    assert r["ok"] is False and r["error"]["code"] == "INVALID_REQUIREMENT" and r["error"]["problems"], r
    assert head(bs) == h and bs.get_board_state("requirements")["data"] == []
    json.dumps(r)


def test_set_requirements_accepts_a_well_formed_power_requirement_and_the_drc_runs(bs):
    bs.set_target("esp32", None, 3.3)
    r = bs.set_requirements([{"id": "R5", "type": "power", "mode": "sleep", "budget_ua": 50.0}, {"id": "R6", "type": "uart", "instance": "UART1", "tx_pin": "GPIO17", "rx_pin": "GPIO16",
                                                                                                "baud": 115200, "tol_pct": 2, "shared": False}])
    assert r["ok"]
    out = bs.run_drc()
    assert out["summary"]["DRC-PWR-01"]["status"] in ("pass", "unknown", "fail")               # chạy được, không ném


def test_run_drc_survives_a_broken_requirement_already_in_the_log(bs):
    """Log ghi trực tiếp (trước khi có kiểm kiểu) vẫn đọc được: run_drc trả mục unknown, không ném; rollback không cần thiết."""
    bs.set_target("stm32g474", "LQFP64", 3.3)
    store = B.EventStore(os.environ["BOARD_STATE_DB"])
    store.append("demo", "requirements_set", {"requirements": [{"id": "R5", "type": "power", "mode": "sleep"}, {"id": "R6", "type": "gpio_out", "pin": ["PA8"]},
                                                              {"id": "R7", "type": "pwm", "pin": "PA9", "signal": "TIM1_CH2", "freq_hz": 1000, "tol_pct": None},
                                                              {"id": "R8", "type": "pwm", "pin": "PA10", "signal": "TIM1_CH3", "freq_hz": 2000, "tol_pct": None}]})
    out = bs.run_drc()
    assert out["complete"] is False and "REQ_INVALID:R6" in [v["code"] for v in out["violations"]]
    r = bs.set_requirements([{"id": "R9", "type": "gpio_in", "pin": "PB0"}])                    # kể cả _timer_contradictions (tol_pct None) cũng không ném
    assert r["ok"]


# --- mục 11: số không hữu hạn / vô lý
@pytest.mark.parametrize("vdd", [float("nan"), float("inf"), -float("inf"), 0, -3.3, True, "3.3", 61])
def test_set_target_rejects_non_finite_or_absurd_vdd(bs, vdd):
    r = bs.set_target("stm32g474", "LQFP64", vdd)
    assert r["ok"] is False and r["error"]["code"] == "INVALID_TARGET" and head(bs) == 0


def test_set_target_rejects_a_non_string_package(bs):
    assert bs.set_target("stm32g474", 64, 3.3)["error"]["code"] == "INVALID_TARGET" and head(bs) == 0


@pytest.mark.parametrize("field, value", [("i_typ_ua", float("nan")), ("i_typ_ua", float("inf")), ("i_typ_ua", -4.0), ("vin_max", float("inf")), ("vin_max", 0), ("vin_max", -1.0),
                                          ("io_vdd", float("nan")), ("io_vdd", 0), ("vih_min", float("nan")), ("vil_max", -0.5), ("voh_min", float("inf")), ("vol_max", float("nan")),
                                          ("i_ua_by_mode", {"sleep": float("nan")}), ("i_ua_by_mode", {"sleep": -1}), ("io_vdd_by_pin", {"B1": float("inf")}), ("io_vdd_by_pin", {"B1": 0})])
def test_add_device_rejects_non_finite_or_negative_numbers(bs, field, value):
    r = bs.add_device("U2", "BME280", 1.8, "I2C", **{field: value})
    assert r["ok"] is False and r["error"]["code"] == "INVALID_DEVICE" and head(bs) == 0
    assert bs.add_device("U2", "BME280", float("nan"), "I2C")["error"]["code"] == "INVALID_DEVICE"


def test_add_device_rejects_ids_that_clash_with_the_chip_or_differ_only_by_case(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    assert bs.add_device("stm32g474", "x", 3.3, "I2C")["error"]["code"] == "INVALID_DEVICE"
    assert bs.add_device("STM32G474", "x", 3.3, "I2C")["error"]["code"] == "INVALID_DEVICE"
    assert bs.add_device("U2", "BME280", 1.8, "I2C")["ok"]
    r = bs.add_device("u2", "BME280", 3.3, "I2C")
    assert r["error"]["code"] == "INVALID_DEVICE" and "U2" in r["error"]["message"]
    assert bs.add_device("U2", "BME280", 3.3, "I2C")["ok"] and len(bs.get_board_state("devices")["data"]) == 1                # cùng id chính xác: cập nhật


# --- mục 12: set_clock_config không ném
@pytest.mark.parametrize("cfg", [{"source": "HSE", "hse_hz": float("nan")}, {"source": "HSE", "hse_hz": float("inf")}, {"source": "PLL", "pll": "x"}, {"source": "HSI16", "ahb_div": [1]},
                                 {"source": "HSI16", "voltage_range": ["range2"]}, {"source": "HSI16", "enabled_peripherals": 5}, {"source": "PLL", "pll": [1]}, {"source": 5}])
def test_set_clock_config_bad_types_are_errors_not_exceptions(bs, cfg):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    h = head(bs)
    r = bs.set_clock_config(cfg)
    assert r["ok"] is False and r["error"]["code"] == "INVALID_CLOCK_CONFIG" and head(bs) == h
    json.dumps(r)


def test_set_clock_config_range2_low_frequency_is_clean_and_recorded(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    r = bs.set_clock_config({"source": "HSE", "hse_hz": 8_000_000, "voltage_range": "range2"})
    assert r["ok"] and r["violations"] == [] and r["derived"]["flash_latency"] == 0
    assert bs.run_drc()["summary"]["DRC-CLK-01"]["status"] == "pass"


# --- mục 3: tín hiệu hướng 'in' trên chân input-only
def test_input_function_on_an_input_only_pin_passes_allocate_and_the_drc(bs):
    """ESP32 Datasheet p.61: GPIO34–39 chỉ nhập. U1RXD/U2RXD/ADC là tín hiệu vào => cả allocate_pin lẫn DRC-PIN-03 phải chấp nhận."""
    bs.set_target("esp32", None, 3.3)
    for pin, sig in (("GPIO34", "U1RXD"), ("GPIO35", "U2RXD"), ("GPIO36", "ADC1_CH0")):
        r = bs.allocate_pin(pin, sig, "R1")
        assert r["ok"], r
    out = bs.run_drc()
    assert out["summary"]["DRC-PIN-03"]["status"] == "pass", [v for v in out["violations"] if v["rule"] == "DRC-PIN-03"]
    assert bs.get_board_state("pins")["data"]["GPIO34"]["mode"] == "AF_IN"
    assert bs.allocate_pin("GPIO39", "U2TXD", "R2")["error"]["code"] == "INPUT_ONLY"             # tín hiệu ra vẫn bị từ chối
    # tín hiệu chưa biết hướng trên chân input-only: không được tự nhận AF_PP rồi báo lỗi; DRC nói 'unknown'
    r = bs.allocate_pin("GPIO38", "FOO_BAR", "R3")
    assert r["ok"] and r["mode"] is None
    out = bs.run_drc()
    assert [v["code"] for v in out["violations"] if v["rule"] == "DRC-PIN-03"] == ["INPUT_ONLY_UNVERIFIED:GPIO38"] and out["ok"]


def test_stm32_default_modes_keep_their_alternate_function_semantics(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    assert bs.allocate_pin("PA8", "TIM1_CH1", "R1")["mode"] == "AF_PP"
    assert bs.allocate_pin("PA9", "USART1_TX", "R2")["mode"] == "AF_PP" and bs.allocate_pin("PA10", "USART1_RX", "R2")["mode"] == "AF_IN"
    assert bs.allocate_pin("PB7", "I2C1_SDA", "R3")["mode"] == "AF_OD" and bs.allocate_pin("PA0", "ADC12_IN1", "R4")["mode"] == "ANALOG"


# --- mục 15: các điểm hở rẻ
def test_the_same_signal_cannot_be_routed_to_two_pins(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    assert bs.allocate_pin("PA8", "I2C3_SCL", "R1")["ok"]
    h = head(bs)
    for owner in ("R1", "R2"):
        r = bs.allocate_pin("PC8", "I2C3_SCL", owner)
        e = r["error"]
        assert not r["ok"] and e["code"] == "SIGNAL_ALREADY_ROUTED" and e["current"]["pin"] == "PA8" and e["current"]["owner"] == "R1", r
    assert head(bs) == h
    assert bs.release_pin("PA8")["ok"] and bs.allocate_pin("PC8", "I2C3_SCL", "R1")["ok"]                       # release trước thì đổi chân được
    assert bs.allocate_pin("PB0", "GPIO_OUT", "R5")["ok"] and bs.allocate_pin("PB1", "GPIO_OUT", "R6")["ok"]    # tín hiệu GPIO chung dùng nhiều chân được
    assert bs.set_target("esp32", None, 3.3, project_id="esp")["ok"]
    assert bs.allocate_pin("GPIO17", "U1TXD", "R7", project_id="esp")["ok"] and bs.allocate_pin("GPIO18", "U1TXD", "R7", project_id="esp")["ok"]    # ESP32 (GPIO matrix): một tín hiệu ra tới nhiều chân hợp lệ


def test_reallocating_a_pin_with_another_mode_is_not_reported_as_unchanged(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    assert bs.allocate_pin("PB0", "GPIO", "R1", mode="output")["ok"]
    assert bs.allocate_pin("PB0", "GPIO", "R1", mode="output")["unchanged"] is True
    assert bs.allocate_pin("PB0", "GPIO", "R1")["unchanged"] is True                                            # không nêu mode: không đổi gì
    r = bs.allocate_pin("PB0", "GPIO", "R1", mode="input")
    assert not r["ok"] and r["error"]["code"] == "CONFLICT" and "release_pin" in r["error"]["message"]
    assert bs.get_board_state("pins")["data"]["PB0"]["mode"] == "output"


@pytest.mark.parametrize("pid", ["   ", "\t", 5, ["x"]])
def test_blank_or_non_string_project_ids_are_rejected(bs, pid):
    for call in (lambda: bs.get_board_state(project_id=pid), lambda: bs.set_target("stm32g474", None, 3.3, project_id=pid), lambda: bs.run_drc(project_id=pid)):
        r = call()
        assert r["ok"] is False and r["error"]["code"] == "INVALID_PROJECT_ID"
    assert B.EventStore(os.environ["BOARD_STATE_DB"]).projects() == []


def test_set_requirements_description_mentions_the_shared_key(bs):
    d = tools(bs)["set_requirements"].description
    assert "shared" in d and "type" in d


# --- mục 9, 16: connect
def test_connect_to_a_pin_without_an_input_limit_in_the_database_is_not_passed(bs):
    """PG10 (NRST) là 'other pins': 4.0 V (Table 14 p.82). 5 V vào đó bị chặn, không được PASS."""
    bs.set_target("stm32g474", "LQFP64", 3.3)
    bs.add_device("US1", "HC-SR04", 5.0, "digital")
    r = bs.connect("US1.ECHO", "stm32g474.PG10", "digital")
    assert not r["ok"] and not r["recorded"] and r["error"]["code"] == "NOT_5V_TOLERANT:PG10"
    assert bs.connect("US1.ECHO", "stm32g474.PB4", "digital")["ok"]                                              # PB4 là FT_c: 5.0 V


def test_connect_analog_to_an_adc_pin_checks_the_adc_input_range(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    bs.add_device("S5", "5V sensor", 5.0, "analog")
    bs.add_device("S3", "3V3 sensor", 3.3, "analog")
    bs.add_device("S4", "3V4 sensor", 3.4, "analog")
    h = head(bs)
    r = bs.connect("S5.OUT", "stm32g474.PA2", "analog")                                                          # PA2 = FT_a + ADC1_IN3: chịu 5 V nhưng vượt dải ADC
    assert not r["ok"] and not r["recorded"] and r["error"]["code"] == "ADC_RANGE:PA2" and r["error"]["suggestions"], r
    r = bs.connect("S4.OUT", "stm32g474.PA2", "analog")
    assert not r["ok"] and not r["recorded"] and r["error"]["code"] == "LEVEL_DATA_UNKNOWN" and r["level_check"]["status"] == "UNKNOWN", r
    assert head(bs) == h
    r = bs.connect("S3.OUT", "stm32g474.PA2", "analog")
    assert r["ok"] and r["recorded"] and any("VDDA" in a for a in r["level_check"]["assumptions"])
    assert bs.connect("S5.OUT", "stm32g474.PB7", "digital")["ok"]                                               # PB7 FT_f, không ADC


def test_connect_ft_pin_above_vdd_plus_0v3_reports_the_pull_resistor_footnote(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    bs.add_device("US1", "HC-SR04", 5.0, "digital")
    r = bs.connect("US1.ECHO", "stm32g474.PB7", "digital")
    assert r["ok"] and any("pull-up" in n and "Table 17" in n for n in r["level_check"]["notes"]), r["level_check"]
    bs.add_device("U3", "3V3 part", 3.3, "digital")
    assert bs.connect("U3.OUT", "stm32g474.PB7", "digital")["level_check"]["notes"] == []


def test_errors_are_values_for_nested_and_odd_inputs(bs):
    bs.set_target("stm32g474", "LQFP64", 3.3)
    calls = [lambda: bs.set_requirements([{"id": "R1", "type": "pwm", "pin": ["PA8"]}]), lambda: bs.set_requirements([None]), lambda: bs.set_requirements({"id": "R1"}),
             lambda: bs.set_clock_config({"source": "PLL", "pll": 3}), lambda: bs.set_clock_config(None), lambda: bs.set_clock_config("[]"),
             lambda: bs.add_device("U1", "x", float("nan"), "I2C"), lambda: bs.add_device(5, "x", 3.3, "I2C"), lambda: bs.allocate_pin(None, "X", "o"),
             lambda: bs.connect("a.b", "c.d", None), lambda: bs.record_decision("q", None, "x"), lambda: bs.get_power_budget(5), lambda: bs.diff(None, None), lambda: bs.rollback(None)]
    for call in calls:
        out = call()
        assert out["ok"] is False and "code" in out["error"]
        json.dumps(out)
    assert head(bs) == 1


def test_set_clock_config_safety_net_turns_an_unexpected_evaluation_failure_into_an_error(bs, monkeypatch):
    from hwmodel import drc as drc_mod
    bs.set_target("stm32g474", "LQFP64", 3.3)
    h = head(bs)
    monkeypatch.setattr(drc_mod, "evaluate_clock_config", lambda cfg, hw=None: {}["missing"])
    r = bs.set_clock_config({"source": "HSI16"})
    assert r["ok"] is False and r["error"]["code"] == "INVALID_CLOCK_CONFIG" and "KeyError" in r["error"]["message"] and head(bs) == h
