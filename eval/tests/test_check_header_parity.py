"""check_header_parity (D24): đối chiếu header CMSIS sinh tự động với header chính thức của ST.

Không dùng mạng và không dùng header ST thật: các test dựng hai header nhỏ ("ST giả" và "header sinh giả") cố ý lệch nhau theo từng loại khác biệt
mà công cụ phải phát hiện. Phần dùng clang (offset thành viên, giá trị macro) bị bỏ qua nếu máy không có clang.
"""
import json
import shutil

import pytest

from eval.tools import check_header_parity as P

HAS_CLANG = shutil.which("clang") is not None
needs_clang = pytest.mark.skipif(not HAS_CLANG, reason="clang is not installed")

ST = r"""
#ifndef __FAKE_ST_H
#define __FAKE_ST_H
#include "core_cm4.h"
#include <stdint.h>

typedef struct
{
  __IO uint32_t CR1;       /*!< control 1,   Address offset: 0x00 */
  __IO uint32_t CR2;
  uint32_t      RESERVED0[2];
  __IO uint32_t PSC;       /* 0x10 */
  __IO uint32_t ARR;       // 0x14
  __IO uint32_t OR;        /* only in ST */
} TIM_TypeDef;

typedef struct
{
  __IO uint32_t MODER;
  __IO uint32_t OTYPER;
  __IO uint32_t IDR;
  __IO uint32_t AFR[2];
} GPIO_TypeDef;

typedef struct { __IO uint32_t CCR; } ADC_Common_TypeDef;
typedef struct { __IO uint32_t CTRL; } SysTick_Type;

#define PERIPH_BASE           0x40000000UL
#define APB2PERIPH_BASE       (PERIPH_BASE + 0x00010000UL)
#define TIM1_BASE             (APB2PERIPH_BASE + 0x2C00UL)
#define GPIOA_BASE            (PERIPH_BASE + \
                               0x08000000UL)
#define ADC12_COMMON_BASE     (PERIPH_BASE + 0x08000300UL)
#define TIM1                  ((TIM_TypeDef *)TIM1_BASE)
#define GPIOA                 ((GPIO_TypeDef *)GPIOA_BASE)
#define ADC12_COMMON          ((ADC_Common_TypeDef *)ADC12_COMMON_BASE)

#define TIM_CR1_CEN_Pos       (0U)
#define TIM_CR1_CEN_Msk       (0x1UL << TIM_CR1_CEN_Pos)
#define TIM_CR1_CEN           TIM_CR1_CEN_Msk
#define TIM_CR1_CMS_Pos       (5U)
#define TIM_CR1_CMS_Msk       (0x3UL << TIM_CR1_CMS_Pos)
#define TIM_CR1_CMS           TIM_CR1_CMS_Msk
#define TIM_CR1_CMS_0         (0x1UL << TIM_CR1_CMS_Pos)
#define TIM_CR1_CMS_1         (0x2UL << TIM_CR1_CMS_Pos)
#define TIM_CR1_ARPE_Pos      (7U)
#define TIM_CR1_ARPE_Msk      (0x1UL << TIM_CR1_ARPE_Pos)
#define TIM_CR1_ARPE          TIM_CR1_ARPE_Msk
#define TIM_OR_HSE32EN_Pos    (1U)
#define TIM_OR_HSE32EN_Msk    (0x1UL << TIM_OR_HSE32EN_Pos)
#define TIM_OR_HSE32EN        TIM_OR_HSE32EN_Msk
#define GPIO_MODER_MODE8_Pos  (16U)
#define GPIO_MODER_MODE8_Msk  (0x3UL << GPIO_MODER_MODE8_Pos)
#define GPIO_MODER_MODE8      GPIO_MODER_MODE8_Msk
#define ADC_CCR_CKMODE_Pos    (16U)
#define ADC_CCR_CKMODE_Msk    (0x3UL << ADC_CCR_CKMODE_Pos)
#define ADC_CCR_CKMODE        ADC_CCR_CKMODE_Msk
#define DAC_CR_EN1_Pos        (0U)
#define DAC_CR_EN1_Msk        (0x1UL << DAC_CR_EN1_Pos)
#define DAC_CR_EN1            DAC_CR_EN1_Msk
#define RCC_CFGR_SW_Pos       (0U)
#define RCC_CFGR_SW_Msk       (0x3UL << RCC_CFGR_SW_Pos)
#define RCC_CFGR_SW           RCC_CFGR_SW_Msk
#define RCC_CFGR_SW_PLL       (0x3UL << RCC_CFGR_SW_Pos)
#define RCC_CFGR_SW_HSI       (0x1UL << RCC_CFGR_SW_Pos)
#define IS_TIM_INSTANCE(INSTANCE)  ((INSTANCE) == TIM1)
#endif /* __FAKE_ST_H */
"""

