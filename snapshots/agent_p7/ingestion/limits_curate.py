"""Giới hạn điện (absolute max / recommended operating / DC) và giới hạn clock của 3 chip -> `electrical_limits`, `clock_limits`.

Đây là dữ liệu TUYỂN CHỌN (curated) — bảng điện/clock trong PDF có định dạng quá hỗn tạp để trích tự động đáng tin
(cột gộp, chú thích chen giữa, ký tự lạ). Để không "bịa" số, MỖI dòng mang `doc`, `page` và một chuỗi trích NGUYÊN VĂN
(`quote`); `verify_row` kiểm tự động rằng (1) chuỗi đó có trên text trang PDF (bỏ qua khoảng trắng/hoa-thường) và (2) mọi
số trong min/typ/max xuất hiện trong chuỗi đó. Dòng không qua kiểm → script dừng, không ghi DB.

Cấu trúc `results[*]` mà `react_agent._hardware_check` / `guardrail.evaluate_hw` cần được giữ: `category`
(absolute_max | recommended_operating | dc_characteristics), `field_type` (supply_voltage, input_voltage, input_voltage_high,
...), `min`, `max` (số hoặc biểu thức theo VDD: "VDD+0.3"), `unit`, `parameter`, `doc`, `page`.
Chuỗi trích có thể gồm nhiều đoạn ngăn cách bằng " ... " (mỗi đoạn phải có trên trang).
"""
from __future__ import annotations

import re

from . import pdfdocs
from .pinout_extract import verify_quote

ST_DS, ST_RM, ESP_DS, NRF_PS = "STM32G474_Datasheet", "STM32G474_RM0440", "ESP32_Datasheet", "nRF52840_PS"
CATEGORIES = {"absolute_max", "recommended_operating", "dc_characteristics", "power_consumption"}


def E(chip, parameter, category, field_type, symbol, mn, typ, mx, unit, doc, page, quote, condition="", applies_to=""):
    return dict(chip=chip, parameter=parameter, category=category, field_type=field_type, symbol=symbol, min=mn, typ=typ,
                max=mx, unit=unit, condition=condition, applies_to=applies_to, doc=doc, page=page, quote=quote)


def _st(parameter, category, field_type, symbol, mn, typ, mx, unit, page, quote, **kw):
    return E("stm32g474", parameter, category, field_type, symbol, mn, typ, mx, unit, ST_DS, page, quote, **kw)


def _esp(parameter, category, field_type, symbol, mn, typ, mx, unit, page, quote, **kw):
    return E("esp32", parameter, category, field_type, symbol, mn, typ, mx, unit, ESP_DS, page, quote, **kw)


def _nrf(parameter, category, field_type, symbol, mn, typ, mx, unit, page, quote, **kw):
    return E("nrf52840", parameter, category, field_type, symbol, mn, typ, mx, unit, NRF_PS, page, quote, **kw)


A, R, D, P = "absolute_max", "recommended_operating", "dc_characteristics", "power_consumption"

