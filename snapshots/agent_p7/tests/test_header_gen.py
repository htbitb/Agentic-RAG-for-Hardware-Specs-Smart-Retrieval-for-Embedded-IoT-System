"""ingestion.header_gen: header CMSIS-style sinh từ DB (SVD + giá trị manual) cho STM32G474.

Offset kỳ vọng: số in trong bản đồ thanh ghi của RM0440 (số trang ở comment). Tên macro theo quy ước của stm32g474xx.h (ST CMSIS):
`<GROUP>_<REG>_<FIELD>_Pos / _Msk / <GROUP>_<REG>_<FIELD>`, và `_0.._n` cho từng bit của trường nhiều bit.
"""
import re
import sqlite3

import pytest

from hwmodel import data
from ingestion import header_gen


@pytest.fixture(scope="module")
def model():
    return header_gen.build_model("stm32g474")


@pytest.fixture(scope="module")
def files(model):
    return header_gen.render(model)


@pytest.fixture(scope="module")
def text(files):
    return files["stm32g474xx.h"]


# ------------------------------------------------------------------ mô hình struct
@pytest.mark.parametrize("group,member,offset", [
    ("GPIO", "MODER", 0x00), ("GPIO", "OTYPER", 0x04), ("GPIO", "IDR", 0x10), ("GPIO", "BSRR", 0x18), ("GPIO", "AFRL", 0x20),
    ("GPIO", "AFRH", 0x24), ("GPIO", "BRR", 0x28),                                  # RM p.355–363 (GPIO register map)
    ("TIM", "CR1", 0x00), ("TIM", "EGR", 0x14), ("TIM", "CCMR1", 0x18), ("TIM", "CCER", 0x20), ("TIM", "PSC", 0x28),
    ("TIM", "ARR", 0x2C), ("TIM", "CCR1", 0x34), ("TIM", "BDTR", 0x44),             # RM p.1262–1270
    ("RCC", "CR", 0x00), ("RCC", "CFGR", 0x08), ("RCC", "PLLCFGR", 0x0C), ("RCC", "AHB2ENR", 0x4C), ("RCC", "APB1ENR1", 0x58),
    ("RCC", "APB2ENR", 0x60), ("RCC", "CCIPR", 0x88),                                # RM p.287–324
    ("USART", "CR1", 0x00), ("USART", "BRR", 0x0C), ("USART", "ISR", 0x1C), ("USART", "TDR", 0x28), ("USART", "PRESC", 0x2C),   # p.1741–1766
    ("I2C", "CR1", 0x00), ("I2C", "TIMINGR", 0x10), ("I2C", "ISR", 0x18), ("I2C", "TXDR", 0x28),                       # p.1672
    ("FLASH", "ACR", 0x00), ("PWR", "CR1", 0x00), ("PWR", "CR5", 0x80),             # p.130, p.267
])
def test_member_offsets_follow_the_manual(model, group, member, offset):
    g = model.groups[group]
    assert g.offset_of(member) == offset


def test_ccmr_input_and_output_views_are_one_member_with_both_field_sets(model):
    names = {f.name for f in model.groups["TIM"].fields["CCMR1"]}
    assert {"OC1M", "OC1PE", "CC1S", "IC1F", "IC1PSC"} <= names


def _reachable_addresses(model):
    """Địa chỉ mà `INSTANCE->MEMBER` (kể cả phần tử mảng AFR[k], EXTICR[k] và thanh ghi gộp) trỏ tới, theo mô hình header."""
    out = set()
    for g in model.groups.values():
        for inst in g.instances:
            for m in g.members:
                for k in range(m.count):
                    out.add(inst.base + m.offset + k * m.size)
                out.update(inst.base + off for _name, off in m.parts)
    return out


def test_every_db_register_is_reachable_at_the_right_address(model):
    con = sqlite3.connect(f"file:{data.default_db()}?mode=ro", uri=True)
    rows = con.execute("SELECT peripheral, name, address FROM registers WHERE chip='stm32g474'").fetchall()
    con.close()
    reach = _reachable_addresses(model)
    missing = [(per, name) for per, name, addr in rows if addr not in reach]
    # ngoại lệ DUY NHẤT (hiện vật của SVD, ST không có chúng): (1) khối "FDCAN" ở 0x4000A400 là SRAM tin nhắn — ST chỉ có macro SRAMCAN_BASE;
    # (2) CKDIV của FDCAN2/FDCAN3 (SVD sao chép thanh ghi cấu hình vào từng instance; chỉ có MỘT FDCAN_CKDIV ở FDCAN_CONFIG = 0x40006500)
    allowed = {("FDCAN2", "CKDIV"), ("FDCAN3", "CKDIV")}
    assert {(per, name) for per, name in missing if per != "FDCAN"} == allowed, missing[:10]
    assert model.extra_bases["SRAMCAN_BASE"] == 0x4000_A400