# Header sinh giả. Khác ST có chủ đích:
#   thiếu: TIM_CR1_ARPE*, TIM_CR1_CMS_1, TIM_OR_HSE32EN*, DAC_CR_EN1* (cả nhóm DAC), RCC_CFGR_SW_HSI, thành viên TIM OR, hàm IS_TIM_INSTANCE,
#          instance ADC12_COMMON; thừa: tên SVD GPIO_MODER_MODER8*, tên theo thể hiện TIM1_CR1_CEN, thanh ghi TIM_ARR_ARR (ST không có),
#          nhóm STK_*, macro lõi Cortex ở 0xE000E010; giá trị khác: TIM_CR1_CMS_Msk (0x1 thay vì 0x3), GPIO_MODER_MODE8_Pos (15 thay vì 16)
GEN = r"""
#ifndef GEN_H
#define GEN_H
#include <stdint.h>
#define __IO volatile

typedef struct
{
  __IO uint32_t CR1;
  __IO uint32_t CR2;
  uint32_t RESERVED0[2];
  __IO uint32_t PSC;
  __IO uint32_t ARR;
} TIM_TypeDef;

typedef struct
{
  __IO uint32_t MODER;
  __IO uint32_t OTYPER;
  __IO uint32_t IDR;
  union {
    __IO uint32_t AFR[2];
    struct { __IO uint32_t AFRL; __IO uint32_t AFRH; };
  };
} GPIO_TypeDef;

typedef struct { __IO uint32_t CTRL; } STK_TypeDef;

#define TIM1_BASE             0x40012C00UL
#define GPIOA_BASE            0x48000000UL
#define STK_BASE              0xE000E010UL
#define TIM1                  ((TIM_TypeDef *) TIM1_BASE)
#define GPIOA                 ((GPIO_TypeDef *) GPIOA_BASE)
#define STK                   ((STK_TypeDef *) STK_BASE)

#define TIM_CR1_CEN_Pos       (0U)
#define TIM_CR1_CEN_Msk       (0x1UL << TIM_CR1_CEN_Pos)
#define TIM_CR1_CEN           TIM_CR1_CEN_Msk
#define TIM1_CR1_CEN          TIM_CR1_CEN_Msk
#define TIM_CR1_CMS_Pos       (5U)
#define TIM_CR1_CMS_Msk       (0x1UL << TIM_CR1_CMS_Pos)
#define TIM_CR1_CMS           TIM_CR1_CMS_Msk
#define TIM_CR1_CMS_0         (0x1UL << TIM_CR1_CMS_Pos)
#define TIM_ARR_ARR_Pos       (0U)
#define TIM_ARR_ARR_Msk       (0xFFFFUL << TIM_ARR_ARR_Pos)
#define TIM_ARR_ARR           TIM_ARR_ARR_Msk
#define GPIO_MODER_MODE8_Pos  (15U)
#define GPIO_MODER_MODE8_Msk  (0x3UL << GPIO_MODER_MODE8_Pos)
#define GPIO_MODER_MODE8      GPIO_MODER_MODE8_Msk
#define GPIO_MODER_MODER8_Pos (16U)
#define GPIO_MODER_MODER8_Msk (0x3UL << GPIO_MODER_MODER8_Pos)
#define GPIO_MODER_MODER8     GPIO_MODER_MODER8_Msk
#define RCC_CFGR_SW_Pos       (0U)
#define RCC_CFGR_SW_Msk       (0x3UL << RCC_CFGR_SW_Pos)
#define RCC_CFGR_SW           RCC_CFGR_SW_Msk
#define RCC_CFGR_SW_PLL       (0x3UL << RCC_CFGR_SW_Pos)
#define STK_CTRL_ENABLE_Pos   (0U)
#define STK_CTRL_ENABLE_Msk   (0x1UL << STK_CTRL_ENABLE_Pos)
#define STK_CTRL_ENABLE       STK_CTRL_ENABLE_Msk
#endif
"""


