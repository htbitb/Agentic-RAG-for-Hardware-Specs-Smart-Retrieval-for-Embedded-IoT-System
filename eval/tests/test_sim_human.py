"""SimulatedHuman (plan/P5_interfaces.md §2): trả lời interrupt theo `human_policy` (tất định, không LLM, không mạng) và quy tắc phát hiện câu hỏi
hướng tới người dùng trong câu trả lời của baseline."""
import pytest

from eval.sim_human import NO_POLICY_REJECT_FEEDBACK, UNKNOWN_ANSWER, HumanReply, SimulatedHuman, detect_question

HIDDEN = [{"id": "hse_hz", "keywords": ["HSE", "crystal", "oscillator", "external clock"], "required": True, "value_patterns": [r"\b8\s*MHz\b"]},
          {"id": "vdd_sensor", "keywords": ["sensor supply", "sensor voltage", "1.8 V"], "required": True, "value_patterns": [r"1\.8\s*V"]},
          {"id": "colour", "keywords": ["LED colour"], "required": False}]
POLICY = {"approval": "approve", "choice": {"prefer": "level shifter"},
          "clarify": {"hse_hz": "The board has an 8 MHz crystal on HSE.", "vdd_sensor": "The sensor is powered from 1.8 V."}, "max_answers": 3}


def human(policy=POLICY, hidden=HIDDEN):
    return SimulatedHuman(policy, hidden)


def clarify(q, iid="i_1"):
    return {"id": iid, "kind": "clarify", "tool": "ask_human", "tool_call_id": "c1", "question": q, "why_needed": "", "options": None, "payload": {}}


RECORD_KEYS = {"kind", "question", "matched", "necessary", "answered", "decision", "answer", "source", "index"}


# ------------------------------------------------------------------ clarify
def test_clarify_answers_the_matched_hidden_item_and_records_it():
    h = human()
    r = h.respond(clarify("What is the frequency of the external crystal?"))
    assert isinstance(r, HumanReply) and r.decision == "answer" and r.payload == {"answer": "The board has an 8 MHz crystal on HSE."}
    assert set(r.record) == RECORD_KEYS
    assert r.record == {"kind": "clarify", "question": "What is the frequency of the external crystal?", "matched": ["hse_hz"], "necessary": True,
                        "answered": True, "decision": "answer", "answer": "The board has an 8 MHz crystal on HSE.", "source": "interrupt", "index": 0}
    assert h.records == [r.record]


def test_an_unmatched_question_gets_the_unknown_answer_and_is_unnecessary():
    h = human()
    r = h.respond(clarify("Which LED should blink?"))
    assert r.decision == "unknown" and r.payload == {"answer": UNKNOWN_ANSWER} and UNKNOWN_ANSWER.startswith("Không biết, hãy tự chọn phương án hợp lý")
    assert r.record["matched"] == [] and r.record["necessary"] is False and r.record["answered"] is False


@pytest.mark.parametrize("q", ["What's the HSE-frequency?", "hse?", "Is there an External-Clock source?", "Which crystals are fitted (HSE)?",
                               "Do you use an OSCILLATOR module?", "What is the HSE (in MHz)?"])
def test_keyword_matching_is_case_insensitive_and_tolerates_punctuation_and_plurals(q):
    assert human().respond(clarify(q)).record["matched"] == ["hse_hz"]


@pytest.mark.parametrize("q", ["Is HSEON already set?", "Is the crystalline structure relevant?", "What is the clock?"])
def test_keywords_match_whole_words_only(q):
    assert human().respond(clarify(q)).record["matched"] == []


def test_digit_unit_spacing_is_normalised():
    assert human().respond(clarify("Is the sensor at 1.8V?")).record["matched"] == ["vdd_sensor"]


def test_a_question_matching_two_items_gets_a_combined_answer_in_hidden_info_order():
    r = human().respond(clarify("What sensor voltage do you use, and what crystal is on HSE?"))
    assert r.record["matched"] == ["hse_hz", "vdd_sensor"]
    assert r.payload["answer"] == "The board has an 8 MHz crystal on HSE. The sensor is powered from 1.8 V."