def test_group_of_resolves_st_instance_names(model):
    assert model.group_of("TIM1") == "TIM" and model.group_of("ADC1") == "ADC" and model.group_of("ADC12_COMMON") == "ADC_Common"
    assert model.group_of("DMA1_Channel3") == "DMA_Channel" and model.group_of("COMP5") == "COMP" and model.group_of("USB") == "USB"


def test_instances_map_to_the_manual_base_addresses(model):
    inst = {i.name: i for g in model.groups.values() for i in g.instances}
    assert inst["TIM1"].base == 0x4001_2C00 and inst["TIM1"].type_name == "TIM_TypeDef"       # p.85
    assert inst["GPIOA"].base == 0x4800_0000 and inst["GPIOA"].type_name == "GPIO_TypeDef"    # p.84
    assert inst["USART1"].base == 0x4001_3800 and inst["I2C1"].base == 0x4000_5400            # p.85, p.86
    assert inst["RCC"].base == 0x4002_1000 and inst["UART4"].type_name == "USART_TypeDef"


def test_no_two_members_of_a_struct_overlap(model):
    for gname, g in model.groups.items():
        spans = sorted((m.offset, m.offset + m.size * m.count, m.name) for m in g.members)
        for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
            assert a1 <= b0, f"{gname}: {an} [{a0:#x},{a1:#x}) overlaps {bn} [{b0:#x},{b1:#x})"


def test_layout_anomalies_are_reported_not_hidden(model):
    # nhóm có bố cục không tương thích được tách theo instance và GHI vào anomalies (HRTIM, ADC, SCB, NVIC, FPU); nhóm dùng trong C3 thì không
    assert isinstance(model.anomalies, list)
    splits = {a["group"] for a in model.anomalies if a["kind"] == "split"}
    assert splits.isdisjoint({"TIM", "GPIO", "RCC", "USART", "I2C", "FLASH", "PWR", "SPI", "DMA", "ADC", "DAC", "COMP", "OPAMP"}), splits
    # duy nhất khác biệt trong nhóm TIM: độ rộng REP của RCR (TIM1/8/20: REP[15:0] p.1264; TIM15–17: REP[7:0] p.1476) — vô hại, giữ bản đầu
    assert {a["detail"] for a in model.anomalies if a["group"] == "TIM"} == {"RCR.REP differs between instances"}


# ------------------------------------------------------------------ macro
def test_instance_and_base_macros(text):
    assert re.search(r"#define\s+TIM1_BASE\s+0x40012C00UL", text)
    assert re.search(r"#define\s+TIM1\s+\(\(TIM_TypeDef \*\)\s*TIM1_BASE\)", text)
    assert re.search(r"#define\s+GPIOA\s+\(\(GPIO_TypeDef \*\)\s*GPIOA_BASE\)", text)
    assert re.search(r"#define\s+UART4\s+\(\(USART_TypeDef \*\)\s*UART4_BASE\)", text)


@pytest.mark.parametrize("name,pos", [
    ("RCC_APB2ENR_TIM1EN", 11), ("RCC_AHB2ENR_GPIOAEN", 0), ("TIM_CR1_CEN", 0), ("TIM_BDTR_MOE", 15), ("TIM_CCER_CC1E", 0),
    ("TIM_CCMR1_OC1PE", 3), ("TIM_EGR_UG", 0), ("USART_CR1_UE", 0), ("USART_CR1_TE", 3), ("USART_CR1_OVER8", 15),
    ("I2C_CR1_PE", 0), ("RCC_CR_PLLON", 24), ("RCC_CR_PLLRDY", 25), ("RCC_PLLCFGR_PLLREN", 24), ("PWR_CR5_R1MODE", 8),
])
def test_single_bit_field_macros(text, name, pos):
    assert re.search(rf"#define\s+{name}_Pos\s+\({pos}U\)", text), name
    assert re.search(rf"#define\s+{name}_Msk\s+\(0x1UL << {name}_Pos\)", text), name
    assert re.search(rf"#define\s+{name}\s+{name}_Msk\b", text), name


@pytest.mark.parametrize("name,pos,width", [
    ("TIM_CR1_CMS", 5, 2), ("RCC_CFGR_HPRE", 4, 4), ("RCC_CFGR_PPRE2", 11, 3), ("RCC_PLLCFGR_PLLN", 8, 7),
    ("RCC_PLLCFGR_PLLR", 25, 2), ("PWR_CR1_VOS", 9, 2), ("GPIO_MODER_MODE8", 16, 2), ("GPIO_AFRH_AFSEL8", 0, 4),
])
def test_multi_bit_field_macros_have_pos_msk_and_per_bit_names(text, name, pos, width):
    # ST có X_0..X_{w-1} cho các trường này (stm32g474xx.h; PLLN 7 bit nằm trong ngoại lệ ST_BITS_ON)
    assert re.search(rf"#define\s+{name}_Pos\s+\({pos}U\)", text), name
    assert re.search(rf"#define\s+{name}_Msk\s+\(0x{(1 << width) - 1:X}UL << {name}_Pos\)", text), name
    for i in range(width):
        assert re.search(rf"#define\s+{name}_{i}\s+\(0x1UL << {pos + i}U\)", text), f"{name}_{i}"
    assert not re.search(rf"#define\s+{name}_{width}\b", text)


