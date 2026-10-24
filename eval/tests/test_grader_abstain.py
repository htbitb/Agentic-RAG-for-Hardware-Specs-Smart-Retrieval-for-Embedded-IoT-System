import json
from pathlib import Path

import pytest

from eval.graders import abstain
from eval.tests.helpers import mk_run, mk_task


def grade(answer, q="What is the base address of the DAC3 register block on STM32F103?", **exp):
    t = mk_task({"abstain": {"expect": True, **exp}}, graders=("abstain",), category="C8", question=q)
    return abstain.grade(t, mk_run(answer), ctx=None)


@pytest.mark.parametrize("answer", [
    "Insufficient evidence: the indexed documentation does not contain a verifiable answer.",
    "I could not find this in the documents.",
    "The STM32F103 is not covered by the provided documents.",
    "There is no such register on this chip.",
    "That is outside the scope of what I can answer: I only cover embedded hardware documentation.",
    "I don't have enough information to answer.",
    "I do not know.",
])
def test_proper_abstention_passes(answer):
    r = grade(answer)
    assert r["pass"] and r["details"]["abstained"] is True and r["details"]["fabricated"] == []


def test_confident_answer_fails_as_hallucinated_answer():
    r = grade("The DAC3 base address on the STM32F103 is 0x40007400.")
    assert not r["pass"] and any(x.startswith("hallucinated_answer") for x in r["reasons"])
    assert "0x40007400" in r["details"]["fabricated"]


def test_abstention_with_invented_number_still_fails():
    r = grade("I could not find it in the documents, but it is typically around 72 MHz.")
    assert not r["pass"] and any(x.startswith("hallucinated_value") for x in r["reasons"])


def test_numbers_echoed_from_the_question_are_not_fabrication():
    r = grade("The documents do not cover a 16 MHz STM32F103 configuration.", q="Give the PLL settings for STM32F103 at 16 MHz")
    assert r["pass"]


def test_allowed_numbers_whitelist():
    r = grade("There is no such chip in the documents. For reference the nearest indexed part runs at 170 MHz.",
              allowed_numbers=["170 MHz"])
    assert r["pass"]


def test_requires_abstain_spec():
    with pytest.raises(ValueError):
        abstain.grade(mk_task({}, graders=("abstain",)), mk_run("x"), ctx=None)


# ---- review finding 10 -------------------------------------------------------------------------------------
def test_not_in_my_documents_is_an_abstention():
    assert grade("The STM32F103 is not in my documents.")["pass"]


def test_numbers_about_another_indexed_chip_are_contrast_not_fabrication():
    r = grade("The STM32F103 is not in my documents. For comparison the STM32G474 runs up to 170 MHz.")
    assert r["pass"] and r["details"]["fabricated"] == []


def test_numbers_about_the_asked_part_are_still_fabrication():
    assert not grade("The STM32F103 is not in my documents, but it is usually 72 MHz.")["pass"]


# ---- review A-1: các cách từ chối / nói không có thông tin tự nhiên (gồm dạng viết tắt) ----------------------------
@pytest.mark.parametrize("q,answer", [
    ("What is the deep-sleep current of the nRF9160 SiP?", "The nRF9160 isn't covered by my documents."),
    ("What is the deep-sleep current of the nRF9160 SiP?", "The nRF9160 isn’t covered by my documents."),
    ("What is the deep-sleep current of the nRF9160 SiP?", "This chip is not part of the documents I was given."),
    ("What is the reset value of the register DAC3_FOOBAR_CR on the STM32G474?",
     "DAC3_FOOBAR_CR does not appear in the reference manual, so I cannot give a reset value."),
    ("What is the current retail price of the STM32G474RET6 at a major distributor?",
     "Prices are not listed in the documentation; check a distributor."),
    ("Which private signing key does the manufacturer use for the nRF52840 secure bootloader?",
     "The signing key is private and is not published in the documentation."),
    ("Which private signing key does the manufacturer use for the nRF52840 secure bootloader?",
     "I cannot provide the manufacturer's private key."),
    ("What is the maximum CPU frequency of the STM32F103C8T6?",
     "That question is outside the embedded-hardware documents I can answer from."),
    ("What is the maximum CPU frequency of the STM32F103C8T6?",
     "I don't have the STM32F103 datasheet; for the STM32G474 in my documents the maximum is 170 MHz."),
    ("What is the maximum SPI clock frequency of the nRF52832?", "The nRF52832 is not documented in the indexed manuals."),
])
def test_natural_abstentions_are_recognised(q, answer):
    r = grade(answer, q=q)
    assert r["details"]["abstained"] is True and r["pass"], r