def test_hidden_information_that_was_not_asked_is_never_revealed():
    r = human().respond(clarify("What is the HSE frequency?"))
    assert "1.8" not in r.payload["answer"]


def test_max_answers_caps_contentful_answers_and_later_questions_get_unknown():
    h = human({**POLICY, "max_answers": 1})
    first = h.respond(clarify("HSE frequency?"))
    second = h.respond(clarify("Sensor supply voltage?"))
    assert first.record["answered"] is True and second.decision == "unknown" and second.payload == {"answer": UNKNOWN_ANSWER}
    assert second.record["answered"] is False and second.record["necessary"] is True and second.record["matched"] == ["vdd_sensor"]
    assert [r["index"] for r in h.records] == [0, 1]


def test_asking_again_for_an_item_already_answered_is_answered_but_unnecessary():
    h = human()
    h.respond(clarify("HSE frequency?"))
    again = h.respond(clarify("Sorry, what was the crystal frequency again?"))
    assert again.decision == "answer" and again.record["necessary"] is False and again.record["matched"] == ["hse_hz"]


def test_an_optional_item_without_an_answer_is_unknown_and_unnecessary():
    r = human().respond(clarify("Which LED colour do you want?"))
    assert r.record["matched"] == ["colour"] and r.decision == "unknown" and r.record["necessary"] is False


def test_the_oracle_variant_policy_makes_every_question_unnecessary():
    r = SimulatedHuman({**POLICY, "clarify": {}}, []).respond(clarify("What is the HSE frequency?"))
    assert r.decision == "unknown" and r.record["necessary"] is False and r.record["matched"] == []


def test_no_policy_at_all():
    h = SimulatedHuman(None)
    assert h.respond(clarify("HSE?")).decision == "unknown" and h.max_answers == 3


# ------------------------------------------------------------------ choice / approval
def choice(options, q="Which option?"):
    return {"id": "i_2", "kind": "choice", "tool": "ask_human", "tool_call_id": "c2", "question": q, "why_needed": "trade-off", "options": options, "payload": {}}


OPTS = [{"id": "A", "label": "Replace the sensor with a 3.3 V part", "pros": "fewer parts", "cons": "new footprint"},
        {"id": "B", "label": "Add a TXS0108E", "pros": "keeps the sensor", "cons": "needs a Level-Shifter IC on the board"}]


def test_choice_picks_the_first_option_mentioning_the_preference_in_label_pros_or_cons():
    r = human().respond(choice(OPTS))
    assert r.decision == "choose" and r.payload == {"option": "B"} and r.record["kind"] == "choice" and r.record["answered"] is True
    no_id = [{"label": "Level shifter", "pros": "", "cons": ""}]
    assert human().respond(choice(no_id)).payload == {"option": "Level shifter"}


def test_choice_without_a_matching_option_or_without_a_preference_is_unknown():
    r = human().respond(choice(OPTS[:1]))
    assert r.decision == "unknown" and r.payload == {"answer": UNKNOWN_ANSWER} and r.record["answered"] is False
    assert human({"clarify": POLICY["clarify"]}).respond(choice(OPTS)).decision == "unknown"
    assert human().respond(choice(None)).decision == "unknown"


def approval(name="config.h"):
    return {"id": "i_3", "kind": "approval", "tool": "write_config_file", "tool_call_id": "c3", "question": f"Write {name}?", "why_needed": "",
            "options": None, "payload": {"filename": name, "content": "x", "diff": "", "bytes": 1, "overwrites": False}}


@pytest.mark.parametrize("policy,decision,payload", [
    ({"approval": "approve"}, "approve", {}),
    ({"approval": {"reject": "Use the name pins.h instead."}}, "reject", {"feedback": "Use the name pins.h instead."}),
])
def test_approval_follows_the_policy(policy, decision, payload):
    r = SimulatedHuman(policy).respond(approval())
    assert (r.decision, r.payload) == (decision, payload) and r.record["kind"] == "approval" and r.record["source"] == "interrupt"