@pytest.mark.parametrize("name,pos,width", [("I2C_TIMINGR_PRESC", 28, 4), ("I2C_TIMINGR_SCLL", 0, 8), ("FLASH_ACR_LATENCY", 0, 4), ("CRC_DR_DR", 0, 32), ("IWDG_RLR_RL", 0, 12)])
def test_multi_bit_fields_without_per_bit_names_in_the_st_header_have_none_here(text, name, pos, width):
    # ST không định nghĩa X_0.. cho các trường này (FLASH dùng FLASH_ACR_LATENCY_nWS thay thế); sinh ra sẽ thành macro mà ST không có
    assert re.search(rf"#define\s+{name}_Pos\s+\({pos}U\)", text), name
    assert re.search(rf"#define\s+{name}_Msk\s+\(0x{(1 << width) - 1:X}UL << {name}_Pos\)", text), name
    assert not re.search(rf"#define\s+{name}_0\b", text), name


def test_four_bit_output_compare_mode_fields_follow_the_st_header(text):
    # RM0440 p.1253: OC1M[3:0] = bit 16 (OC1M[3]) + bits 6:4. Header ST (dòng 15134–15140): TIM_CCMR1_OC1M_Msk = (0x1007UL << TIM_CCMR1_OC1M_Pos),
    # _0.._2 là từng bit thấp, _3 = (0x1000UL << Pos) = bit 16; KHÔNG có TIM_CCMR1_OC1M_3_Pos/_Msk
    assert re.search(r"#define\s+TIM_CCMR1_OC1M_Pos\s+\(4U\)", text)
    assert re.search(r"#define\s+TIM_CCMR1_OC1M_Msk\s+\(0x1007UL << TIM_CCMR1_OC1M_Pos\)", text)
    for i, bit in enumerate((4, 5, 6)):
        assert re.search(rf"#define\s+TIM_CCMR1_OC1M_{i}\s+\(0x1UL << {bit}U\)", text)
    assert re.search(r"#define\s+TIM_CCMR1_OC1M_3\s+\(0x1UL << 16U\)", text)
    assert not re.search(r"TIM_CCMR1_OC1M_3_(Pos|Msk)", text)
    assert re.search(r"#define\s+TIM_CCMR2_OC4M_Msk\s+\(0x1007UL << TIM_CCMR2_OC4M_Pos\)", text)      # bit 24 và 14:12: 0x1007 << 12
    assert re.search(r"#define\s+TIM_SMCR_SMS_Msk\s+\(0x10007UL << TIM_SMCR_SMS_Pos\)", text)          # SMS[3] ở bit 16, SMS[2:0] ở bit 2:0
    assert re.search(r"#define\s+TIM_SMCR_TS_Msk\s+\(0x30007UL << TIM_SMCR_TS_Pos\)", text)            # TS[4:0]: bit 6:4 và 21:20
    assert not re.search(r"TIM_CCMR1_OC1M_3_Pos|TIM_SMCR_SMS_3_Pos", text)


def test_split_usart_cr1_fields_also_have_the_combined_st_macros(text):
    # Header ST giữ cả macro gộp lẫn macro thành phần: USART_CR1_M = M0 (bit 12) | M1 (bit 28), DEDT/DEAT 5 bit (RM0440 USART_CR1, p.1767–1768)
    assert re.search(r"#define\s+USART_CR1_M_Pos\s+\(12U\)", text)
    assert re.search(r"#define\s+USART_CR1_M_Msk\s+\(0x10001UL << USART_CR1_M_Pos\)", text)
    assert re.search(r"#define\s+USART_CR1_M\s+USART_CR1_M_Msk", text)
    assert re.search(r"#define\s+USART_CR1_M0\s+USART_CR1_M0_Msk", text) and re.search(r"#define\s+USART_CR1_M1_Pos\s+\(28U\)", text)
    assert re.search(r"#define\s+USART_CR1_DEDT_Pos\s+\(16U\)", text) and re.search(r"#define\s+USART_CR1_DEDT_Msk\s+\(0x1FUL << USART_CR1_DEDT_Pos\)", text)
    assert re.search(r"#define\s+USART_CR1_DEAT_Pos\s+\(21U\)", text) and re.search(r"#define\s+USART_CR1_DEAT_Msk\s+\(0x1FUL << USART_CR1_DEAT_Pos\)", text)


@pytest.mark.parametrize("name,pos", [
    ("GPIO_MODER_MODE8", 16), ("GPIO_MODER_MODE0", 0), ("GPIO_MODER_MODE15", 30), ("GPIO_OTYPER_OT8", 8), ("GPIO_OSPEEDR_OSPEED8", 16),
    ("GPIO_PUPDR_PUPD8", 16), ("GPIO_AFRH_AFSEL8", 0), ("GPIO_AFRH_AFSEL9", 4), ("GPIO_AFRL_AFSEL7", 28), ("GPIO_BSRR_BS8", 8),
    ("GPIO_BSRR_BR8", 24), ("GPIO_IDR_ID8", 8), ("GPIO_ODR_OD8", 8),
])
def test_gpio_field_names_follow_the_st_convention_not_the_svd_names(text, name, pos):
    # SVD gọi các trường này MODER8 / AFRH8 / ...; header ST gọi MODE8 / AFSEL8 / OT8 / PUPD8 — người viết code dựa vào tên ST
    assert re.search(rf"#define\s+{name}_Pos\s+\({pos}U\)", text), name


