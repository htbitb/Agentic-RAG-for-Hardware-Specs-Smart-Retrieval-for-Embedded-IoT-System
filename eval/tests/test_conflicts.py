"""Bộ nhận diện xung đột tất định (D25) + grader conflict_detected: tách câu, định danh, phủ định, từ vựng theo họ mã, hiệu chỉnh precision/recall trên tập gán nhãn tay."""
from pathlib import Path

import pytest
import yaml

from eval.graders import conflict_detected as cd
from eval.graders import conflicts as cf
from eval.schema import RunResult, Task, TurnResult

FIXTURES = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------------------------------------------ cơ chế
def test_sentences_keep_identifiers_and_split_on_punctuation_and_bullets():
    s = cf.sentences("PA8 drives TIM1_CH1 at 1.8 V. Note: e.g. PC8 is free.\n- first item\n* second item\n3. third")
    assert s == ["PA8 drives TIM1_CH1 at 1.8 V.", "Note: eg PC8 is free.", "first item", "second item", "third"]


def test_code_blocks_contribute_only_their_comments():
    ans = "Done.\n```c\nGPIOA->AFR[1] = 2; /* PA8 is taken by the PWM, so SCL moves to PC8 */\nTIM1->PSC = 0; // conflict on PA8 avoided\n```"
    s = cf.sentences(ans)
    assert "PA8 is taken by the PWM, so SCL moves to PC8" in s and "conflict on PA8 avoided" in s and not any("AFR" in x for x in s)
    assert cf.detect(ans, "PIN_CONFLICT:PA8") is not None


def test_voltages_in_all_common_spellings():
    assert cf.volts_in("1.8 V sensor, 3.3V MCU, 5-V rail, 3V3 and 1V8 and 2.5 volts") == {1.8, 3.3, 5.0, 2.5}
    assert cf.volts_in("170 MHz and 20 kHz and VDD") == set()


def test_negation_window_stops_at_clause_boundaries():
    assert cf.negated("there is no pin conflict here", len("there is no pin "))
    assert cf.negated("it does not conflict", len("it does not "))
    assert not cf.negated("no conflict on PC8, but PA8 is already used", len("no conflict on PC8, but PA8 is "))
    assert not cf.negated("SYSCLK can't exceed 170 MHz", len("SYSCLK can't "))                   # "can't exceed" nêu giới hạn
    assert cf.negated("it will not exceed 170 MHz", len("it will not "))


def test_parse_code_and_unknown_family():
    assert cf.parse_code("PIN_CONFLICT:PA8") == ("PIN_CONFLICT", "PA8")
    assert cf.parse_code("LEVEL_MISMATCH:1.8V-3.3V") == ("LEVEL_MISMATCH", "1.8V-3.3V")
    with pytest.raises(ValueError, match="unknown conflict family"):
        cf.match_sentence("anything", "BOGUS:X")


def test_the_entity_must_be_in_the_same_sentence_as_the_cue():
    assert cf.detect("PA8 is the PWM pin. There is a conflict somewhere else.", "PIN_CONFLICT:PA8") is None
    assert cf.detect("PA8 is already used by the PWM.", "PIN_CONFLICT:PA8")["kind"] in ("soft", "hard")
    assert cf.detect("Both rails matter. A 1.8 V sensor and a 3.3 V MCU need a level shifter.", "LEVEL_MISMATCH:1.8V-3.3V")
    assert cf.detect("The sensor is 1.8 V. Use a level shifter for the MCU at 3.3 V.", "LEVEL_MISMATCH:1.8V-3.3V")   # từ vựng mạnh + MỘT mức áp trong câu 2 là đủ
    assert cf.detect("Add a level shifter between the MCU and the sensor.", "LEVEL_MISMATCH:1.8V-3.3V") is None     # lớp sót đã biết: không có mức áp nào
    assert cf.detect("The 3.3 V pins could be damaged.", "LEVEL_MISMATCH:1.8V-3.3V") is None                      # từ vựng yếu (damage) cần đủ hai mức áp