ELECTRICAL: list[dict] = [
    # ------------------------------------------------------------------ STM32G474 (DS12288 Rev 6)
    _st("Supply voltage VDD", A, "supply_voltage", "VDD-VSS", "-0.3", None, "4.0", "V", 82,
        "VDD - VSS External main supply voltage (including VDD, VDDA, VBAT and VREF+) -0.3 4.0",
        condition="Table 14. External main supply voltage (including VDD, VDDA, VBAT and VREF+)"),
    _st("Input voltage VIN on FT_xxx pins except FT_c", A, "input_voltage", "VIN", "-0.3", None, "VDD+4.0", "V", 82,
        "Input voltage on FT_xxx pins except FT_c pins VSS-0.3 min (VDD, VDDA) + 4.0",
        condition="Table 14: min = VSS-0.3 V; max = min(VDD, VDDA)+4.0 V (formula applies to the supplies of that I/O "
                  "structure; above 4 V the internal pull-up/pull-down must be disabled)",
        applies_to="FT_xxx except FT_c"),
    _st("Input voltage VIN on FT_c pins", A, "input_voltage", "VIN", "-0.3", None, "5.5", "V", 82,
        "Input voltage on FT_c pins V SS-0.3 5.5", condition="Table 14: min = VSS-0.3 V", applies_to="FT_c"),
    _st("Input voltage VIN on TT_xx pins", A, "input_voltage", "VIN", "-0.3", None, "4.0", "V", 82,
        "Input voltage on TT_xx pins V SS-0.3 4.0", condition="Table 14: min = VSS-0.3 V", applies_to="TT_xx"),
    _st("Input voltage VIN on any other pins", A, "input_voltage", "VIN", "-0.3", None, "4.0", "V", 82,
        "Input voltage on any other pins V SS-0.3 4.0", condition="Table 14: min = VSS-0.3 V", applies_to="other pins"),
    _st("Output current sunk by any I/O and control pin", A, "current", "IIO(PIN)", None, None, "20", "mA", 83,
        "Output current sunk by any I/O and control pin except FT_f 20", condition="Table 15; FT_f pins: also 20 mA"),
    _st("Output current sourced by any I/O and control pin", A, "current", "IIO(PIN)", None, None, "20", "mA", 83,
        "Output current sourced by any I/O and control pin 20", condition="Table 15"),
    _st("Storage temperature", A, "temperature", "TSTG", "-65", None, "150", "°C", 83,
        "TSTG Storage temperature range –65 to +150 °C", condition="Table 16"),
    _st("Maximum junction temperature", A, "temperature", "TJ", None, None, "150", "°C", 83,
        "TJ Maximum junction temperature 150 °C", condition="Table 16"),
    _st("Supply voltage VDD", R, "supply_voltage", "VDD", "1.71", None, "3.6", "V", 84,
        "VDD Standard operating voltage - 1.71 (1) 3.6 V",
        condition="Table 17 standard operating voltage; when RESET is released functionality is guaranteed down to VBOR0 min"),
    _st("Analog supply voltage VDDA (ADC or COMP used)", R, "analog_supply_voltage", "VDDA", "1.62", None, "3.6", "V", 84,
        "ADC or COMP used 1.62 3.6", condition="Table 17; 1.71 V for DAC, 2.0 V for OPAMP, 2.4 V for VREFBUF"),
    _st("Backup operating voltage VBAT", R, "backup_supply_voltage", "VBAT", "1.55", None, "3.6", "V", 84,
        "VBAT Backup operating voltage - 1.55 3.6 V", condition="Table 17"),
    _st("Input voltage VIN on TT_xx pins", R, "input_voltage", "VIN", "-0.3", None, "VDD+0.3", "V", 84,
        "TT_xx -0.3 V DD+0.3", condition="Table 17: min = -0.3 V", applies_to="TT_xx"),
    _st("Input voltage VIN on FT_c pins", R, "input_voltage", "VIN", "-0.3", None, "5", "V", 84,
        "FT_c -0.3 5", condition="Table 17: min = -0.3 V", applies_to="FT_c"),
    _st("Input voltage VIN on all I/O except TT_xx and FT_c", R, "input_voltage", "VIN", "-0.3", None, "5.5", "V", 84,
        "All I/O except TT_xx and FT_c -0.3 MIN(MIN(VDD, VDDA)+3.6 V, 5.5 V)",
        condition="Table 17: max = MIN(MIN(VDD, VDDA)+3.6 V, 5.5 V), i.e. 5.5 V when VDD >= 1.9 V; above min(VDD,VDDA)+0.3 V "
                  "the internal pull-up/pull-down must be disabled", applies_to="FT_xxx except FT_c"),
    _st("Ambient temperature, suffix 6", R, "temperature", "TA", "-40", None, "85", "°C", 84,
        "Maximum power dissipation -40 85", condition="Table 17, suffix 6 version, maximum power dissipation"),
    _st("Ambient temperature, suffix 3", R, "temperature", "TA", "-40", None, "125", "°C", 84,
        "Maximum power dissipation -40 125", condition="Table 17, suffix 3 version, maximum power dissipation"),
    _st("Junction temperature, suffix 6", R, "temperature", "TJ", "-40", None, "105", "°C", 84,
        "Suffix 6 version -40 105", condition="Table 17"),
    _st("Junction temperature, suffix 3", R, "temperature", "TJ", "-40", None, "130", "°C", 84,
        "Suffix 3 version -40 130", condition="Table 17"),
    _st("Input low level voltage VIL", D, "input_voltage_low", "VIL", None, None, "0.3*VDD", "V", 128,
        "All except FT_c 1.62 V<VDD<3.6 V - - 0.3xVDD", condition="Table 54, all I/O except FT_c, 1.62 V < VDD < 3.6 V"),
    _st("Input high level voltage VIH", D, "input_voltage_high", "VIH", "0.7*VDD", None, None, "V", 128,
        "All except FT_c 1.62 V<VDD<3.6 V 0.7xVDD", condition="Table 54, all I/O except FT_c, 1.62 V < VDD < 3.6 V"),
    _st("Output low level voltage VOL", D, "output_voltage_low", "VOL", None, None, "0.4", "V", 130,
        "CMOS port |IIO| = 2 mA for FT_c I/Os = 8 mA for other I/Os VDD ≥ 2.7 V -0 . 4",
        condition="Table 55, CMOS port, |IIO| = 8 mA (2 mA for FT_c), VDD >= 2.7 V"),
    _st("Output high level voltage VOH", D, "output_voltage_high", "VOH", "VDD-0.4", None, None, "V", 130,
        "VOH(3) Output high level voltage for an I/O pin V DD-0.4 -",
        condition="Table 55, CMOS port, |IIO| = 8 mA (2 mA for FT_c), VDD >= 2.7 V"),
    # ------------------------------------------------------------------ ESP32 (Datasheet v5.3)
    _esp("Supply voltage VDD3P3 / VDDA / VDD3P3_RTC / VDD3P3_CPU / VDD_SDIO", A, "supply_voltage", "VDD", "-0.3", None, "3.6", "V", 51,
         "VDDA, VDD3P3, VDD3P3_RTC, VDD3P3_CPU, VDD_SDIO Allowed input voltage ⚶0.3 3.6 V", condition="Table 5-1 allowed input voltage"),
    _esp("Cumulative IO output current", A, "current", "Ioutput", None, None, "1200", "mA", 51,
         "Ioutput1 Cumulative IO output current — 1200 mA", condition="Table 5-1"),
    _esp("Storage temperature", A, "temperature", "TSTORE", "-40", None, "150", "°C", 51,
         "TST ORE Storage temperature ⚶40 150 °C", condition="Table 5-1"),
    _esp("Supply voltage VDDA / VDD3P3_RTC / VDD3P3 / VDD_SDIO (3.3 V mode)", R, "supply_voltage", "VDD", "2.3", "3.3", "3.6", "V", 51,
         "pins per power domain 2.3/3.0 note 2 3.3 3.6 V",
         condition="Table 5-2: min 3.0 V for chips with 3.3 V flash/PSRAM in-package; 2.3 V for chips without in-package flash/PSRAM"),
    _esp("Supply voltage VDD3P3_CPU", R, "supply_voltage", "VDD3P3_CPU", "1.8", "3.3", "3.6", "V", 51,
         "VDD3P3_CPU Voltage applied to power supply pin 1.8 3.3 3.6 V", condition="Table 5-2"),
    _esp("Current delivered by external power supply", R, "current", "IVDD", "0.5", None, None, "A", 51,
         "IV DD Current delivered by external power supply 0.5 — — A", condition="Table 5-2"),
    _esp("Operating temperature", R, "temperature", "T", "-40", None, "125", "°C", 51,
         "T note 3 Operating temperature ⚶40 — 125 °C", condition="Table 5-2; 85 °C max for ESP32-U4WDH and ESP32-D0WDRH2-V3 (in-package flash/PSRAM)"),
    _esp("High-level input voltage VIH", D, "input_voltage_high", "VIH", "0.75*VDD", None, "VDD+0.3", "V", 52,
         "VIH High-level input voltage 0.75 × VDD 1 — VDD 1 + 0.3 V",
         condition="Table 5-3 (3.3 V, 25 °C); VDD is the I/O voltage of the pin's power domain; max = VDD + 0.3 V"),
    _esp("Low-level input voltage VIL", D, "input_voltage_low", "VIL", "-0.3", None, "0.25*VDD", "V", 52,
         "VIL Low-level input voltage ⚶0.3 — 0.25 × VDD 1 V", condition="Table 5-3"),
    _esp("High-level output voltage VOH", D, "output_voltage_high", "VOH", "0.8*VDD", None, None, "V", 52,
         "VOH High-level output voltage 0.8 × VDD 1 — — V", condition="Table 5-3"),
    _esp("Low-level output voltage VOL", D, "output_voltage_low", "VOL", None, None, "0.1*VDD", "V", 52,
         "VOL Low-level output voltage — — 0.1 × VDD 1 V", condition="Table 5-3"),
    _esp("High-level source current IOH (VDD3P3_CPU power domain)", D, "current", "IOH", None, "40", None, "mA", 52,
         "VDD3P3_CPU power domain 1, 2 — 40 — mA",
         condition="Table 5-3: VDD = 3.3 V, VOH >= 2.64 V, output drive strength set to the maximum; per-pin current falls to about 29 mA as more pins source current"),
    _esp("High-level source current IOH (VDD_SDIO power domain)", D, "current", "IOH", None, "20", None, "mA", 52,
         "VDD_SDIO power domain 1, 3 — 20 — mA", condition="Table 5-3: VDD = 3.3 V, VOH >= 2.64 V, maximum drive strength"),
    _esp("Low-level sink current IOL", D, "current", "IOL", None, "28", None, "mA", 52,
         "output drive strength set to the maximum) — 28 — mA", condition="Table 5-3: VDD = 3.3 V, VOL = 0.495 V, maximum drive strength"),
    _esp("CHIP_PU reset release voltage VIH_nRST", D, "reset_pin_voltage", "VIH_nRST", "0.75*VDD", None, "VDD+0.3", "V", 52,
         "(CHIP_PU voltage is within the specified range) 0.75 × VDD 1 — VDD 1 + 0.3 V", condition="Table 5-3"),
    _esp("CHIP_PU low-level input voltage VIL_nRST", D, "reset_pin_voltage", "VIL_nRST", None, None, "0.6", "V", 52,
         "VIL_nRST Low-level input voltage of CHIP_PU to shut down the chip — — 0.6 V", condition="Table 5-3"),
    _esp("Deep-sleep current: ULP coprocessor powered up", P, "current", "IDD", None, "150", None, "µA", 30,
         "The ULP coprocessor is powered up. 150 µA", condition="Table 4-2 power modes; Deep-sleep"),
    _esp("Deep-sleep current: ULP sensor-monitored pattern", P, "current", "IDD", None, "100", None, "µA", 30,
         "ULP sensor-monitored pattern 100 µA @1% duty", condition="Table 4-2; Deep-sleep, 1% duty"),
    _esp("Deep-sleep current: RTC timer + RTC memory", P, "current", "IDD", None, "10", None, "µA", 30,
         "RTC timer + RTC memory 10 µA", condition="Table 4-2; Deep-sleep, RTC timer and RTC memory powered"),
    _esp("Hibernation current: RTC timer only", P, "current", "IDD", None, "5", None, "µA", 30,
         "Hibernation RTC timer only 5 µA", condition="Table 4-2; Hibernation, only the RTC timer on the slow clock"),
    _esp("Light-sleep current", P, "current", "IDD", None, "0.8", None, "mA", 30,
         "Light-sleep - 0.8 mA", condition="Table 4-2"),
    _esp("Power-off current", P, "current", "IDD", None, "1", None, "µA", 30,
         "Power off CHIP_PU is set to low level, the chip is powered down. 1 µA", condition="Table 4-2"),
    _esp("Modem-sleep current, 80 MHz dual-core", P, "current", "IDD", "20", None, "31", "mA", 30,
         "Normal speed: 80 MHz Dual-core chip(s) 20 mA ~ 31 mA", condition="Table 4-2; CPU powered up, dual-core chips"),
    _esp("Modem-sleep current, 160 MHz dual-core", P, "current", "IDD", "27", None, "44", "mA", 30,
         "160 MHz * Dual-core chip(s) 27 mA ~ 44 mA", condition="Table 4-2; CPU powered up, dual-core chips"),
    _esp("Modem-sleep current, 240 MHz dual-core", P, "current", "IDD", "30", None, "68", "mA", 30,
         "240 MHz * Dual-core chip(s) 30 mA ~ 68 mA", condition="Table 4-2; CPU powered up, dual-core chips"),
    # ------------------------------------------------------------------ nRF52840 (PS v1.11)
    _nrf("Supply voltage VDD", A, "supply_voltage", "VDD", "-0.3", None, "3.9", "V", 972, "VDD -0.3 +3.9 V", condition="Table 101"),
    _nrf("High-voltage supply VDDH", A, "supply_voltage_high", "VDDH", "-0.3", None, "5.8", "V", 972, "VDDH -0.3 +5.8 V", condition="Table 101"),
    _nrf("USB supply VBUS", A, "supply_voltage_usb", "VBUS", "-0.3", None, "5.8", "V", 972, "VBUS -0.3 +5.8 V", condition="Table 101"),
    _nrf("I/O pin voltage (VDD <= 3.6 V)", A, "input_voltage", "VI/O", "-0.3", None, "VDD+0.3", "V", 972,
         "VI/O, VDD ≤3.6 V -0.3 VDD + 0.3 V", condition="Table 101, VDD <= 3.6 V", applies_to="all GPIO"),
    _nrf("I/O pin voltage (VDD > 3.6 V)", A, "input_voltage", "VI/O", "-0.3", None, "3.9", "V", 972,
         "VI/O, VDD >3.6 V -0.3 3.9 V", condition="Table 101, VDD > 3.6 V", applies_to="all GPIO"),
    _nrf("NFC antenna pin current", A, "current", "INFC1/2", None, None, "80", "mA", 972, "INFC1/2 80 mA", condition="Table 101"),
    _nrf("Storage temperature (aQFN73)", A, "temperature", "TSTORE", "-40", None, "125", "°C", 972,
         "Environmental aQFN73 package Storage temperature -40 +125 °C", condition="Table 101"),
    _nrf("Supply voltage VDD", R, "supply_voltage", "VDD", "1.7", "3.0", "3.6", "V", 971,
         "VDD VDD supply voltage, independent of DCDC enable 1.7 3.0 3.6 V", condition="Table 100"),
    _nrf("High-voltage supply VDDH", R, "supply_voltage_high", "VDDH", "2.5", "3.7", "5.5", "V", 971,
         "VDDH VDDH supply voltage, independent of DCDC enable 2.5 3.7 5.5 V", condition="Table 100"),
    _nrf("USB supply VBUS", R, "supply_voltage_usb", "VBUS", "4.35", "5.0", "5.5", "V", 971,
         "VBUS VBUS USB supply voltage 4.35 5.0 5.5 V", condition="Table 100"),
    _nrf("Operating temperature", R, "temperature", "TA", "-40", "25", "85", "°C", 971,
         "TA Operating temperature -40 25 85 °C", condition="Table 100"),
    _nrf("Input high voltage VIH", D, "input_voltage_high", "VIH", "0.7*VDD", None, None, "V", 370,
         "VIH Input high voltage 0.7 x VDD VDD V",
         condition="6.9.3.1 GPIO electrical specification: logic-high range is 0.7×VDD to VDD (VDD is the upper edge of the range, "
                   "not a damage limit, so it is not stored as `max`); the absolute maximum I/O voltage is VDD+0.3 V (Table 101, p.972)"),
    _nrf("Input low voltage VIL", D, "input_voltage_low", "VIL", "0", None, "0.3*VDD", "V", 370,
         "VIL Input low voltage VSS 0.3 x VDD V", condition="6.9.3.1: min = VSS"),
    _nrf("Output high voltage VOH (standard drive)", D, "output_voltage_high", "VOH,SD", "VDD-0.4", None, "VDD", "V", 370,
         "VOH,SD Output high voltage, standard drive, 0.5 mA, VDD ≥ 1.7 VDD - 0.4 VDD V",
         condition="6.9.3.1: standard drive, 0.5 mA, VDD >= 1.7 V"),
    _nrf("Output low voltage VOL (standard drive)", D, "output_voltage_low", "VOL,SD", "0", None, "0.4", "V", 370,
         "VOL,SD Output low voltage, standard drive, 0.5 mA, VDD ≥ 1.7 VSS VSS + 0.4 V",
         condition="6.9.3.1: standard drive, 0.5 mA, VDD >= 1.7 V; min = VSS, max = VSS+0.4 V"),
    _nrf("Output low current IOL (standard drive)", D, "current", "IOL,SD", "1", "2", "4", "mA", 370,
         "IOL,SD Current at VSS+0.4 V, output set low, standard drive, VDD ≥ 1.7 1 2 4 mA", condition="6.9.3.1"),
    _nrf("Output high current IOH (standard drive)", D, "current", "IOH,SD", "1", "2", "4", "mA", 370,
         "IOH,SD Current at VDD-0.4 V, output set high, standard drive, VDD ≥ 1.7 1 2 4 mA", condition="6.9.3.1"),
]