def test_f4_style_gpio_names_are_plain_compatibility_aliases_like_in_the_st_header(text):
    # stm32g474xx.h giữ tên kiểu F4 dưới dạng BÍ DANH (dòng ~5941: GPIO_MODER_MODER0 = GPIO_MODER_MODE0), không có _Pos/_Msk riêng
    assert re.search(r"#define\s+GPIO_MODER_MODER8\s+GPIO_MODER_MODE8\b", text)
    assert re.search(r"#define\s+GPIO_MODER_MODER8_1\s+GPIO_MODER_MODE8_1\b", text)
    assert re.search(r"#define\s+GPIO_AFRH_AFRH0\s+GPIO_AFRH_AFSEL8\b", text)
    assert re.search(r"#define\s+GPIO_BSRR_BS_3\s+GPIO_BSRR_BS3\b", text) and re.search(r"#define\s+GPIO_IDR_IDR_3\s+GPIO_IDR_ID3\b", text)
    assert not re.search(r"GPIO_MODER_MODER8_(Pos|Msk)\b", text) and not re.search(r"GPIO_AFRH_AFRH8\b", text)


def test_gpio_afr_is_an_array_without_afrl_afrh_members(text, model):
    # ST: `__IO uint32_t AFR[2]` (không có AFRL/AFRH rời); mô hình vẫn tra được offset của AFRL/AFRH (thanh ghi DB) cho codeparse
    assert re.search(r"__IO uint32_t AFR\[2\]", text)
    assert not re.search(r"\bAFRL;|\bAFRH;", text)
    assert model.groups["GPIO"].offset_of("AFR") == 0x20 and model.groups["GPIO"].offset_of("AFRL") == 0x20 and model.groups["GPIO"].offset_of("AFRH") == 0x24
    assert re.search(r"__IO uint32_t EXTICR\[4\]", text) and model.groups["SYSCFG"].offset_of("EXTICR") == 0x08


@pytest.mark.parametrize("name,expr", [
    ("FLASH_ACR_LATENCY_4WS", "(4UL << FLASH_ACR_LATENCY_Pos)"), ("RCC_CFGR_SW_PLL", "(3UL << RCC_CFGR_SW_Pos)"),
    ("RCC_CFGR_SW_HSI", "(1UL << RCC_CFGR_SW_Pos)"), ("RCC_CFGR_SWS_PLL", "(3UL << RCC_CFGR_SWS_Pos)"),
    ("RCC_CFGR_HPRE_DIV2", "(8UL << RCC_CFGR_HPRE_Pos)"), ("RCC_CFGR_HPRE_DIV1", "(0UL << RCC_CFGR_HPRE_Pos)"),
    ("RCC_CFGR_PPRE1_DIV2", "(4UL << RCC_CFGR_PPRE1_Pos)"), ("RCC_CFGR_PPRE2_DIV16", "(7UL << RCC_CFGR_PPRE2_Pos)"),
])
def test_curated_st_value_macros(text, name, expr):
    # giá trị theo RM0440 p.289–293 (CFGR/PLLCFGR) và p.130 (FLASH_ACR); tên theo stm32g4xx header của ST
    assert re.search(rf"#define\s+{re.escape(name)}\s+{re.escape(expr)}", text), name


def test_pll_source_choices_are_field_macros_in_the_st_header(text):
    # stm32g474xx.h: RCC_PLLCFGR_PLLSRC_HSI = bit 1 (giá trị 2), RCC_PLLCFGR_PLLSRC_HSE = bits 1:0 (giá trị 3) — định nghĩa kiểu trường, có _Pos/_Msk (RM0440 p.293)
    assert re.search(r"#define\s+RCC_PLLCFGR_PLLSRC_HSI_Pos\s+\(1U\)", text) and re.search(r"#define\s+RCC_PLLCFGR_PLLSRC_HSI_Msk\s+\(0x1UL << RCC_PLLCFGR_PLLSRC_HSI_Pos\)", text)
    assert re.search(r"#define\s+RCC_PLLCFGR_PLLSRC_HSE_Pos\s+\(0U\)", text) and re.search(r"#define\s+RCC_PLLCFGR_PLLSRC_HSE_Msk\s+\(0x3UL << RCC_PLLCFGR_PLLSRC_HSE_Pos\)", text)


@pytest.mark.parametrize("name,pos", [
    ("USART_ISR_RXNE_RXFNE", 5), ("USART_ISR_TXE_TXFNF", 7), ("USART_CR1_RXNEIE_RXFNEIE", 5), ("USART_CR1_TXEIE_TXFNFIE", 7),
    ("USART_ISR_RXNE", 5), ("USART_ISR_TXE", 7), ("USART_CR1_RXNEIE", 5)])
