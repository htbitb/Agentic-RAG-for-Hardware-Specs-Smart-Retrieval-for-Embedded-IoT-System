"""Đường chạy thật của agent v1 với DỮ LIỆU P1 (vòng lặp/guardrail/verifier KHÔNG đổi — D10): guardrail phần cứng vẫn
từ chối đúng; verifier chấp nhận câu trả lời trích dẫn từ kết quả tool; không còn hằng số mô phỏng trên đường chạy."""
import pytest

import config
from agent.llm import LLMResponse
from agent.react_agent import HardwareAgent
from agent.verifier import verify

pytestmark = pytest.mark.skipif(not (config.HW_DB.is_file() and config.TEXT_INDEX_DB.is_file()),
                                reason="data/hw_specs.sqlite and data/text_index.* not built")


class StubLLM:
    simulated = False
    name = "stub"

    def __init__(self, script=None):
        self.script, self.calls = list(script or []), 0

    def chat(self, messages, tools, seed=None):
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        return LLMResponse("Insufficient evidence: stub model.", [], {"in": 1, "out": 1})


@pytest.fixture(scope="module")
def agent():
    a = HardwareAgent(transport="inproc", llm=StubLLM())
    yield a
    a.close()


@pytest.mark.parametrize("question,doc,page", [
    ("Can I apply 5 V to the VDD pin of the STM32G474?", "STM32G474_Datasheet", 82),
    ("I want to connect 5 V to GPIO4 on an ESP32, is that OK?", "ESP32_Datasheet", 52),
    ("Is it fine to feed 5 V to the VDD supply of an nRF52840?", "nRF52840_PS", 972),
])
def test_hardware_guardrail_still_refuses_overvoltage_with_real_data(agent, question, doc, page):
    res = agent.ask(question, session_id="t1")
    assert res["status"] == "refused"
    assert f"[{doc} p.{page}]" in res["answer"]
    assert agent.llm.calls == 0                         # từ chối bằng mã, không gọi LLM


def test_within_limits_request_is_not_refused(agent):
    before = agent.llm.calls
    res = agent.ask("Can I apply 3.3 V to the VDD pin of the ESP32?", session_id="t2")
    assert res["status"] == "answered" and agent.llm.calls > before


def test_known_limitation_guardrail_is_conservative_across_stm32_pin_types(agent):
    """evaluate_hw lấy MIN trên mọi hàng input_voltage (FT_xxx 7.3, FT_c 5.5, TT 4.0, khác 4.0) nên 5 V vào chân FT_a (chịu
    5 V) vẫn bị từ chối. Quá bảo thủ, không sửa ở P1 (D10) — ghi nhận cho P6."""
    res = agent.ask("Can I apply 5 V to the PA8 pin of the STM32G474?", session_id="t3")
    assert res["status"] == "refused" and "4.0 V" in res["answer"]


def test_tool_observation_feeds_the_verifier_end_to_end():
    reply = [
        LLMResponse(None, [{"id": "c1", "name": "get_register_bitfields",
                            "arguments": {"chip": "stm32g474", "peripheral": "TIM1", "register": "CR1"}}], {"in": 1, "out": 1}),
        LLMResponse("TIM1_CR1 is at 0x40012C00 [STM32G474_RM0440 p.1235].", [], {"in": 1, "out": 1}),
    ]
    a = HardwareAgent(transport="inproc", llm=StubLLM(reply))
    try:
        res = a.ask("What is the address of TIM1_CR1 on the STM32G474?", session_id="t4")
        assert res["status"] == "answered" and res["verification"]["passed"] and not res["verification"]["abstained"]
    finally:
        a.close()


def test_verifier_rejects_a_citation_page_that_no_tool_returned():
    obs = [{"registers": [{"address": "0x40012C00", "doc": "STM32G474_RM0440", "page": 1235}]}]
    v = verify("address of TIM1_CR1?", "It is 0x40012C00 [STM32G474_RM0440 p.817].", obs)
    assert not v["passed"] and any("V3" in i for i in v["issues"])


def test_search_manual_results_are_citable_by_the_verifier(agent):
    res = agent.hub.call("search_manual", {"query": "RTC wakeup timer register WUTR", "chip": "stm32g474", "k": 3})
    hit = res["results"][0]
    ans = f"See [{hit['doc']} p.{hit['page_start']}]."
    assert verify("where is the wakeup timer register?", ans, [res])["passed"]


def test_no_simulated_constants_remain_on_the_running_path():
    import mcp_servers.hw_knowledge_server as hk
    import mcp_servers.text_manual_server as tm
    for mod in (hk, tm):
        for name in ("PINOUT", "REGISTERS", "ELECTRICAL", "CHUNKS", "DOCUMENTS"):
            assert not hasattr(mod, name), f"{mod.__name__}.{name} is a leftover simulated constant"


def test_nrf_pin_guardrail_uses_the_absolute_maximum_not_the_logic_high_range(agent):
    """3.5 V trên chân nRF ở VDD 3.3 V nằm trong VDD+0.3 = 3.6 V (PS Table 101): không được từ chối; 5 V thì có (và trích p.972)."""
    ok = agent.ask("Can I apply 3.5 V to the P0.05 pin of the nRF52840?", session_id="t5")
    assert ok["status"] == "answered"
    bad = agent.ask("Can I apply 5 V to the P0.05 pin of the nRF52840?", session_id="t6")
    assert bad["status"] == "refused" and "3.6 V" in bad["answer"] and "[nRF52840_PS p.972]" in bad["answer"]
