"""Table & Register MCP Server: structured pin mux, SVD registers, electrical limits, and logic-level checks."""
import re
from ingestion.unit_normalizer import eval_vdd_expr
from mcp_servers import create_mcp

mcp = create_mcp("table-register")

CHIPS = ["esp32", "stm32g474", "nrf52840"]

PINOUT = {
    ("stm32g474", "PA8"): {
        "pad_name": "PA8",
        "functions": [
            {"af": 0, "function": "RCC_MCO", "notes": "Master clock output", "doc": "STM32G474_Datasheet", "page": 62},
            {"af": 4, "function": "I2C3_SCL", "notes": "I2C3 clock", "doc": "STM32G474_Datasheet", "page": 62},
            {"af": 6, "function": "TIM1_CH1", "notes": "TIM1 channel 1 PWM / OC output", "doc": "STM32G474_Datasheet", "page": 62},
            {"af": 7, "function": "USART1_CK", "notes": "USART1 synchronous clock", "doc": "STM32G474_Datasheet", "page": 62},
        ],
    },
    ("esp32", "GPIO18"): {
        "pad_name": "GPIO18",
        "functions": [
            {"af": None, "function": "LEDC_PWM / VSPICLK", "notes": "Bidirectional GPIO routed via GPIO Matrix", "doc": "ESP32_Datasheet", "page": 22},
        ],
    },
    ("esp32", "GPIO34"): {
        "pad_name": "VDET_1 / GPIO34",
        "functions": [
            {"af": None, "function": "ADC1_CH6", "notes": "INPUT-ONLY pin (no output driver or internal pull-up/down)", "doc": "ESP32_Datasheet", "page": 20},
        ],
    },
}

REGISTERS = {
    ("stm32g474", "TIM1"): [
        {
            "name": "TIM1_CR1",
            "address": "0x40012C00",
            "offset": "0x00",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "TIM1 control register 1",
            "doc": "STM32G474_RM0440",
            "page": 1277,
            "bitfields": [
                {"field": "CEN", "bits": "[0]", "description": "Counter enable"},
                {"field": "ARPE", "bits": "[7]", "description": "Auto-reload preload enable"},
            ],
        },
        {
            "name": "TIM1_CCMR1",
            "address": "0x40012C18",
            "offset": "0x18",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "TIM1 capture/compare mode register 1",
            "doc": "STM32G474_RM0440",
            "page": 1298,
            "bitfields": [
                {"field": "OC1PE", "bits": "[3]", "description": "Output compare 1 preload enable"},
                {"field": "OC1M", "bits": "[6:4]", "description": "Output compare 1 mode (0110: PWM mode 1)"},
            ],
        },
        {
            "name": "TIM1_CCER",
            "address": "0x40012C20",
            "offset": "0x20",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "TIM1 capture/compare enable register",
            "doc": "STM32G474_RM0440",
            "page": 1305,
            "bitfields": [
                {"field": "CC1E", "bits": "[0]", "description": "Capture/Compare 1 output enable"},
                {"field": "CC1P", "bits": "[1]", "description": "Capture/Compare 1 output polarity"},
            ],
        },
        {
            "name": "TIM1_PSC",
            "address": "0x40012C28",
            "offset": "0x28",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "TIM1 prescaler register",
            "doc": "STM32G474_RM0440",
            "page": 1310,
            "bitfields": [
                {"field": "PSC", "bits": "[15:0]", "description": "Prescaler value"},
            ],
        },
        {
            "name": "TIM1_ARR",
            "address": "0x40012C2C",
            "offset": "0x2C",
            "access": "RW",
            "reset_value": "0x0000FFFF",
            "description": "TIM1 auto-reload register",
            "doc": "STM32G474_RM0440",
            "page": 1311,
            "bitfields": [
                {"field": "ARR", "bits": "[15:0]", "description": "Auto-reload period value"},
            ],
        },
        {
            "name": "TIM1_CCR1",
            "address": "0x40012C34",
            "offset": "0x34",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "TIM1 capture/compare register 1",
            "doc": "STM32G474_RM0440",
            "page": 1313,
            "bitfields": [
                {"field": "CCR1", "bits": "[15:0]", "description": "Capture/Compare 1 duty cycle value"},
            ],
        },
        {
            "name": "TIM1_BDTR",
            "address": "0x40012C44",
            "offset": "0x44",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "TIM1 break and dead-time register",
            "doc": "STM32G474_RM0440",
            "page": 1318,
            "bitfields": [
                {"field": "MOE", "bits": "[15]", "description": "Main output enable"},
            ],
        },
    ],
    ("stm32g474", "RCC"): [
        {
            "name": "RCC_AHB2ENR",
            "address": "0x4002104C",
            "offset": "0x4C",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "AHB2 peripheral clock enable register",
            "doc": "STM32G474_RM0440",
            "page": 291,
            "bitfields": [
                {"field": "GPIOAEN", "bits": "[0]", "description": "IO port A clock enable"},
            ],
        },
        {
            "name": "RCC_APB2ENR",
            "address": "0x40021060",
            "offset": "0x60",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "APB2 peripheral clock enable register",
            "doc": "STM32G474_RM0440",
            "page": 296,
            "bitfields": [
                {"field": "TIM1EN", "bits": "[11]", "description": "TIM1 timer clock enable"},
            ],
        },
    ],
    ("stm32g474", "GPIOA"): [
        {
            "name": "GPIOA_MODER",
            "address": "0x48000000",
            "offset": "0x00",
            "access": "RW",
            "reset_value": "0xABFFFFFF",
            "description": "GPIO port A mode register",
            "doc": "STM32G474_RM0440",
            "page": 346,
            "bitfields": [
                {"field": "MODER8", "bits": "[17:16]", "description": "Port A pin 8 mode bits (10: Alternate function mode)"},
            ],
        },
        {
            "name": "GPIOA_AFRH",
            "address": "0x48000024",
            "offset": "0x24",
            "access": "RW",
            "reset_value": "0x00000000",
            "description": "GPIO port A alternate function high register",
            "doc": "STM32G474_RM0440",
            "page": 351,
            "bitfields": [
                {"field": "AFSEL8", "bits": "[3:0]", "description": "Alternate function selection for PA8 (0110: AF6 TIM1_CH1)"},
            ],
        },
    ],
}