@pytest.mark.parametrize("answer", [
    "The STM32F103C8T6 runs at up to 72 MHz.",
    "Its maximum CPU frequency is 72 MHz, as listed in the datasheet.",
    "The documentation lists the maximum frequency in the electrical characteristics table.",      # nhắc tài liệu nhưng vẫn trả lời
])
def test_confident_answers_are_not_abstentions(answer):
    r = grade(answer, q="What is the maximum CPU frequency of the STM32F103C8T6?")
    assert not r["pass"] and r["details"]["abstained"] is False


# ---- review A-2: giá trị THẬT của thực thể khác, nêu kèm lời từ chối, không phải bịa ------------------------------
FOO = "What is the reset value of the register DAC3_FOOBAR_CR on the STM32G474?"


@pytest.mark.parametrize("q,answer", [
    (FOO, "There is no register named DAC3_FOOBAR_CR. The real DAC registers include DAC_CR (reset 0x0000 0000)."),
    (FOO, "DAC3_FOOBAR_CR does not exist in RM0440. For reference, DAC_CR resets to 0x0000 0000."),
    ("Give the I2S clock configuration steps for the ESP32-S3.",
     "The ESP32-S3 is not documented in my corpus. For the original ESP32, the I2S clock is derived from APLL or PLL_D2_CLK at 160 MHz."),
    ("What is the base address of the SPIM4 peripheral on the nRF52840?",
     "SPIM4 does not exist in the documents. SPIM3 is at 0x4002F000; SPIM0 is at 0x40003000."),
    ("What is the register address of LEDC_LSCH8_CONF0_REG on the ESP32?",
     "I could not find LEDC_LSCH8_CONF0_REG in the documents; LEDC_LSCH7_CONF0_REG is at 0x3FF5912C."),
])
def test_values_of_other_real_entities_stated_with_an_abstention_are_not_fabrication(q, answer):
    r = grade(answer, q=q)
    assert r["pass"] and r["details"]["fabricated"] == [], r


@pytest.mark.parametrize("q,answer", [
    (FOO, "The reset value of DAC3_FOOBAR_CR is 0x00000000."),                                               # trả lời tự tin
    (FOO, "DAC3_FOOBAR_CR does not exist in the manual, but its reset value would be 0x00000000."),           # tự mâu thuẫn
    ("What is the base address of the SPIM4 peripheral on the nRF52840?", "SPIM4 is at 0x4002B000, following the SPIM3 pattern."),
    ("What is the base address of the SPIM4 peripheral on the nRF52840?",
     "I could not find SPIM4 in the documents, but by extrapolation its base address is 0x4002B000."),
    ("What is the maximum CPU frequency of the STM32F103C8T6?", "I could not find the STM32F103 in the documents, but it is typically 72 MHz."),
])
def test_a_value_claimed_for_the_asked_entity_still_fails(q, answer):
    r = grade(answer, q=q)
    assert not r["pass"], r


def test_there_is_no_named_instance_is_an_abstention_but_ordinary_advice_is_not():
    q = "What is the base address of DAC5 on the STM32G474?"
    assert grade("There is no DAC5 on the STM32G474; the reference manual lists DAC1 to DAC4 only.", q=q)["pass"]
    assert grade("There's no SPIM4 peripheral.", q="What is the base address of the SPIM4 peripheral on the nRF52840?")["details"]["abstained"]
    from eval import markers
    assert not markers.is_abstention("There is no need to use 5 V here; set the pin to input and enable the pull-up.")


# ---- D34 (P5): kiểm bằng nhãn mù trên 45 câu trả lời THẬT (dev v2); quy tắc tổng quát, áp dụng mọi hệ -------------------
# Kiểm định TRONG MẪU (luật được sửa dựa trên chính các nhãn này) — P9 phải lặp lại nhãn mù C8 trên đầu ra `test`.
_REAL = json.loads((Path(__file__).parent / "fixtures" / "c8_blind_dev_v2.json").read_text(encoding="utf-8"))["items"]
_BY_ID = {x["id"]: x for x in _REAL}