@pytest.fixture()
def dirs(tmp_path):
    st, gen = tmp_path / "st" / "Include", tmp_path / "gen"
    st.mkdir(parents=True)
    gen.mkdir()
    (st / "stm32fake.h").write_text(ST)
    (gen / "stm32fake.h").write_text(GEN)
    return st, gen


@pytest.fixture()
def defs():
    return P.parse_defines(ST), P.parse_defines(GEN)


# ------------------------------------------------------------------ parse
def test_parse_defines_strips_comments_joins_continuations_and_keeps_function_like_macros():
    d = P.parse_defines("/* c\n#define HIDDEN 1\n*/\n#define A (1U) /* x */\n#define B  // y\n#define C(x, y) ((x) + (y))\n"
                        "#define D 1 + \\\n   2\n#undef A\n#define E\n")
    assert "HIDDEN" not in d and "A" not in d
    assert d["B"].body == "" and d["E"].body == ""
    assert d["C"].params == ("x", "y") and d["C"].body == "((x) + (y))"
    assert d["D"].body.split() == ["1", "+", "2"]
    assert d["D"].line == 7                       # dòng bắt đầu của chỉ thị (đếm cả dòng bị nối)


def test_macro_kinds(defs):
    st, _ = defs
    kinds = P.macro_kinds(st)
    assert kinds["__FAKE_ST_H"] == "guard"
    assert kinds["TIM_CR1_CEN_Pos"] == "pos" and kinds["TIM_CR1_CEN_Msk"] == "msk"
    assert kinds["TIM_CR1_CEN"] == "field" and kinds["TIM_CR1_CMS_0"] == "field_bit"
    assert kinds["RCC_CFGR_SW_PLL"] == "value"
    assert kinds["TIM1"] == "instance" and kinds["TIM1_BASE"] == "base" and kinds["PERIPH_BASE"] == "base"
    assert kinds["IS_TIM_INSTANCE"] == "function_like"


def test_parse_instances_gives_type_and_base_name(defs):
    st, gen = defs
    assert P.parse_instances(st) == {"TIM1": ("TIM_TypeDef", "TIM1_BASE"), "GPIOA": ("GPIO_TypeDef", "GPIOA_BASE"),
                                     "ADC12_COMMON": ("ADC_Common_TypeDef", "ADC12_COMMON_BASE")}
    assert P.parse_instances(gen)["STK"] == ("STK_TypeDef", "STK_BASE")


def test_python_evaluator_resolves_nested_base_macros_and_refuses_everything_else(defs):
    st, _ = defs
    assert P.eval_int_macro("GPIOA_BASE", st) == 0x4800_0000
    assert P.eval_int_macro("TIM1_BASE", st) == 0x4001_2C00
    assert P.eval_int_macro("TIM_CR1_CMS_Msk", st) == 0x60
    assert P.eval_int_macro("IS_TIM_INSTANCE", st) is None           # hàm
    assert P.eval_int_macro("TIM1", st) is None                      # con trỏ
    assert P.eval_int_macro("NO_SUCH", st) is None
    evil = P.parse_defines("#define X __import__('os').system('true')\n#define Y (1 << Z)\n#define Z Y\n")
    assert P.eval_int_macro("X", evil) is None and P.eval_int_macro("Y", evil) is None     # không eval mã, chặn vòng