ELECTRICAL = {
    "esp32": [
        {
            "parameter": "Supply voltage VDD3P3 / VDD",
            "category": "absolute_max",
            "field_type": "supply_voltage",
            "min": "-0.3",
            "typ": None,
            "max": "3.6",
            "unit": "V",
            "condition": "Absolute Maximum Rating (stress beyond 3.6 V causes permanent damage)",
            "doc": "ESP32_Datasheet",
            "page": 42,
        },
        {
            "parameter": "Recommended operating supply voltage VDD",
            "category": "recommended_operating",
            "field_type": "supply_voltage",
            "min": "3.0",
            "typ": "3.3",
            "max": "3.6",
            "unit": "V",
            "condition": "Normal operating conditions (2.3 V min for single-core variant without flash)",
            "doc": "ESP32_Datasheet",
            "page": 42,
        },
        {
            "parameter": "High-level input voltage VIH",
            "category": "dc_characteristics",
            "field_type": "input_voltage_high",
            "min": "0.75*VDD",
            "typ": None,
            "max": "VDD+0.3",
            "unit": "V",
            "condition": "Digital GPIO input",
            "doc": "ESP32_Datasheet",
            "page": 43,
        },
        {
            "parameter": "Low-level input voltage VIL",
            "category": "dc_characteristics",
            "field_type": "input_voltage_low",
            "min": "-0.3",
            "typ": None,
            "max": "0.25*VDD",
            "unit": "V",
            "condition": "Digital GPIO input",
            "doc": "ESP32_Datasheet",
            "page": 43,
        },
        {
            "parameter": "High-level output voltage VOH",
            "category": "dc_characteristics",
            "field_type": "output_voltage_high",
            "min": "0.8*VDD",
            "typ": None,
            "max": "VDD",
            "unit": "V",
            "condition": "CMOS output driver",
            "doc": "ESP32_Datasheet",
            "page": 43,
        },
        {
            "parameter": "Low-level output voltage VOL",
            "category": "dc_characteristics",
            "field_type": "output_voltage_low",
            "min": "0.0",
            "typ": None,
            "max": "0.1*VDD",
            "unit": "V",
            "condition": "CMOS output driver",
            "doc": "ESP32_Datasheet",
            "page": 43,
        },
        {
            "parameter": "Deep-sleep current with RTC timer and RTC memory",
            "category": "power_consumption",
            "field_type": "current",
            "min": None,
            "typ": "10",
            "max": None,
            "unit": "uA",
            "condition": "RTC timer + RTC memory enabled (ULP powered down)",
            "doc": "ESP32_Datasheet",
            "page": 45,
        },
        {
            "parameter": "Deep-sleep current (RTC timer only, RTC memory off)",
            "category": "power_consumption",
            "field_type": "current",
            "min": None,
            "typ": "5",
            "max": None,
            "unit": "uA",
            "condition": "RTC timer only",
            "doc": "ESP32_Datasheet",
            "page": 45,
        },
    ],
    "stm32g474": [
        {
            "parameter": "Supply voltage VDD",
            "category": "absolute_max",
            "field_type": "supply_voltage",
            "min": "-0.3",
            "typ": None,
            "max": "4.0",
            "unit": "V",
            "condition": "Absolute Maximum Rating",
            "doc": "STM32G474_Datasheet",
            "page": 92,
        },
        {
            "parameter": "Recommended operating supply voltage VDD",
            "category": "recommended_operating",
            "field_type": "supply_voltage",
            "min": "1.71",
            "typ": "3.3",
            "max": "3.6",
            "unit": "V",
            "condition": "Standard operating voltage",
            "doc": "STM32G474_Datasheet",
            "page": 94,
        },
    ],
    "nrf52840": [
        {
            "parameter": "Supply voltage VDD",
            "category": "absolute_max",
            "field_type": "supply_voltage",
            "min": "-0.3",
            "typ": None,
            "max": "3.9",
            "unit": "V",
            "condition": "Absolute Maximum Rating",
            "doc": "nRF52840_PS",
            "page": 72,
        },
        {
            "parameter": "Recommended operating supply voltage VDD",
            "category": "recommended_operating",
            "field_type": "supply_voltage",
            "min": "1.7",
            "typ": "3.0",
            "max": "3.6",
            "unit": "V",
            "condition": "Normal voltage mode",
            "doc": "nRF52840_PS",
            "page": 73,
        },
        {
            "parameter": "Input high voltage VIH",
            "category": "dc_characteristics",
            "field_type": "input_voltage_high",
            "min": "0.7*VDD",
            "typ": None,
            "max": "VDD+0.3",
            "unit": "V",
            "condition": "GPIO input pin (Absolute Max input voltage is VDD + 0.3 V)",
            "doc": "nRF52840_PS",
            "page": 139,
        },
        {
            "parameter": "Input low voltage VIL",
            "category": "dc_characteristics",
            "field_type": "input_voltage_low",
            "min": "0.0",
            "typ": None,
            "max": "0.3*VDD",
            "unit": "V",
            "condition": "GPIO input pin",
            "doc": "nRF52840_PS",
            "page": 139,
        },
        {
            "parameter": "Output high voltage VOH",
            "category": "dc_characteristics",
            "field_type": "output_voltage_high",
            "min": "VDD-0.4",
            "typ": None,
            "max": "VDD",
            "unit": "V",
            "condition": "Standard drive",
            "doc": "nRF52840_PS",
            "page": 139,
        },
        {
            "parameter": "Output low voltage VOL",
            "category": "dc_characteristics",
            "field_type": "output_voltage_low",
            "min": "0.0",
            "typ": None,
            "max": "0.4",
            "unit": "V",
            "condition": "Standard drive",
            "doc": "nRF52840_PS",
            "page": 139,
        },
    ],
}