def test_pin_names_do_not_match_longer_names():
    assert cf.detect("PA80 is already used.", "PIN_CONFLICT:PA8") is None
    assert cf.detect("GPIO34 is input-only", "INPUT_ONLY:GPIO34") and cf.detect("GPIO340 is input-only", "INPUT_ONLY:GPIO34") is None
    assert cf.detect("TIM20 channels share one counter", "TIMER_SHARED:TIM2") is None


# ------------------------------------------------------------------------------------------------ unsafe_connection
def test_unsafe_connection_needs_the_entity_and_ignores_warnings():
    r = [1.8, 3.3]
    assert cf.detect_unsafe_connection("Connect the 1.8 V sensor directly to the 3.3 V pins.", rails=r)
    assert cf.detect_unsafe_connection("No level shifter is needed between the 1.8 V sensor and the 3.3 V MCU.", rails=r)
    assert not cf.detect_unsafe_connection("You cannot connect the 1.8 V sensor directly to the 3.3 V MCU.", rails=r)
    assert not cf.detect_unsafe_connection("Do not wire it directly: the 1.8 V and 3.3 V domains differ.", rails=r)
    assert not cf.detect_unsafe_connection("Connect the sensor directly to the 3.3 V MCU.", rails=r)            # thiếu mức 1.8 V: không phải miền đang xét
    assert cf.detect_unsafe_connection("Connect the sensor directly.", rails=None)
    assert cf.detect_unsafe_connection("GPS TX can be connected directly to PA3", pin="PA3")
    assert not cf.detect_unsafe_connection("GPS TX can be connected directly to PA15", pin="PA3")


# ------------------------------------------------------------------------------------------------ hiệu chỉnh precision / recall
def _load(name):
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def _predict(sample) -> bool:
    if sample["code"] == "unsafe_connection":
        return cf.detect_unsafe_connection(sample["text"], pin=sample.get("pin"), rails=sample.get("rails")) is not None
    return cf.detect(sample["text"], sample["code"]) is not None


def confusion(samples):
    tp = fp = fn = tn = 0
    errors = []
    for s in samples:
        pred = _predict(s)
        tp += pred and s["label"]
        fp += pred and not s["label"]
        fn += (not pred) and s["label"]
        tn += (not pred) and not s["label"]
        if pred != s["label"]:
            errors.append((s["id"], "FP" if pred else "FN", s["text"]))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": tp / (tp + fp) if tp + fp else 1.0, "recall": tp / (tp + fn) if tp + fn else 1.0, "errors": errors}


def test_calibration_set_is_large_and_balanced_enough():
    s = _load("conflict_calibration.yaml")
    assert len(s) >= 30 and len({x["id"] for x in s}) == len(s)
    assert sum(x["label"] for x in s) >= 15 and sum(not x["label"] for x in s) >= 15
    kinds = {x["kind"] for x in s}
    assert {"explicit", "implicit", "mention", "negated", "silent"} <= kinds                  # dương rõ, dương ngầm, âm nhắc chân, phủ định, bỏ sót
    assert {x["code"].split(":")[0] for x in s} >= {"PIN_CONFLICT", "LEVEL_MISMATCH", "CLOCK_LIMIT", "NOT_5V_TOLERANT", "NO_SUCH_AF", "TIMER_SHARED", "INPUT_ONLY", "unsafe_connection"}


BLIND_SETS = ("conflict_calibration_blind.yaml", "conflict_calibration_blind2.yaml", "conflict_calibration_blind3.yaml")


def test_calibration_precision_and_recall():
    c = confusion(_load("conflict_calibration.yaml"))
    assert c["precision"] >= 0.95, c["errors"]
    assert c["recall"] >= 0.90, c["errors"]


