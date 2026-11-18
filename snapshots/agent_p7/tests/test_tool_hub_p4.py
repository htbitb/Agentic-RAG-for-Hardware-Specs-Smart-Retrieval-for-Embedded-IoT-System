"""P4 / D32: ToolHub đăng ký hw-sandbox + board-state, chỉ retry tool read-only, cô lập project_id của Board State, ẩn server theo cờ ablation."""
import pytest

from agent import tools as hub_mod
from agent.tools import PERMISSIONS, SERVERS, ToolHub

SANDBOX = {"solve_timer_config", "simulate_register_writes", "analyze_c_code", "compile_check"}
BOARD = {"get_board_state", "set_target", "set_requirements", "allocate_pin", "release_pin", "set_clock_config", "add_device", "connect",
         "get_power_budget", "run_drc", "record_decision", "diff", "rollback"}


@pytest.fixture()
def empty_hub(monkeypatch):
    """Hub không nạp server nào: tool giả được gắn tay để thử chính sách retry."""
    monkeypatch.setattr(hub_mod.time, "sleep", lambda s: None)
    return ToolHub(transport="inproc", disabled_servers=tuple(SERVERS))


def _install(hub, monkeypatch, name, perm, fn):
    monkeypatch.setitem(PERMISSIONS, name, perm)
    hub.owner[name] = "fake"
    hub._fn[name] = fn


def _flaky(failures, side_effects):
    """Ghi (side effect) rồi ném lỗi `failures` lần đầu: mô phỏng timeout SAU khi đã ghi."""
    def fn(**kw):
        side_effects.append(kw)
        if len(side_effects) <= failures:
            raise TimeoutError("late timeout after the write")
        return {"ok": True, "n": len(side_effects)}
    return fn


def test_read_only_tool_is_retried_until_it_succeeds(empty_hub, monkeypatch):
    log = []
    _install(empty_hub, monkeypatch, "fake_read", "read-only", _flaky(2, log))
    res = empty_hub.call("fake_read", {"a": 1})
    assert res["ok"] and len(log) == 3 and empty_hub.stats["retries"] == 2


def test_a_bad_argument_error_is_deterministic_and_is_not_retried_even_for_read_only(empty_hub, monkeypatch):
    log = []

    def fn(**kw):
        log.append(kw)
        raise TypeError("fake_read() got an unexpected keyword argument 'reason'")

    _install(empty_hub, monkeypatch, "fake_read", "read-only", fn)
    res = empty_hub.call("fake_read", {"reason": "x"})
    assert len(log) == 1 and "unexpected keyword argument" in res["error"] and empty_hub.stats["retries"] == 0


@pytest.mark.parametrize("perm", ["state-mutating", "sandboxed-exec", "control"])
def test_non_read_only_tool_is_never_retried(empty_hub, monkeypatch, perm):
    """Timeout sau khi ghi rồi retry sẽ nhân đôi sự kiện (D32): đúng MỘT lần gọi, lỗi được trả cho agent."""
    log = []
    _install(empty_hub, monkeypatch, "fake_write", perm, _flaky(1, log))
    res = empty_hub.call("fake_write", {"a": 1})
    assert len(log) == 1 and "TimeoutError" in res["error"] and empty_hub.stats["retries"] == 0 and res["retries"] == 0


