"""MCP server hw-sandbox: 4 tool (solve_timer_config, simulate_register_writes, analyze_c_code, compile_check), quyền `sandboxed-exec`,
giới hạn kích thước/thời gian, chạy được inproc và stdio. Đăng ký vào danh sách server của ToolHub từ P4."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

import config
from agent import tools as hub_mod
from mcp_servers import hw_sandbox_server as sb
from hwmodel_helpers import MOD, PWM_PA8

AGENT_DIR = Path(__file__).resolve().parents[1]
PWM_C = """
#include <stm32g4xx.h>
int main(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8) | GPIO_MODER_MODE8_1;
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL8) | (6U << GPIO_AFRH_AFSEL8_Pos);
    TIM1->PSC = 0; TIM1->ARR = 8499; TIM1->CCR1 = 2125;
    TIM1->CCMR1 = (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER = TIM_CCER_CC1E; TIM1->BDTR = TIM_BDTR_MOE; TIM1->CR1 = TIM_CR1_CEN;
    while (1) { }
}
"""


def tools():
    return {t.name: t for t in asyncio.run(sb.mcp.list_tools())}


def test_server_exposes_exactly_the_four_tools_with_documented_parameters():
    t = tools()
    assert set(t) == {"solve_timer_config", "simulate_register_writes", "analyze_c_code", "compile_check"}
    assert all(len(x.description) > 80 for x in t.values())
    assert {"chip", "timer", "target_hz", "duty_pct", "channel", "tim_clk_hz", "pclk_hz", "apb_prescaler"} <= set(t["solve_timer_config"].inputSchema["properties"])
    assert {"chip", "ops", "initial", "hse_hz"} <= set(t["simulate_register_writes"].inputSchema["properties"])
    assert {"code", "chip"} <= set(t["analyze_c_code"].inputSchema["properties"])
    assert {"code", "chip"} <= set(t["compile_check"].inputSchema["properties"])


def test_permissions_are_sandboxed_exec_and_the_server_is_registered_from_p4():
    names = {"solve_timer_config", "simulate_register_writes", "analyze_c_code", "compile_check"}
    for name in names:
        assert hub_mod.PERMISSIONS[name] == "sandboxed-exec"
    assert "hw-sandbox" in hub_mod.SERVERS                          # P4 (D32): đăng ký vào ToolHub; S2D là snapshot P1 nên không bị ảnh hưởng
    hub = hub_mod.ToolHub(transport="inproc", session_id="t")
    assert names <= set(hub.tool_names())
    assert not names & set(hub_mod.ToolHub(transport="inproc", disabled_servers=("hw-sandbox",)).tool_names())


def test_solve_timer_config_tool():
    r = sb.solve_timer_config("stm32g474", "TIM1", 20000, 25, 1, tim_clk_hz=170_000_000)
    assert r["ok"] and r["registers"] == {"TIM1_PSC": 0, "TIM1_ARR": 8499, "TIM1_CCR1": 2125}
    r = sb.solve_timer_config("stm32g474", "TIM1", 20000, 25, 1, pclk_hz=85_000_000, apb_prescaler=2)
    assert r["tim_clk_hz"] == 170_000_000


def test_simulate_register_writes_tool_runs_the_reference_sequence():
    r = sb.simulate_register_writes("stm32g474", PWM_PA8, initial="sysclk_170mhz_pll_hsi16_apb_div1")
    pwm = [e for e in r["effects"] if e["kind"] == "pwm"][0]
    assert pwm["pin"] == "PA8" and pwm["pwm_hz"] == 20_000.0 and r["ok"]


def test_ops_may_be_given_as_a_json_string():
    r = sb.simulate_register_writes("stm32g474", json.dumps(PWM_PA8[:2]), initial="reset")
    assert r["n_ops"] == 2 and r["violations"] == []


def test_simulate_reports_a_classic_error_with_its_code():
    ops = [op for i, op in enumerate(PWM_PA8) if i != 9]            # thiếu MOE
    r = sb.simulate_register_writes("stm32g474", ops, initial="sysclk_170mhz_pll_hsi16_apb_div1")
    assert [v["code"] for v in r["violations"] if v["severity"] == "error"] == ["SIM-TIM-MOE"]


def test_analyze_c_code_tool_then_simulate_end_to_end():
    a = sb.analyze_c_code(PWM_C)
    assert a["ok"] and a["complete"]
    r = sb.simulate_register_writes("stm32g474", a["ops"], initial="sysclk_170mhz_pll_hsi16_apb_div1")
    assert r["ok"] and [e for e in r["effects"] if e["kind"] == "pwm"][0]["duty_pct"] == 25.0


def test_compile_check_tool():
    assert sb.compile_check(PWM_C)["status"] == "ok"
    assert sb.compile_check("int main(void){ int x = ; }")["status"] == "error"
    assert sb.compile_check("int main(void){return 0;}", "esp32")["status"] == "skipped"


def test_bad_input_returns_an_error_dict_not_an_exception():
    assert "error" in sb.simulate_register_writes("stm32g474", [{"op": "toggle", "reg": "TIM1_PSC", "value": 1}])
    assert "error" in sb.simulate_register_writes("atmega", [])
    assert "error" in sb.simulate_register_writes("stm32g474", "not json")
    assert "error" in sb.simulate_register_writes("stm32g474", [], initial="sysclk_999")
    assert "error" in sb.simulate_register_writes("stm32g474", [{"op": "write", "value": 1}])


def test_size_limits():
    big = [{"op": "write", "reg": "TIM1_PSC", "value": 0}] * (sb.MAX_OPS + 1)
    assert "too many ops" in sb.simulate_register_writes("stm32g474", big)["error"]
    assert "error" in sb.analyze_c_code("x" * (sb.MAX_CODE_BYTES + 1))
    assert sb.compile_check("x" * (sb.MAX_CODE_BYTES + 1))["status"] == "error"


def test_a_slow_call_is_cut_by_the_timeout(monkeypatch):
    import time
    monkeypatch.setattr(sb, "TIMEOUT_S", 0.2)
    monkeypatch.setattr(sb, "_simulate", lambda *a, **k: time.sleep(2))
    r = sb.simulate_register_writes("stm32g474", [])
    assert "timed out" in r["error"]


def test_results_are_json_serialisable():
    json.dumps(sb.simulate_register_writes("stm32g474", PWM_PA8, initial="reset"))
    json.dumps(sb.analyze_c_code(PWM_C))


def test_stdio_transport_serves_the_same_tools():
    mcp = pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        env = {"AGENT_DOTENV": "0", "LLM_API_KEY": "", "PATH": os.environ.get("PATH", "")}
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_servers.hw_sandbox_server"], cwd=str(AGENT_DIR), env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool("solve_timer_config", arguments={"chip": "stm32g474", "timer": "TIM1", "target_hz": 20000, "duty_pct": 25,
                                                                         "channel": 1, "tim_clk_hz": 170000000})
                return names, json.loads(res.content[0].text)

    names, out = asyncio.run(asyncio.wait_for(go(), 120))
    assert names == {"solve_timer_config", "simulate_register_writes", "analyze_c_code", "compile_check"}
    assert out["registers"]["TIM1_ARR"] == 8499
