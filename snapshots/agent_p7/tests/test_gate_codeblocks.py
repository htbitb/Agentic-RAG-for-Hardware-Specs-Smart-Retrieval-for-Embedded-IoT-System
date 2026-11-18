"""Gate v3 — tách khối code C khỏi câu trả lời (độc lập với eval/graders) và phần văn xuôi cho G1/G4."""
import pytest

from agent.gate import codeblocks as cb

MAIN = """#include "stm32g4xx.h"
int main(void) {
    TIM1->PSC = 0;
    while (1) {}
}"""


def test_tagged_c_blocks_are_extracted_case_insensitively_with_their_position():
    ans = f"Intro.\n```C\n{MAIN}\n```\nThen a helper:\n```cpp\nvoid f(void) {{ TIM1->ARR = 1; }}\n```\n"
    blocks = cb.extract_c_blocks(ans)
    assert [b.n for b in blocks] == [1, 2] and blocks[0].body == MAIN
    assert cb.extract_c_code(ans) == MAIN + "\n\n" + "void f(void) { TIM1->ARR = 1; }"


def test_every_embedded_c_tag_is_accepted():
    for tag in ("c", "cpp", "h", "arm", "cmsis", "stm32", "c99", "embedded-c"):
        assert cb.extract_c_code(f"```{tag}\nTIM1->PSC = 0;\n```") == "TIM1->PSC = 0;", tag


def test_blocks_in_other_languages_are_ignored_but_still_counted_for_numbering():
    ans = "```python\nx = 1;\n```\n```json\n{\"a\": 1}\n```\n```c\nTIM1->PSC = 0;\n```"
    blocks = cb.extract_c_blocks(ans)
    assert [(b.n, b.body) for b in blocks] == [(3, "TIM1->PSC = 0;")]


def test_untagged_block_is_kept_only_if_it_looks_like_c():
    assert cb.extract_c_code("```\nRCC->APB2ENR |= RCC_APB2ENR_TIM1EN;\n```") == "RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;"
    assert cb.extract_c_code("```\nPA8 -> TIM1_CH1 (AF6)\nPA9 -> USART1_TX\n```") == ""            # sơ đồ chân, không có ';'
    assert cb.extract_c_code("```\n{\"pin\": \"PA8\", \"af\": 6}\n```") == ""                       # JSON
    assert cb.extract_c_code("```\nSet PSC to zero, then enable the counter.\n```") == ""


def test_identical_blocks_are_not_repeated():
    ans = f"```c\n{MAIN}\n```\nSame again:\n```c\n{MAIN}\n```"
    assert cb.extract_c_code(ans) == MAIN


def test_register_fragments_next_to_a_full_program_are_dropped():
    ans = f"Do NOT write:\n```c\nTIM1->BDTR = 0;\n```\nFull program:\n```c\n{MAIN}\n```\nHelper:\n```c\nstatic void g(void) {{ TIM1->CCR1 = 5; }}\n```"
    assert cb.extract_c_code(ans) == MAIN + "\n\n" + "static void g(void) { TIM1->CCR1 = 5; }"


def test_fragments_without_any_program_are_kept():
    ans = "```c\nUSART2->BRR = 0x683;\n```\nand\n```c\nUSART2->CR1 = USART_CR1_UE;\n```"
    assert cb.extract_c_code(ans) == "USART2->BRR = 0x683;\n\nUSART2->CR1 = USART_CR1_UE;"


def test_an_unterminated_final_fence_still_yields_its_code():
    assert cb.extract_c_code("text\n```c\nTIM1->PSC = 0;\n") == "TIM1->PSC = 0;"


def test_prose_drops_analysed_c_fences_but_keeps_inline_code_text():
    """Fix round 1 (C3): mã nội tuyến được G1 kiểm (trước đây bị bỏ); chỉ khối C mà G2 phân tích bị loại."""
    ans = "Use `TIM1->PSC = 0x10` at 170 MHz.\n```c\nTIM1->ARR = 0x2133;\n```\nDone at 20 kHz."
    p = cb.prose(ans)
    assert "0x10" in p and "0x2133" not in p and "170 MHz" in p and "20 kHz" in p


def test_program_of_a_full_answer_is_not_wrapped_and_locates_lines_per_block():
    ans = f"```c\n{MAIN}\n```\ntext\n```c\nvoid h(void) {{\n    TIM1->ARR = 9;\n}}\n```"
    prog = cb.program(ans)
    assert prog.wrapped is False and prog.code == cb.extract_c_code(ans)
    assert prog.locate(3) == "code block 1, line 3"
    assert prog.locate(8) == "code block 2, line 2"                 # 5 dòng khối 1 + 1 dòng trống ngăn cách + dòng 2 của khối 2


def test_fragment_only_answers_are_wrapped_into_a_function_with_the_device_header():
    ans = "```c\n#include \"stm32g4xx.h\"\nUSART2->BRR = 0x683;\n```\n```c\nUSART2->CR1 = USART_CR1_UE;\n```"
    prog = cb.program(ans)
    assert prog.wrapped is True
    assert prog.code.count("#include") == 1 and "void" in prog.code and prog.code.rstrip().endswith("}")
    line = next(i for i, l in enumerate(prog.code.split("\n"), 1) if "USART2->CR1" in l)
    assert prog.locate(line) == "code block 2, line 1"
    line = next(i for i, l in enumerate(prog.code.split("\n"), 1) if "USART2->BRR" in l)
    assert prog.locate(line) == "code block 1, line 2"


def test_no_c_code_gives_no_program():
    assert cb.program("Only prose here, 20 kHz.") is None