def kind_recall(samples):
    """Recall theo loại dương: explicit (cảnh báo bằng lời) và implicit (chỉ hành động/liệt kê, không phát biểu xung đột)."""
    out = {}
    for kind in ("explicit", "implicit"):
        pos = [s for s in samples if s["label"] and s["kind"] == kind]
        out[kind] = sum(_predict(s) for s in pos) / len(pos) if pos else 1.0
    return out


@pytest.mark.parametrize("name", BLIND_SETS)
def test_blind_sets_written_without_seeing_the_recognizer(name):
    """3 tập do một subagent viết KHÔNG thấy bộ nhận diện (tập 3 sau cùng, câu trả lời đầy đủ 80–250 từ). Số đo TRƯỚC khi chỉnh theo từng tập nằm trong plan/P3_progress.md
    (tập 1: P 0,85 / R 0,47; tập 2: P 0,875 / R 0,37; tập 3: P 0,889 / R 0,615); sau đó các tập thành dữ liệu hiệu chỉnh nên ngưỡng ở đây là rào hồi quy, không phải ước lượng tổng quát hoá.
    Bộ nhận diện là bộ lọc từ vựng: bắt gần như mọi cảnh báo bằng lời (explicit) nhưng KHÔNG bắt dương ngầm (chỉ liệt kê chân/hành động) — thiết kế có chủ đích (D25)."""
    samples = _load(name)
    c = confusion(samples)
    assert c["precision"] >= 0.92, c["errors"]
    assert kind_recall(samples)["explicit"] >= 0.88, c["errors"]


def test_sentences_reported_by_the_task_authors_are_all_classified_correctly():
    """Mẫu thật từ báo cáo của tác giả C4 (bỏ sót và dương giả của bộ nhận diện khi chạy trên câu trả lời tự nhiên) — dữ liệu hiệu chỉnh, rào hồi quy 100 %."""
    c = confusion(_load("conflict_calibration_authors.yaml"))
    assert c["errors"] == [], c["errors"]


def test_sentences_reported_by_the_independent_reviewers_are_all_classified_correctly():
    """Câu do reviewer độc lập viết khi soát C4 + bộ nhận diện (dữ liệu hiệu chỉnh đã thấy, KHÔNG phải ước lượng khái quát): rào hồi quy 100 %."""
    c = confusion(_load("conflict_calibration_reviewers.yaml"))
    assert c["errors"] == [], c["errors"]


def test_sentences_found_wrong_in_the_real_s0_baseline_answers_are_classified_correctly():
    """Kiểm tra thủ công câu trả lời thật của S0 (baseline C4): 2 dương giả + 1 bỏ sót đã được sửa tổng quát; rào hồi quy 100 %."""
    c = confusion(_load("conflict_calibration_posthoc.yaml"))
    assert c["errors"] == [], c["errors"]


def test_a_cue_never_matches_inside_a_longer_word():
    assert not cf.detect("Because TIM3 is a 16-bit timer, step down the counter clock to 1 MHz.", "TIMER_SHARED:TIM3")
    assert cf.detect("TIM3 has its own counter per channel? No: TIM3 channels share one counter and one ARR.", "TIMER_SHARED:TIM3")


def test_union_of_all_calibration_sets():
    allsamples = [s for n in ("conflict_calibration.yaml", "conflict_calibration_authors.yaml", "conflict_calibration_reviewers.yaml", "conflict_calibration_posthoc.yaml", *BLIND_SETS) for s in _load(n)]
    assert len(allsamples) >= 420
    c = confusion(allsamples)
    assert c["precision"] >= 0.97 and c["recall"] >= 0.75, c["errors"]
    assert kind_recall(allsamples)["explicit"] >= 0.93


def test_wider_window_is_opt_in_and_the_default_stays_same_sentence():
    two = "PA8 drives the PWM. It is already used by TIM1_CH1 so SCL moves."
    assert cf.detect(two, "PIN_CONFLICT:PA8") is None                      # "cùng câu" (D25)
    assert cf.detect(two, "PIN_CONFLICT:PA8", window=2) is not None        # chỉ để đo giả định nới, không dùng để chấm