# ------------------------------------------------------------------ (a)(b) so sánh tên macro
def test_compare_macros_lists_missing_extra_and_coverage(defs):
    st, gen = defs
    r = P.compare_macros(st, gen)
    miss = {n for names in r["missing"].values() for n in names}
    extra = {n for names in r["extra"].values() for n in names}
    assert miss == {"TIM_CR1_ARPE_Pos", "TIM_CR1_ARPE_Msk", "TIM_CR1_ARPE", "TIM_CR1_CMS_1", "TIM_OR_HSE32EN_Pos", "TIM_OR_HSE32EN_Msk",
                    "TIM_OR_HSE32EN", "DAC_CR_EN1_Pos", "DAC_CR_EN1_Msk", "DAC_CR_EN1", "RCC_CFGR_SW_HSI", "IS_TIM_INSTANCE",
                    "ADC12_COMMON", "ADC12_COMMON_BASE", "ADC_CCR_CKMODE_Pos", "ADC_CCR_CKMODE_Msk", "ADC_CCR_CKMODE",
                    "PERIPH_BASE", "APB2PERIPH_BASE"}
    assert extra == {"TIM1_CR1_CEN", "TIM_ARR_ARR_Pos", "TIM_ARR_ARR_Msk", "TIM_ARR_ARR", "GPIO_MODER_MODER8_Pos", "GPIO_MODER_MODER8_Msk",
                     "GPIO_MODER_MODER8", "STK", "STK_BASE", "STK_CTRL_ENABLE_Pos", "STK_CTRL_ENABLE_Msk", "STK_CTRL_ENABLE", "__IO"}
    c = r["counts"]
    assert c["common"] == c["st"] - c["missing"] == c["generated"] - c["extra"]
    assert "__FAKE_ST_H" not in miss and "GEN_H" not in extra                      # chốt chặn include không tính
    assert r["by_kind"]["pos"]["missing"] == 4 and r["by_kind"]["pos"]["extra"] == 3
    assert r["by_kind"]["pos"]["coverage"] == pytest.approx(r["by_kind"]["pos"]["common"] / r["by_kind"]["pos"]["st"])


def test_missing_macros_are_categorised_by_how_much_of_the_name_gen_knows(defs):
    st, gen = defs
    m = P.compare_macros(st, gen)["missing"]
    assert set(m["group_absent"]) == {"DAC_CR_EN1_Pos", "DAC_CR_EN1_Msk", "DAC_CR_EN1",
                                      "ADC_CCR_CKMODE_Pos", "ADC_CCR_CKMODE_Msk", "ADC_CCR_CKMODE"}    # cả nhóm DAC, ADC không có
    assert set(m["register_absent"]) == {"TIM_OR_HSE32EN_Pos", "TIM_OR_HSE32EN_Msk", "TIM_OR_HSE32EN"}   # nhóm TIM có, thanh ghi OR không
    assert set(m["field_absent"]) == {"TIM_CR1_ARPE_Pos", "TIM_CR1_ARPE_Msk", "TIM_CR1_ARPE", "TIM_CR1_CMS_1", "RCC_CFGR_SW_HSI"}
    assert set(m["instance"]) == {"ADC12_COMMON"} and set(m["base"]) == {"ADC12_COMMON_BASE", "PERIPH_BASE", "APB2PERIPH_BASE"}
    assert set(m["function_like"]) == {"IS_TIM_INSTANCE"}