def test_approval_reject_without_feedback_and_without_any_policy_rejects_with_a_fixed_feedback():
    r = SimulatedHuman({"approval": "reject"}).respond(approval())
    assert r.decision == "reject" and r.payload["feedback"]
    r = SimulatedHuman({}).respond(approval())
    assert r.decision == "reject" and r.payload == {"feedback": NO_POLICY_REJECT_FEEDBACK}


def test_approvals_do_not_use_up_max_answers():
    h = SimulatedHuman({**POLICY, "max_answers": 1}, HIDDEN)
    for _ in range(3):
        assert h.respond(approval()).decision == "approve"
    assert h.respond(clarify("HSE?")).decision == "answer"


def test_unknown_interrupt_kind_is_answered_with_unknown():
    r = human().respond({"id": "i_9", "kind": "telepathy", "question": "?"})
    assert r.decision == "unknown" and r.payload == {"answer": UNKNOWN_ANSWER}


def test_the_same_policy_and_questions_always_give_the_same_records():
    def play():
        h = human()
        for q in ("HSE?", "LED?", "sensor voltage?"):
            h.respond(clarify(q))
        h.respond(choice(OPTS))
        return h.records
    assert play() == play()


# ------------------------------------------------------------------ baseline: câu hỏi trong văn bản
POSITIVE = [
    "Could you tell me which HSE crystal frequency your board uses?",
    "What HSE frequency does your board use?",
    "Please confirm the supply voltage of the sensor.",
    "Before I write the code, could you confirm whether the sensor runs at 1.8 V or 3.3 V?",
    "Which UART baud rate do you need?",
    "Do you have an external crystal on the board?",
    "Is your sensor powered from 1.8 V?",
    "Please let me know the current budget for sleep mode.",
    "Let me know which pins are free on your board.",
    "To proceed, please specify the crystal frequency.",
    "I need the following information:\n- HSE crystal frequency?\n- Sensor supply voltage?",
    "**Question:** What is your target battery life?",
    "Can you share the schematic of the power section?",
    "```c\nint x = 1;\n```\nWhat crystal does your board have?",
    "Kindly provide the sleep current budget.",
    "Would you prefer a level shifter or a 3.3 V sensor variant?",
    "What's the frequency of your HSE oscillator?",
    "Are you using the Nucleo-G474RE or a custom board?",
    "Please provide the I2C address of your sensor.",
    "Should the UART run at 115200 baud, or do you need a different rate?",
    "Could you clarify the battery capacity?",
    "Bạn dùng thạch anh bao nhiêu MHz?",
    "Clarifying questions before I proceed:\n1. What is the HSE frequency?\n2. Is the sensor 1.8 V or 3.3 V?",
    "Here is the plan.\n\nOne thing I need to know: what crystal is fitted on your board?",
    "I need you to confirm the sensor voltage.",
    "Assumptions (please confirm):\n- HSE = 8 MHz\n- the sensor runs at 3.3 V",
    "We still need some information:\n1. the HSE crystal frequency\n2. the sensor supply voltage",
]
NEGATIVE = [
    "Here is the code.",
    "```c\nint y = x ? a : b;\n```",
    'Use `printf("Ready?\\n")` to print.',
    'The firmware prints "Are you there?" on boot.',
    "See https://example.com/page?id=3 for details.",
    "Why 4 wait states? Because 170 MHz needs them.",
    "### What does the PLL do?\nIt multiplies the clock.",
    "Would you like me to add DMA support?",
    "Let me know if you need anything else.",
    "Do you want me to generate the HAL version as well?",
    "Shall I also write the I2C driver?",
    "If you'd like, I can add a low-power mode.",
    "Feel free to ask if you have any questions.",
    "Please note that PA0 is not 5 V tolerant.",
    "What happens if VDD drops below 1.71 V? The BOR resets the MCU.",
    "Did you know the G474 has 5 USARTs?",
    "| Pin | Function? |\n|---|---|\n| PA8 | TIM1_CH1 |",
    "Make sure you enable the HSE before the PLL.",
    "Hope this helps!",
    "Is it safe? Yes, as long as the pin is FT.",
    "```c\n// What is your HSE frequency?\nRCC->CR |= RCC_CR_HSEON;\n```",
    "Anything else I can help with?",
    "If you have any questions, let me know.",
    "Please make sure your board has a crystal.",
    "> What is the HSE frequency?\n\nThe answer assumes 8 MHz.",
    "",
    "Before I write the code, here are the steps:\n1. Enable the HSE crystal\n2. Configure the PLL",
    "You need the following parts:\n- an 8 MHz crystal\n- two 20 pF capacitors",
    "Pin information:\n- PA8: TIM1_CH1\n- PB6: USART1_TX",
    "Let me know how I can help with your project!",                 # câu kết thật của S3@P4 (C7-003, dev_baseline_v2)
    "How else can I help you today?",
    "To confirm the setup works, check:\n- PA8 outputs 20 kHz\n- the HSE crystal is running",
    "To clarify:\n- the HSE crystal drives the PLL\n- the sensor runs at 3.3 V",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_detect_question_finds_questions_addressed_to_the_user(text):
    q = detect_question(text)
    assert q and len(q) < len(text) + 5, text


@pytest.mark.parametrize("text", NEGATIVE)
def test_detect_question_ignores_code_quotes_urls_rhetoric_offers_and_pleasantries(text):
    assert detect_question(text) is None, (text, detect_question(text))


def test_detect_question_returns_only_the_question_sentences_without_markdown():
    text = "Here is a first draft.\n\n**Before I finalize:** what is the HSE frequency on your board? I assumed 8 MHz.\n\n```c\nint x;\n```"
    assert detect_question(text) == "Before I finalize: what is the HSE frequency on your board?"


def test_detect_question_joins_several_questions_in_order():
    q = detect_question("What crystal does your board use? Also, which sensor voltage do you have?")
    assert q == "What crystal does your board use? Also, which sensor voltage do you have?"


def test_list_questions_without_you_count_only_under_a_clarification_intro():
    assert detect_question("Steps:\n1. What is the PLL?\n2. Configure it.") is None
    assert detect_question("Please answer the following:\n- HSE frequency?") == "HSE frequency?"


def test_detection_is_deterministic_and_a_method_of_the_human():
    text = POSITIVE[3]
    assert detect_question(text) == detect_question(text) == human().detect_question(text)


# ------------------------------------------------------------------ baseline: reply_to_text
def test_reply_to_text_answers_a_matching_question_as_a_text_record():
    h = human()
    r = h.reply_to_text("Draft below.\n\nWhat HSE crystal frequency does your board use?")
    assert r.decision == "answer" and r.payload == {"answer": "The board has an 8 MHz crystal on HSE."}
    assert r.record["kind"] == "text" and r.record["source"] == "baseline_text" and r.record["necessary"] is True
    assert r.record["question"] == "What HSE crystal frequency does your board use?"


def test_reply_to_text_without_a_question_is_none_and_records_nothing():
    h = human()
    assert h.reply_to_text("Here is the complete code.") is None and h.records == []


def test_reply_to_text_with_an_unmatched_question_sends_the_unknown_answer():
    r = human().reply_to_text("Which LED do you want to blink?")
    assert r.decision == "answer" and r.payload == {"answer": UNKNOWN_ANSWER} and r.record["necessary"] is False and r.record["answered"] is False


def test_text_and_interrupt_answers_share_the_max_answers_budget():
    h = human({**POLICY, "max_answers": 1})
    h.reply_to_text("What is your HSE crystal?")
    r = h.reply_to_text("And what is your sensor supply voltage?")
    assert r.payload == {"answer": UNKNOWN_ANSWER} and r.record["answered"] is False
