"""Hiệu chỉnh SVD theo Reference Manual (STM32G474 / RM0440 Rev 9).

Nguyên tắc (D07, P1): SVD của hãng có lỗi; DB giữ nguyên SVD và ghi `rm_reset_value` khi manual khác — simulator ưu tiên manual.
Ở đây chỉ có phần P1 KHÔNG thể biểu diễn trong DB: mặt nạ ghi (độ rộng thanh ghi). Mỗi mục có `evidence` (trang PDF của RM0440,
manifest page_offset = 0) và được test (`test_hwmodel_regmap`). Thêm mục mới chỉ khi đã đọc trang RM.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Erratum:
    id: str
    chip: str
    regs: tuple[str, ...]                  # rid dạng "TIM1_ARR"
    rw_mask: int | None = None             # mặt nạ bit ghi được theo RM
    evidence: str = ""


_ARR20_TIMERS = ("TIM1", "TIM8", "TIM20", "TIM3", "TIM4", "TIM6", "TIM7", "TIM15", "TIM16", "TIM17")

ERRATA: tuple[Erratum, ...] = (
    Erratum("ARR-20BIT", "stm32g474", tuple(f"{t}_ARR" for t in _ARR20_TIMERS), rw_mask=0x000F_FFFF,
            evidence="RM0440 'Bits 19:0 ARR[19:0]' (dithering): p.1263 TIM1/8/20, p.1388 TIM3/4, p.1470 TIM15, p.1496 TIM16/17, "
                     "p.1528 TIM6/7. SVD khai báo ARR 16 bit (hoặc 32 bit cho TIM3/4 vì derivedFrom TIM2). TIM2/TIM5: ARR[31:0] (p.1389)."),
    Erratum("TIM25-32BIT", "stm32g474", tuple(f"{t}_{r}" for t in ("TIM2", "TIM5") for r in ("CNT", "ARR", "CCR1", "CCR2", "CCR3", "CCR4")),
            rw_mask=0xFFFF_FFFF,
            evidence="RM0440 p.1387 'TIMx_CNT (x = 2, 5)' CNT[31:0]; p.1389 'Bits 31:0 ARR[31:0]'; p.1390 'Bits 31:0 CCR1[31:0]'. "
                     "SVD của TIM2/TIM5 chỉ khai báo ARR/CCRx 16 bit (CNT 16 bit + UIFCPY) dù hai bộ đếm này 32 bit."),
    Erratum("TIM34-16BIT", "stm32g474", tuple(f"{t}_{r}" for t in ("TIM3", "TIM4") for r in ("CCR1", "CCR2", "CCR3", "CCR4")),
            rw_mask=0x0000_FFFF,
            evidence="RM0440 p.1389: TIM3/TIM4 'CCR1[19:0]' và chế độ không dithering: 'CCR1[19:16] bits are reset' => 16 bit hiệu dụng. "
                     "SVD derivedFrom TIM2 => 32 bit (sai). TIM2/5: CCR1[31:0] (p.1390)."),
    Erratum("TIM34-CNT16", "stm32g474", ("TIM3_CNT", "TIM4_CNT"), rw_mask=0x0000_FFFF,
            evidence="RM0440 p.1387: CNT 32 bit chỉ cho TIM2/TIM5 (x = 2, 5); TIM3/TIM4 là bộ đếm 16 bit. SVD derivedFrom TIM2."),
)


def for_chip(chip: str) -> dict[str, Erratum]:
    out: dict[str, Erratum] = {}
    for e in ERRATA:
        if e.chip == chip:
            for r in e.regs:
                out[r.upper()] = e
    return out