def test_board_state_write_is_not_duplicated_by_a_timeout(monkeypatch):
    """Kiểm bằng tool THẬT: record_decision ghi xong rồi hạ tầng ném timeout; hub không gọi lại => đúng một sự kiện."""
    monkeypatch.setattr(hub_mod.time, "sleep", lambda s: None)
    hub = ToolHub(transport="inproc", disabled_servers=("text-manual", "hw-knowledge", "hw-sandbox"), session_id="t-retry")
    hub.project_id = "retry-proj"
    real = hub._fn["record_decision"]
    calls = []

    def write_then_timeout(**kw):
        calls.append(kw)
        real(**kw)
        raise TimeoutError("response lost")

    hub._fn["record_decision"] = write_then_timeout
    assert hub.call("set_target", {"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3})["ok"]
    res = hub.call("record_decision", {"question": "q", "options": ["a", "b"], "chosen": "a"})
    assert "TimeoutError" in res["error"] and len(calls) == 1
    decisions = hub.call("get_board_state", {"section": "decisions"})["data"]
    assert [d["id"] for d in decisions] == ["D1"]


def test_servers_and_permissions_for_the_four_servers():
    assert set(SERVERS) == {"text-manual", "hw-knowledge", "hw-sandbox", "board-state"}
    hub = ToolHub(transport="inproc", session_id="t")
    names = set(hub.tool_names())
    assert SANDBOX <= names and BOARD <= names and "naive_search" not in names
    assert all(PERMISSIONS[n] == "sandboxed-exec" for n in SANDBOX)
    assert all(hub.owner[n] == "hw-sandbox" for n in SANDBOX) and all(hub.owner[n] == "board-state" for n in BOARD)
    assert PERMISSIONS["update_plan"] == "control" and PERMISSIONS["finish"] == "control"


@pytest.mark.parametrize("server,hidden", [("hw-sandbox", SANDBOX), ("board-state", BOARD)])
def test_disabling_a_server_hides_its_tools(server, hidden):
    hub = ToolHub(transport="inproc", disabled_servers=(server,))
    assert not hidden & set(hub.tool_names()) and not hidden & set(hub.owner)
    assert "tool" in hub.call(sorted(hidden)[0], {})["error"]


def test_board_state_tools_do_not_show_project_id_to_the_model():
    hub = ToolHub(transport="inproc", session_id="t")
    specs = {s["name"]: s for s in hub.specs}
    assert all("project_id" not in specs[n]["inputSchema"]["properties"] for n in BOARD)
    assert all("project_id" not in specs[n]["inputSchema"].get("required", []) for n in BOARD)


def test_board_state_is_scoped_to_the_hubs_project_and_cannot_be_redirected():
    a = ToolHub(transport="inproc", disabled_servers=("text-manual", "hw-knowledge", "hw-sandbox"))
    b = ToolHub(transport="inproc", disabled_servers=("text-manual", "hw-knowledge", "hw-sandbox"))
    a.project_id, b.project_id = "proj-a", "proj-b"
    assert a.call("set_target", {"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3})["ok"]
    assert b.call("get_board_state", {"section": "targets"})["data"] == []
    assert a.call("get_board_state", {"section": "targets"})["data"][0]["chip"] == "stm32g474"
    # tham số project_id do mô hình tự gửi bị ghi đè bởi project của hub
    assert b.call("get_board_state", {"section": "targets", "project_id": "proj-a"})["data"] == []


def test_the_v1_agent_keeps_its_old_toolset_by_default():
    from agent.react_agent import HardwareAgent
    from agent.llm import LLMResponse

    class Stub:
        simulated = True
        name = "stub"

        def chat(self, messages, tools, seed=None):
            return LLMResponse("x", [], {"in": 1, "out": 1})

    a = HardwareAgent(transport="inproc", llm=Stub())
    try:
        assert not (SANDBOX | BOARD) & set(a.hub.tool_names())
    finally:
        a.close()


def test_internal_calls_are_not_counted_as_agent_tool_calls():
    hub = ToolHub(transport="inproc", disabled_servers=("text-manual", "hw-knowledge", "hw-sandbox"))
    hub.project_id = "internal-proj"
    hub.call("get_board_state", {})
    hub.call("get_board_state", {}, internal=True)
    assert hub.stats["calls"] == 2 and hub.stats["agent_calls"] == 1


# ---------------------------------------------------------------- tham số lạ do mô hình tự thêm (pilot: run_drc(reason=...) gây TypeError 17 lần)
def test_unknown_arguments_are_dropped_and_reported_instead_of_crashing_the_tool():
    hub = ToolHub(transport="inproc", disabled_servers=("text-manual", "hw-knowledge", "hw-sandbox"))
    hub.project_id = "unknown-args"
    res = hub.call("run_drc", {"reason": "check the design"})
    assert "error" not in res and res["ok"] in (True, False) and res["ignored_arguments"] == ["reason"]
    res = hub.call("run_drc", {})
    assert "ignored_arguments" not in res


def test_a_real_argument_error_is_still_reported_when_a_required_argument_is_missing():
    hub = ToolHub(transport="inproc", disabled_servers=("text-manual", "hw-sandbox", "board-state"))
    res = hub.call("get_register_bitfields", {"periferal": "TIM1"})
    assert "error" in res and res.get("ignored_arguments") == ["periferal"]


def test_arguments_listed_in_the_schema_are_never_dropped():
    hub = ToolHub(transport="inproc", disabled_servers=("text-manual", "hw-sandbox", "board-state"))
    res = hub.call("list_chips", {})
    assert "error" not in res and "ignored_arguments" not in res