def test_extra_macros_are_categorised_with_the_reason_they_would_not_build_with_the_real_header(defs):
    st, gen = defs
    e = P.compare_macros(st, gen)["extra"]
    assert set(e["core_peripheral"]) == {"STK", "STK_BASE", "STK_CTRL_ENABLE_Pos", "STK_CTRL_ENABLE_Msk", "STK_CTRL_ENABLE"}   # PPB nội bộ 0xE000E010
    assert set(e["per_instance"]) == {"TIM1_CR1_CEN"}                       # tên theo thể hiện, ST chỉ dùng tên nhóm TIM_
    assert set(e["register_not_in_st"]) == {"TIM_ARR_ARR_Pos", "TIM_ARR_ARR_Msk", "TIM_ARR_ARR"}
    assert set(e["field_not_in_st"]) == {"GPIO_MODER_MODER8_Pos", "GPIO_MODER_MODER8_Msk", "GPIO_MODER_MODER8"}   # tên SVD khác tên ST
    assert set(e["other"]) == {"__IO"}


def test_only_the_internal_private_peripheral_bus_counts_as_core(defs):
    # ARMv7-M: 0xE0000000-0xE003FFFF là PPB nội bộ (NVIC/SCB/SysTick/MPU/FPU: do CMSIS-Core của ARM định nghĩa); DBGMCU ở 0xE0042000 là PPB ngoài —
    # ST tự định nghĩa `DBGMCU_TypeDef` trong header thiết bị nên KHÔNG được phân loại là lõi Cortex
    st, _ = defs
    gen = P.parse_defines(GEN + "\n#define DBGMCU_BASE 0xE0042000UL\n#define DBGMCU ((DBGMCU_TypeDef *) DBGMCU_BASE)\n"
                          "#define DBGMCU_CR_DBG_SLEEP_Pos (0U)\n#define DBGMCU_CR_DBG_SLEEP_Msk (0x1UL << DBGMCU_CR_DBG_SLEEP_Pos)\n"
                          "#define DBGMCU_CR_DBG_SLEEP DBGMCU_CR_DBG_SLEEP_Msk\n")
    e = P.compare_macros(st, gen)["extra"]
    assert "DBGMCU_CR_DBG_SLEEP" not in e.get("core_peripheral", []) and "DBGMCU_CR_DBG_SLEEP" in e["group_not_in_st"]
    assert {"DBGMCU", "DBGMCU_BASE"} <= set(e["instance"]) | set(e["base"])
    assert "STK" in e["core_peripheral"]


def test_extra_detail_offers_a_closest_st_name_as_a_hint_only(defs):
    st, gen = defs
    detail = P.compare_macros(st, gen)["extra_detail"]
    hint = detail["GPIO_MODER_MODER8_Msk"]
    assert hint["category"] == "field_not_in_st" and hint["closest_st"] == "GPIO_MODER_MODE8_Msk"


def test_names_are_compared_in_full_without_normalisation():
    st = P.parse_defines("#define TIM_CR1_CEN_Pos (0U)\n#define TIM_CR1_CEN_Msk (1UL)\n#define TIM_CR1_CEN TIM_CR1_CEN_Msk\n")
    gen = P.parse_defines("#define tim_cr1_cen_Pos (0U)\n#define TIM_CR1_CEN_POS (0U)\n#define TIM_CR1_CEN_Msk (1UL)\n")
    r = P.compare_macros(st, gen)
    assert set(r["missing"]["field_absent"]) == {"TIM_CR1_CEN_Pos", "TIM_CR1_CEN"}


# ------------------------------------------------------------------ instance
def test_compare_instances_reports_missing_extra_and_type_differences(defs):
    st, gen = defs
    gen2 = dict(gen)
    gen2.update(P.parse_defines("#define GPIOA ((GPIOA_TypeDef *) GPIOA_BASE)\n"))
    r = P.compare_instances(P.parse_instances(st), P.parse_instances(gen2))
    assert r["missing"] == ["ADC12_COMMON"] and r["extra"] == ["STK"]
    assert r["type_differs"] == [{"instance": "GPIOA", "st": "GPIO_TypeDef", "generated": "GPIOA_TypeDef"}]
    assert r["common"] == 2 and r["st"] == 3