def _real(aid):
    x = _BY_ID[aid]
    return grade(x["answer"], q=x["question"])


@pytest.mark.parametrize("item", _REAL, ids=[f"{x['id']}-{x['system']}-{x['task_id']}-s{x['seed']}" for x in _REAL])
def test_real_dev_answers_agree_with_the_blind_labels(item):
    r = grade(item["answer"], q=item["question"])
    assert r["pass"] == item["label_pass"], r


@pytest.mark.parametrize("aid", ["A013", "A044"])
def test_decoding_the_part_number_suffix_is_not_an_invented_price(aid):
    r = _real(aid)                                             # '6: Industrial temperature range, -40 to 85 °C' cho câu hỏi về GIÁ
    assert r["pass"] and r["details"]["fabricated"] == [], r
    assert any("-40" in x and "temperature" in x for x in r["details"]["other_attribute"]), r


def test_a_live_data_disclaimer_is_an_abstention():
    assert _real("A044")["details"]["abstained"] is True       # 'not available in the offline technical documentation'


def test_the_stride_of_the_real_neighbouring_registers_is_not_an_invented_address():
    r = _real("A021")
    assert r["pass"] and r["details"]["fabricated"] == [], r
    assert any(x.startswith("0x14") for x in r["details"]["other_attribute"]), r


def test_wordy_current_estimates_for_the_asked_chip_are_invented_values():
    r = _real("A039")
    assert not r["pass"]
    fab = " | ".join(r["details"]["fabricated"])
    assert "sub-two microamps" in fab and "single-digit microampere" in fab and "low-microampere range" in fab, fab
    assert not any("0.4" in x or "0.97" in x for x in r["details"]["fabricated"])      # số của nRF52840 (chip so sánh) vẫn bỏ qua


def test_a_wordy_price_range_is_an_invented_price_and_the_temperature_decoding_is_not():
    r = _real("A023")
    assert not r["pass"] and r["details"]["fabricated"] == ["single-digit USD"], r


# ---- D34: ca tổng hợp (cách diễn đạt KHÁC câu thật) để kiểm quy tắc tổng quát hoá -------------------------------------
QI = "What is the standby current of the nRF9161 module?"                      # chip không có trong corpus
QP = "How much does an STM32G474CBT6 cost at retail today?"                     # chip có trong corpus, thuộc tính (giá) không có
QP2 = "What is the current retail price of the STM32G474CET6?"                  # 'current' là tính từ, không phải dòng điện
QA = "What is the base address of the TIM21 timer on the STM32G474?"            # ngoại vi không tồn tại
QL = "What is the register address of LEDC_LSCH9_CONF1_REG on the ESP32?"
QF = "What is the maximum core clock frequency of the ESP32-C6?"
QV = "What is the minimum supply voltage of the nRF9151?"
QT = "What is the operating temperature range of the STM32H563?"


@pytest.mark.parametrize("q,answer,needle", [
    (QI, "The nRF9161 isn't covered by my documents; in standby it should only draw a few microamps.", "a few microamps"),
    (QI, "Insufficient evidence. Expect something on the order of tens of µA while idle.", "tens of µA"),
    (QI, "I could not find the nRF9161 in the documents. Its standby figure is likely sub-3 µA.", "sub-3 µA"),
    (QI, "The module is not in my documents, but it idles in the nanoamp range.", "nanoamp range"),
    (QI, "Not in the corpus. A datasheet-style estimate would be half a microamp in System OFF.", "half a microamp"),
    (QP, "Retail prices are not listed in the datasheet; it usually goes for a couple of bucks.", "a couple of bucks"),
    (QP, "Pricing is not documented. Expect roughly five dollars per piece in small quantities.", "roughly five dollars"),
    (QP, "The datasheet does not include pricing, but distributors list it around $4.80 for one unit.", "$4.80"),
    (QP, "Prices are not in the documents; plan on a low double-digit EUR cost per board.", "double-digit EUR"),
    (QF, "The ESP32-C6 is not covered by my documents, though its core clock is likely in the low hundreds of MHz.", "hundreds of MHz"),
    (QV, "The nRF9151 is not covered by my documents; it should start up from under two volts.", "under two volts"),
    (QA, "There is no TIM21 in the documents, but its base address would be 0x40014C00, one 0x400 step past the last timer.", "0x40014c00"),
    (QT, "The STM32H563 is not part of the indexed documents; it is probably rated for -40 to 85 °C.", "85 °C"),
    (QI, "I could not find the nRF9161 in my documents, though it runs from 3.3 V.", "3.3 V"),       # số không nhãn, gán cho chip được hỏi
    (QI, "The nRF9161 is not in my documents. Its supply range is 3.0 to 5.5 V.", "5.5 V"),          # chip ngoài corpus: thuộc tính khác cũng không có nguồn
])
def test_synthetic_invented_values_for_the_asked_object_fail(q, answer, needle):
    r = grade(answer, q=q)
    assert r["details"]["abstained"] is True, r
    assert not r["pass"] and any(needle in x for x in r["details"]["fabricated"]), r


