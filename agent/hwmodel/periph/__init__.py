"""Lớp ngữ nghĩa STM32G474: mỗi module đọc trạng thái thanh ghi (đã qua lớp chung) và suy ra hiệu ứng vật lý.

Giao diện chung: `effects(ctx) -> (effects, violations, notes)`; không module nào ghi lại vào RegisterFile
(ngoại lệ có chủ đích: `rcc.refresh_status` mô phỏng cờ RDY/SWS do phần cứng cập nhật).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..clock_tree import ClockState
from ..regmap import RegisterFile, RegMap


@dataclass
class Ctx:
    rf: RegisterFile
    regmap: RegMap
    clocks: ClockState
    pins: dict                                                  # gpio.read_pins(...)
    gated: dict = field(default_factory=dict)                   # peripheral -> {"count", "first_at_op", "ops"}
    enabled: set = field(default_factory=set)                   # peripheral có clock
    sigmap: object = None                                       # gpio.SignalMap

    def val(self, rid: str) -> int:
        reg = self.regmap.get(rid)
        return 0 if reg is None else self.rf.value(reg)

    def clock_on(self, peripheral: str) -> bool:
        return peripheral in self.enabled
