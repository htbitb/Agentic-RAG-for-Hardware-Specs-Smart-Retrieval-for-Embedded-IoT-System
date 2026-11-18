"""Board State (W2): sự kiện bất biến (event-sourced), trạng thái = fold thuần các sự kiện, diff, snapshot, rollback (là sự kiện mới).

Không cần DB phần cứng: lõi này chỉ lưu và gộp sự kiện; việc kiểm tra (AF, giới hạn, mức logic) thuộc server và DRC."""
import copy
import json
import sqlite3

import pytest

from hwmodel import board_state as B


def ev(version, type_, payload, actor="agent"):
    return {"version": version, "ts": f"2026-10-22T10:00:{version:02d}+00:00", "actor": actor, "type": type_, "payload": payload}


TARGET = ("target_set", {"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3})
PA8 = ("pin_allocated", {"pin": "PA8", "chip": "stm32g474", "signal": "TIM1_CH1", "af": 6, "peripheral": "TIM1", "owner": "R1", "mode": "AF_PP", "shared": False})
PB8 = ("pin_allocated", {"pin": "PB8", "chip": "stm32g474", "signal": "I2C3_SCL", "af": 8, "peripheral": "I2C3", "owner": "R2", "mode": "AF_OD", "shared": False})


def events(*pairs):
    return [ev(i + 1, t, p) for i, (t, p) in enumerate(pairs)]


# ----------------------------------------------------------------------------------------------- fold
def test_empty_state_has_every_section_of_the_plan_model():
    s = B.empty_state("demo")
    assert s["project_id"] == "demo" and s["version"] == 0
    assert set(s) == {"project_id", "version", *B.SECTIONS}
    assert s["pins"] == {} and s["peripherals"] == {} and s["targets"] == [] and s["clock"] is None


def test_fold_is_pure_and_deterministic():
    evs = events(TARGET, PA8, PB8)
    before = copy.deepcopy(evs)
    s1, s2 = B.fold("demo", evs), B.fold("demo", evs)
    assert s1 == s2 and evs == before                       # không đổi đầu vào
    assert s1 is not s2                                      # mỗi lần trả bản mới
    s1["pins"]["PA8"]["owner"] = "hacked"
    assert B.fold("demo", evs)["pins"]["PA8"]["owner"] == "R1"
    assert s2["version"] == 3


def test_target_pin_and_peripheral_registry():
    s = B.fold("demo", events(TARGET, PA8, PB8))
    assert s["targets"] == [{"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3}]
    assert s["pins"]["PA8"] == {"chip": "stm32g474", "signal": "TIM1_CH1", "af": 6, "owner": "R1", "mode": "AF_PP", "shared_with": []}
    assert s["peripherals"]["TIM1"]["owners"] == ["R1"] and s["peripherals"]["TIM1"]["signals"] == {"PA8": "TIM1_CH1"}
    assert s["peripherals"]["I2C3"]["owners"] == ["R2"]
    assert s["peripherals"]["TIM1"]["clock_enabled"] is None          # chưa khai báo cấu hình clock


def test_second_target_with_same_chip_replaces_and_other_chip_appends():
    s = B.fold("demo", events(TARGET, ("target_set", {"chip": "stm32g474", "package": "LQFP100", "vdd": 3.0}),
                              ("target_set", {"chip": "esp32", "package": None, "vdd": 3.3})))
    assert [(t["chip"], t["package"], t["vdd"]) for t in s["targets"]] == [("stm32g474", "LQFP100", 3.0), ("esp32", None, 3.3)]


def test_release_pin_removes_it_and_empties_the_peripheral():
    s = B.fold("demo", events(TARGET, PA8, ("pin_released", {"pin": "PA8"})))
    assert s["pins"] == {} and "TIM1" not in s["peripherals"]


def test_peripheral_keeps_other_pins_after_one_is_released():
    ch2 = ("pin_allocated", {"pin": "PA9", "chip": "stm32g474", "signal": "TIM1_CH2", "af": 6, "peripheral": "TIM1", "owner": "R3", "mode": "AF_PP", "shared": False})
    s = B.fold("demo", events(TARGET, PA8, ch2, ("pin_released", {"pin": "PA8"})))
    assert s["peripherals"]["TIM1"]["owners"] == ["R3"] and s["peripherals"]["TIM1"]["signals"] == {"PA9": "TIM1_CH2"}


def test_two_owners_on_one_peripheral_are_both_listed_in_allocation_order():
    ch2 = ("pin_allocated", {"pin": "PA9", "chip": "stm32g474", "signal": "TIM1_CH2", "af": 6, "peripheral": "TIM1", "owner": "R3", "mode": "AF_PP", "shared": False})
    s = B.fold("demo", events(TARGET, PA8, ch2))
    assert s["peripherals"]["TIM1"]["owners"] == ["R1", "R3"]


def test_shared_bus_pin_records_second_owner_without_replacing_the_first():
    sda1 = ("pin_allocated", {"pin": "PB7", "chip": "stm32g474", "signal": "I2C1_SDA", "af": 4, "peripheral": "I2C1", "owner": "bus-i2c1", "mode": "AF_OD", "shared": True})
    sda2 = ("pin_allocated", {"pin": "PB7", "chip": "stm32g474", "signal": "I2C1_SDA", "af": 4, "peripheral": "I2C1", "owner": "U3-sensor", "mode": "AF_OD", "shared": True})
    s = B.fold("demo", events(TARGET, sda1, sda2))
    assert s["pins"]["PB7"]["owner"] == "bus-i2c1" and s["pins"]["PB7"]["shared_with"] == ["U3-sensor"]
    s = B.fold("demo", events(TARGET, sda1, sda2, ("pin_released", {"pin": "PB7"})))
    assert s["pins"] == {}


def test_requirements_upsert_by_id_keeps_order():
    r1 = {"id": "R1", "type": "pwm", "pin": "PA8", "freq_hz": 20000, "duty_pct": 25, "status": "pending"}
    r2 = {"id": "R2", "type": "i2c", "instance": "I2C3", "status": "pending"}
    r1b = {**r1, "status": "satisfied", "evidence": "sim#12"}
    s = B.fold("demo", events(("requirements_set", {"requirements": [r1, r2]}), ("requirements_set", {"requirements": [r1b]})))
    assert [r["id"] for r in s["requirements"]] == ["R1", "R2"] and s["requirements"][0]["status"] == "satisfied"


def test_devices_nets_decisions_artifacts():
    dev = {"id": "U2", "part": "BME280", "vdd": 1.8, "interface": "I2C", "i_typ_ua": 3.6}
    net = {"from": "stm32g474.PB7", "to": "U2.SDA", "kind": "bidirectional", "level_check": {"status": "FAIL"}}
    dec = {"id": "D1", "question": "I2C3_SCL đặt ở chân nào?", "options": ["PB8", "PC8"], "chosen": "PB8", "by": "human", "rationale": "PA8 đã dùng cho PWM"}
    art = {"file": "pwm_tim1.c", "status": "approved", "sim_ref": "sim#12"}
    s = B.fold("demo", events(("device_added", {"device": dev}), ("net_connected", {"net": net}), ("decision_recorded", {"decision": dec}),
                              ("artifact_recorded", {"artifact": art}), ("device_added", {"device": {**dev, "vdd": 3.3}})))
    assert s["devices"] == [{**dev, "vdd": 3.3}] and s["nets"] == [net] and s["decisions"] == [dec] and s["artifacts"] == [art]


def test_reconnecting_the_same_endpoints_replaces_the_net():
    n1 = {"from": "a.X", "to": "b.Y", "kind": "digital", "level_check": {"status": "FAIL"}}
    n2 = {"from": "a.X", "to": "b.Y", "kind": "digital", "level_check": {"status": "PASS"}}
    s = B.fold("demo", events(("net_connected", {"net": n1}), ("net_connected", {"net": n2})))
    assert s["nets"] == [n2]


def test_clock_event_stores_cfg_derived_and_violations_and_sets_peripheral_gates():
    cfg = {"source": "HSI16", "enabled_peripherals": ["TIM1", "GPIOA"]}
    clk = ("clock_configured", {"cfg": cfg, "derived": {"sysclk_hz": 16000000}, "violations": []})
    s = B.fold("demo", events(TARGET, PA8, PB8, clk))
    assert s["clock"]["derived"]["sysclk_hz"] == 16000000 and s["clock"]["enabled_peripherals"] == ["TIM1", "GPIOA"]
    assert s["peripherals"]["TIM1"]["clock_enabled"] is True and s["peripherals"]["I2C3"]["clock_enabled"] is False
    later = ("pin_allocated", {"pin": "PA9", "chip": "stm32g474", "signal": "USART1_TX", "af": 7, "peripheral": "USART1", "owner": "R9", "mode": "AF_PP", "shared": False})
    s = B.fold("demo", events(TARGET, clk, later))
    assert s["peripherals"]["USART1"]["clock_enabled"] is False                # cấp phát sau khi khai báo clock vẫn được đối chiếu
    no_list = ("clock_configured", {"cfg": {"source": "HSI16"}, "derived": {}, "violations": []})
    s = B.fold("demo", events(TARGET, PA8, no_list))
    assert s["peripherals"]["TIM1"]["clock_enabled"] is None                    # không khai báo danh sách => không biết, không đoán


def test_unknown_event_type_is_rejected():
    with pytest.raises(ValueError, match="unknown event type"):
        B.fold("demo", events(("nope", {})))


def test_versions_must_be_consecutive():
    with pytest.raises(ValueError, match="version"):
        B.fold("demo", [ev(1, *TARGET), ev(3, *PA8)])


# ----------------------------------------------------------------------------------------------- rollback / snapshot / diff
def test_rollback_restores_content_as_a_new_event_and_later_events_apply_on_top():
    evs = events(TARGET, PA8, PB8, ("rolled_back", {"to_version": 2, "reason": "undo I2C3"}), ("pin_allocated", {**PB8[1], "pin": "PC8", "owner": "R2"}))
    s = B.fold("demo", evs)
    assert s["version"] == 5 and set(s["pins"]) == {"PA8", "PC8"}
    history = B.history("demo", evs)
    assert [h["version"] for h in history] == [0, 1, 2, 3, 4, 5]
    assert set(history[3]["pins"]) == {"PA8", "PB8"} and set(history[4]["pins"]) == {"PA8"} and history[4]["version"] == 4


def test_rollback_to_a_state_that_itself_followed_a_rollback():
    evs = events(TARGET, PA8, PB8, ("rolled_back", {"to_version": 2}), ("rolled_back", {"to_version": 3}))
    h = B.history("demo", evs)
    assert set(h[5]["pins"]) == {"PA8", "PB8"} and h[5]["version"] == 5


def test_rollback_target_must_be_in_the_past():
    with pytest.raises(ValueError, match="to_version"):
        B.fold("demo", events(TARGET, ("rolled_back", {"to_version": 2})))
    with pytest.raises(ValueError, match="to_version"):
        B.fold("demo", events(TARGET, ("rolled_back", {"to_version": -1})))


def test_diff_reports_added_removed_changed_by_section():
    evs = events(TARGET, PA8, PB8, ("pin_released", {"pin": "PB8"}), ("requirements_set", {"requirements": [{"id": "R1", "type": "pwm", "status": "pending"}]}),
                 ("requirements_set", {"requirements": [{"id": "R1", "type": "pwm", "status": "satisfied"}]}))
    h = B.history("demo", evs)
    d = B.diff(h[2], h[3])
    assert [(c["section"], c["op"], c["key"]) for c in d] == [("pins", "added", "PB8"), ("peripherals", "added", "I2C3")]
    d = B.diff(h[3], h[4])
    assert [(c["section"], c["op"], c["key"]) for c in d] == [("pins", "removed", "PB8"), ("peripherals", "removed", "I2C3")]
    d = B.diff(h[5], h[6])
    assert d == [{"section": "requirements", "op": "changed", "key": "R1", "fields": ["status"], "before": {"id": "R1", "type": "pwm", "status": "pending"},
                  "after": {"id": "R1", "type": "pwm", "status": "satisfied"}}]
    assert B.diff(h[3], h[3]) == []                                        # version không phải nội dung


def test_diff_clock_lists_changed_keys():
    a = B.fold("p", events(("clock_configured", {"cfg": {"source": "HSI16"}, "derived": {"sysclk_hz": 16000000}, "violations": []})))
    b = B.fold("p", events(("clock_configured", {"cfg": {"source": "HSE", "hse_hz": 8000000}, "derived": {"sysclk_hz": 8000000}, "violations": []})))
    [c] = B.diff(a, b)
    assert c["section"] == "clock" and c["op"] == "changed" and set(c["fields"]) == {"source", "hse_hz", "derived"}


# ----------------------------------------------------------------------------------------------- lưu trữ SQLite
def test_store_appends_events_with_consecutive_versions_and_folds_back(tmp_path):
    st = B.EventStore(tmp_path / "bs.sqlite")
    assert st.head("demo") == 0 and st.events("demo") == []
    assert st.append("demo", *TARGET) == 1
    assert st.append("demo", *PA8, actor="agent") == 2
    assert st.append("other", *TARGET) == 1                                 # project độc lập
    es = st.events("demo")
    assert [(e["version"], e["type"], e["actor"]) for e in es] == [(1, "target_set", "agent"), (2, "pin_allocated", "agent")]
    assert es[0]["ts"] and es[0]["payload"] == TARGET[1]
    assert B.fold("demo", es)["pins"]["PA8"]["signal"] == "TIM1_CH1"
    assert st.events("demo", upto=1) == es[:1]
    assert sorted(st.projects()) == ["demo", "other"]


def test_store_persists_across_connections(tmp_path):
    path = tmp_path / "bs.sqlite"
    B.EventStore(path).append("demo", *TARGET)
    assert B.EventStore(path).head("demo") == 1


def test_store_row_layout_matches_the_brief(tmp_path):
    path = tmp_path / "bs.sqlite"
    st = B.EventStore(path)
    st.append("demo", *TARGET, actor="human")
    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("PRAGMA table_info(events)")]
    assert cols == ["project_id", "version", "ts", "actor", "type", "payload_json"]
    row = con.execute("SELECT project_id, version, actor, type, payload_json FROM events").fetchone()
    assert row[:4] == ("demo", 1, "human", "target_set") and json.loads(row[4]) == TARGET[1]


def test_history_is_immutable_in_the_database(tmp_path):
    path = tmp_path / "bs.sqlite"
    st = B.EventStore(path)
    st.append("demo", *TARGET)
    con = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE events SET actor='x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM events")


def test_optimistic_concurrency_rejects_a_stale_writer(tmp_path):
    st = B.EventStore(tmp_path / "bs.sqlite")
    st.append("demo", *TARGET)
    st.append("demo", *PA8, expected_version=1)
    with pytest.raises(B.VersionConflict):
        st.append("demo", *PB8, expected_version=1)                          # người khác đã ghi version 2
    assert st.head("demo") == 2


def test_unknown_event_type_is_rejected_before_it_is_stored(tmp_path):
    st = B.EventStore(tmp_path / "bs.sqlite")
    with pytest.raises(ValueError, match="unknown event type"):
        st.append("demo", "bogus", {})
    assert st.head("demo") == 0


def test_board_facade_snapshot_diff_rollback(tmp_path):
    b = B.Board(B.EventStore(tmp_path / "bs.sqlite"), "demo")
    b.append(*TARGET)
    b.append(*PA8)
    v = b.append(*PB8)
    assert v == 3 and b.head() == 3
    assert b.state()["version"] == 3 and set(b.snapshot(2)["pins"]) == {"PA8"} and b.snapshot(0)["pins"] == {}
    assert [c["key"] for c in b.diff(2, 3)["changes"] if c["section"] == "pins"] == ["PB8"]
    new_version = b.rollback(2, actor="human", reason="undo")
    assert new_version == 4 and set(b.state()["pins"]) == {"PA8"}
    assert b.store.head("demo") == 4 and len(b.store.events("demo")) == 4               # lịch sử không bị xoá
    assert b.store.events("demo")[-1]["type"] == "rolled_back" and b.store.events("demo")[-1]["actor"] == "human"
    assert set(b.snapshot(3)["pins"]) == {"PA8", "PB8"}                                  # vẫn xem được trạng thái trước rollback
    with pytest.raises(ValueError, match="version"):
        b.snapshot(9)
    with pytest.raises(ValueError, match="version"):
        b.rollback(9)


def test_default_db_path_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("BOARD_STATE_DB", str(tmp_path / "x.sqlite"))
    assert B.default_db_path() == tmp_path / "x.sqlite"
    monkeypatch.delenv("BOARD_STATE_DB")
    assert B.default_db_path().name == "board_state.sqlite" and B.default_db_path().parent.name == "data"


# ----------------------------------------------------------------------------------------------- sửa sau review mã (mục 13, 14)
def test_insert_or_replace_cannot_overwrite_an_existing_event(tmp_path):
    """INSERT OR REPLACE / REPLACE INTO xoá-rồi-ghi hàng cũ mà không chạy trigger DELETE: phải bị trigger BEFORE INSERT chặn."""
    path = tmp_path / "bs.sqlite"
    st = B.EventStore(path)
    st.append("demo", *TARGET, actor="agent")
    con = sqlite3.connect(path)
    for stmt in ("INSERT OR REPLACE INTO events(project_id, version, ts, actor, type, payload_json) VALUES ('demo', 1, 't', 'evil', 'target_set', '{}')",
                 "REPLACE INTO events(project_id, version, ts, actor, type, payload_json) VALUES ('demo', 1, 't', 'evil', 'target_set', '{}')"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            con.execute(stmt)
    assert st.events("demo")[0]["actor"] == "agent" and st.events("demo")[0]["payload"] == TARGET[1]
    con.execute("INSERT INTO events(project_id, version, ts, actor, type, payload_json) VALUES ('demo', 2, 't', 'x', 'target_set', '{}')")      # version mới vẫn ghi được


def test_trigger_is_added_to_a_database_created_before_the_fix(tmp_path):
    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE events(project_id TEXT NOT NULL, version INTEGER NOT NULL, ts TEXT NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, payload_json TEXT NOT NULL,"
                      " PRIMARY KEY(project_id, version));")
    con.execute("INSERT INTO events VALUES ('demo', 1, 't', 'agent', 'target_set', ?)", (json.dumps(TARGET[1]),))
    con.commit()
    con.close()
    B.EventStore(path)                                                                         # mở lại: tạo trigger còn thiếu
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        sqlite3.connect(path).execute("REPLACE INTO events VALUES ('demo', 1, 't', 'evil', 'target_set', '{}')")


@pytest.mark.parametrize("type_, payload", [
    ("rolled_back", {"to_version": 99}), ("rolled_back", {}), ("rolled_back", {"to_version": True}), ("pin_released", {}), ("pin_allocated", {"pin": "PA8"}),
    ("target_set", {}), ("requirements_set", {"requirements": "R1"}), ("device_added", {}), ("net_connected", {"net": {}}), ("clock_configured", {}),
    ("decision_recorded", {"decision": 5}), ("target_set", {"chip": "stm32g474", "vdd": float("nan")}), ("target_set", {"chip": "x", "bad": {1, 2}})])
def test_append_dry_runs_the_event_so_a_bad_payload_never_corrupts_the_log(tmp_path, type_, payload):
    st = B.EventStore(tmp_path / "bs.sqlite")
    st.append("demo", *TARGET)
    with pytest.raises(ValueError):
        st.append("demo", type_, payload)
    assert st.head("demo") == 1
    b = B.Board(st, "demo")
    assert b.state()["version"] == 1                                                         # state() vẫn đọc được, log nguyên vẹn
    assert b.rollback(0) == 2                                                                 # và rollback vẫn dùng được


def test_append_rejects_a_non_object_payload_and_accepts_a_valid_release_of_a_free_pin(tmp_path):
    st = B.EventStore(tmp_path / "bs.sqlite")
    with pytest.raises(ValueError, match="payload"):
        st.append("demo", "target_set", ["not", "an", "object"])
    assert st.append("demo", "pin_released", {"pin": "PA8"}) == 1                              # nhả chân chưa cấp là hợp lệ (idempotent)