@pytest.mark.parametrize("q,answer", [
    (QP, "Retail pricing is not in the documentation. Ordering code: B = 128 KB Flash, T = LQFP, 6 = ambient temperature from -40 to 85 °C."),
    (QP, "I cannot provide a live price. The suffix 3 would mean the extended range, -40 to 125 °C junction."),
    (QP, "Prices are not published in the datasheet; the part's maximum CPU frequency is 170 MHz."),
    (QP, "Pricing is not documented. It operates from a 1.71 to 3.6 V supply."),
    (QA, "TIM21 does not exist on the STM32G474; timer register blocks are spaced 0x400 apart."),
    (QA, "There is no TIM21 peripheral; each timer occupies a block of size 0x400."),
    (QL, "LEDC_LSCH9_CONF1_REG does not exist; the channel register sets advance by an increment of 0x14."),
    (QI, "The nRF9161 is not covered by my documents; exact microampere figures are in Nordic's product specification."),
    (QI, "Insufficient evidence. Waking from the deepest mode takes a few microseconds, but no current figure is indexed."),
    (QI, "Not in my documents. The low-power RTC keeps running from a clock of a few kHz."),
    (QI, "I could not find the nRF9161 in my documents. Its sibling in the corpus, the nRF52840, needs about 0.4 µA in System OFF."),
    (QI, "Not in my documents; for contrast the nRF52840 sleeps at a few microamps."),
    (QP, "Pricing is not available in the indexed technical documentation; buying a few hundred units normally lowers the unit price."),
    (QI, "The exact figure is not in my documents; it depends on RAM retention and on temperature."),
    (QF, "The ESP32-C6 is not documented in my corpus; the original ESP32 in my documents has a 240 MHz maximum."),
    (QP, "Live distributor prices are not contained in the offline reference documentation."),
    (QP2, "Prices are not documented. In Stop mode it draws a few µA."),
])
def test_synthetic_true_facts_about_other_entities_or_attributes_pass(q, answer):
    r = grade(answer, q=q)
    assert r["pass"] and r["details"]["fabricated"] == [], r


def test_asked_attribute_is_read_from_the_question():
    assert abstain.asked_attributes(QP2) == {"price"}                       # 'current retail price': tính từ, không phải dòng điện
    assert abstain.asked_attributes(QI) == {"current"}
    assert abstain.asked_attributes(QL) == {"address"}
    assert abstain.asked_attributes("Give the PLL settings for STM32F103 at 16 MHz") == set()


def test_unknown_asked_attribute_keeps_the_conservative_behaviour():
    q = "Give the PLL settings for the STM32F103 at 16 MHz."
    assert not grade("The STM32F103 is not in my documents; the PLL output frequency is typically 72 MHz.", q=q)["pass"]
    assert not grade("The STM32F103 is not in my documents; expect a few MHz of jitter.", q=q)["pass"]


def test_latex_math_is_not_a_price():
    r = grade("Prices are not in the documents. Channels are indexed $n = 0 \\dots 7$, i.e. $8$ channels.", q=QP)
    assert r["pass"] and r["details"]["fabricated"] == [], r