# ------------------------------------------------------------------------------------------------ fix round 1 (C3, I4, I5)
def test_latex_is_normalised_to_plain_numbers_and_units():
    n = cb.normalize_text
    assert "4.6 V" in " ".join(n(r"$V_{DD,max} = 4.6\,\text{V}$").split())
    assert "4.6 V" in " ".join(n(r"$4.6\text{ V}$").split())
    assert "50 µs" in " ".join(n(r"$T = 50\ \mu\text{s}$").split())
    assert "(170 000 000) / (20 000)" in " ".join(n(r"$\frac{170\,000\,000}{20\,000}$").split())
    assert "4 × 85 = 340 MHz" in " ".join(n(r"$4 \times 85 = 340\text{ MHz}$").split())
    assert "f_TIM1CLK" in n(r"$f_{\text{TIM1CLK}}$")


def test_prose_keeps_inline_code_and_non_c_fences_but_drops_the_c_code_g2_analyses():
    ans = ("TIM1 base is `0x40013C00`.\n```text\nVDD absolute maximum: 4.6 V\n```\n```\nVDD max 4.7 V\n```\n"
           "```c\nint main(void) { TIM1->ARR = 0x2133; while (1) { } }\n```\n")
    p = cb.prose(ans)
    assert "0x40013C00" in p and "4.6 V" in p and "4.7 V" in p and "0x2133" not in p


def test_prior_prose_drops_every_fence_and_inline_code():
    p = cb.prior_prose("PCLK1 = $85\\text{ MHz}$ `x = 13`.\n```text\n98 MHz\n```\n")
    assert "85 MHz" in p and "13" not in p and "98" not in p


@pytest.mark.parametrize("text,values", [
    ("20,000 Hz", {20000.0, 20.0}), ("170,000,000 Hz", {170e6}), ("20.000 Hz", {20.0, 20000.0}), ("170.000.000 Hz", {170e6}),
    ("4,0 V", {4.0}), ("1,71 V", {1.71}), ("1,234.5 Hz", {1234.5}), ("1.234,5 Hz", {1234.5}), ("170 000 000 Hz", {170e6}),
    ("1.7e8 Hz", {1.7e8}), ("-0.3 V", {-0.3}), ("−0.3 V", {-0.3}), ("4.6 volts", {4.6})])
def test_quantities_accept_digit_grouping_and_decimal_commas(text, values):
    q = cb.quantities(text)
    assert len(q) == 1 and set(q[0].values) == values and q[0].unknown is False, q


def test_a_quantity_glued_to_an_unparseable_number_is_flagged_unknown():
    q = cb.quantities("The rails are 1,2,3 V.")
    assert len(q) == 1 and q[0].unknown is True


@pytest.mark.parametrize("s,advice", [("Use a 3.3 V regulator.", True), ("You can power VDD from 5 V.", True),
                                      ("Bạn có thể cấp trực tiếp 5 V vào chân VDD.", True), ("Hãy nối VDD với nguồn 5 V.", True),
                                      ("The board runs at 3.3 V.", False), ("VDD = 5 V works.", False)])
def test_advice_detection_in_english_and_vietnamese(s, advice):
    assert cb.is_advice(s) is advice


@pytest.mark.parametrize("s", ["Do not apply 5 V to VDD.", "Không cấp 5 V vào VDD.", "Tránh vượt quá 4,0 V.", "Giá trị tối đa tuyệt đối là 4.0 V.",
                               "Đừng nối 5 V.", "Never exceed 4 V."])
def test_negation_and_warning_words_in_both_languages(s):
    assert cb.has_negation(s)


def test_sentences_split_on_sentence_ends_and_lines_but_not_decimals():
    assert [t for _, _, t in cb.sentences("VDD is 4.0 V. Use 3.3 V; keep it.\n- PSC = 0")] == ["VDD is 4.0 V.", "Use 3.3 V;", "keep it.", "- PSC = 0"]


# ------------------------------------------------------------------------------------------------ fix round 2 (I-3, m4)
@pytest.mark.parametrize("latex,folded", [(r"$1.7 \times 10^{8}$ Hz", "1.7e8 Hz"), (r"$2.5 \times 10^{-3}$ A", "2.5e-3 A"), ("3·10^6 Hz", "3e6 Hz"),
                                          (r"$2 \cdot 10^{4}$ Hz", "2e4 Hz"), (r"$5\,10^{3}$ Hz", "5e3 Hz"), (r"$10^{6}$ Hz", "1e6 Hz"),
                                          ("1.7 × 10^8 Hz", "1.7e8 Hz")])
def test_i3_scientific_notation_is_folded_into_one_number(latex, folded):
    assert folded in " ".join(cb.normalize_text(latex).split())


def test_i3_an_exponent_is_never_read_as_the_number_before_a_unit():
    q = cb.quantities(cb.normalize_text(r"$f = \frac{170 \times 10^{6}\,\text{Hz}}{8500} = 20\,\text{kHz}$"))
    assert [(x.si, x.base) for x in q] == [((170e6,), "Hz"), ((20e3,), "Hz")]
    assert cb.quantities("x^6 Hz") == [] and cb.quantities("x^{6} Hz") == []


def test_m4_a_number_too_large_for_a_float_is_unknown_not_an_exception():
    assert cb.number_values("1e309") == []
    q = cb.quantities("f = 1e309 Hz")
    assert len(q) == 1 and q[0].unknown is True


def test_i3_folding_keeps_surrounding_parentheses():
    assert " ".join(cb.normalize_text("(1.7 × 10^8)/8500 and 2·10^(3)").split()) == "(1.7e8)/8500 and 2e3"
