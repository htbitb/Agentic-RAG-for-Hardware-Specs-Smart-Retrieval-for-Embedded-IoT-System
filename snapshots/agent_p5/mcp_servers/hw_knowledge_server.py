"""hw-knowledge MCP Server: dữ liệu phần cứng THẬT (SVD -> thanh ghi/field, bảng AF/IO_MUX/PSEL, giới hạn điện & clock).

Thay thế `table_register_server.py` (hằng số mô phỏng, 3 chân/11 thanh ghi). Giữ tên tool cũ; thêm `find_pins_for_signal`,
`get_clock_limits`, `search_registers`. Đầu ra lớn được phân trang/cắt và luôn mang `doc` + `page` để trích dẫn.
"""
import config
from mcp_servers import create_mcp
from mcp_servers.hw_queries import HwStore

mcp = create_mcp("hw-knowledge")
_STORE: HwStore | None = None


def _store() -> HwStore:
    global _STORE
    if _STORE is None:
        _STORE = HwStore(config.HW_DB)
    return _STORE


def _reset() -> None:
    """Dùng trong test: mở lại DB theo `config.HW_DB`."""
    global _STORE
    _STORE = None


@mcp.tool()
def list_chips() -> dict:
    """List the chips in the structured hardware database (esp32, stm32g474, nrf52840) with counts of peripherals, registers, pins and limits."""
    return _store().list_chips()


@mcp.tool()
def query_pin_alternate_function(chip: str, pin: str) -> dict:
    """Alternate functions / pin multiplexing of ONE pin (STM32G474: PA8 -> AF0..AF15 from the datasheet AF table; ESP32: GPIO18 or pad name e.g. VDET_1 -> IO_MUX Function0..5, input-only/strapping/flash flags; nRF52840: P0.05 -> fixed functions such as AIN3, peripherals are routed with PSEL). Also returns I/O structure and 5 V tolerance (STM32) with doc/page citations."""
    return _store().query_pin_alternate_function(chip, pin)


@mcp.tool()
def find_pins_for_signal(chip: str, signal: str, limit: int = 50) -> dict:
    """Reverse lookup: which pins can carry a peripheral signal? e.g. chip=stm32g474 signal=TIM1_CH1 (exact signal) or USART2 (all USART2 signals); esp32 U0TXD; nrf52840 AIN7. Returns pin, AF number, doc/page; paginated via `limit` with `truncated`/`total`."""
    return _store().find_pins_for_signal(chip, signal, limit)


@mcp.tool()
def get_register_bitfields(chip: str, peripheral: str | None = None, register: str | None = None, field: str | None = None,
                           limit: int = 30, offset: int = 0) -> dict:
    """Memory-mapped registers from the vendor CMSIS-SVD with manual page citations: absolute address (ESP32 also the AHB/DPORT alias), reset value/mask, access, reserved/rw masks, bit fields and enumerated values. Give peripheral+register (e.g. TIM1 + CR1, or register=TIM1_CR1; nRF cluster registers like PSEL.SCL), or only a peripheral to list its registers (paginated with limit/offset, `truncated`, `next_offset`). Use `field` to get one field with all its enumerated values. Warnings flag registers that exist only in the SVD or whose reset value differs from the manual."""
    return _store().get_register_bitfields(chip, peripheral, register, field, limit, offset)


@mcp.tool()
def search_registers(chip: str, query: str, limit: int = 15) -> dict:
    """Find registers when the exact name is unknown: free text over register names, descriptions and field names (e.g. 'wakeup timer', 'pll configuration') or an absolute address (0x40012C00). Returns peripheral, register, address, doc/page and a match score."""
    return _store().search_registers(chip, query, limit)


@mcp.tool()
def get_electrical_specs(chip: str, parameter: str = "", category: str | None = None, vdd: float | None = None) -> dict:
    """Electrical specifications with verbatim source quotes: Absolute Maximum Ratings (category=absolute_max), Recommended Operating Conditions (recommended_operating) and DC characteristics (dc_characteristics: VIH/VIL/VOH/VOL, currents). Keep absolute maximum and recommended values separate. `vdd` evaluates VDD-relative limits such as VDD+0.3. Each row has min/typ/max, unit, condition, applies_to (pin type), doc and page."""
    return _store().get_electrical_specs(chip, parameter, category, vdd)


@mcp.tool()
def get_clock_limits(chip: str, parameter: str = "") -> dict:
    """Clock limits with doc/page: max SYSCLK/HCLK/PCLK, HSE/LSE/HSI ranges, PLL input/VCO/output ranges per voltage scaling range, and the STM32G474 flash wait-state (LATENCY) table by HCLK and VCORE range. `parameter` is free text, e.g. 'flash wait states', 'PLL VCO', 'CPU frequency'."""
    return _store().get_clock_limits(chip, parameter)


@mcp.tool()
def check_logic_level_compatibility(src_chip: str, dst_chip: str, src_vdd: float = 3.3, dst_vdd: float = 3.3,
                                    dst_io_structure: str | None = None) -> dict:
    """Check whether a digital output of src_chip at src_vdd can safely drive an input of dst_chip at dst_vdd (noise margins VOH>=VIH, VOL<=VIL and overvoltage against the destination's maximum input voltage). Optional dst_io_structure (STM32: FT, TT, FT_c) refines the destination limit. Returns PASS/FAIL per rule with the doc/page evidence."""
    return _store().check_logic_level_compatibility(src_chip, dst_chip, src_vdd, dst_vdd, dst_io_structure)


if __name__ == "__main__":
    mcp.run()
