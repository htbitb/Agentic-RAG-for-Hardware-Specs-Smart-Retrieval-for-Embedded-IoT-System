"""RCC STM32G474: cổng clock ngoại vi (RCC_AHBxENR / RCC_APBxENRy), cờ RDY/SWS do phần cứng cập nhật, khoá ghi PLL.

Nguồn: RM0440 §7.2 (cây clock) và §7.4 (thanh ghi). 'When the peripheral clock is not active, the peripheral registers read or write
access is not supported' (p.285, p.305–308) => mô hình coi lệnh GHI bị bỏ qua (và đọc về 0).
Giả định (nêu trong kết quả): HSIRDY / HSERDY / PLLRDY lên ngay khi bật nguồn; không mô phỏng thời gian ổn định.
"""
from __future__ import annotations

from ..clock_tree import CR_HSEON, CR_HSERDY, CR_HSION, CR_HSIRDY, CR_PLLON, CR_PLLRDY, bits

# peripheral (tên trong DB) -> (thanh ghi ENR, tên trường)
_ENR = {
    "RCC_AHB1ENR": {"DMA1": "DMA1EN", "DMA2": "DMA2EN", "DMAMUX": "DMAMUX1EN", "CORDIC": "CORDICEN", "FMAC": "FMACEN",
                    "FLASH": "FLASHEN", "CRC": "CRCEN"},
    "RCC_AHB2ENR": {**{f"GPIO{c}": f"GPIO{c}EN" for c in "ABCDEFG"}, "ADC1": "ADC12EN", "ADC2": "ADC12EN", "ADC12_Common": "ADC12EN",
                    "ADC3": "ADC345EN", "ADC4": "ADC345EN", "ADC5": "ADC345EN", "ADC345_Common": "ADC345EN",
                    "DAC1": "DAC1EN", "DAC2": "DAC2EN", "DAC3": "DAC3EN", "DAC4": "DAC4EN", "RNG": "RNGEN"},
    "RCC_AHB3ENR": {"FMC": "FMCEN", "QUADSPI": "QSPIEN"},
    "RCC_APB1ENR1": {"TIM2": "TIM2EN", "TIM3": "TIM3EN", "TIM4": "TIM4EN", "TIM5": "TIM5EN", "TIM6": "TIM6EN", "TIM7": "TIM7EN",
                     "CRS": "CRSEN", "RTC": "RTCAPBEN", "TAMP": "RTCAPBEN", "WWDG": "WWDGEN", "SPI2": "SPI2EN", "SPI3": "SPI3EN",
                     "USART2": "USART2EN", "USART3": "USART3EN", "UART4": "UART4EN", "UART5": "UART5EN", "I2C1": "I2C1EN",
                     "I2C2": "I2C2EN", "USB_FS_device": "USBEN", "FDCAN": "FDCANEN", "FDCAN1": "FDCANEN", "FDCAN2": "FDCANEN",
                     "FDCAN3": "FDCANEN", "PWR": "PWREN", "I2C3": "I2C3EN", "LPTIMER1": "LPTIM1EN"},
    "RCC_APB1ENR2": {"LPUART1": "LPUART1EN", "I2C4": "I2C4EN", "UCPD1": "UCPD1EN"},
    "RCC_APB2ENR": {"SYSCFG": "SYSCFGEN", "COMP": "SYSCFGEN", "VREFBUF": "SYSCFGEN", "OPAMP": "SYSCFGEN",   # p.313: SYSCFG + COMP + VREFBUF + OPAMP
                    "TIM1": "TIM1EN", "SPI1": "SPI1EN", "TIM8": "TIM8EN", "USART1": "USART1EN", "SPI4": "SPI4EN",
                    "TIM15": "TIM15EN", "TIM16": "TIM16EN", "TIM17": "TIM17EN", "TIM20": "TIM20EN", "SAI": "SAI1EN",
                    **{f"HRTIM_{n}": "HRTIM1EN" for n in ("Common", "Master", "TIMA", "TIMB", "TIMC", "TIMD", "TIME", "TIMF")}},
}
GATES: dict[str, tuple[str, str]] = {per: (enr, fld) for enr, m in _ENR.items() for per, fld in m.items()}
# Không có cổng clock trong RCC_xxxENR: thanh ghi RCC, EXTI, IWDG (LSI), DBGMCU và lõi Cortex-M4 (NVIC/SCB/STK/MPU/FPU)
UNGATED = {"RCC", "EXTI", "IWDG", "DBGMCU", "NVIC", "NVIC_STIR", "SCB", "SCB_ACTLR", "STK", "MPU", "FPU", "FPU_CPACR"}