def _c(chip, doc, parameter, symbol, mn, typ, mx, unit, page, quote, condition=""):
    return dict(chip=chip, parameter=parameter, symbol=symbol, min=mn, typ=typ, max=mx, unit=unit, condition=condition,
                doc=doc, page=page, quote=quote, category=None)


def CLOCK_ROWS() -> list[dict]:
    rows = [
        # ---- STM32G474
        _c("stm32g474", ST_DS, "AHB clock frequency (HCLK / SYSCLK limit)", "fHCLK", "0", None, "170", "MHz", 84,
           "fHCLK Internal AHB clock frequency - 0 170", "Table 17 general operating conditions"),
        _c("stm32g474", ST_DS, "APB1 clock frequency", "fPCLK1", "0", None, "170", "MHz", 84,
           "fPCLK1 Internal APB1 clock frequency - 0 170", "Table 17"),
        _c("stm32g474", ST_DS, "APB2 clock frequency", "fPCLK2", "0", None, "170", "MHz", 84,
           "fPCLK2 Internal APB2 clock frequency - 0 170", "Table 17"),
        _c("stm32g474", ST_DS, "HSE crystal/ceramic resonator frequency", "fOSC_IN", "4", "8", "48", "MHz", 117,
           "fOSC_IN Oscillator frequency - 4 8 48 MHz", "Table 41 HSE oscillator characteristics"),
        _c("stm32g474", ST_DS, "LSE crystal frequency", "fLSE", None, "32.768", None, "kHz", 119,
           "Table 42. LSE oscillator characteristics (fLSE = 32.768 kHz)", "Table 42"),
        _c("stm32g474", ST_DS, "HSI16 internal oscillator frequency", "fHSI16", "15.88", None, "16.08", "MHz", 120,
           "fHSI16 HSI16 Frequency V DD=3.0 V, TA=30 °C 15.88 - 16.08 MHz", "Table 43, VDD = 3.0 V, TA = 30 °C"),
        _c("stm32g474", ST_DS, "PLL input clock", "fPLL_IN", "2.66", None, "16", "MHz", 123,
           "PLL input clock(2) ... -2 . 6 6 - 1 6 M H z", "Table 46; choose the division factor M to obtain this range"),
        _c("stm32g474", ST_DS, "PLL VCO output", "fVCO_OUT", "96", None, "344", "MHz", 123,
           "fVCO_OUT PLL VCO output Voltage scaling Range 1 96 - 344", "Table 46, voltage scaling Range 1"),
        _c("stm32g474", ST_DS, "PLL VCO output", "fVCO_OUT", "96", None, "128", "MHz", 123,
           "Voltage scaling Range 2 96 - 128", "Table 46, voltage scaling Range 2"),
        _c("stm32g474", ST_DS, "PLL output clock P", "fPLL_P_OUT", "2.0645", None, "170", "MHz", 123,
           "Boost mode 2.0645 - 170", "Table 46, voltage scaling Range 1 boost mode"),
        _c("stm32g474", ST_DS, "PLL output clock P", "fPLL_P_OUT", "2.0645", None, "150", "MHz", 123,
           "Voltage scaling Range 1 2.0645 - 150", "Table 46, voltage scaling Range 1 (normal)"),
        _c("stm32g474", ST_DS, "PLL output clock P", "fPLL_P_OUT", "2.0645", None, "26", "MHz", 123,
           "Voltage scaling Range 2 2.0645 - 26", "Table 46, voltage scaling Range 2"),
        _c("stm32g474", ST_DS, "PLL output clock R (system clock path)", "fPLL_R_OUT", "8", None, "150", "MHz", 123,
           "Voltage scaling Range 1 8 - 150", "Table 46, voltage scaling Range 1 (normal); boost mode 170 MHz"),
        _c("stm32g474", ST_DS, "PLL output clock R (system clock path)", "fPLL_R_OUT", "8", None, "26", "MHz", 123,
           "Voltage scaling Range 2 8 - 26", "Table 46, voltage scaling Range 2"),
        # ---- ESP32
        _c("esp32", ESP_DS, "CPU clock frequency (maximum)", "fCPU", None, None, "240", "MHz", 26,
           "7 -stage pipeline to support the clock frequency of up to 240 MHz", "160 MHz for ESP32-S0WD (NRND)"),
        _c("esp32", ESP_DS, "External crystal oscillator frequency", "fXTAL", "2", None, "60", "MHz", 4,
           "External 2 MHz ~ 60 MHz crystal oscillator (40 MHz only for Wi-Fi/Bluetooth functionality)", "Features"),
        _c("esp32", ESP_DS, "CPU PLL clock (typical)", "fPLL", None, "160", None, "MHz", 29,
           "(typically 160 MHz)", "4.2.1 CPU clock: external crystal also feeds a PLL"),
        _c("esp32", ESP_DS, "Internal oscillator", "fOSC8M", None, "8", None, "MHz", 29,
           "ESP32 has an internal 8 MHz oscillator", "4.2.1 CPU clock"),
        _c("esp32", ESP_DS, "RTC internal RC oscillator", "fRTC_RC", None, "150", None, "kHz", 29,
           "Internal RC oscillator (typically about 150 kHz, and adjustable)", "4.2.2 RTC clock"),
        _c("esp32", ESP_DS, "RTC external low-speed crystal", "fXTAL32K", None, "32", None, "kHz", 29,
           "External low-speed (32 kHz) crystal clock", "4.2.2 RTC clock"),
        # ---- nRF52840
        _c("nrf52840", NRF_PS, "CPU clock", "fCPU", None, "64", None, "MHz", 21,
           "The CPU clock speed is 64 MHz", "Chapter 4.1 CPU"),
        _c("nrf52840", NRF_PS, "HFCLK nominal output frequency (HFXO)", "fNOM_HFXO", None, "64", None, "MHz", 171,
           "fNOM_HFXO Nominal output frequency 64 MHz", "5.4.4.2 64 MHz crystal oscillator (HFXO)"),
        _c("nrf52840", NRF_PS, "HFXO external crystal frequency", "fXTAL_HFXO", None, "32", None, "MHz", 171,
           "fXTAL_HFXO External crystal frequency 32 MHz", "5.4.4.2"),
        _c("nrf52840", NRF_PS, "HFINT internal oscillator nominal frequency", "fNOM_HFINT", None, "64", None, "MHz", 171,
           "fNOM_HFINT Nominal output frequency 64 MHz", "5.4.4.1 64 MHz internal oscillator (HFINT)"),
        _c("nrf52840", NRF_PS, "LFXO crystal frequency", "fNOM_LFXO", None, "32.768", None, "kHz", 171,
           "fNOM_LFXO Crystal frequency 32.768 kHz", "5.4.4.3"),
        _c("nrf52840", NRF_PS, "LFRC nominal frequency", "fNOM_LFRC", None, "32.768", None, "kHz", 172,
           "fNOM_LFRC Nominal frequency 32.768 kHz", "5.4.4.4"),
    ]
    # Bảng wait-state flash của RM0440 (Table 9, Category 3): HCLK tối đa cho mỗi số wait state theo dải điện áp lõi
    table = {0: ("≤ 34 ≤ 30 ≤ 12", (34, 30, 12)), 1: ("≤ 68 ≤ 60 ≤ 24", (68, 60, 24)), 2: ("≤ 102 ≤ 90 ≤ 26", (102, 90, 26)),
             3: ("≤ 136 ≤ 120 -", (136, 120, None)), 4: ("≤ 170 ≤ 150 -", (170, 150, None))}
    ranges = ("VCORE Range 1 boost mode", "VCORE Range 1 normal mode", "VCORE Range 2")
    for ws, (cells, vals) in table.items():
        cyc = ws + 1
        for rng, v in zip(ranges, vals):
            if v is None:
                continue
            rows.append(_c("stm32g474", ST_RM, f"Flash wait states: {ws} WS (LATENCY = {ws}) maximum HCLK", "HCLK",
                           None, None, str(v), "MHz", 98, f"{ws} WS ({cyc} CPU cycles) {cells}",
                           f"Table 9 (category 3 devices); {rng}"))
    return rows