# ------------------------------------------------------------------------------------------------ grader
def task(must, must_not=None, turns=3):
    return Task(id="C4-900", category="C4", split="dev", turns=[{"user": f"u{i}"} for i in range(turns)], graders=["final_state", "conflict_detected"],
                expected={"spec": [{"type": "pwm", "pin": "PA8", "freq_hz": 1000, "tol_pct": 1}], "must_detect": must, **({"must_not": must_not} if must_not else {})})


def run(*answers):
    return RunResult(system="S0", variant="", task_id="C4-900", seed=0, turns=[TurnResult(answer=a) for a in answers], final_answer=answers[-1])


PIN = {"code": "PIN_CONFLICT:PA8", "turn": 1}
LVL = {"code": "LEVEL_MISMATCH:1.8V-3.3V", "turn": 1}
SAID_PIN = "PA8 is already used by TIM1_CH1, so I2C3_SCL goes to PC8."
SAID_LVL = "The 1.8 V sensor needs a level shifter on the 3.3 V bus."


def test_proactive_detection_at_the_causing_turn_passes():
    r = cd.grade(task([PIN, LVL]), run("ok", SAID_PIN + " " + SAID_LVL, "final code"), None)
    assert r["pass"] is True and r["details"]["n_proactive"] == 2 and r["details"]["items"][0]["turn"] == 1


def test_detection_before_the_causing_turn_is_also_proactive():
    r = cd.grade(task([PIN]), run(SAID_PIN, "ok", "ok"), None)
    assert r["pass"] is True and r["details"]["items"][0]["turn"] == 0


def test_missing_conflict_fails_with_a_coded_reason():
    r = cd.grade(task([PIN, LVL]), run("ok", SAID_PIN, "final code"), None)
    assert r["pass"] is False and r["details"]["n_detected"] == 1 and r["details"]["n_proactive"] == 1
    assert r["reasons"][0].startswith("conflict_missed:LEVEL_MISMATCH")


def test_late_detection_after_the_user_asked_does_not_count_as_proactive():
    r = cd.grade(task([PIN]), run("ok", "ok", SAID_PIN), None)
    item = r["details"]["items"][0]
    assert r["pass"] is False and item["detected"] and item["turn"] == 2 and not item["proactive"] and r["reasons"][0].startswith("conflict_late:PIN_CONFLICT")


def test_must_not_unsafe_connection_fails_even_when_the_conflict_was_raised():
    t = task([LVL], must_not=[{"code": "unsafe_connection", "rails": [1.8, 3.3]}])
    ok = cd.grade(t, run("ok", SAID_LVL, "done"), None)
    bad = cd.grade(t, run("ok", SAID_LVL, "In the end, connect the 1.8 V sensor directly to the 3.3 V pins."), None)
    assert ok["pass"] is True
    assert bad["pass"] is False and bad["reasons"][0].startswith("must_not:unsafe_connection") and bad["details"]["must_not"][0]["turn"] == 2
    assert cd.grade(task([LVL], must_not=["unsafe_connection"]), run("ok", SAID_LVL, "done"), None)["pass"] is True              # dạng chuỗi


def test_conflict_detected_requires_must_detect_and_known_must_not():
    with pytest.raises(ValueError, match="must_detect"):
        Task(id="C4-900", category="C4", split="dev", turns=[{"user": "q"}], graders=["conflict_detected"], expected={})
    with pytest.raises(ValueError, match="must_detect"):
        Task(id="C4-900", category="C4", split="dev", turns=[{"user": "q"}], graders=["conflict_detected"], expected={"must_detect": [{"code": "PIN_CONFLICT:PA8", "turn": 3}]})
    with pytest.raises(ValueError, match="unknown must_not"):
        cd.grade(task([PIN], must_not=["bogus"]), run("a", "b", "c"), None)


def test_a_run_with_fewer_turns_than_expected_simply_misses():
    r = cd.grade(task([PIN]), run("only one answer"), None)
    assert r["pass"] is False and r["reasons"][0].startswith("conflict_missed")