def test_usart_fifo_aware_names_of_the_st_header_exist_next_to_the_svd_names(text, name, pos):
    # RM0440 p.1748 (ISR: RXNE/RXFNE bit 5, TXE/TXFNF bit 7), p.1743 (CR1: RXNEIE/RXFNEIE bit 5, TXEIE/TXFNFIE bit 7)
    assert re.search(rf"#define\s+{name}_Pos\s+\({pos}U\)", text), name


def test_register_access_helper_macros_are_defined_like_stm32g4xx_h(files):
    h = files["stm32g4xx.h"]
    for m in ("SET_BIT", "CLEAR_BIT", "READ_BIT", "CLEAR_REG", "WRITE_REG", "READ_REG", "MODIFY_REG"):
        assert re.search(rf"#define\s+{m}\(", h), m


def test_irq_numbers_follow_the_vector_table(text):
    # RM0440 Table 100 p.438: TIM1_BRK/TIM15 = 24, TIM1_UP/TIM16 = 25, TIM2 = 28, I2C1_EV = 31, USART1 = 37; Cortex-M4: HardFault -13, SysTick -1
    for name, n in (("TIM1_BRK_TIM15", 24), ("TIM1_UP_TIM16", 25), ("TIM2", 28), ("I2C1_EV", 31), ("USART1", 37)):
        assert re.search(rf"\b{name}_IRQn\s*=\s*{n}\b", text), name
    assert re.search(r"\bHardFault_IRQn\s*=\s*-13\b", text) and re.search(r"\bSysTick_IRQn\s*=\s*-1\b", text)


def test_analyze_mode_hides_the_struct_definitions(text):
    assert "#ifdef HWMODEL_ANALYZE" in text
    assert re.search(r"typedef struct GPIO_TypeDef_ GPIO_TypeDef;", text)


def test_output_is_deterministic_and_has_a_checksum(model):
    a, b = header_gen.render(model), header_gen.render(header_gen.build_model("stm32g474"))
    assert a == b
    assert re.fullmatch(r"[0-9a-f]{64}", header_gen.checksum(a))


def test_other_chips_are_not_supported():
    with pytest.raises(ValueError, match="stm32g474"):
        header_gen.build_model("esp32")


def test_write_creates_a_self_contained_include_dir(tmp_path):
    header_gen.write(tmp_path, "stm32g474")
    for f in ("stm32g474xx.h", "stm32g4xx.h", "system_stm32g4xx.h", "core_cm4.h", "include/stdint.h", "include/stdbool.h", "include/stddef.h"):
        assert (tmp_path / f).is_file(), f


# ================================================================== D24: tên theo header ST (ca cụ thể; giá trị từ stm32g474xx.h của cmsis-device-g4 v1.2.6 / RM0440)
def _inst(model, name):
    return next(i for g in model.groups.values() for i in g.instances if i.name == name)


def _members(model, type_name):
    g = next(g for g in model.groups.values() if g.type_name == type_name)
    return {m.name: m.offset for m in g.members}


@pytest.mark.parametrize("name,base", [("ADC1", 0x5000_0000), ("ADC2", 0x5000_0100), ("ADC3", 0x5000_0400), ("ADC4", 0x5000_0500), ("ADC5", 0x5000_0600)])
def test_every_adc_instance_uses_the_one_st_adc_struct(model, name, base):
    i = _inst(model, name)
    assert i.type_name == "ADC_TypeDef" and i.base == base                 # ST (dòng ~1418): ADC1..ADC5 cùng ADC_TypeDef; địa chỉ RM0440 p.85–86


def test_adc_common_blocks_are_their_own_struct_and_macros_use_the_adc_prefix(model, text):
    for name, base in (("ADC12_COMMON", 0x5000_0300), ("ADC345_COMMON", 0x5000_0700)):
        i = _inst(model, name)
        assert i.type_name == "ADC_Common_TypeDef" and i.base == base
    assert _members(model, "ADC_Common_TypeDef") == {"CSR": 0x00, "CCR": 0x08, "CDR": 0x0C}
    assert re.search(r"#define\s+ADC_CCR_CKMODE_Pos\s+\(16U\)", text) and re.search(r"#define\s+ADC_CSR_ADRDY_MST_Pos\s+\(0U\)", text)
    assert not re.search(r"#define\s+ADC\d+(_COMMON)?_\w+_(Pos|Msk)\b", text), "macro theo thể hiện (ADC1_CR_ADEN) không có trong header ST"