# ------------------------------------------------------------------ an toàn: header là dữ liệu không tin cậy
@pytest.mark.parametrize("line", ['#include "/etc/passwd"', '#include "../x.h"', "#include_next <a.h>", "#import <a.h>", "#embed \"a.bin\"",
                                  "#define H \"a.h\"\n#include H"])
def test_headers_with_dangerous_directives_are_refused(tmp_path, line):
    (tmp_path / "evil.h").write_text(f"{line}\n")
    with pytest.raises(P.UnsafeHeader):
        P.check_header_safe(tmp_path / "evil.h")


def test_normal_includes_are_accepted(dirs):
    st, gen = dirs
    P.check_header_safe(st / "stm32fake.h")
    P.check_header_safe(gen / "stm32fake.h")


# ------------------------------------------------------------------ (c) offset thành viên (clang)
@needs_clang
def test_struct_layout_reads_members_offsets_and_sizes_from_clang(dirs, tmp_path):
    st, gen = dirs
    lay = P.struct_layouts(st, "stm32fake.h", tmp_path / "w1")
    tim = lay["TIM_TypeDef"]
    assert tim["members"]["CR1"] == 0 and tim["members"]["PSC"] == 0x10 and tim["members"]["ARR"] == 0x14 and tim["members"]["OR"] == 0x18
    assert tim["size"] == 0x1C and lay["GPIO_TypeDef"]["members"]["AFR"] == 0x0C
    glay = P.struct_layouts(gen, "stm32fake.h", tmp_path / "w2")
    assert glay["GPIO_TypeDef"]["members"]["AFRL"] == 0x0C and glay["GPIO_TypeDef"]["members"]["AFRH"] == 0x10    # union ẩn danh
    assert glay["GPIO_TypeDef"]["members"]["AFR"] == 0x0C


@needs_clang
def test_compare_layouts_per_instance_finds_missing_extra_and_shifted_members(dirs, tmp_path):
    st, gen = dirs
    text = GEN.replace("  uint32_t RESERVED0[2];\n  __IO uint32_t PSC;", "  uint32_t RESERVED0[1];\n  __IO uint32_t PSC;")      # PSC lệch 4 byte
    (gen / "stm32fake.h").write_text(text)
    lay_st, lay_gen = P.struct_layouts(st, "stm32fake.h", tmp_path / "w1"), P.struct_layouts(gen, "stm32fake.h", tmp_path / "w2")
    r = P.compare_layouts(lay_st, lay_gen, P.parse_instances(P.parse_defines(ST)), P.parse_instances(P.parse_defines(text)))
    tim = r["by_instance_type"]["TIM_TypeDef->TIM_TypeDef"]
    assert tim["instances"] == ["TIM1"]
    assert tim["offset_mismatch"] == {"PSC": {"st": 0x10, "generated": 0x0C}, "ARR": {"st": 0x14, "generated": 0x10}}
    assert tim["missing_in_generated"] == ["OR"] and tim["extra_in_generated"] == []
    gp = r["by_instance_type"]["GPIO_TypeDef->GPIO_TypeDef"]
    assert gp["offset_mismatch"] == {} and gp["missing_in_generated"] == [] and gp["extra_in_generated"] == ["AFRH", "AFRL"]    # AFRL/AFRH: ST không có
    assert r["totals"]["offset_mismatch"] == 2 and r["totals"]["missing_in_generated"] == 1
    assert r["totals"]["members_matching"] == r["totals"]["members_checked"] - 2 - 1
    assert "RESERVED0" not in tim["offset_mismatch"]                                       # RESERVED không phải giao diện