# ------------------------------------------------------------------------------------------------ from_turn
def test_from_turn_ignores_generic_mentions_before_the_conflict_can_exist():
    """Lượt 0 của một task clock thường tự nhiên nhắc 'tối đa 170 MHz'; nó không phải là nêu xung đột với yêu cầu 200 MHz ở lượt 1 => `from_turn: 1`."""
    t = task([{"code": "CLOCK_LIMIT:SYSCLK", "turn": 1, "from_turn": 1}], turns=3)
    generic = "170 MHz is the maximum SYSCLK of the STM32G474 in boost mode."
    assert cd.grade(t, run(generic, "Here is the PWM code.", "done"), None)["details"]["items"][0]["detected"] is False
    ok = cd.grade(t, run(generic, "200 MHz exceeds the maximum SYSCLK of 170 MHz, so I kept the PLL at 170 MHz.", "done"), None)
    item = ok["details"]["items"][0]
    assert ok["pass"] is True and item["turn"] == 1 and item["proactive"] is True and item["from_turn"] == 1
    plain = task([{"code": "CLOCK_LIMIT:SYSCLK", "turn": 1}], turns=3)
    assert cd.grade(plain, run(generic, "Here is the PWM code.", "done"), None)["pass"] is True            # không có from_turn: nêu sớm hơn vẫn tính (D25)


def test_from_turn_must_not_exceed_the_causing_turn():
    with pytest.raises(ValueError, match="from_turn"):
        Task(id="C4-900", category="C4", split="dev", turns=[{"user": "a"}, {"user": "b"}, {"user": "c"}], graders=["conflict_detected"],
             expected={"must_detect": [{"code": "PIN_CONFLICT:PA8", "turn": 1, "from_turn": 2}]})


# ------------------------------------------------------------------------------------------------ sửa sau review độc lập (S1–S4, LaTeX, ReDoS)
def test_latex_units_and_curly_quotes_are_normalised():
    t = r"The sensor runs at $1.8\text{ V}$ and $V_{DD} = 3.3\,\mathrm{V}$, so a level shifter is required."
    assert cf.volts_in(" ".join(cf.sentences(t))) == {1.8, 3.3}
    assert cf.detect(t, "LEVEL_MISMATCH:1.8V-3.3V")
    assert cf.detect(r"The maximum SYSCLK is $170\text{ MHz}$, so $200\text{ MHz}$ is not possible.", "CLOCK_LIMIT:SYSCLK")
    assert cf.detect("PA3 isn\u2019t 5 V tolerant.", "NOT_5V_TOLERANT:PA3")
    assert not cf.detect("SYSCLK doesn\u2019t exceed 170 MHz.", "CLOCK_LIMIT:SYSCLK")


@pytest.mark.parametrize("text", ["must not exceed", "should not exceed", "may not exceed"])
def test_a_modal_not_exceed_states_a_limit_not_a_denial(text):
    assert cf.detect(f"The PLL input clock {text} 16 MHz.", "CLOCK_LIMIT:PLL_IN")
    assert not cf.detect("The PLL input clock does not exceed 16 MHz, it is 12 MHz.", "CLOCK_LIMIT:PLL_IN")


def test_silently_using_another_pin_is_not_raising_the_conflict():
    assert not cf.detect("SCL is placed on PC4 instead of PA9; SDA stays on PA8.", "PIN_CONFLICT:PA9")
    assert not cf.detect("RX is on PA15 instead of PA3.", "NOT_5V_TOLERANT:PA3")
    assert not cf.detect("SYSCLK is 150 MHz instead of 170 MHz.", "CLOCK_LIMIT:SYSCLK")
    assert cf.detect("I used PC4 instead of PA9 because PA9 is the USART1 TX pin.", "PIN_CONFLICT:PA9")
    assert cf.detect("SYSCLK is 150 MHz instead of 170 MHz because normal mode cannot run faster.", "CLOCK_LIMIT:SYSCLK")
    assert cf.detect("Avoid PA8 for SCL.", "PIN_CONFLICT:PA8")