@pytest.mark.parametrize("parent,n,base", [("DMA1", 1, 0x4002_0008), ("DMA1", 8, 0x4002_0094), ("DMA2", 1, 0x4002_0408), ("DMA2", 5, 0x4002_0458)])
def test_dma_channels_are_separate_instances_like_in_the_st_header(model, text, parent, n, base):
    i = _inst(model, f"{parent}_Channel{n}")
    assert i.type_name == "DMA_Channel_TypeDef" and i.base == base          # ST: DMA1_Channel1_BASE = DMA1_BASE + 0x0008, bước 0x14 (RM0440 DMA register map)
    assert _members(model, "DMA_Channel_TypeDef") == {"CCR": 0, "CNDTR": 4, "CPAR": 8, "CMAR": 12}
    assert _members(model, "DMA_TypeDef") == {"ISR": 0, "IFCR": 4}
    assert re.search(r"#define\s+DMA_CCR_EN_Pos\s+\(0U\)", text) and re.search(r"#define\s+DMA_IFCR_CGIF1_Pos\s+\(0U\)", text)


def test_register_member_names_follow_st_where_the_svd_differs(model):
    assert _members(model, "DAC_TypeDef")["SWTRIGR"] == 0x04 and "SWTRGR" not in _members(model, "DAC_TypeDef") and _members(model, "DAC_TypeDef")["CR"] == 0
    assert {k: v for k, v in _members(model, "DBGMCU_TypeDef").items()} == {"IDCODE": 0, "CR": 4, "APB1FZR1": 8, "APB1FZR2": 12, "APB2FZ": 16}
    assert _members(model, "TIM_TypeDef")["OR"] == 0x68 and "OR1" not in _members(model, "TIM_TypeDef")           # TIM16/17 OR1 (RM0440 p.1505) = TIM_TypeDef.OR của ST


@pytest.mark.parametrize("name,base", [("COMP1", 0x4001_0200), ("COMP7", 0x4001_0218), ("OPAMP", 0x4001_0300), ("OPAMP1", 0x4001_0300), ("OPAMP6", 0x4001_0314)])
def test_comp_and_opamp_have_one_instance_per_unit_with_st_alias_opamp(model, name, base):
    i = _inst(model, name)
    assert i.base == base and i.type_name == ("COMP_TypeDef" if name.startswith("COMP") else "OPAMP_TypeDef")
    assert _members(model, "COMP_TypeDef") == {"CSR": 0} and _members(model, "OPAMP_TypeDef") == {"CSR": 0, "TCMR": 0x18}


def test_fdcan_clock_divider_is_its_own_config_instance(model, text):
    i = _inst(model, "FDCAN_CONFIG")
    assert i.type_name == "FDCAN_Config_TypeDef" and i.base == 0x4000_6500 and _members(model, "FDCAN_Config_TypeDef") == {"CKDIV": 0}
    assert "CKDIV" not in _members(model, "FDCAN_GlobalTypeDef") and _inst(model, "FDCAN1").type_name == "FDCAN_GlobalTypeDef"
    assert not any(i.name == "FDCAN" for g in model.groups.values() for i in g.instances), "khối SVD 0x4000A400 là SRAM tin nhắn, không phải thanh ghi"
    assert re.search(r"#define\s+SRAMCAN_BASE\s+0x4000A400UL", text) and re.search(r"#define\s+FDCAN_CKDIV_PDIV_Pos\s+\(0U\)", text)


def test_flash_bank2_registers_exist_as_in_rm0440_and_the_st_header(model, text):
    # RM0440 p.142–145: FLASH_PCROP2SR 0x44, PCROP2ER 0x48, WRP2AR 0x4C, WRP2BR 0x50, SEC2R 0x74 (DBANK); SVD không có
    m = _members(model, "FLASH_TypeDef")
    assert (m["PCROP2SR"], m["PCROP2ER"], m["WRP2AR"], m["WRP2BR"], m["SEC2R"]) == (0x44, 0x48, 0x4C, 0x50, 0x74)
    assert re.search(r"#define\s+FLASH_WRP2AR_WRP2A_END_Pos\s+\(16U\)", text) and re.search(r"#define\s+FLASH_SEC2R_SEC_SIZE2_Msk\s+\(0xFFUL << FLASH_SEC2R_SEC_SIZE2_Pos\)", text)


def test_memory_map_names_are_memory_addresses_and_register_blocks_use_r_base(text):
    # ST: FLASH_BASE = bộ nhớ flash 0x08000000 (RM0440 p.83), FLASH_R_BASE = thanh ghi FLASH 0x40022000; FMC_BASE = 0x60000000, FMC_R_BASE = 0xA0000000
    for name, value in (("FLASH_BASE", "0x08000000UL"), ("SRAM1_BASE", "0x20000000UL"), ("SRAM2_BASE", "0x20014000UL"), ("CCMSRAM_BASE", "0x10000000UL"),
                        ("PERIPH_BASE", "0x40000000UL"), ("FMC_BASE", "0x60000000UL"), ("FLASH_R_BASE", "0x40022000UL"), ("FMC_R_BASE", "0xA0000000UL"),
                        ("QSPI_R_BASE", "0xA0001000UL"), ("UID_BASE", "0x1FFF7590UL"), ("FLASHSIZE_BASE", "0x1FFF75E0UL"), ("PACKAGE_BASE", "0x1FFF7500UL")):
        assert re.search(rf"#define\s+{name}\s+\(?{value}\)?", text), name
    assert re.search(r"#define\s+FLASH\s+\(\(FLASH_TypeDef \*\) FLASH_R_BASE\)", text) and re.search(r"#define\s+QUADSPI\s+\(\(QUADSPI_TypeDef \*\) QSPI_R_BASE\)", text)
    assert not re.search(r"#define\s+QUADSPI_BASE\b", text)
    assert re.search(r"#define\s+LSI_STARTUP_TIME\s+130U", text)                # DS12288 Table 45 p.122: tSU(LSI) max 130 µs