@needs_clang
def test_compare_layouts_matches_identical_structs(dirs, tmp_path):
    st, _ = dirs
    lay = P.struct_layouts(st, "stm32fake.h", tmp_path / "w1")
    inst = P.parse_instances(P.parse_defines(ST))
    r = P.compare_layouts(lay, lay, inst, inst)
    assert r["totals"]["offset_mismatch"] == 0 and r["totals"]["missing_in_generated"] == 0 and r["totals"]["extra_in_generated"] == 0
    assert r["totals"]["members_checked"] > 0 and r["totals"]["members_matching"] == r["totals"]["members_checked"]


# ------------------------------------------------------------------ giá trị macro (clang)
@needs_clang
def test_evaluate_macros_uses_clang_constant_folding(dirs, tmp_path):
    st, _ = dirs
    vals = P.evaluate_macros(st, "stm32fake.h", ["TIM_CR1_CMS_Msk", "TIM_CR1_CMS_1", "TIM1_BASE", "RCC_CFGR_SW_PLL"], tmp_path / "w")
    assert vals == {"TIM_CR1_CMS_Msk": 0x60, "TIM_CR1_CMS_1": 0x40, "TIM1_BASE": 0x4001_2C00, "RCC_CFGR_SW_PLL": 3}


@needs_clang
def test_evaluate_macros_drops_names_that_do_not_fold_instead_of_failing(dirs, tmp_path):
    st, _ = dirs
    vals = P.evaluate_macros(st, "stm32fake.h", ["TIM_CR1_CEN_Pos", "IS_TIM_INSTANCE", "NOT_A_MACRO"], tmp_path / "w")
    assert vals == {"TIM_CR1_CEN_Pos": 0, "IS_TIM_INSTANCE": None, "NOT_A_MACRO": None}


@needs_clang
def test_compare_values_flags_same_name_different_value(defs, dirs, tmp_path):
    st, gen = dirs
    sd, gd = defs
    r = P.compare_values(sd, gd, st, gen, "stm32fake.h", tmp_path / "w")
    bad = {m["name"]: (m["st"], m["generated"]) for m in r["mismatch"]}
    assert bad == {"TIM_CR1_CMS_Msk": (0x60, 0x20), "GPIO_MODER_MODE8_Pos": (16, 15), "GPIO_MODER_MODE8_Msk": (0x30000, 0x18000),
                   "GPIO_MODER_MODE8": (0x30000, 0x18000), "TIM_CR1_CMS": (0x60, 0x20)}
    assert r["evaluated"] > 0 and r["match"] == r["evaluated"] - len(bad)
    assert r["unevaluated"] == []


@needs_clang
def test_compare_values_also_checks_same_name_base_address_macros(dirs, tmp_path):
    # vd. FLASH_BASE: ST = 0x08000000 (bộ nhớ flash), header sinh từng dùng tên đó cho thanh ghi FLASH (0x40022000) — phải bị bắt
    st, gen = dirs
    (gen / "stm32fake.h").write_text(GEN.replace("#define TIM1_BASE             0x40012C00UL", "#define TIM1_BASE             0x40012D00UL"))
    sd, gd = P.parse_defines(ST), P.parse_defines((gen / "stm32fake.h").read_text())
    r = P.compare_values(sd, gd, st, gen, "stm32fake.h", tmp_path / "w")
    assert {"name": "TIM1_BASE", "st": 0x4001_2C00, "generated": 0x4001_2D00} in r["mismatch"]


