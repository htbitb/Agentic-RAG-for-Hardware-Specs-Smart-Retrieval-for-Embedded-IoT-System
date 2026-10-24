"""Text-Manual MCP Server: hybrid search over ESP32, STM32G474, nRF52840, and FreeRTOS documentation."""
import re
import config
from mcp_servers import create_mcp

mcp = create_mcp("text-manual")

DOCUMENTS = [
    {"doc": "ESP32_Datasheet", "chip": "esp32", "title": "ESP32 Series Datasheet v4.3", "pages": 65},
    {"doc": "ESP32_TRM", "chip": "esp32", "title": "ESP32 Technical Reference Manual v5.1", "pages": 742},
    {"doc": "ESP32_Low_Power_AppNote", "chip": "esp32", "title": "ESP32 Low-Power Management Application Note", "pages": 18},
    {"doc": "STM32G474_Datasheet", "chip": "stm32g474", "title": "STM32G474xB/xC/xE Datasheet (DS12288)", "pages": 236},
    {"doc": "STM32G474_RM0440", "chip": "stm32g474", "title": "STM32G4 Series Reference Manual (RM0440)", "pages": 2124},
    {"doc": "nRF52840_PS", "chip": "nrf52840", "title": "nRF52840 Product Specification v1.8", "pages": 619},
    {"doc": "FreeRTOS_Ref_Manual", "chip": "freertos", "title": "FreeRTOS Reference Manual v10.5.0", "pages": 412},
]

CHUNKS = [
    {
        "chunk_id": "freertos_xtaskcreate_01",
        "doc": "FreeRTOS_Ref_Manual",
        "chip": "freertos",
        "page": 44,
        "page_start": 44,
        "page_end": 45,
        "section": "2.1 xTaskCreate API Reference",
        "text": (
            "[FreeRTOS Reference Manual > xTaskCreate] "
            "BaseType_t xTaskCreate(TaskFunction_t pvTaskCode, const char * const pcName, "
            "configSTACK_DEPTH_TYPE usStackDepth, void *pvParameters, UBaseType_t uxPriority, "
            "TaskHandle_t *pxCreatedTask). "
            "Return values: If the task was created successfully then pdPASS is returned. "
            "Otherwise errCOULD_NOT_ALLOCATE_REQUIRED_MEMORY is returned when xTaskCreate cannot "
            "allocate the task control block (TCB) or task stack because insufficient FreeRTOS heap "
            "memory is available (configTOTAL_HEAP_SIZE)."
        ),
    },
    {
        "chunk_id": "esp32_low_power_01",
        "doc": "ESP32_Low_Power_AppNote",
        "chip": "esp32",
        "page": 6,
        "page_start": 6,
        "page_end": 7,
        "section": "3.2 Deep-sleep Current Optimization Tips",
        "text": (
            "[ESP32 Low-Power App Note > Deep-sleep Current Tips] "
            "To minimize ESP32 deep-sleep current consumption to 10 uA (with RTC timer and RTC memory enabled), "
            "isolate unused GPIO pins using rtc_gpio_isolate() to prevent leakage currents through internal "
            "pull-up or pull-down resistors. Power down flash and external PSRAM before calling esp_deep_sleep_start(). "
            "When only the RTC timer is active and RTC memory is powered down, deep-sleep current drops to 5 uA."
        ),
    },
    {
        "chunk_id": "esp32_pwm_ledc_01",
        "doc": "ESP32_TRM",
        "chip": "esp32",
        "page": 374,
        "page_start": 374,
        "page_end": 376,
        "section": "14.2 LED PWM Controller (LEDC) & GPIO Matrix",
        "text": (
            "[ESP32 TRM > LEDC PWM Configuration] "
            "The ESP32 LED PWM Controller (LEDC) generates up to 16 independent PWM channels routed via the "
            "GPIO Matrix to any output-capable GPIO pin. Note that GPIO34, GPIO35, GPIO36, and GPIO39 are "
            "input-only pins and cannot be used for PWM output. Configure the timer frequency and duty resolution "
            "in LEDC_HSTIMER0_CONF_REG, then bind the channel in LEDC_HSCH0_CONF0_REG and route the signal via "
            "GPIO_FUNCx_OUT_SEL_CFG_REG."
        ),
    },
    {
        "chunk_id": "stm32g474_pwm_proc_01",
        "doc": "STM32G474_RM0440",
        "chip": "stm32g474",
        "page": 1265,
        "page_start": 1265,
        "page_end": 1266,
        "section": "29.3.10 TIM1 PWM Mode Configuration Procedure",
        "text": (
            "[STM32G474 RM0440 > TIM1 PWM Mode Configuration] "
            "To configure TIM1_CH1 on PA8 as a PWM output: "
            "1. Enable GPIOA clock in RCC_AHB2ENR and TIM1 clock in RCC_APB2ENR (bit TIM1EN = 1). "
            "2. Configure PA8 in Alternate Function mode (MODER8 = 10) and select AF6 (TIM1_CH1) in GPIOA_AFRH (AFSEL8 = 0110). "
            "3. Set the prescaler in TIM1_PSC, auto-reload period in TIM1_ARR, and duty cycle in TIM1_CCR1. "
            "4. Select PWM mode 1 (OC1M = 0110) and enable preload (OC1PE = 1) in TIM1_CCMR1. "
            "5. Enable capture/compare channel 1 output (CC1E = 1) in TIM1_CCER and set Main Output Enable (MOE = 1) in TIM1_BDTR. "
            "6. Enable the counter (CEN = 1) in TIM1_CR1."
        ),
    },
    {
        "chunk_id": "nrf52840_gpio_01",
        "doc": "nRF52840_PS",
        "chip": "nrf52840",
        "page": 135,
        "page_start": 135,
        "page_end": 136,
        "section": "6.9 GPIO — General Purpose Input/Output",
        "text": (
            "[nRF52840 Product Specification > GPIO Electrical & Configuration] "
            "Each nRF52840 GPIO pin is configured via PIN_CNF[n] inside the P0 (0x50000000) or P1 (0x50000300) "
            "peripheral. In Normal Voltage mode, VDD ranges from 1.7 V to 3.6 V, and input high voltage VIH is "
            "0.7 * VDD while maximum allowed input pin voltage is VDD + 0.3 V."
        ),
    },
]