def test_cortex_m_core_peripherals_are_in_core_cm4_h_not_in_the_device_header(files, text):
    # ST: stm32g474xx.h không định nghĩa NVIC/SCB/SysTick/MPU/FPU (do core_cm4.h của ARM); ở đây chúng nằm trong core_cm4.h sinh ra (tên theo SVD, không đối chiếu được)
    core = files["core_cm4.h"]
    for needle in ("STK_TypeDef", "NVIC_TypeDef", "SCB_TypeDef", "#define STK_BASE"):
        assert needle in core and needle not in text
    assert '#include "core_cm4.h"' in text and "DBGMCU_TypeDef" in text           # DBGMCU (0xE0042000) là của ST, giữ trong header thiết bị


def test_hal_feature_flags_are_derived_from_the_register_database(text):
    # header ST: RTC_BACKUP_NB 32u (32 thanh ghi TAMP_BKPxR), RTC_TAMP_NB 3u, RTC_TAMP_INT_NB 4u (ITAMP3..6), ADC_MULTIMODE_SUPPORT (CCR.DUAL), DAC_CHANNEL2_SUPPORT…
    assert re.search(r"#define\s+RTC_BACKUP_NB\s+32u", text) and re.search(r"#define\s+RTC_TAMP_NB\s+3u", text) and re.search(r"#define\s+RTC_TAMP_INT_NB\s+4u", text)
    for flag in ("ADC_MULTIMODE_SUPPORT", "DAC_CHANNEL2_SUPPORT", "RCC_HSI48_SUPPORT", "RCC_PLLP_DIV_2_31_SUPPORT", "SPI_I2S_SUPPORT", "RTC_TAMP_INT_6_SUPPORT"):
        assert re.search(rf"^#define\s+{flag}\s*$", text, re.M), flag


def test_every_st_naming_table_entry_applies_to_the_database(model):
    assert [a for a in model.anomalies if a["kind"] == "overlay_unmatched"] == []


def test_pwr_voltage_monitor_bits_follow_the_st_header_numbering(text):
    # stm32g474xx.h (dòng ~10800/10890): PVME1..PVME4 = bit 4..7, PVMO1..PVMO4 = bit 12..15. RM0440 Rev 9 p.254 chỉ còn PVME1/2 ở bit 6/7 (đánh số lại) và SVD
    # theo cách đó: macro theo header ST vì code người dùng biên dịch với nó
    for name, pos in (("PWR_CR2_PVME1", 4), ("PWR_CR2_PVME2", 5), ("PWR_CR2_PVME3", 6), ("PWR_CR2_PVME4", 7), ("PWR_SR2_PVMO1", 12), ("PWR_SR2_PVMO4", 15)):
        assert re.search(rf"#define\s+{name}_Pos\s+\({pos}U\)", text), name


@pytest.mark.parametrize("name,msk", [("QUADSPI_CR_FTHRES", "0xFUL"), ("DBGMCU_IDCODE_DEV_ID", "0xFFFUL"), ("TIM_CNT_CNT", "0xFFFFFFFFUL"), ("TIM_ARR_ARR", "0xFFFFFFFFUL"),
                                      ("COMP_CSR_INMSEL", "0xFUL"), ("SYSCFG_EXTICR1_EXTI0", "0x7UL"), ("TIM_CCR5_CCR5", "0xFFFFFUL")])
def test_field_widths_follow_the_st_header_where_the_svd_is_narrower_or_wider(text, name, msk):
    assert re.search(rf"#define\s+{name}_Msk\s+\({msk} << {name}_Pos\)", text), name


def test_syscfg_exti_port_selection_values(text):
    # stm32g474xx.h ~14470: SYSCFG_EXTICR1_EXTI0_PA = 0 … _PG = 6; EXTI1 trong EXTICR1 dịch 4 bit; cổng G chỉ có cho đường 0–9
    assert re.search(r"#define\s+SYSCFG_EXTICR1_EXTI0_PG\s+\(0x00000006U\)", text) and re.search(r"#define\s+SYSCFG_EXTICR1_EXTI1_PB\s+\(0x00000010U\)", text)
    assert re.search(r"#define\s+SYSCFG_EXTICR4_EXTI15_PF\s+\(0x00005000U\)", text) and not re.search(r"SYSCFG_EXTICR3_EXTI10_PG\b", text)