@mcp.tool()
def list_chips() -> dict:
    """List supported microcontroller chips in the structured register/electrical database."""
    return {"chips": CHIPS}


@mcp.tool()
def query_pin_alternate_function(chip: str, pin: str) -> dict:
    """Query alternate functions and pad multiplexing for a specific chip and pin (e.g. STM32G474 PA8)."""
    key = (chip.lower().strip(), pin.upper().strip())
    entry = PINOUT.get(key)
    if not entry:
        return {"chip": chip, "pin": pin, "functions": [], "error": f"No pinout entry for {chip} {pin}"}
    return {"chip": chip.lower(), "pin": pin.upper(), "pad_name": entry["pad_name"], "functions": entry["functions"]}


@mcp.tool()
def get_register_bitfields(chip: str, peripheral: str | None = None, register: str | None = None) -> dict:
    """Retrieve memory-mapped register addresses, reset values, and bitfield descriptions from CMSIS-SVD."""
    c = chip.lower().strip()
    p = (peripheral or "").upper().strip()
    regs = list(REGISTERS.get((c, p), []))
    if register:
        rname = register.upper().strip()
        regs = [r for r in regs if r["name"].upper() == rname]
    if not regs:
        return {"chip": c, "peripheral": p, "count": 0, "registers": [],
                "error": f"No registers found for {chip} peripheral={peripheral} register={register}"}
    return {"chip": c, "peripheral": p, "count": len(regs), "registers": regs}


