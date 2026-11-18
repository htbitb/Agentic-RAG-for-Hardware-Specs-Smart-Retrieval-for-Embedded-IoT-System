"""(Đặt trong hwmodel/ để bản đóng băng eval/vendor/hwmodel/ tự đầy đủ; `ingestion/header_gen.py` chỉ là lớp tương thích.)

Sinh header CMSIS-style (`stm32g474xx.h`, `stm32g4xx.h`, `core_cm4.h`) từ DB P1 (SVD + giá trị manual) — cho `compile_check` và `analyze_c_code`.

Tên trong header phải GIỐNG header chính thức của ST (`stm32g474xx.h` của cmsis-device-g4 v1.2.6, D24): người viết code bare-metal dựa vào tên ST, nên
* macro/tên bit mà ST có và header sinh thiếu ⇒ chấm sai (false fail); macro mà ST không có nhưng header sinh có ⇒ code không biên dịch được ngoài đời vẫn "đạt";
* đối chiếu tự động: `eval/tools/check_header_parity.py` (tên macro, giá trị, offset thành viên, instance). Test `test_header_gen.py` yêu cầu 0 khác biệt cho các họ
  ngoại vi nêu trong COVERED_FAMILIES (giá trị kỳ vọng lấy từ chính header ST, không sinh bằng module này — D19).

Cách dựng (mọi thứ dẫn xuất từ DB trừ các bảng tuyển chọn ở mục "lớp tên ST", mỗi bảng ghi nguồn):
* struct theo nhóm peripheral (`TIM_TypeDef`, `GPIO_TypeDef`…) với padding đúng offset; hợp nhất mọi instance cùng nhóm (TIM1 ∪ TIM15…); hai cách nhìn Input/Output của
  CCMRx thành MỘT thành viên; GPIO có `AFR[2]`, SYSCFG có `EXTICR[4]` (như ST, không có AFRL/AFRH rời).
* ST tách một số khối SVD thành nhiều instance nhỏ (DMA1_Channel1…, COMP1…, OPAMP1…, FDCAN_CONFIG): bảng `_CARVES`; ADC1…5 chung `ADC_TypeDef`, khối `*_COMMON` là
  `ADC_Common_TypeDef`; tên thành viên/instance/trường đổi sang tên ST theo bảng tuyển chọn (đối chiếu vị trí bit với DB, kèm trang RM0440).
* macro instance `TIM1`, `TIM1_BASE`, `<GROUP>_<REG>_<FIELD>_Pos / _Msk / <GROUP>_<REG>_<FIELD>` và `_0.._n` cho trường nhiều bit (quy ước của ST);
  trường 4 bit mà SVD tách thành `X` (3 bit) và `X_3` (OC1M[3]…) được gộp như ST (mặt nạ gồm cả bit cao).
* macro GIÁ TRỊ có tên theo ST mà SVD không có (`RCC_CFGR_SW_PLL`, `FLASH_ACR_LATENCY_4WS`, `RCC_CFGR_HPRE_DIV2`…): bảng tuyển chọn `VALUE_MACROS`
  (giá trị lấy từ RM0440 p.130, p.289–293); họ bí danh tương thích F4 của ST (`GPIO_MODER_MODER8`…) sinh theo quy tắc.
* ngoại vi lõi Cortex-M (NVIC, SCB, SysTick, MPU, FPU) KHÔNG nằm trong header thiết bị của ST (do CMSIS-Core `core_cm4.h` của ARM định nghĩa, với tên khác SVD): ở đây
  chúng nằm trong `core_cm4.h` SINH RA (tên theo SVD, KHÔNG đối chiếu được vì không có bản của ARM) để `stm32g474xx.h` chỉ còn tên của ST.
* `#ifdef HWMODEL_ANALYZE`: struct để mở (incomplete type) để `pycparser` không phải đọc định nghĩa struct; bố cục lấy từ mô hình này.
Chỉ STM32G474. Sinh tất định (cùng DB ⇒ cùng byte) và có `checksum`.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import data

CHIP = "stm32g474"
_CTYPE = {32: "uint32_t", 16: "uint16_t", 8: "uint8_t"}
PPB_INTERNAL = (0xE000_0000, 0xE004_0000)       # ARMv7-M: PPB nội bộ (NVIC/SCB/SysTick/MPU/FPU) — của CMSIS-Core; DBGMCU (0xE0042000) là của ST


@dataclass
class Member:
    name: str
    offset: int
    size: int               # byte
    count: int = 1
    parts: tuple = ()       # ((tên thanh ghi DB, offset), …) khi thành viên mảng gộp nhiều thanh ghi (AFR[2] ← AFRL, AFRH)


@dataclass
class FieldDef:
    name: str
    bit_offset: int
    bit_width: int
    hi: tuple = ()          # vị trí tuyệt đối của các bit cao tách rời trong SVD (OC1M[3] ở bit 16): ST gộp vào mặt nạ của trường


@dataclass
class MacroReg:
    """Một thanh ghi theo cách ST đặt tên macro: `<prefix>_<token>_<field>`."""
    prefix: str
    token: str
    fields: list[FieldDef] = field(default_factory=list)


@dataclass
class Instance:
    name: str
    base: int
    type_name: str


@dataclass
class GroupModel:
    name: str
    type_name: str
    prefix: str = ""
    members: list[Member] = field(default_factory=list)
    macro_regs: list[MacroReg] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)

    def __post_init__(self):
        self.prefix = self.prefix or self.name

    @property
    def fields(self) -> dict[str, list[FieldDef]]:
        """token thanh ghi -> trường (chỉ các macro mang tiền tố của nhóm)."""
        return {r.token: r.fields for r in self.macro_regs if r.prefix == self.prefix}

    @property
    def core(self) -> bool:
        return bool(self.instances) and all(PPB_INTERNAL[0] <= i.base < PPB_INTERNAL[1] for i in self.instances)

    def offset_of(self, member: str) -> int | None:
        for m in self.members:
            if m.name == member:
                return m.offset
            for pname, poff in m.parts:
                if pname == member:
                    return poff
        return None


@dataclass
class HeaderModel:
    chip: str
    groups: dict[str, GroupModel]
    interrupts: dict[str, int]
    anomalies: list[dict]
    instance_group: dict[str, str]
    extra_bases: dict[str, int] = field(default_factory=dict)      # macro `<tên>_BASE` không gắn với con trỏ struct (SRAMCAN_BASE…)

    def group_of(self, peripheral: str) -> str:
        return self.instance_group[peripheral]


def member_name(peripheral: str, register: str, group: str | None = None) -> str:
    """Tên thành viên struct từ tên thanh ghi SVD: bỏ tiền tố `<peripheral>_` (và `<group>_` nếu có: SVD của DAC1 đặt tên `DAC_CR`) và hậu tố Input/Output."""
    n = register
    for pre in (peripheral, group):
        if pre and n.upper().startswith(pre.upper() + "_"):
            n = n[len(pre) + 1:]
            break
    return re.sub(r"_(Input|Output)$", "", n)


# ====================================================================================== lớp tên ST (D24)
# Nguồn của mọi bảng dưới đây: `stm32g474xx.h` của STMicroelectronics/cmsis-device-g4 v1.2.6 (corpus/headers/…, sha256 trong corpus/manifest.yaml) đối chiếu với DB
# (vị trí/độ rộng bit của trường phải trùng DB, kiểm bằng test) và RM0440 (số trang ghi ở từng mục). Tên ST được lấy làm chuẩn vì code người dùng được viết/biên dịch
# với chính header đó; không bảng nào chứa tên mà ST không có.

# ---- nhóm / kiểu / tiền tố / instance
_ST_GROUP_OF = {"ADC12_Common": "ADC_Common", "ADC345_Common": "ADC_Common"}           # RM0440 ADCx_CSR p.705, ADCx_CCR p.706: khối "common" của cặp/bộ ADC là struct riêng
_ST_TYPE_NAME = {"FDCAN": "FDCAN_GlobalTypeDef"}                                        # ST: FDCAN_GlobalTypeDef (không phải FDCAN_TypeDef)
_ST_PREFIX = {"ADC_Common": "ADC"}      # tiền tố macro ≠ tên nhóm struct (các nhóm tách bởi _CARVES lấy tiền tố từ chính mục _Carve)
_ST_INSTANCE = {"ADC12_Common": "ADC12_COMMON", "ADC345_Common": "ADC345_COMMON", "LPTIMER1": "LPTIM1", "USB_FS_device": "USB", "SAI": "SAI1"}
_ST_DROP_INSTANCE = {"FDCAN"}              # SVD đặt khối "FDCAN" ở 0x4000A400 = SRAM tin nhắn FDCAN (ST: chỉ có macro SRAMCAN_BASE, không có con trỏ struct)
_ST_BASE_NAME = {"FLASH": "FLASH_R_BASE", "QUADSPI": "QSPI_R_BASE", "FMC": "FMC_R_BASE"}    # ST: FLASH_BASE/FMC_BASE là địa chỉ BỘ NHỚ (0x08000000/0x60000000), thanh ghi có tên *_R_BASE
_ST_EXTRA_BASES = {"SRAMCAN_BASE": "FDCAN"}                                            # <tên macro> -> thiết bị DB có địa chỉ đó
_ST_INSTANCE_ALIAS = {"DAC": "DAC1", "OPAMP": "OPAMP1", "DMAMUX1": "DMAMUX1_Channel0"}                                # ST: `DAC` = DAC1, `OPAMP` = OPAMP1 (cùng địa chỉ)

# ---- tên thành viên struct (thanh ghi) theo ST: (nhóm, tên SVD sau khi bỏ tiền tố) -> tên ST
_ST_MEMBER = {("DAC", "SWTRGR"): "SWTRIGR",                                            # ST DAC_TypeDef.SWTRIGR (SVD và RM0440 p.746: SWTRGR)
              ("DBGMCU", "APB1L_FZ"): "APB1FZR1", ("DBGMCU", "APB1H_FZ"): "APB1FZR2", ("DBGMCU", "APB2_FZ"): "APB2FZ",     # RM0440 p.2109
              ("TIM", "OR1"): "OR"}                                                        # TIM16/17 TIMx_OR1 p.1505 = TIM_TypeDef.OR của ST
# thành viên mảng của ST gộp từ nhiều thanh ghi SVD liên tiếp: (nhóm, tên ST) -> các thanh ghi SVD (macro vẫn mang tên từng thanh ghi: SYSCFG_EXTICR1_…);
# GPIOx_AFRL/AFRH RM0440 p.359–360, SYSCFG_EXTICRx p.367
_ST_ARRAYS = {("GPIO", "AFR"): ("AFRL", "AFRH"), ("SYSCFG", "EXTICR"): ("EXTICR1", "EXTICR2", "EXTICR3", "EXTICR4")}
# tiền tố macro của một thanh ghi khác nhóm struct: (nhóm, token) -> tiền tố (ST đặt macro AF1/AF2 của timer theo TIM1_AF1_…)
_ST_REG_PREFIX = {("TIM", "AF1"): "TIM1", ("TIM", "AF2"): "TIM1"}


@dataclass(frozen=True)
class _Carve:
    """ST tách một nhóm thanh ghi lặp lại của khối SVD thành struct nhỏ + nhiều instance (DMA1_Channel1…): offset thành viên tính từ thanh ghi đầu của từng nhóm."""
    parents: tuple             # tên peripheral DB
    group: str
    prefix: str
    names: tuple               # tên thành viên ST
    svd: tuple                 # mẫu tên thanh ghi (đã bỏ tiền tố) với {n}
    indices: tuple
    instance: str              # mẫu tên instance với {parent}, {n}
    drop_from: tuple = ()      # peripheral DB khác có cùng thanh ghi nhưng không sinh instance (FDCAN2/3: CKDIV)
    tokens: tuple = ()         # token macro của từng thành viên khi ST đặt khác tên thành viên (DMAMUX: CCR -> CxCR); rỗng = giống tên thành viên


_CARVES = (
    _Carve(("DMA1", "DMA2"), "DMA_Channel", "DMA", ("CCR", "CNDTR", "CPAR", "CMAR"), ("CCR{n}", "CNDTR{n}", "CPAR{n}", "CMAR{n}"),
           tuple(range(1, 9)), "{parent}_Channel{n}"),                                  # RM0440 DMA_CCRx p.411 (ISR p.407): CCRx/CNDTRx/CPARx/CMARx, bước 20 byte
    _Carve(("COMP",), "COMP", "COMP", ("CSR",), ("C{n}CSR",), tuple(range(1, 8)), "COMP{n}"),                  # RM0440 COMP_CxCSR p.772
    _Carve(("OPAMP",), "OPAMP", "OPAMP", ("CSR", "TCMR"), ("OPAMP{n}_CSR", "OPAMP{n}_TCMR"), tuple(range(1, 7)), "OPAMP{n}"),            # OPAMPx_CSR p.788, OPAMPx_TCMR p.806
    _Carve(("FDCAN1",), "FDCAN_Config", "FDCAN", ("CKDIV",), ("CKDIV",), (None,), "FDCAN_CONFIG", drop_from=("FDCAN2", "FDCAN3")),   # RM0440 FDCAN_CKDIV p.2012 @ FDCAN1+0x100
    # DMAMUX (RM0440 p.429–432): kênh x = C{x}CR @ 4x, trạng thái kênh CSR/CFR @ 0x80, bộ tạo yêu cầu RG{x}CR @ 0x100 + 4x, trạng thái RGSR/RGCFR @ 0x140
    _Carve(("DMAMUX",), "DMAMUX_Channel", "DMAMUX", ("CCR",), ("C{n}CR",), tuple(range(16)), "DMAMUX1_Channel{n}", tokens=("CxCR",)),
    _Carve(("DMAMUX",), "DMAMUX_ChannelStatus", "DMAMUX", ("CSR", "CFR"), ("CSR", "CFR"), (None,), "DMAMUX1_ChannelStatus"),
    _Carve(("DMAMUX",), "DMAMUX_RequestGen", "DMAMUX", ("RGCR",), ("RG{n}CR",), tuple(range(4)), "DMAMUX1_RequestGenerator{n}", tokens=("RGxCR",)),
    _Carve(("DMAMUX",), "DMAMUX_RequestGenStatus", "DMAMUX", ("RGSR", "RGCFR"), ("RGSR", "RGCFR"), (None,), "DMAMUX1_RequestGenStatus"),
    # SAI (RM0440 p.1923, PDMCR p.1946): hai khối con A/B (SAI1_Block_A @ SAI+0x04, SAI1_Block_B @ SAI+0x24); SVD gọi IMR là AIM/BIM
    _Carve(("SAI",), "SAI_Block", "SAI", ("CR1", "CR2", "FRCR", "SLOTR", "IMR", "SR", "CLRFR", "DR"),
           ("{n}CR1", "{n}CR2", "{n}FRCR", "{n}SLOTR", "{n}IM", "{n}SR", "{n}CLRFR", "{n}DR"), ("A", "B"), "SAI1_Block_{n}",
           tokens=("xCR1", "xCR2", "xFRCR", "xSLOTR", "xIMR", "xSR", "xCLRFR", "xDR")),
)

# Bản đồ bộ nhớ và địa chỉ bus (RM0440 §2.2.2: Figure 2 p.83, Table 3 p.83–87; SRAM2 0x2001 4000 p.88; bí danh bit-band theo công thức p.88). Giá trị như header ST.
_ST_MEMORY_MAP = (
    ("FLASH_BASE", "(0x08000000UL)"), ("SRAM1_BASE", "(0x20000000UL)"), ("SRAM2_BASE", "(0x20014000UL)"), ("CCMSRAM_BASE", "(0x10000000UL)"),
    ("PERIPH_BASE", "(0x40000000UL)"), ("FMC_BASE", "(0x60000000UL)"), ("QSPI_BASE", "(0x90000000UL)"),
    ("SRAM1_BB_BASE", "(0x22000000UL)"), ("SRAM2_BB_BASE", "(0x22280000UL)"), ("CCMSRAM_BB_BASE", "(0x22300000UL)"), ("PERIPH_BB_BASE", "(0x42000000UL)"),
    ("SRAM_BASE", "SRAM1_BASE"), ("SRAM_BB_BASE", "SRAM1_BB_BASE"),
    ("SRAM1_SIZE_MAX", "(0x00014000UL)"), ("SRAM2_SIZE", "(0x00004000UL)"), ("CCMSRAM_SIZE", "(0x00008000UL)"),
    ("APB1PERIPH_BASE", "PERIPH_BASE"), ("APB2PERIPH_BASE", "(PERIPH_BASE + 0x00010000UL)"), ("AHB1PERIPH_BASE", "(PERIPH_BASE + 0x00020000UL)"),
    ("AHB2PERIPH_BASE", "(PERIPH_BASE + 0x08000000UL)"),
    ("FMC_BANK1", "FMC_BASE"), ("FMC_BANK1_1", "FMC_BANK1"), ("FMC_BANK1_2", "(FMC_BANK1 + 0x04000000UL)"), ("FMC_BANK1_3", "(FMC_BANK1 + 0x08000000UL)"),
    ("FMC_BANK1_4", "(FMC_BANK1 + 0x0C000000UL)"), ("FMC_BANK3", "(FMC_BASE  + 0x20000000UL)"),
    ("PACKAGE_BASE", "(0x1FFF7500UL)"), ("UID_BASE", "(0x1FFF7590UL)"), ("FLASHSIZE_BASE", "(0x1FFF75E0UL)"),      # dữ liệu chữ ký thiết bị (RM0440 p.2121–2122)
    ("LSI_STARTUP_TIME", "130U"),                                                                                  # tSU(LSI) tối đa 130 µs (DS12288 Table 45 p.122)
)

# Thanh ghi mà RM0440 (và header ST) có nhưng SVD/DB không có: (nhóm, tên, offset, trang RM0440). Trường của chúng khai báo trong ST_FIELD_ADD.
_ST_EXTRA_REGS = {"FLASH": (("PCROP2SR", 0x44, 142), ("PCROP2ER", 0x48, 143), ("WRP2AR", 0x4C, 143), ("WRP2BR", 0x50, 144), ("SEC2R", 0x74, 145))}   # ngân hàng 2 (DBANK)

_ST_PREFIX.update({c.group: c.prefix for c in _CARVES})

# ---- trường: đổi tên / bỏ / thêm / ghép bit cao / hình học (khoá: "<tiền tố>_<token>")
# Mỗi mục khoá bằng "<tiền tố>_<token thanh ghi>" của macro ST. Vị trí/độ rộng bit của mọi trường đổi tên hoặc ghép phải khớp DB (test đối chiếu header ST kiểm).
# Phần lớn là khác biệt tên giữa SVD và RM0440/header ST (SVD sao chép nhầm, đặt tên theo F4…); phần "thêm" là macro ST có mà SVD không có;
# phần "hình học" là nơi ST dùng độ rộng/vị trí khác SVD (RM0440 là chuẩn; ghi chú trong plan/P3_D24_notes.md).
ST_FIELD_RENAME: dict[str, dict[str, str]] = {
    "ADC_CSR": {'ADDRDY_MST': 'ADRDY_MST'},
    "COMP_CSR": {'POL': 'POLARITY', 'BLANKSEL': 'BLANKING'},
    "CRC_INIT": {'CRC_INIT': 'INIT'},
    "DBGMCU_APB1FZR1": {'DBG_TIMER2_STOP': 'DBG_TIM2_STOP', 'DBG_TIMER6_STOP': 'DBG_TIM6_STOP', 'DBG_LPTIMER_STOP': 'DBG_LPTIM1_STOP'},
    "DBGMCU_APB2FZ": {'DBG_HRTIM0_STOP': 'DBG_HRTIM1_STOP'},
    "FDCAN_ILS": {'RxFIFO0': 'RXFIFO0', 'RxFIFO1': 'RXFIFO1'},
    "FLASH_OPTR": {'IDWG_SW': 'IWDG_SW', 'SRAM2_PE': 'SRAM_PE', 'SRAM2_RST': 'CCMSRAM_RST'},
    "OPAMP_CSR": {'OPAEN': 'OPAMPxEN', 'FORCE_VP': 'FORCEVP', 'VP_SEL': 'VPSEL', 'VM_SEL': 'VMSEL', 'OPAHSM': 'HIGHSPEEDEN', 'OPAINTOEN': 'OPAMPINTEN', 'PGA_GAIN': 'PGGAIN', 'CALOUT': 'OUTCAL'},
    "OPAMP_TCMR": {'VMS_SEL': 'VMSSEL', 'VPS_SEL': 'VPSSEL', 'T1CM_EN': 'T1CMEN', 'T8CM_EN': 'T8CMEN', 'T20CM_EN': 'T20CMEN'},
    "PWR_CR2": {'PVMEN2': 'PVME4', 'PVMEN1': 'PVME3', 'PVDLS': 'PLS'},
    "PWR_CR3": {'EIWUL': 'EIWF', 'UCPD1_DBDIS': 'UCPD_DBDIS', 'UCPD1_STDBY': 'UCPD_STDBY'},
    "RCC_AHB2SMENR": {'RNGEN': 'RNGSMEN'},
    "RTC_CR": {'WCKSEL': 'WUCKSEL'},
    "SAI_xCLRFR": {'OVRUDR': 'COVRUDR', 'MUTEDET': 'CMUTEDET', 'WCKCFG': 'CWCKCFG', 'CNRDY': 'CCNRDY', 'LFSDET': 'CLFSDET'},
    "SAI_xCR1": {'OutDri': 'OUTDRIV', 'MCJDIV': 'MCKDIV'},
    "SAI_xCR2": {'FFLUS': 'FFLUSH', 'MUTECN': 'MUTECNT'},
    "SAI_xIMR": {'MUTEDET': 'MUTEDETIE', 'WCKCFG': 'WCKCFGIE'},
    "SPI_CR1": {'DFF': 'CRCL'},
    "SPI_CR2": {'LDMA_RX': 'LDMARX', 'LDMA_TX': 'LDMATX'},
    "SPI_RXCRCR": {'RxCRC': 'RXCRC'},
    "SPI_SR": {'TIFRFE': 'FRE'},
    "SPI_TXCRCR": {'TxCRC': 'TXCRC'},
    "SYSCFG_MEMRMP": {'FB_mode': 'FB_MODE'},
    "TAMP_CR2": {'TAMP1NOER': 'TAMP1NOERASE', 'TAMP2NOER': 'TAMP2NOERASE', 'TAMP3NOER': 'TAMP3NOERASE'},
    "TIM1_AF2": {'BKINE': 'BK2INE'},
    "TIM_BDTR": {'BK2ID': 'BK2BID'},
    "UCPD_CFG1": {'PSC_USBPDCLK': 'PSC_UCPDCLK'},
    "USART_CR2": {'TAINV': 'DATAINV'},
    "USART_ICR": {'NCF': 'NECF'},
    "USART_ISR": {'NF': 'NE'},
}

ST_FIELD_DROP: dict[str, tuple] = {
    "ADC_CFGR": ('ALIGN_5', 'AWDCH1CH'),
    "ADC_DIFSEL": ('DIFSEL_0', 'DIFSEL_1_18'),
    "DBGMCU_APB2FZ": ('DBG_HRTIM1_STOP', 'DBG_HRTIM2_STOP', 'DBG_HRTIM3_STOP'),
    "EXTI_FTSR1": ('FT18',),
    "EXTI_FTSR2": ('FT35', 'FT36', 'FT37'),
    "EXTI_IMR2": ('IM43',),
    "EXTI_PR1": ('PIF18',),
    "EXTI_PR2": ('PIF35', 'PIF36', 'PIF37'),
    "EXTI_RTSR1": ('RT18', 'RT'),
    "EXTI_SWIER1": ('SWI18',),
    "EXTI_SWIER2": ('SWI35', 'SWI36', 'SWI37'),
    "FLASH_KEYR": ('KEYR',),
    "FLASH_OPTKEYR": ('OPTKEYR',),
    "FLASH_PDKEYR": ('PDKEYR',),
    "PWR_CR1": ('FPD_STOP',),
    "RCC_AHB2ENR": ('AESEN',),
    "RCC_AHB2RSTR": ('AESRST',),
    "RCC_AHB2SMENR": ('AESSMEN',),
    "RNG_DR": ('RNDATA',),
    "SAI_xCR1": ('SAIAEN', 'SAIBEN'),
    "SAI_xIMR": ('LFSDET',),
    "SYSCFG_CFGR1": ('FPU_IE',),
    "TIM_CCMR1": ('ICPCS',),
    "TIM_CCMR3": ('OC5M_bit3',),
    "TIM_ECR": ('IBLK',),
    "USART_BRR": ('DIV_Fraction', 'DIV_Mantissa'),
    "USART_CR1": ('DEDT0', 'DEDT1', 'DEDT2', 'DEDT3', 'DEDT4', 'DEAT0', 'DEAT1', 'DEAT2', 'DEAT3', 'DEAT4'),
    "USART_CR2": ('ABRMOD0', 'ABRMOD1', 'ADD0_3', 'ADD4_7'),
}

ST_FIELD_ADD: dict[str, tuple] = {
    "ADC_DIFSEL": (('DIFSEL', 0, 19),),
    "DAC_CR": (('HFSEL', 15, 1),),
    "EXTI_EMR2": (('EM41', 9, 1), ('EM42', 10, 1), ('EM', 0, 11)),
    "EXTI_FTSR1": (('FT17', 17, 1), ('FT29', 29, 1), ('FT30', 30, 1), ('FT31', 31, 1)),
    "EXTI_FTSR2": (('FT32', 0, 1), ('FT33', 1, 1), ('FT39', 7, 1), ('FT40', 8, 1), ('FT41', 9, 1)),
    "EXTI_IMR1": (('IM', 0, 32),),
    "EXTI_IMR2": (('IM', 0, 11),),
    "EXTI_PR1": (('PIF17', 17, 1), ('PIF29', 29, 1), ('PIF30', 30, 1), ('PIF31', 31, 1)),
    "EXTI_PR2": (('PIF32', 0, 1), ('PIF33', 1, 1), ('PIF39', 7, 1), ('PIF40', 8, 1), ('PIF41', 9, 1)),
    "EXTI_RTSR1": (('RT17', 17, 1), ('RT29', 29, 1), ('RT30', 30, 1), ('RT31', 31, 1)),
    "EXTI_SWIER1": (('SWI17', 17, 1), ('SWI29', 29, 1), ('SWI30', 30, 1), ('SWI31', 31, 1)),
    "EXTI_SWIER2": (('SWI32', 0, 1), ('SWI33', 1, 1), ('SWI39', 7, 1), ('SWI40', 8, 1), ('SWI41', 9, 1)),
    "FLASH_CR": (('BKER', 11, 1), ('MER2', 15, 1), ('SEC_PROT2', 29, 1)),
    "FLASH_OPTR": (('BFB2', 20, 1), ('DBANK', 22, 1)),
    "FLASH_PCROP2ER": (('PCROP2_END', 0, 15),),
    "FLASH_PCROP2SR": (('PCROP2_STRT', 0, 15),),
    "FLASH_SEC2R": (('SEC_SIZE2', 0, 8),),
    "FLASH_WRP2AR": (('WRP2A_STRT', 0, 7), ('WRP2A_END', 16, 7)),
    "FLASH_WRP2BR": (('WRP2B_STRT', 0, 7), ('WRP2B_END', 16, 7)),
    "I2C_CR1": (('SWRST', 13, 1),),
    "I2C_OAR2": (('OA2MASK01', 8, 1), ('OA2MASK02', 9, 1), ('OA2MASK03', 8, 2), ('OA2MASK04', 10, 1), ('OA2MASK05', 8, 1, (10,)), ('OA2MASK06', 9, 2), ('OA2MASK07', 8, 3)),
    "PWR_CR1": (('LPMS_STOP1', 0, 1), ('LPMS_STANDBY', 0, 2), ('LPMS_SHUTDOWN', 2, 1)),
    "PWR_CR2": (('PVME', 4, 4), ('PVME2', 5, 1), ('PVME1', 4, 1), ('PLS_LEV1', 1, 1), ('PLS_LEV2', 2, 1), ('PLS_LEV3', 1, 2), ('PLS_LEV4', 3, 1), ('PLS_LEV5', 1, 1, (3,)), ('PLS_LEV6', 2, 2), ('PLS_LEV7', 1, 3)),
    "PWR_CR3": (('EWUP', 0, 5),),
    "PWR_PUCRG": (('PG15', 15, 1), ('PG14', 14, 1), ('PG13', 13, 1), ('PG12', 12, 1), ('PG11', 11, 1)),
    "PWR_SCR": (('CWUF', 0, 5),),
    "PWR_SR1": (('WUF', 0, 5),),
    "PWR_SR2": (('PVMO4', 15, 1), ('PVMO3', 14, 1)),
    "QUADSPI_CCR": (('DHHC', 30, 1),),
    "RCC_PLLCFGR": (('PLLSRC_HSI', 1, 1), ('PLLSRC_HSE', 0, 2)),
    "SAI_xCLRFR": (('CFREQ', 3, 1),),
    "SAI_xCR1": (('SAIEN', 16, 1),),
    "SPI_I2SCFGR": (('ASTRTEN', 12, 1),),
    "SPI_SR": (('CHSIDE', 2, 1), ('UDR', 3, 1)),
    "TAMP_CR2": (('TAMP1MF', 16, 1), ('TAMP2MF', 17, 1), ('TAMP3MF', 18, 1)),
    "USART_BRR": (('LPUART', 0, 20),),
    "USART_CR1": (('RXNEIE_RXFNEIE', 5, 1), ('TXEIE_TXFNFIE', 7, 1), ('M', 12, 1, (28,)), ('DEDT', 16, 5), ('DEAT', 21, 5)),
    "USART_CR2": (('ABRMODE', 21, 2), ('ADD', 24, 8)),
    "USART_ISR": (('RXNE_RXFNE', 5, 1), ('TXE_TXFNF', 7, 1)),
}

ST_FIELD_FOLD: dict[str, dict[str, tuple]] = {
    "LPTIM_OR": {'IN1': ('IN1_2_1',), 'IN2': ('IN2_2_1',)},
    "TIM_CCMR1": {'OC1M': ('OC1M_3',), 'OC2M': ('OC2M_3',)},
    "TIM_CCMR2": {'OC3M': ('OC3M_3',), 'OC4M': ('OC4M_3',)},
    "TIM_CCMR3": {'OC6M': ('OC6M_bit3',)},
    "TIM_CR2": {'MMS': ('MMS_3',)},
    "TIM_SMCR": {'SMS': ('SMS_3',), 'TS': ('TS_4_3',)},
}

ST_FIELD_SPLIT: dict[str, dict[str, str]] = {          # trường nhiều bit SVD -> ST dùng từng cờ 1 bit <tiền tố>0.. (DMAMUX_CSR_SOF0..15)
    "DMAMUX_CSR": {"SOF": "SOF"}, "DMAMUX_CFR": {"CSOF": "CSOF"}, "DMAMUX_RGSR": {"OF": "OF"}, "DMAMUX_RGCFR": {"COF": "COF"},
}
ST_FIELD_GEOM: dict[str, dict[str, tuple]] = {
    "COMP_CSR": {'INMSEL': (4, 4)},
    "DBGMCU_IDCODE": {'DEV_ID': (0, 12)},
    "LPTIM_CFGR": {'TRIGSEL': (13, 3, (29,))},
    "PWR_SR2": {'PVMO2': (13, 1), 'PVMO1': (12, 1)},
    "QUADSPI_CR": {'FTHRES': (8, 4)},
    "SYSCFG_EXTICR1": {'EXTI0': (0, 3), 'EXTI1': (4, 3), 'EXTI2': (8, 3), 'EXTI3': (12, 3)},
    "SYSCFG_EXTICR2": {'EXTI4': (0, 3), 'EXTI5': (4, 3), 'EXTI6': (8, 3), 'EXTI7': (12, 3)},
    "SYSCFG_EXTICR3": {'EXTI8': (0, 3), 'EXTI9': (4, 3), 'EXTI10': (8, 3), 'EXTI11': (12, 3)},
    "SYSCFG_EXTICR4": {'EXTI12': (0, 3), 'EXTI13': (4, 3), 'EXTI14': (8, 3), 'EXTI15': (12, 3)},
    "TIM_ARR": {'ARR': (0, 32)},
    "TIM_CCMR3": {'OC5M': (4, 3, (16,))},
    "TIM_CCR1": {'CCR1': (0, 32)},
    "TIM_CCR2": {'CCR2': (0, 32)},
    "TIM_CCR3": {'CCR3': (0, 32)},
    "TIM_CCR4": {'CCR4': (0, 32)},
    "TIM_CCR5": {'CCR5': (0, 20)},
    "TIM_CCR6": {'CCR6': (0, 20)},
    "TIM_CNT": {'CNT': (0, 32)},
    "USART_BRR": {'BRR': (0, 16)},
}

# Bit riêng lẻ `<trường>_0.._n`: ST có cho trường 2–6 bit (kể cả bit cao ghép), trừ các ngoại lệ dưới đây; trường rộng hơn không có trừ ST_BITS_ON.
# (ST_BITS_OFF/ON đo từ header ST; quy tắc độ rộng chỉ để bảng ngắn.)
ST_BITS_MAX_WIDTH = 6
ST_BITS_ON = frozenset({
    "DMAMUX_CxCR_DMAREQ_ID", "SAI_xFRCR_FRL", "SAI_xFRCR_FSALL", "ADC_AWD2CR_AWD2CH", "ADC_AWD3CR_AWD3CH", "ADC_CALFACT_CALFACT_D", "ADC_CALFACT_CALFACT_S", "ADC_DIFSEL_DIFSEL", "FMAC_PARAM_FUNC",
    "RCC_CRRCR_HSI48CAL", "RCC_ICSCR_HSICAL", "RCC_ICSCR_HSITRIM", "RCC_PLLCFGR_PLLN", "RTC_CALR_CALM", "TIM_BDTR_DTG", "TIM_DTR2_DTGF", "TIM_ECR_PW",
    "UCPD_CFG1_RXORDSETEN", "WWDG_CFR_W", "WWDG_CR_T"
})

ST_BITS_OFF = frozenset({
    "FLASH_OPTR_BOR_LEV", "DAC_CCR_OTRIM1", "DAC_CCR_OTRIM2", "FDCAN_CKDIV_PDIV", "FDCAN_CREL_REL", "FDCAN_CREL_STEP", "FDCAN_CREL_SUBSTEP", "FDCAN_CREL_YEAR",
    "FDCAN_DBTP_DBRP", "FDCAN_DBTP_DSJW", "FDCAN_DBTP_DTSEG1", "FDCAN_DBTP_DTSEG2", "FDCAN_HPMS_BIDX", "FDCAN_HPMS_FIDX", "FDCAN_HPMS_MSI",
    "FDCAN_PSR_ACT", "FDCAN_PSR_DLEC", "FDCAN_PSR_LEC", "FDCAN_RXF0A_F0AI", "FDCAN_RXF0S_F0FL", "FDCAN_RXF0S_F0GI", "FDCAN_RXF0S_F0PI",
    "FDCAN_RXF1A_F1AI", "FDCAN_RXF1S_F1FL", "FDCAN_RXF1S_F1GI", "FDCAN_RXF1S_F1PI", "FDCAN_RXGFC_ANFE", "FDCAN_RXGFC_ANFS", "FDCAN_RXGFC_LSE",
    "FDCAN_RXGFC_LSS", "FDCAN_TEST_TX", "FDCAN_TOCC_TOS", "FDCAN_TSCC_TCP", "FDCAN_TSCC_TSS", "FDCAN_TXBAR_AR", "FDCAN_TXBCF_CF", "FDCAN_TXBCIE_CFIE",
    "FDCAN_TXBCR_CR", "FDCAN_TXBRP_TRP", "FDCAN_TXBTIE_TIE", "FDCAN_TXBTO_TO", "FDCAN_TXEFA_EFAI", "FDCAN_TXEFS_EFFL", "FDCAN_TXEFS_EFGI",
    "FDCAN_TXEFS_EFPI", "FDCAN_TXFQS_TFFL", "FDCAN_TXFQS_TFGI", "FDCAN_TXFQS_TFQPI", "FLASH_ACR_LATENCY", "FMAC_X1BUFCFG_FULL_WM",
    "FMAC_YBUFCFG_EMPTY_WM", "I2C_CR1_DNF", "I2C_OAR2_OA2MASK03", "I2C_OAR2_OA2MASK05", "I2C_OAR2_OA2MASK06", "I2C_OAR2_OA2MASK07", "I2C_OAR2_OA2MSK",
    "I2C_TIMINGR_PRESC", "I2C_TIMINGR_SCLDEL", "I2C_TIMINGR_SDADEL", "OPAMP_CSR_TRIMOFFSETN", "OPAMP_CSR_TRIMOFFSETP", "PWR_CR1_LPMS",
    "PWR_CR1_LPMS_STANDBY", "PWR_CR2_PLS", "PWR_CR2_PLS_LEV3", "PWR_CR2_PLS_LEV5", "PWR_CR2_PLS_LEV6", "PWR_CR2_PLS_LEV7", "PWR_CR2_PVME",
    "PWR_CR3_EWUP", "PWR_SCR_CWUF", "PWR_SR1_WUF", "QUADSPI_CCR_DCYC", "QUADSPI_CR_FTHRES", "QUADSPI_DCR_FSIZE", "QUADSPI_SR_FLEVEL",
    "RCC_PLLCFGR_PLLSRC_HSE", "SYSCFG_EXTICR1_EXTI0", "SYSCFG_EXTICR1_EXTI1", "SYSCFG_EXTICR1_EXTI2", "SYSCFG_EXTICR1_EXTI3", "SYSCFG_EXTICR2_EXTI4",
    "SYSCFG_EXTICR2_EXTI5", "SYSCFG_EXTICR2_EXTI6", "SYSCFG_EXTICR2_EXTI7", "SYSCFG_EXTICR3_EXTI10", "SYSCFG_EXTICR3_EXTI11", "SYSCFG_EXTICR3_EXTI8",
    "SYSCFG_EXTICR3_EXTI9", "SYSCFG_EXTICR4_EXTI12", "SYSCFG_EXTICR4_EXTI13", "SYSCFG_EXTICR4_EXTI14", "SYSCFG_EXTICR4_EXTI15", "TIM_BDTR_BK2F",
    "TIM_BDTR_BKF", "UCPD_RX_ORDSET_RXSOPKINVALID", "USART_CR1_M", "VREFBUF_CCR_TRIM"
})

# tên trường GPIO theo header ST (SVD dùng MODER8 / AFRH8…)
_GPIO_ST = (("MODER", r"^MODER(\d+)$", r"MODE\1"), ("OSPEEDR", r"^OSPEEDR(\d+)$", r"OSPEED\1"), ("PUPDR", r"^PUPDR(\d+)$", r"PUPD\1"),
            ("AFRL", r"^AFRL(\d+)$", r"AFSEL\1"), ("AFRH", r"^AFRH(\d+)$", r"AFSEL\1"), ("IDR", r"^IDR(\d+)$", r"ID\1"), ("ODR", r"^ODR(\d+)$", r"OD\1"))

# macro giá trị của header ST (không có trong SVD): (nhóm, thanh ghi, trường, [(hậu tố, giá trị)])
_HPRE = [("DIV1", 0), ("DIV2", 8), ("DIV4", 9), ("DIV8", 10), ("DIV16", 11), ("DIV64", 12), ("DIV128", 13), ("DIV256", 14), ("DIV512", 15)]
_PPRE = [("DIV1", 0), ("DIV2", 4), ("DIV4", 5), ("DIV8", 6), ("DIV16", 7)]
VALUE_MACROS = [
    ("FLASH", "ACR", "LATENCY", [(f"{n}WS", n) for n in range(16)]),                     # RM0440 p.130
    ("RCC", "CFGR", "SW", [("HSI", 1), ("HSE", 2), ("PLL", 3)]),                           # p.289
    ("RCC", "CFGR", "SWS", [("HSI", 1), ("HSE", 2), ("PLL", 3)]),
    ("RCC", "CFGR", "HPRE", _HPRE), ("RCC", "CFGR", "PPRE1", _PPRE), ("RCC", "CFGR", "PPRE2", _PPRE),   # p.290
]

# Macro GIÁ TRỊ/bí danh của header ST mà SVD không có (RM0440: trang của thanh ghi ghi bên cạnh): nhóm -> ((tên, thân), …)
_MCO = [("DIV1", 0), ("DIV2", 1), ("DIV4", 2), ("DIV8", 3), ("DIV16", 4)]
ST_EXTRA_MACROS: dict[str, tuple] = {
    "FLASH": tuple((f"FLASH_OPTR_BOR_LEV_{n}", f"({n}UL << FLASH_OPTR_BOR_LEV_Pos)") for n in range(5)),           # BOR_LEV[2:0] 000..100 (RM0440 p.138): ST đặt GIÁ TRỊ, không phải từng bit
    "RCC": tuple((f"RCC_CFGR_MCOPRE_{d}", f"({v}UL << RCC_CFGR_MCOPRE_Pos)") for d, v in _MCO)                    # MCOPRE[2:0] (RM0440 p.289)
           + (("RCC_CFGR_MCO_PRE", "RCC_CFGR_MCOPRE"),) + tuple((f"RCC_CFGR_MCO_PRE_{d[3:]}", f"RCC_CFGR_MCOPRE_{d}") for d, _ in _MCO),
    "I2C": (("I2C_OAR2_OA2NOMASK", "(0x0UL << I2C_OAR2_OA2MASK_Pos)"),),                                           # OA2MASK = 000: không che (RM0440 p.1680)
    "PWR": (("PWR_CR1_LPMS_STOP0", "(0x0UL << PWR_CR1_LPMS_Pos)"), ("PWR_CR2_PLS_LEV0", "(0x0UL << PWR_CR2_PLS_Pos)")),   # LPMS 000 = Stop 0 (p.253); PLS 000 (p.254)
    "DMAMUX_Channel": (("DMAMUX_CxCR_DMAREQ_ID_7", "(0x80UL << DMAMUX_CxCR_DMAREQ_ID_Pos)"),),                          # chỉ có ở header ST (DMAREQ_ID[6:0] có 7 bit; RM0440 p.~ coi bit 7 là dự trữ)
    "SYSCFG": tuple((f"SYSCFG_CFGR1_FPU_IE_{i}", f"(0x1UL << {26 + i}U)") for i in range(6)),                       # FPU_IE[5:0] ở bit 31:26 (RM0440 p.365)
}


def _st_alias_macros(group: str) -> list[tuple[str, str]]:
    """Bí danh tương thích F4 mà header ST giữ lại (GPIO_MODER_MODER8 = GPIO_MODER_MODE8…) và giá trị cổng EXTI của SYSCFG_EXTICRx (RM0440 p.367)."""
    out: list[tuple[str, str]] = []
    if group == "GPIO":
        for n in range(16):
            for suf in ("", "_0", "_1"):
                out += [(f"GPIO_MODER_MODER{n}{suf}", f"GPIO_MODER_MODE{n}{suf}"), (f"GPIO_OSPEEDER_OSPEEDR{n}{suf}", f"GPIO_OSPEEDR_OSPEED{n}{suf}"),
                        (f"GPIO_PUPDR_PUPDR{n}{suf}", f"GPIO_PUPDR_PUPD{n}{suf}")]
            out += [(f"GPIO_OTYPER_OT_{n}", f"GPIO_OTYPER_OT{n}"), (f"GPIO_OTYPER_IDR_{n}", f"GPIO_IDR_ID{n}"), (f"GPIO_OTYPER_ODR_{n}", f"GPIO_ODR_OD{n}"),
                    (f"GPIO_IDR_IDR_{n}", f"GPIO_IDR_ID{n}"), (f"GPIO_ODR_ODR_{n}", f"GPIO_ODR_OD{n}"), (f"GPIO_BSRR_BS_{n}", f"GPIO_BSRR_BS{n}"),
                    (f"GPIO_BSRR_BR_{n}", f"GPIO_BSRR_BR{n}"), (f"GPIO_BRR_BR_{n}", f"GPIO_BRR_BR{n}")]
        out += [(f"GPIO_AFRL_AFRL{n}", f"GPIO_AFRL_AFSEL{n}") for n in range(8)] + [(f"GPIO_AFRH_AFRH{n}", f"GPIO_AFRH_AFSEL{n + 8}") for n in range(8)]
    elif group == "SYSCFG":
        for line in range(16):                                    # EXTI<line> trong EXTICR<line//4+1>: cổng A..F cho mọi dòng, G chỉ dòng 0..9 (như header ST)
            for port, letter in enumerate("ABCDEFG"):
                if letter == "G" and line > 9:
                    continue
                out.append((f"SYSCFG_EXTICR{line // 4 + 1}_EXTI{line}_P{letter}", f"(0x{port << (4 * (line % 4)):08X}U)"))
    return out


_CORE_IRQ = [("NonMaskableInt", -14), ("HardFault", -13), ("MemoryManagement", -12), ("BusFault", -11), ("UsageFault", -10),
             ("SVCall", -5), ("DebugMonitor", -4), ("PendSV", -2), ("SysTick", -1)]


def _group_name(row_group: str | None, per: str) -> str:
    g = _ST_GROUP_OF.get(per) or (row_group or per).upper()
    return re.sub(r"[^A-Za-z0-9_]", "_", g)


@dataclass
class _Reg:
    svd: str
    member: str
    offset: int
    size: int
    fields: list[FieldDef]
    token: str = ""            # token macro nếu khác tên thành viên


@dataclass
class _Unit:
    """Một instance ST: con trỏ kiểu `<group>_TypeDef *` tại `base`, kèm các thanh ghi của nó."""
    instance: str
    db_name: str
    base: int
    group: str
    regs: list[_Reg]


def _load(chip, db_path):
    con = sqlite3.connect(f"file:{db_path or data.default_db()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        pers = con.execute("SELECT name, base_address, group_name FROM peripherals WHERE chip=? ORDER BY base_address, name", (chip,)).fetchall()
        regs = con.execute("SELECT id, peripheral, name, offset, size FROM registers WHERE chip=? ORDER BY peripheral, offset, id", (chip,)).fetchall()
        flds = con.execute("SELECT register_id, name, bit_offset, bit_width FROM fields WHERE chip=? ORDER BY register_id, bit_offset", (chip,)).fetchall()
    finally:
        con.close()
    fl_by_reg: dict[int, list] = {}
    for f in flds:
        fl_by_reg.setdefault(f["register_id"], []).append(f)
    reg_by_per: dict[str, list] = {}
    for r in regs:
        reg_by_per.setdefault(r["peripheral"], []).append(r)
    return pers, reg_by_per, fl_by_reg


def _default_units(pers, reg_by_per, fl_by_reg) -> list[_Unit]:
    units = []
    for p in pers:
        per = p["name"]
        group = _group_name(p["group_name"], per)
        regs: list[_Reg] = []
        for r in reg_by_per.get(per, []):
            n = member_name(per, r["name"], group)
            n = _ST_MEMBER.get((group, n), n)
            regs.append(_Reg(r["name"], n, int(r["offset"]), int(r["size"] or 32) // 8,
                             [FieldDef(f["name"], int(f["bit_offset"]), int(f["bit_width"])) for f in fl_by_reg.get(r["id"], [])]))
        units.append(_Unit(per, per, int(p["base_address"]), group, regs))
    return units


def _apply_carves(units: list[_Unit], anomalies: list[dict]) -> list[_Unit]:
    by_db = {u.db_name: u for u in units}
    out: list[_Unit] = []
    for c in _CARVES:
        for parent in c.parents + c.drop_from:
            u = by_db.get(parent)
            if u is None:
                continue
            for n in c.indices:
                take = [next((r for r in u.regs if r.member == t.format(n=n)), None) for t in c.svd]
                if any(r is None for r in take):
                    anomalies.append({"group": c.group, "kind": "carve", "detail": f"{parent}: registers {[t.format(n=n) for t in c.svd]} not all present"})
                    continue
                if parent in c.drop_from:
                    u.regs = [r for r in u.regs if r not in take]
                    continue
                anchor = take[0].offset
                child_regs = [_Reg(r.svd, name, r.offset - anchor, r.size, [FieldDef(f.name, f.bit_offset, f.bit_width) for f in r.fields],
                                   c.tokens[i] if c.tokens else "") for i, (name, r) in enumerate(zip(c.names, take))]
                out.append(_Unit(c.instance.format(parent=parent, n=n), parent, u.base + anchor, c.group, child_regs))
                u.regs = [r for r in u.regs if r not in take]
    kept = [u for u in units if u.regs or not any(u.db_name in c.parents + c.drop_from for c in _CARVES)]
    return kept + out


def _merge_fields(dst: list[FieldDef], src: list[FieldDef], gname: str, token: str, anomalies: list[dict]) -> None:
    known = {f.name: f for f in dst}
    for f in src:
        k = known.get(f.name)
        if k is None:
            nf = FieldDef(f.name, f.bit_offset, f.bit_width, f.hi)
            dst.append(nf)
            known[f.name] = nf
        elif (k.bit_offset, k.bit_width) != (f.bit_offset, f.bit_width):
            if k.bit_offset == f.bit_offset and f.bit_width > k.bit_width:        # cùng vị trí, rộng hơn (TIM2/5 CNT 32 bit so với 16 bit): lấy rộng nhất như ST
                k.bit_width = f.bit_width
            anomalies.append({"group": gname, "kind": "field_position", "detail": f"{token}.{f.name} differs between instances"})


def build_model(chip: str = CHIP, db_path=None, attrs_path=None) -> HeaderModel:
    if chip != CHIP:
        raise ValueError(f"header_gen supports {CHIP} only (got {chip!r})")
    pers, reg_by_per, fl_by_reg = _load(chip, db_path)
    anomalies: list[dict] = []
    units = [u for u in _default_units(pers, reg_by_per, fl_by_reg)]
    units = _apply_carves(units, anomalies)
    extra_bases = {}
    for macro, dbname in _ST_EXTRA_BASES.items():
        p = next((p for p in pers if p["name"] == dbname), None)
        if p is not None:
            extra_bases[macro] = int(p["base_address"])
    units = [u for u in units if u.db_name not in _ST_DROP_INSTANCE or u.instance != u.db_name]

    # nhóm có xung đột (cùng tên thành viên khác offset, hoặc hai thành viên khác tên chồng nhau) => tách riêng từng instance
    by_group: dict[str, list[_Unit]] = {}
    for u in units:
        by_group.setdefault(u.group, []).append(u)
    for g, us in by_group.items():
        if len(us) < 2:
            continue
        seen_off: dict[str, int] = {}
        conflict = False
        spans: dict[int, str] = {}
        for u in us:
            for r in u.regs:
                if seen_off.setdefault(r.member, r.offset) != r.offset:
                    conflict = True
                if spans.setdefault(r.offset, r.member) != r.member:
                    conflict = True
        if conflict:
            anomalies.append({"group": g, "kind": "split", "detail": f"instances of {g} have incompatible layouts; one struct per instance"})
            for u in us:
                u.group = re.sub(r"[^A-Za-z0-9_]", "_", u.instance.upper())

    groups: dict[str, GroupModel] = {}
    instance_group: dict[str, str] = {}
    for u in units:
        gname = u.group
        g = groups.setdefault(gname, GroupModel(name=gname, type_name=_ST_TYPE_NAME.get(gname, f"{gname}_TypeDef"), prefix=_ST_PREFIX.get(gname, gname)))
        iname = _ST_INSTANCE.get(u.instance, u.instance)
        g.instances.append(Instance(name=iname, base=u.base, type_name=g.type_name))
        instance_group[iname] = gname
        have = {m.name: m for m in g.members}
        mregs = {(r.prefix, r.token): r for r in g.macro_regs}
        for r in u.regs:
            if r.member not in have:
                m = Member(name=r.member, offset=r.offset, size=r.size)
                g.members.append(m)
                have[r.member] = m
            token = r.token or r.member
            prefix = _ST_REG_PREFIX.get((gname, r.member), g.prefix)
            mr = mregs.get((prefix, token))
            if mr is None:
                mr = MacroReg(prefix, token)
                g.macro_regs.append(mr)
                mregs[(prefix, token)] = mr
            _merge_fields(mr.fields, r.fields, gname, token, anomalies)
    used: set = set()
    for alias, target in _ST_INSTANCE_ALIAS.items():
        gname = instance_group.get(target)
        if gname is not None:
            t = next(i for i in groups[gname].instances if i.name == target)
            groups[gname].instances.append(Instance(alias, t.base, t.type_name))
            instance_group[alias] = gname
    for g in groups.values():
        for name, off, _page in _ST_EXTRA_REGS.get(g.name, ()):
            if g.offset_of(name) is None:
                g.members.append(Member(name, off, 4))
                g.macro_regs.append(MacroReg(g.prefix, name))
        g.members.sort(key=lambda m: m.offset)
        for (gname, arr), parts in _ST_ARRAYS.items():
            if gname != g.name:
                continue
            ms = [next((m for m in g.members if m.name == p), None) for p in parts]
            if all(m is not None for m in ms) and all(b.offset == a.offset + a.size for a, b in zip(ms, ms[1:])):
                merged = Member(arr, ms[0].offset, ms[0].size, count=len(ms), parts=tuple((m.name, m.offset) for m in ms))
                g.members = [m for m in g.members if m not in ms] + [merged]
                g.members.sort(key=lambda m: m.offset)
        _apply_field_overlay(g, used)
    anomalies += _unused_overlay_entries(used)
    side = json.loads(Path(attrs_path or data.default_attrs()).read_text(encoding="utf-8"))
    interrupts = side["chips"][chip]["interrupts"]
    return HeaderModel(chip=chip, groups=groups, interrupts=interrupts, anomalies=anomalies, instance_group=instance_group, extra_bases=extra_bases)


def _st_rule_name(prefix: str, token: str, name: str) -> str | None:
    """Họ tên trường đều đặn mà ST đặt khác SVD (quy tắc thay cho bảng dài; vị trí bit khớp DB, test đối chiếu header ST kiểm từng macro)."""
    if prefix == "GPIO":                                          # SVD MODER8 / AFRH8 / IDR8… -> ST MODE8 / AFSEL8 / ID8…
        for reg, pat, repl in _GPIO_ST:
            if token == reg and re.fullmatch(pat, name):
                return re.sub(pat, repl, name)
    elif prefix == "PWR":                                         # SVD PDCRA.PD0 / PUCRA.PU0 (chữ D/U của chữ cái cổng) -> ST PA0
        m = re.fullmatch(r"(?:PDCR|PUCR)([A-G])", token)
        if m and re.fullmatch(r"P[DU]\d+", name):
            return f"P{m.group(1)}{name[2:]}"
    elif prefix == "DMA" and token == "IFCR":                     # IFCR là thanh ghi XOÁ cờ: ST đặt CGIFx/CTCIFx/CHTIFx/CTEIFx (RM0440 DMA_IFCR)
        if re.fullmatch(r"(?:GIF|TCIF|HTIF|TEIF)\d+", name):
            return "C" + name
    elif prefix == "SYSCFG" and token == "SWPR":                  # SVD Page0_WP -> ST PAGE0
        m = re.fullmatch(r"Page(\d+)_WP", name)
        if m:
            return f"PAGE{m.group(1)}"
    elif prefix == "TAMP" and re.fullmatch(r"BKP\d+R", token) and name == "BKP":      # ST: macro mang tên thanh ghi (TAMP_BKP0R_Pos), không có phần trường
        return ""
    elif prefix == "ADC":
        m = re.fullmatch(r"JDR([1-4])", token)
        if m and name == f"JDATA{m.group(1)}":                    # SVD JDATA1..4 -> ST JDATA
            return "JDATA"
        m = re.fullmatch(r"OFR([2-4])", token)
        if m and name.startswith("OFFSET1"):                      # SVD sao chép nhầm OFFSET1 vào OFR2..4 -> ST OFFSET2..4
            return "OFFSET" + m.group(1) + name[len("OFFSET1"):]
    return None


def _apply_field_overlay(g: GroupModel, used: set) -> None:
    """Áp bảng tên ST lên các macro_reg của nhóm; ghi vào `used` mỗi mục đã khớp (mục không khớp = DB đổi/bảng sai ⇒ anomalies)."""
    for mr in g.macro_regs:
        key = f"{mr.prefix}_{mr.token}"
        by_name = {f.name: f for f in mr.fields}
        for name, geo in ST_FIELD_GEOM.get(key, {}).items():
            f = by_name.get(name)
            if f is not None:
                f.bit_offset, f.bit_width = geo[0], geo[1]
                f.hi = tuple(geo[2]) if len(geo) > 2 else ()
                used.add(("geom", key, name))
        for main, sibs in ST_FIELD_FOLD.get(key, {}).items():
            m = by_name.get(main)
            for sib in sibs:
                f = by_name.get(sib)
                if m is None or f is None:
                    continue
                m.hi += tuple(range(f.bit_offset, f.bit_offset + f.bit_width))
                mr.fields.remove(f)
                used.add(("fold", key, sib))
        for name, stem in ST_FIELD_SPLIT.get(key, {}).items():
            f = by_name.get(name)
            if f is not None:
                mr.fields.remove(f)
                mr.fields += [FieldDef(f"{stem}{i}", f.bit_offset + i, 1) for i in range(f.bit_width)]
                used.add(("split", key, name))
        for name in ST_FIELD_DROP.get(key, ()):
            if any(f.name == name for f in mr.fields):
                mr.fields = [f for f in mr.fields if f.name != name]
                used.add(("drop", key, name))
        ren = ST_FIELD_RENAME.get(key, {})
        for f in mr.fields:
            ruled = _st_rule_name(mr.prefix, mr.token, f.name)
            if f.name in ren:
                used.add(("rename", key, f.name))
            f.name = ren.get(f.name, ruled if ruled is not None else f.name)
        for name, off, width, *hi in ST_FIELD_ADD.get(key, ()):
            if not any(f.name == name for f in mr.fields):
                mr.fields.append(FieldDef(name, off, width, tuple(hi[0]) if hi else ()))
            used.add(("add", key, name))


def _unused_overlay_entries(used: set) -> list[dict]:
    out = []
    tables = {"geom": ST_FIELD_GEOM, "fold": ST_FIELD_FOLD, "drop": ST_FIELD_DROP, "rename": ST_FIELD_RENAME, "add": ST_FIELD_ADD, "split": ST_FIELD_SPLIT}
    for kind, table in tables.items():
        for key, entry in table.items():
            if kind == "add":
                names = [e[0] for e in entry]
            elif kind == "drop":
                names = list(entry)
            elif kind == "fold":
                names = [s for sibs in entry.values() for s in sibs]
            else:
                names = list(entry)
            for n in names:
                if (kind, key, n) not in used:
                    out.append({"group": key.split("_")[0], "kind": "overlay_unmatched", "detail": f"{kind} {key}.{n}: not applicable to the register database"})
    return out


# ------------------------------------------------------------------------------------------ render
def _reserved(k: int, gap: int) -> str:
    return f"  uint32_t RESERVED{k}[{gap // 4}];" if gap % 4 == 0 else f"  uint8_t RESERVED{k}[{gap}];"


def _struct(g: GroupModel) -> str:
    lines = [f"typedef struct", "{"]
    pos, k = 0, 0
    for m in g.members:
        if m.offset > pos:
            lines.append(_reserved(k, m.offset - pos))
            k += 1
            pos = m.offset
        decl = f"{m.name}[{m.count}]" if m.count > 1 else m.name
        lines.append(f"  __IO {_CTYPE[m.size * 8]} {decl};".ljust(40) + f"/* Address offset: 0x{m.offset:02X} */")
        pos = m.offset + m.size * m.count
    lines.append(f"}} {g.type_name};")
    return "\n".join(lines)


def _field_macros(g: GroupModel) -> list[tuple[str, str]]:
    """[(tên macro, thân)] theo thứ tự xuất hiện."""
    out: list[tuple[str, str]] = []
    done: set[str] = set()

    def put(name: str, body: str) -> None:
        if name not in done:
            done.add(name)
            out.append((name, body))

    def emit(base: str, off: int, width: int, hi: tuple = ()) -> None:
        mask = ((1 << width) - 1) | sum(1 << (b - off) for b in hi)
        put(f"{base}_Pos", f"({off}U)")
        put(f"{base}_Msk", f"(0x{mask:X}UL << {base}_Pos)")
        put(base, f"{base}_Msk")
        eff = width + len(hi)
        if (2 <= eff <= ST_BITS_MAX_WIDTH and base not in ST_BITS_OFF) or base in ST_BITS_ON:
            for b in range(width):
                put(f"{base}_{b}", f"(0x1UL << {off + b}U)")
            for j, b in enumerate(hi):
                put(f"{base}_{width + j}", f"(0x1UL << {b}U)")

    for mr in g.macro_regs:
        for f in mr.fields:
            base = f"{mr.prefix}_{mr.token}" + (f"_{f.name}" if f.name else "")
            emit(base, f.bit_offset, f.bit_width, f.hi)
    for grp, member, fld, values in VALUE_MACROS:
        if grp != g.name:
            continue
        for suffix, v in values:
            put(f"{g.prefix}_{member}_{fld}_{suffix}", f"({v}UL << {g.prefix}_{member}_{fld}_Pos)")
    for name, body in ST_EXTRA_MACROS.get(g.name, ()):
        put(name, body)
    for name, body in _st_alias_macros(g.name):
        put(name, body)
    return out


def _render_group_block(groups: list[GroupModel]) -> list[str]:
    hdr: list[str] = ["#ifdef HWMODEL_ANALYZE", "/* analysis mode: struct layouts live in the Python model; pycparser only needs the type names */"]
    for g in groups:
        hdr.append(f"typedef struct {g.type_name}_ {g.type_name};")
    hdr.append("#else")
    for g in groups:
        hdr += [_struct(g), ""]
    hdr.append("#endif /* HWMODEL_ANALYZE */")
    hdr.append("")
    for g in groups:
        for inst in sorted(g.instances, key=lambda i: (i.base, i.name)):
            bname = _ST_BASE_NAME.get(inst.name, f"{inst.name}_BASE")
            hdr.append(f"#define {bname}".ljust(40) + f"0x{inst.base:08X}UL")
            hdr.append(f"#define {inst.name}".ljust(40) + f"(({inst.type_name} *) {bname})")
    return hdr


def _feature_macros(model: HeaderModel) -> list[tuple[str, str]]:
    """Cờ tính năng/đếm của header ST (HAL dùng), dẫn xuất từ chính DB: `ADC_MULTIMODE_SUPPORT` nếu khối ADC common có CCR.DUAL, RTC_BACKUP_NB = số BKPxR…"""
    def fields(group: str, token: str) -> set[str]:
        g = model.groups.get(group)
        return {f.name for mr in (g.macro_regs if g else []) if mr.token == token for f in mr.fields}

    out: list[tuple[str, str]] = []
    tamp = model.groups.get("TAMP")
    n_bkp = sum(1 for m in (tamp.members if tamp else []) if re.fullmatch(r"BKP\d+R", m.name))
    cr1 = fields("TAMP", "CR1")
    n_tamp, n_itamp = sum(1 for f in cr1 if re.fullmatch(r"TAMP\dE", f)), sum(1 for f in cr1 if re.fullmatch(r"ITAMP\dE", f))
    if "ITAMP6E" in cr1:
        out.append(("RTC_TAMP_INT_6_SUPPORT", ""))
    if n_itamp:
        out.append(("RTC_TAMP_INT_NB", f"{n_itamp}u"))
    if n_tamp:
        out.append(("RTC_TAMP_NB", f"{n_tamp}u"))
    if n_bkp:
        out.append(("RTC_BACKUP_NB", f"{n_bkp}u"))
    if "DUAL" in fields("ADC_Common", "CCR"):
        out.append(("ADC_MULTIMODE_SUPPORT", ""))
    if "EN2" in fields("DAC", "CR"):
        out.append(("DAC_CHANNEL2_SUPPORT", ""))
    if "HSI48ON" in fields("RCC", "CRRCR"):
        out.append(("RCC_HSI48_SUPPORT", ""))
    if "PLLPDIV" in fields("RCC", "PLLCFGR"):
        out.append(("RCC_PLLP_DIV_2_31_SUPPORT", ""))
    if "I2SCFGR" in {mr.token for mr in (model.groups["SPI"].macro_regs if "SPI" in model.groups else [])}:
        out.append(("SPI_I2S_SUPPORT", ""))
    return out


def render(model: HeaderModel) -> dict[str, str]:
    groups = sorted(model.groups.values(), key=lambda g: g.name)
    device = [g for g in groups if not g.core]
    core = [g for g in groups if g.core]
    hdr: list[str] = ["/* Generated by ingestion/header_gen.py from the P1 register database. DO NOT EDIT. STM32G474 (CMSIS-style). */",
                      "#ifndef STM32G474XX_H", "#define STM32G474XX_H", "",
                      "#define __CM4_REV 0x0001U", "#define __MPU_PRESENT 1U", "#define __NVIC_PRIO_BITS 4U", "#define __Vendor_SysTickConfig 0U",
                      "#define __FPU_PRESENT 1U", "",
                      '#include "core_cm4.h"', '#include "system_stm32g4xx.h"', "#include <stdint.h>", "",
                      "typedef enum {"]
    for name, n in _CORE_IRQ:
        hdr.append(f"  {name}_IRQn = {n},")
    for name, n in sorted(model.interrupts.items(), key=lambda kv: (kv[1], kv[0])):
        hdr.append(f"  {name}_IRQn = {n},")
    hdr += ["} IRQn_Type;", ""]
    hdr += [f"#define {n}".ljust(40) + b for n, b in _ST_MEMORY_MAP] + [""]
    hdr += _render_group_block(device)
    for macro, base in sorted(model.extra_bases.items()):
        hdr.append(f"#define {macro}".ljust(40) + f"0x{base:08X}UL")
    hdr += [f"#define {n} {b}".rstrip() for n, b in _feature_macros(model)]
    hdr.append("")
    for g in device:
        macros = _field_macros(g)
        if macros:
            hdr.append(f"/* ---- {g.name} ---- */")
            hdr += [(f"#define {n}".ljust(52) + b).rstrip() for n, b in macros]
            hdr.append("")
    hdr += ["#endif /* STM32G474XX_H */", ""]
    corehdr: list[str] = ["/* core_cm4.h - stand-in for ARM CMSIS-Core: Cortex-M4 core peripherals (NVIC, SCB, SysTick, MPU, FPU) with the SVD names. NOT checked against ARM's header. */",
                          "#ifndef CORE_CM4_H_", "#define CORE_CM4_H_", "", "#include <stdint.h>", "#define __I  volatile const", "#define __O  volatile", "#define __IO volatile", ""]
    corehdr += _render_group_block(core)
    corehdr.append("")
    for g in core:
        macros = _field_macros(g)
        if macros:
            corehdr.append(f"/* ---- {g.name} ---- */")
            corehdr += [(f"#define {n}".ljust(52) + b).rstrip() for n, b in macros]
            corehdr.append("")
    corehdr += ["#endif /* CORE_CM4_H_ */", ""]
    main = ["/* stm32g4xx.h - register access helpers (as in ST's stm32g4xx.h) and minimal CMSIS core stubs */",
            "#ifndef STM32G4XX_H", "#define STM32G4XX_H", "", "#include <stdint.h>", "#define STM32G474xx", '#include "stm32g474xx.h"', "",
            "#define SET_BIT(REG, BIT)     ((REG) |= (BIT))", "#define CLEAR_BIT(REG, BIT)   ((REG) &= ~(BIT))",
            "#define READ_BIT(REG, BIT)    ((REG) & (BIT))", "#define CLEAR_REG(REG)        ((REG) = (0x0))",
            "#define WRITE_REG(REG, VAL)   ((REG) = (VAL))", "#define READ_REG(REG)         ((REG))",
            "#define MODIFY_REG(REG, CLEARMASK, SETMASK)  WRITE_REG((REG), (((READ_REG(REG)) & (~(CLEARMASK))) | (SETMASK)))", "",
            "#define __NOP()  ((void)0)", "#define __DSB()  ((void)0)", "#define __ISB()  ((void)0)", "#define __DMB()  ((void)0)",
            "#define __WFI()  ((void)0)", "#define __WFE()  ((void)0)", "#define __SEV()  ((void)0)",
            "#define __enable_irq()   ((void)0)", "#define __disable_irq()  ((void)0)", "",
            '#include "system_stm32g4xx.h"', "",
            "void NVIC_EnableIRQ(IRQn_Type IRQn);", "void NVIC_DisableIRQ(IRQn_Type IRQn);", "void NVIC_SetPriority(IRQn_Type IRQn, uint32_t priority);",
            "void NVIC_ClearPendingIRQ(IRQn_Type IRQn);", "void NVIC_SetPendingIRQ(IRQn_Type IRQn);", "uint32_t NVIC_GetPendingIRQ(IRQn_Type IRQn);",
            "void NVIC_SystemReset(void);", "uint32_t SysTick_Config(uint32_t ticks);", "",
            "#endif /* STM32G4XX_H */", ""]
    std = {
        "include/stdint.h": ("#ifndef _HW_STDINT_H\n#define _HW_STDINT_H\ntypedef signed char int8_t;\ntypedef unsigned char uint8_t;\n"
                             "typedef short int16_t;\ntypedef unsigned short uint16_t;\ntypedef int int32_t;\ntypedef unsigned int uint32_t;\n"
                             "typedef long long int64_t;\ntypedef unsigned long long uint64_t;\ntypedef int intptr_t;\ntypedef unsigned int uintptr_t;\n"
                             "#define INT8_MAX 127\n#define UINT8_MAX 255U\n#define INT16_MAX 32767\n#define UINT16_MAX 65535U\n"
                             "#define INT32_MAX 2147483647\n#define UINT32_MAX 4294967295U\n#endif\n"),
        "include/stdbool.h": "#ifndef _HW_STDBOOL_H\n#define _HW_STDBOOL_H\n#define bool _Bool\n#define true 1\n#define false 0\n#endif\n",
        "include/stddef.h": ("#ifndef _HW_STDDEF_H\n#define _HW_STDDEF_H\ntypedef unsigned int size_t;\ntypedef int ptrdiff_t;\n"
                             "#define NULL ((void *)0)\n#define offsetof(t, m) __builtin_offsetof(t, m)\n#endif\n"),
        "include/string.h": ("#ifndef _HW_STRING_H\n#define _HW_STRING_H\n#include <stddef.h>\nvoid *memset(void *s, int c, size_t n);\n"
                             "void *memcpy(void *d, const void *s, size_t n);\nsize_t strlen(const char *s);\n#endif\n"),
        "include/stdlib.h": "#ifndef _HW_STDLIB_H\n#define _HW_STDLIB_H\n#include <stddef.h>\n#endif\n",
        "include/stdio.h": "#ifndef _HW_STDIO_H\n#define _HW_STDIO_H\nint printf(const char *fmt, ...);\nint puts(const char *s);\n#endif\n",
        "include/limits.h": ("#ifndef _HW_LIMITS_H\n#define _HW_LIMITS_H\n#define CHAR_BIT 8\n#define INT_MAX 2147483647\n"
                            "#define UINT_MAX 4294967295U\n#endif\n"),
    }
    # tên header CMSIS thường được #include trong code bare-metal; chỉ chuyển tiếp sang stm32g4xx.h
    thin = {"system_stm32g4xx.h": ("#ifndef SYSTEM_STM32G4XX_H\n#define SYSTEM_STM32G4XX_H\n#include <stdint.h>\nextern uint32_t SystemCoreClock;\n"
                                  "void SystemInit(void);\nvoid SystemCoreClockUpdate(void);\n#endif\n")}
    return {"stm32g474xx.h": "\n".join(hdr), "stm32g4xx.h": "\n".join(main), "core_cm4.h": "\n".join(corehdr), **thin, **std}


def checksum(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0" + files[name].encode() + b"\0")
    return h.hexdigest()


def write(out_dir, chip: str = CHIP, db_path=None) -> dict[str, str]:
    files = render(build_model(chip, db_path))
    out = Path(out_dir)
    for name, text in files.items():
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return files


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    files = write(a.out)
    print(f"{a.out}: {len(files)} files, sha256 {checksum(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