# ================================================================== D24: đối chiếu với header chính thức của ST (cmsis-device-g4 v1.2.6)
# Giá trị kỳ vọng lấy từ chính `stm32g474xx.h` của ST (ghim sha256 trong corpus/manifest.yaml), KHÔNG sinh bằng header_gen (D19).
# Công cụ: eval/tools/check_header_parity.py (so tên macro đầy đủ, offset thành viên struct và giá trị macro bằng clang).
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ST_DIR = ROOT / "corpus" / "headers" / "cmsis-device-g4_v1.2.6" / "Include"
HAS_CLANG = shutil.which("clang") is not None

# Họ ngoại vi mà header sinh phải KHỚP header ST (tên macro thiếu/thừa, giá trị, offset, instance). Phần còn lại (HRTIM, DMAMUX, FMC, SAI, USB,
# macro lõi Cortex-M, macro hàm IS_*_INSTANCE của HAL) được báo cáo trong plan/P3_D24_notes.md là phần dư có chủ đích.
COVERED_FAMILIES = {"ADC", "DMAMUX", "SAI", "COMP", "CORDIC", "CRC", "CRS", "DAC", "DBGMCU", "DMA", "EXTI", "FDCAN", "FLASH", "FMAC", "GPIO", "I2C", "IWDG", "LPTIM",
                    "OPAMP", "PWR", "QUADSPI", "RCC", "RNG", "RTC", "SPI", "SYSCFG", "TAMP", "TIM", "UCPD", "USART", "VREFBUF", "WWDG"}


@pytest.fixture(scope="module")
def parity(tmp_path_factory):
    if not ST_DIR.joinpath("stm32g474xx.h").is_file():
        pytest.skip("official ST headers not downloaded (corpus/headers)")
    if not HAS_CLANG:
        pytest.skip("clang is not installed")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from eval.tools import check_header_parity as P
    P.verify_manifest_files(P.manifest_entry())                        # header ST còn nguyên vẹn so với sha256 ghim
    gen = tmp_path_factory.mktemp("gen")
    header_gen.write(gen, "stm32g474")
    rep = P.build_report(ST_DIR, gen, workdir=tmp_path_factory.mktemp("work"))
    st_defs = P.parse_defines((ST_DIR / "stm32g474xx.h").read_text(errors="replace"))
    inst = P.parse_instances(st_defs)
    covered_t0 = set(COVERED_FAMILIES) | {n for n, (t, _) in inst.items() if P._group_of_type(t) in COVERED_FAMILIES}
    return {"P": P, "rep": rep, "inst": inst, "covered_t0": covered_t0}


# Macro của ST KHÔNG tái tạo (có ghi lý do trong plan/P3_D24_notes.md): thanh ghi không có trong RM0440/DB/struct của ST (DMAMUX_IPHW_*: macro "mồ côi"),
# macro hàm IS_*_INSTANCE của HAL (D20: không HAL/LL), và USB_EPnR kiểu địa chỉ có cú pháp sai trong chính header ST (`USB_BASE + 0x0x00000004`).
NOT_REPRODUCED = re.compile(r"^(DMAMUX_IPHW_|IS_\w+_INSTANCE$)")


def _covered_names(parity, names):
    P, cov = parity["P"], parity["covered_t0"]
    return sorted(n for n in names if ((P._tok0(n) or n) in cov or (n.endswith("_BASE") and n[:-5] in cov) or n in cov) and not NOT_REPRODUCED.match(n))


def test_official_header_macros_missing_in_covered_families(parity):
    miss = [n for names in parity["rep"]["macros"]["missing"].values() for n in names]
    assert _covered_names(parity, miss) == []


def test_generated_macros_the_official_header_does_not_have_in_covered_families(parity):
    extra = [n for cat, names in parity["rep"]["macros"]["extra"].items() if cat != "core_peripheral" for n in names]
    assert _covered_names(parity, extra) == []


def test_macro_values_agree_with_the_official_header_in_covered_families(parity):
    bad = [m["name"] for m in parity["rep"]["values"]["mismatch"]]
    assert _covered_names(parity, bad) == []


def test_instance_names_types_and_bases_agree_with_the_official_header(parity):
    P, rep = parity["P"], parity["rep"]
    cov = parity["covered_t0"]
    ins = rep["instances"]
    assert [n for n in ins["missing"] if n in cov] == []
    assert [n for n in ins["extra"] if n in cov] == []
    assert [d for d in ins["type_differs"] if d["instance"] in cov] == []
    assert [b for b in rep["bases"]["mismatch"] if b["instance"] in cov] == []


def test_struct_members_and_offsets_agree_with_the_official_header(parity):
    cov = parity["covered_t0"]
    bad = {}
    for pair, v in parity["rep"]["offsets"]["by_instance_type"].items():
        if not any(i in cov for i in v["instances"]):
            continue
        if v["offset_mismatch"] or v["missing_in_generated"] or v["extra_in_generated"] or v["size_st"] != v["size_generated"]:
            bad[pair] = {k: v[k] for k in ("offset_mismatch", "missing_in_generated", "extra_in_generated", "size_st", "size_generated")}
    assert bad == {}