PLLREN = 1 << 24
# bit của từng trường (RM0440 §7.4.13–7.4.18) — test_hwmodel_rcc_layout đối chiếu với SVD
_FIELD_BIT: dict[str, dict[str, int]] = {}


def _bit(regmap, enr: str, fld: str) -> int:
    reg = regmap.get(enr)
    f = reg.field(fld) if reg else None
    if f is None:
        raise KeyError(f"{enr}.{fld} not in the register map")
    return f.bit_offset


def gate_bit(regmap, peripheral: str):
    """(rid thanh ghi ENR, vị trí bit) hoặc None nếu ngoại vi không bị cổng."""
    g = GATES.get(peripheral)
    if g is None:
        return None
    return g[0], _bit(regmap, g[0], g[1])


def enabled_peripherals(rf, regmap) -> set[str]:
    """Ngoại vi có clock (kể cả những ngoại vi không bị cổng không được liệt kê)."""
    out = set()
    for per, (enr, fld) in GATES.items():
        if rf.value(regmap.get(enr)) & (1 << _bit(regmap, enr, fld)):
            out.add(per)
    return out


def clock_on(rf, regmap, peripheral: str) -> bool | None:
    """True/False nếu có cổng; None nếu không bị cổng (RCC, lõi, EXTI...) hoặc không biết."""
    g = gate_bit(regmap, peripheral)
    if g is None:
        return None
    return bool(rf.value(regmap.get(g[0])) & (1 << g[1]))


def enable_name(peripheral: str) -> str:
    enr, fld = GATES[peripheral]
    return f"{enr}.{fld}"


def refresh_status(rf, regmap) -> None:
    """Cờ RDY và SWS do phần cứng đặt (giả định: ngay lập tức)."""
    cr_reg, cfgr_reg = regmap.get("RCC_CR"), regmap.get("RCC_CFGR")
    cr, cfgr, pll = rf.value(cr_reg), rf.value(cfgr_reg), rf.value(regmap.get("RCC_PLLCFGR"))
    pllsrc = bits(pll, 0, 2)
    src_ok = (pllsrc == 0b10 and bool(cr & CR_HSION)) or (pllsrc == 0b11 and bool(cr & CR_HSEON))
    rdy = (CR_HSIRDY if cr & CR_HSION else 0) | (CR_HSERDY if cr & CR_HSEON else 0) | (CR_PLLRDY if (cr & CR_PLLON and src_ok) else 0)
    rf.force(cr_reg, (cr & ~(CR_HSIRDY | CR_HSERDY | CR_PLLRDY)) | rdy)
    sw, sws = bits(cfgr, 0, 2), bits(cfgr, 2, 2)
    # PLL làm SYSCLK cần ngõ ra R được bật: RCC_PLLCFGR.PLLREN = 1 (RM0440 p.292 'PLL R clock output enable (used as system clock)', p.278 bước 5)
    ready = {0b01: bool(rdy & CR_HSIRDY), 0b10: bool(rdy & CR_HSERDY), 0b11: bool(rdy & CR_PLLRDY) and bool(pll & PLLREN)}
    if ready.get(sw):
        sws = sw
    elif not ready.get(sws, False):
        sws = 0b01 if rdy & CR_HSIRDY else sws                      # nguồn đang dùng bị tắt: phần cứng về HSI16 nếu có
    rf.force(cfgr_reg, (cfgr & ~0xC) | (sws << 2))


# Trường của RCC_PLLCFGR chỉ ghi được khi PLL tắt (RM p.292–293): PLLSRC, PLLM, PLLN, PLLR, PLLQ, PLLP, PLLPDIV
PLL_PROTECTED = (0b11 << 0) | (0b1111 << 4) | (0x7F << 8) | (0b11 << 25) | (0b11 << 21) | (1 << 17) | (0x1F << 27)