def _score(chunk: dict, query: str) -> float:
    tokens = set(re.findall(r"[a-z0-9_]{2,}", query.lower()))
    hay = (chunk["section"] + " " + chunk["text"]).lower()
    words = set(re.findall(r"[a-z0-9_]{2,}", hay))
    overlap = len(tokens & words)
    bonus = sum(1.5 for t in tokens if len(t) > 5 and t in hay)
    return round(overlap + bonus, 2)


@mcp.tool()
def search_manual(query: str, chip: str | None = None, k: int = config.TOP_K) -> dict:
    """Hybrid search across hardware manuals, datasheets, application notes, and FreeRTOS documentation."""
    pool = CHUNKS
    if chip:
        c = chip.lower()
        pool = [x for x in CHUNKS if x["chip"] == c or c == "freertos" and x["chip"] == "freertos"]
        if not pool:
            return {"query": query, "chip": chip, "results": [], "error": f"No documentation indexed for chip '{chip}'."}
    ranked = sorted(pool, key=lambda x: -_score(x, query))[: max(1, int(k))]
    return {"query": query, "chip": chip, "results": ranked}


@mcp.tool()
def naive_search(query: str, k: int = config.TOP_K) -> dict:
    """Baseline unrouted text search."""
    return search_manual(query=query, chip=None, k=k)


@mcp.tool()
def get_chunk_context(chunk_id: str, window: int = 1) -> dict:
    """Return a chunk and its surrounding neighbors from the same document."""
    idx = next((i for i, c in enumerate(CHUNKS) if c["chunk_id"] == chunk_id), -1)
    if idx < 0:
        return {"chunk_id": chunk_id, "results": [], "error": f"Unknown chunk_id '{chunk_id}'"}
    doc = CHUNKS[idx]["doc"]
    lo = max(0, idx - int(window))
    hi = min(len(CHUNKS), idx + int(window) + 1)
    neighbors = [c for c in CHUNKS[lo:hi] if c["doc"] == doc]
    return {"chunk_id": chunk_id, "results": neighbors}


@mcp.tool()
def list_documents() -> dict:
    """List all indexed hardware manuals and datasheets."""
    return {"count": len(DOCUMENTS), "documents": DOCUMENTS}


if __name__ == "__main__":
    mcp.run()