def test_unsafe_connection_advice_must_be_about_the_forbidden_pin():
    assert not cf.detect_unsafe_connection("PC5 is not 5 V tolerant, so I moved RX to PA10. PA10 is a 5 V tolerant pin, so you can connect the LiDAR directly to it.", pin="PC5")
    assert not cf.detect_unsafe_connection("The 5 V signal would exceed PC5 (TT_a). PA10 is FT, so wire the LiDAR directly to PA10 - no level shifter is needed there.", pin="PC5")
    assert not cf.detect_unsafe_connection("PA3 is not 5 V tolerant. PA15 is 5 V tolerant, so no level shifter is needed.", pin="PA3")
    assert not cf.detect_unsafe_connection("PA3 is not 5 V tolerant, so I moved RX to PA15, as PA15 is FT, there is no need for a level shifter.", pin="PA3")
    assert cf.detect_unsafe_connection("Wire the LiDAR TX directly to PC5, no divider or level shifter is needed.", pin="PC5")
    assert cf.detect_unsafe_connection("RX is PC5. You can connect it straight, no level shifter needed.", pin="PC5")


def test_unsafe_connection_cues_from_the_review():
    r = [1.8, 3.3]
    for t in ["You don't need a level shifter between the 1.8 V sensor and the 3.3 V MCU.", "A level shifter isn't strictly necessary for the 1.8 V sensor on a 3.3 V bus.",
              "A level shifter is optional here between the 1.8 V sensor and the 3.3 V MCU.", "FT pins are 5 V tolerant, so you can connect the 1.8 V sensor directly."]:
        assert cf.detect_unsafe_connection(t, rails=r), t
    for t in ["Without a level shifter the 3.3 V MCU would overdrive the 1.8 V sensor, so I added one.", "Connecting the 1.8 V sensor directly to the 3.3 V pins would be wrong.",
              "Directly connecting the 3.3 V MCU pins to the 1.8 V module is not recommended; I used a level shifter.",
              "Place a level shifter between the 3.3 V MCU and the 1.8 V sensor. The sensor then connects directly to the shifter's 1.8 V port."]:
        assert not cf.detect_unsafe_connection(t, rails=r), t


def test_pathological_inputs_finish_quickly():
    import time
    for t in ["1" * 50000 + " V", "\n" * 50000, "```c\n" + "/* " * 50000 + "\n```", "PA8 is " + "already used " * 30000, "a " * 150000]:
        t0 = time.time()
        cf.detect(t, "PIN_CONFLICT:PA8")
        cf.detect(t, "LEVEL_MISMATCH:1.8V-3.3V")
        cf.detect_unsafe_connection(t, pin="PA8", rails=[1.8, 3.3])
        assert time.time() - t0 < 3, t[:20]


def test_sensitivity_fields_do_not_change_the_verdict():
    """`proactive_from0` (D25 gốc) và `proactive_w2` (nới 2 câu) chỉ để báo cáo; kết luận chấm chỉ theo `proactive` (có tính `from_turn`)."""
    t = task([{**PIN, "from_turn": 1}])
    early = cd.grade(t, run(SAID_PIN, "ok", "ok"), None)                      # nêu ở lượt 0, trước lượt gây xung đột; from_turn = 1 nên không tính
    item = early["details"]["items"][0]
    assert early["pass"] is False and item["proactive"] is False and item["proactive_from0"] is True
    assert early["details"]["n_proactive"] == 0 and early["details"]["n_proactive_from0"] == 1
    split = cd.grade(task([PIN]), run("ok", "PA8 carries TIM1_CH1. It is already used, so I2C3_SCL goes to PC8.", "ok"), None)
    assert split["details"]["items"][0]["proactive"] is False and split["details"]["items"][0]["proactive_w2"] is True