@needs_clang
def test_compare_bases_checks_instance_addresses(defs, dirs, tmp_path):
    st, gen = dirs
    sd, gd = defs
    r = P.compare_bases(P.parse_instances(sd), P.parse_instances(gd), sd, gd, st, gen, "stm32fake.h", tmp_path / "w")
    assert r["mismatch"] == [] and r["checked"] == 2 and r["match"] == 2          # TIM1 và GPIOA khớp địa chỉ
    gd2 = dict(gd)
    gd2.update(P.parse_defines("#define GPIOA_BASE 0x48000400UL\n#define GPIOA ((GPIO_TypeDef *) GPIOA_BASE)\n"))
    (gen / "stm32fake.h").write_text(GEN.replace("#define GPIOA_BASE            0x48000000UL", "#define GPIOA_BASE            0x48000400UL"))
    r2 = P.compare_bases(P.parse_instances(sd), P.parse_instances(gd2), sd, gd2, st, gen, "stm32fake.h", tmp_path / "w2")
    assert r2["mismatch"] == [{"instance": "GPIOA", "st": 0x4800_0000, "generated": 0x4800_0400}]


# ------------------------------------------------------------------ báo cáo và CLI
def test_build_report_without_clang_still_compares_names(dirs, tmp_path):
    st, gen = dirs
    rep = P.build_report(st, gen, "stm32fake.h", workdir=tmp_path / "w", use_clang=False)
    assert rep["macros"]["counts"]["missing"] > 0 and rep["offsets"] is None and rep["values"] is None
    assert rep["limitations"] and any("clang" in s for s in rep["limitations"])
    assert rep["instances"]["missing"] == ["ADC12_COMMON"]


def test_markdown_report_has_counts_coverage_and_categories(dirs, tmp_path):
    st, gen = dirs
    rep = P.build_report(st, gen, "stm32fake.h", workdir=tmp_path / "w", use_clang=False)
    md = P.render_markdown(rep, max_list=3)
    for needle in ("Thiếu trong header sinh", "Thừa trong header sinh", "register_not_in_st", "core_peripheral", "coverage", "TIM_CR1_ARPE"):
        assert needle in md, needle
    assert md.count("TIM_OR_HSE32EN") <= 3                                  # danh sách bị cắt theo max_list; JSON mới có đủ


@needs_clang
def test_cli_writes_json_and_markdown(dirs, tmp_path, capsys):
    st, gen = dirs
    out = tmp_path / "out"
    rc = P.main(["--st-dir", str(st), "--generated-dir", str(gen), "--main-header", "stm32fake.h", "--out", str(out)])
    assert rc == 0
    rep = json.loads((out / "header_parity.json").read_text())
    assert rep["offsets"]["totals"]["offset_mismatch"] == 0 and rep["values"]["mismatch"]
    assert (out / "header_parity.md").read_text().startswith("# ")
    assert "missing" in capsys.readouterr().out


def test_cli_strict_mode_fails_when_headers_differ(dirs, tmp_path):
    st, gen = dirs
    assert P.main(["--st-dir", str(st), "--generated-dir", str(gen), "--main-header", "stm32fake.h", "--out", str(tmp_path / "o"),
                   "--no-clang", "--strict"]) == 1
    (gen / "stm32fake.h").write_text((st / "stm32fake.h").read_text())
    assert P.main(["--st-dir", str(st), "--generated-dir", str(gen), "--main-header", "stm32fake.h", "--out", str(tmp_path / "o2"),
                   "--no-clang", "--strict"]) == 0


# ------------------------------------------------------------------ manifest
def test_pinned_st_headers_in_the_corpus_manifest_match_their_recorded_sha256():
    """Header ST đã tải (nếu có trong máy này) khớp sha256 ghim trong corpus/manifest.yaml; không có thì bỏ qua."""
    entry = P.manifest_entry()
    if entry is None or not all((P.CORPUS / f["path"]).is_file() for f in entry["files"]):
        pytest.skip("ST headers not downloaded on this machine")
    assert entry["kind"] == "header" and entry["commit"] and len(entry["commit"]) == 40 and entry["tag"] == "v1.2.6"
    P.verify_manifest_files(entry)                      # ném lỗi nếu lệch
    assert all(len(f["sha256"]) == 64 for f in entry["files"])
