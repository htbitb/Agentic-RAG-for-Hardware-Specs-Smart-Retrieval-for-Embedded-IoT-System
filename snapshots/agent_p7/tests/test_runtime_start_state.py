"""D36: trạng thái khởi đầu của G2 do INTAKE trích từ lời người dùng / Board State, không do agent tự chọn."""
import pytest

from agent.runtime.start_state import extract_start, preset_from_derived

CONV = ("Initial state: SYSCLK = HCLK = PCLK1 = PCLK2 = 170 MHz (PLL fed by HSI16, AHB/APB1/APB2 prescalers = 1, voltage Range 1 boost mode, Flash wait states "
        "already set). Write bare-metal C ...")


@pytest.mark.parametrize("text,preset", [
    (CONV, "sysclk_170mhz_pll_hsi16_apb_div1"),
    ("Initial state: SYSCLK = HCLK = PCLK2 = 170 MHz (PLL fed by HSI16, voltage Range 1 boost mode, Flash wait states already set); the APB2 prescaler is 1 and the "
     "APB1 prescaler is 2, so PCLK1 = 85 MHz.", "sysclk_170mhz_pll_hsi16_apb1_div2"),
    ("Initial state: SYSCLK = HCLK = PCLK1 = PCLK2 = 170 MHz (PLL fed by HSI16); the APB1 prescaler is 1 and the APB2 prescaler is 2, so PCLK2 = 85 MHz.",
     "sysclk_170mhz_pll_hsi16_apb2_div2"),
    ("Initial state: the chip has just come out of reset: SYSCLK = HCLK = PCLK1 = PCLK2 = 16 MHz (HSI16), all prescalers are 1, no peripheral clock enabled.", "reset"),
    ("Initial state: the chip is in its reset state (HSI16 at 16 MHz).", "reset"),
    ("The clock is already running at SYSCLK = 80 MHz from the PLL (HSI16 source), all prescalers 1.", "sysclk_80mhz_pll_hsi16_apb_div1"),
    ("Plan a PWM output on PA8 for an STM32G474 at 170 MHz (PLL from HSI16, APB prescalers 1).", "sysclk_170mhz_pll_hsi16_apb_div1"),
    ("The MCU is running at 80 MHz from the PLL (HSI16).", "sysclk_80mhz_pll_hsi16_apb_div1"),
])
def test_the_start_preset_is_read_from_the_description_of_the_initial_state(text, preset):
    st = extract_start([text], None)
    assert st["initial"] == preset and st["source"] == "user_text" and st["evidence"]


@pytest.mark.parametrize("text", [
    "Generate a PWM at 20 kHz on PA8.",
    "Configure the PLL so that SYSCLK = 170 MHz from the HSE.",                     # 170 MHz là mục tiêu của thiết kế, không phải trạng thái khởi đầu
    "Design a node: STM32G474 drives a motor by PWM; the SYSCLK must be at most 170 MHz.",
    "Initial state: SYSCLK = 100 MHz from the PLL, all prescalers 1.",             # không có preset tương ứng
    "Configure PWM 20 kHz on PA8 of an STM32G474 at 170 MHz (PLL from HSI16, APB prescalers 1).",      # câu mục tiêu có động từ cấu hình: không phải trạng thái
    "Make the MCU run at 170 MHz from the PLL (HSI16).",
])
def test_text_that_does_not_describe_a_known_initial_state_gives_no_preset(text):
    assert extract_start([text], None)["initial"] is None


def test_the_latest_description_wins_across_turns():
    st = extract_start([CONV, "Actually the chip has just come out of reset: SYSCLK = 16 MHz (HSI16)."], None)
    assert st["initial"] == "reset"


def test_both_apb_prescalers_at_two_has_no_preset():
    assert extract_start(["Initial state: SYSCLK = 170 MHz from the PLL (HSI16); the APB1 prescaler is 2 and the APB2 prescaler is 2."], None)["initial"] is None


@pytest.mark.parametrize("text,hz", [
    ("The board has an 8 MHz crystal on HSE.", 8_000_000),
    ("HSE = 25 MHz", 25_000_000),
    ("The HSE crystal is 12 MHz.", 12_000_000),
    ("An external 24 MHz oscillator feeds HSE.", 24_000_000),
    ("HSE: 16MHz", 16_000_000),
])
def test_the_hse_frequency_is_read_from_the_users_words(text, hz):
    assert extract_start([text], None)["hse_hz"] == hz


def test_no_hse_when_only_other_clocks_are_mentioned():
    assert extract_start(["The RTC uses a 32.768 kHz crystal; SYSCLK 170 MHz."], None)["hse_hz"] is None


def test_human_answers_count_like_user_text():
    st = extract_start([CONV, "Generate PWM."], None, human_answers=["The board has a 12 MHz crystal on HSE."])
    assert st["hse_hz"] == 12_000_000 and st["initial"] == "sysclk_170mhz_pll_hsi16_apb_div1"


def test_the_board_clock_is_used_when_the_user_did_not_describe_a_start_state():
    board = {"clock": {"cfg": {"source": "PLL"}, "derived": {"sysclk_hz": 170_000_000, "hclk_hz": 170_000_000, "pclk1_hz": 85_000_000, "pclk2_hz": 170_000_000,
                                                              "sysclk_source": "PLL", "pll": {"source": "HSI16"}}}}
    st = extract_start(["Add an I2C sensor."], board)
    assert st["initial"] == "sysclk_170mhz_pll_hsi16_apb1_div2" and st["source"] == "board_clock"


def test_the_users_description_beats_the_board_clock():
    board = {"clock": {"cfg": {"source": "PLL"}, "derived": {"sysclk_hz": 80_000_000, "hclk_hz": 80_000_000, "pclk1_hz": 80_000_000, "pclk2_hz": 80_000_000,
                                                              "sysclk_source": "PLL", "pll": {"source": "HSI16"}}}}
    assert extract_start([CONV], board)["initial"] == "sysclk_170mhz_pll_hsi16_apb_div1"


@pytest.mark.parametrize("derived,preset", [
    ({"sysclk_hz": 16_000_000, "hclk_hz": 16_000_000, "pclk1_hz": 16_000_000, "pclk2_hz": 16_000_000, "sysclk_source": "HSI16"}, "reset"),
    ({"sysclk_hz": 170_000_000, "hclk_hz": 170_000_000, "pclk1_hz": 170_000_000, "pclk2_hz": 85_000_000, "sysclk_source": "PLL", "pll": {"source": "HSI16"}},
     "sysclk_170mhz_pll_hsi16_apb2_div2"),
    ({"sysclk_hz": 168_000_000, "hclk_hz": 168_000_000, "pclk1_hz": 168_000_000, "pclk2_hz": 168_000_000, "sysclk_source": "PLL", "pll": {"source": "HSE"}}, None),
    ({"sysclk_hz": 170_000_000, "hclk_hz": 170_000_000, "pclk1_hz": 170_000_000, "pclk2_hz": 170_000_000, "sysclk_source": "PLL", "pll": {"source": "HSE"}}, None),
])
def test_preset_from_derived_frequencies(derived, preset):
    assert preset_from_derived(derived) == preset