# --------------------------------------------------------------------------- kiểm tra tự động
def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def verify_row(r: dict) -> list[str]:
    problems: list[str] = []
    if r.get("category") is not None and r["category"] not in CATEGORIES:
        problems.append(f"unknown category {r['category']!r}")
    if not r.get("unit"):
        problems.append("missing unit")
    if not r.get("quote"):
        return problems + ["missing quote"]
    page = r.get("page")
    if not isinstance(page, int):
        return problems + ["missing page"]
    text = _squash(pdfdocs.load_pages(r["doc"]).get(page, ""))
    for frag in r["quote"].split(" ... "):
        if _squash(frag) not in text:
            problems.append(f"quote not found on {r['doc']} p.{page}: {frag!r}")
    sq = _squash(r["quote"].replace(" ... ", ""))
    for fld in ("min", "typ", "max"):
        v = r.get(fld)
        if v is None:
            continue
        for tok in re.findall(r"\d+(?:\.\d+)?", str(v)):
            if tok not in sq:
                problems.append(f"number {tok!r} ({fld}) not in quote")
    return problems


# --------------------------------------------------------------------------- ghi DB
def main(argv: list[str] | None = None) -> int:
    import argparse

    from . import hwdb

    ap = argparse.ArgumentParser(description="Giới hạn điện & clock (curated, có trích dẫn kiểm tự động) -> hw_specs.sqlite")
    ap.add_argument("--db", default=str(hwdb.DEFAULT_DB))
    a = ap.parse_args(argv)
    rows_e, rows_c = ELECTRICAL, CLOCK_ROWS()
    failures = {f"{r['chip']}/{r['parameter']}": p for r in rows_e + rows_c if (p := verify_row(r))}
    if failures:
        for k, v in failures.items():
            print("FAIL", k, v)
        return 1
    conn = hwdb.connect(a.db)
    hwdb.init_schema(conn)
    for t in ("electrical_limits", "clock_limits"):
        conn.execute(f"DELETE FROM {t}")
    for r in rows_e:
        conn.execute("INSERT INTO electrical_limits(chip, parameter, category, field_type, symbol, min, typ, max, unit, condition,"
                     " applies_to, doc, page, quote, source, verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                     (r["chip"], r["parameter"], r["category"], r["field_type"], r["symbol"], r["min"], r["typ"], r["max"],
                      r["unit"], r["condition"], r["applies_to"], r["doc"], r["page"], r["quote"], "curated"))
    for r in rows_c:
        conn.execute("INSERT INTO clock_limits(chip, parameter, symbol, min, typ, max, unit, condition, doc, page, quote,"
                     " source, verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
                     (r["chip"], r["parameter"], r["symbol"], r["min"], r["typ"], r["max"], r["unit"], r["condition"],
                      r["doc"], r["page"], r["quote"], "curated"))
    conn.commit()
    print(f"electrical_limits: {len(rows_e)} rows, clock_limits: {len(rows_c)} rows (all quotes verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