@mcp.tool()
def get_electrical_specs(chip: str, parameter: str = "", category: str | None = None, vdd: float | None = None) -> dict:
    """Query electrical specifications (Absolute Maximum Ratings, Recommended Operating Conditions, sleep currents)."""
    c = chip.lower().strip()
    rows = ELECTRICAL.get(c, [])
    if not rows:
        return {"chip": c, "results": [], "error": f"No electrical specifications indexed for chip '{chip}'."}
    tokens = set(re.findall(r"[a-z0-9_]{2,}", parameter.lower()))
    out = []
    for row in rows:
        if category and row["category"] != category:
            continue
        hay = f"{row['parameter']} {row['category']} {row['field_type']} {row['condition']}".lower()
        words = set(re.findall(r"[a-z0-9_]{2,}", hay))
        score = len(tokens & words) + (2 if any(t in row["parameter"].lower() for t in tokens) else 0)
        rec = dict(row, match_score=score if tokens else 1)
        if vdd is not None and any("VDD" in str(row.get(k) or "") for k in ("min", "typ", "max")):
            rec["evaluated_at_vdd"] = {
                "vdd": vdd,
                "min": eval_vdd_expr(row.get("min"), vdd),
                "typ": eval_vdd_expr(row.get("typ"), vdd),
                "max": eval_vdd_expr(row.get("max"), vdd),
            }
        out.append(rec)
    out.sort(key=lambda x: -x["match_score"])
    return {"chip": c, "results": out}


@mcp.tool()
def check_logic_level_compatibility(src_chip: str, dst_chip: str, src_vdd: float = 3.3, dst_vdd: float = 3.3) -> dict:
    """Check whether a digital output from src_chip at src_vdd can safely drive an input on dst_chip at dst_vdd."""
    s_specs = {r["field_type"]: r for r in ELECTRICAL.get(src_chip.lower(), [])}
    d_specs = {r["field_type"]: r for r in ELECTRICAL.get(dst_chip.lower(), [])}
    voh_r = s_specs.get("output_voltage_high")
    vol_r = s_specs.get("output_voltage_low")
    vih_r = d_specs.get("input_voltage_high")
    vil_r = d_specs.get("input_voltage_low")
    if not (voh_r and vol_r and vih_r and vil_r):
        return {"error": f"Missing logic-level specs for {src_chip} -> {dst_chip}"}

    voh_min = eval_vdd_expr(voh_r["min"], src_vdd)
    voh_max = eval_vdd_expr(voh_r["max"], src_vdd)
    vol_max = eval_vdd_expr(vol_r["max"], src_vdd)
    vih_min = eval_vdd_expr(vih_r["min"], dst_vdd)
    vih_max = eval_vdd_expr(vih_r["max"], dst_vdd)
    vil_max = eval_vdd_expr(vil_r["max"], dst_vdd)

    checks = [
        {
            "rule": "VOH_min >= VIH_min (high-level noise margin)",
            "status": "PASS" if voh_min >= vih_min else "FAIL",
            "detail": f"src VOH_min = {voh_min} V >= dst VIH_min = {vih_min} V",
        },
        {
            "rule": "VOL_max <= VIL_max (low-level noise margin)",
            "status": "PASS" if vol_max <= vil_max else "FAIL",
            "detail": f"src VOL_max = {vol_max} V <= dst VIL_max = {vil_max} V",
        },
        {
            "rule": "VOH_max <= VIH_max (overvoltage / absolute-max input safety)",
            "status": "PASS" if voh_max <= vih_max else "FAIL",
            "detail": f"src VOH_max = {voh_max} V vs dst max input voltage VIH_max = {vih_max} V (VDD + 0.3 V)",
        },
    ]
    verdict = "compatible" if all(c["status"] == "PASS" for c in checks) else "incompatible (overvoltage / level mismatch)"
    return {
        "src": src_chip.lower(),
        "dst": dst_chip.lower(),
        "src_vdd": src_vdd,
        "dst_vdd": dst_vdd,
        "verdict": verdict,
        "checks": checks,
        "evidence": [
            {"doc": voh_r["doc"], "page": voh_r["page"]},
            {"doc": vih_r["doc"], "page": vih_r["page"]},
        ],
    }


if __name__ == "__main__":
    mcp.run()
