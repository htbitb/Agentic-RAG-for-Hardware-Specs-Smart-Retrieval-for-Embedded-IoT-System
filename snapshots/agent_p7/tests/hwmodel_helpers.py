"""Hàm dựng op / tra kết quả cho golden test của hwmodel. KHÔNG chứa logic mô phỏng (D19)."""


def W(reg, value):
    return {"op": "write", "reg": reg, "value": value}


def SET(reg, mask):
    return {"op": "set_bits", "reg": reg, "mask": mask}


def CLR(reg, mask):
    return {"op": "clear_bits", "reg": reg, "mask": mask}


def MOD(reg, mask, value):
    return {"op": "modify", "reg": reg, "mask": mask, "value": value}


def errors(res):
    return sorted({v["code"] for v in res["violations"] if v["severity"] == "error"})


def warnings(res):
    return sorted({v["code"] for v in res["violations"] if v["severity"] == "warning"})


def codes(res):
    return sorted({v["code"] for v in res["violations"]})


def effects_of(res, **match):
    return [e for e in res["effects"] if all(e.get(k) == v for k, v in match.items())]


def one_effect(res, **match):
    found = effects_of(res, **match)
    assert len(found) == 1, f"expected exactly one effect {match}, got {found!r} (all: {res['effects']!r})"
    return found[0]


def without(seq, *indexes):
    return [op for i, op in enumerate(seq) if i not in set(indexes)]


def replaced(seq, index, op):
    out = list(seq)
    out[index] = op
    return out


# ---- chuỗi khởi tạo PWM TIM1_CH1 trên PA8 (20 kHz, 25%) với SYSCLK = PCLK2 = 170 MHz
# Thứ tự bước theo RM0440 §29.3.13 (p.1178): chọn PWM mode trong OCxM, bật preload (OCxPE, ARPE), đặt UG trước khi chạy,
# bật CCxE (+ MOE cho advanced timer, Table 282 p.1261), rồi CEN. Vị trí bit lấy từ RM (số trang ở comment).
PWM_PA8 = [
    SET("RCC_AHB2ENR", 1 << 0),                                   # 0  GPIOAEN, bit 0 (p.308)
    SET("RCC_APB2ENR", 1 << 11),                                  # 1  TIM1EN, bit 11 (p.313)
    MOD("GPIOA_MODER", 0b11 << 16, 0b10 << 16),                   # 2  MODER8 = 10 (alternate function), p.355
    MOD("GPIOA_AFRH", 0xF << 0, 6),                               # 3  AFSEL8 = AF6; DS12288 Table 13 p.73: PA8 AF6 = TIM1_CH1
    W("TIM1_PSC", 0),                                             # 4  f = 170e6 / ((0+1) * (8499+1)) = 20 kHz
    W("TIM1_ARR", 8499),                                          # 5
    W("TIM1_CCR1", 2125),                                         # 6  2125 / 8500 = 25 %
    MOD("TIM1_CCMR1", (0b111 << 4) | (1 << 3) | (1 << 16), (0b110 << 4) | (1 << 3)),   # 7  OC1M = 0110 (PWM mode 1), OC1PE = 1 (p.1253)
    SET("TIM1_CCER", 1 << 0),                                     # 8  CC1E, bit 0 (p.1260)
    SET("TIM1_BDTR", 1 << 15),                                    # 9  MOE, bit 15 (p.1270)
    SET("TIM1_CR1", 1 << 7),                                      # 10 ARPE, bit 7 (p.1235)
    SET("TIM1_EGR", 1 << 0),                                      # 11 UG, bit 0 (p.1249)
    SET("TIM1_CR1", 1 << 0),                                      # 12 CEN, bit 0 (p.1236)
]
IDX = dict(gpioa_clk=0, tim1_clk=1, moder=2, afrh=3, psc=4, arr=5, ccr=6, ccmr=7, ccer=8, moe=9, arpe=10, ug=11, cen=12)
CLK170 = "sysclk_170mhz_pll_hsi16_apb_div1"
