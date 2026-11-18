"""simulate_register_writes: chạy một chuỗi op trên RegisterFile (lớp chung) + lớp ngữ nghĩa STM32G474.

Luồng mỗi op:  resolve → cổng clock (RCC) → áp dụng (mặt nạ access) → hook sau ghi (RCC: RDY/SWS, khoá PLL, giới hạn clock, Flash WS).
Cuối chuỗi: suy ra hiệu ứng (PWM / UART / I2C / chân AF) từ trạng thái cuối và báo mọi điều kiện chặn hiệu ứng thành violation.

Nguyên tắc trung thực: `unmodeled` liệt kê thanh ghi/tính năng chương trình dùng mà mô hình không hiểu — KHÔNG BAO GIỜ được tính là pass.
"""
from __future__ import annotations

import re

from .clock_tree import CR_HSEON, CR_HSION, CR_PLLON, Limits, bits, decode, load_limits
from .periph import Ctx, i2c, rcc, tim, usart
from .periph import gpio
from .regmap import OPS, RegisterFile, load_regmap, violation

SEMANTIC_CHIPS = {"stm32g474"}

_PWR_CR5_R1MODE = 1 << 8


def _op(kind, reg, **kw):
    return {"op": kind, "reg": reg, **kw}


def _pll(n: int, m_code: int = 0b0011, r_code: int = 0b00) -> dict:
    return _op("write", "RCC_PLLCFGR", value=(1 << 24) | (r_code << 25) | (n << 8) | (m_code << 4) | 0b10)


_PLL170 = [_op("clear_bits", "PWR_CR5", mask=_PWR_CR5_R1MODE), _op("modify", "FLASH_ACR", mask=0xF, value=4), _pll(85),
           _op("set_bits", "RCC_CR", mask=CR_PLLON), _op("modify", "RCC_CFGR", mask=0b11, value=0b11)]
PRESETS: dict[str, list[dict]] = {
    "reset": [],
    # HSI16 / 4 = 4 MHz  x 85 = 340 MHz VCO  / 2 = 170 MHz; Range 1 boost (R1MODE = 0), Flash 4 WS (RM Table 9 p.98)
    "sysclk_170mhz_pll_hsi16_apb_div1": _PLL170,
    "sysclk_170mhz_pll_hsi16_apb2_div2": _PLL170 + [_op("modify", "RCC_CFGR", mask=0b111 << 11, value=0b100 << 11)],
    "sysclk_170mhz_pll_hsi16_apb1_div2": _PLL170 + [_op("modify", "RCC_CFGR", mask=0b111 << 8, value=0b100 << 8)],
    # 16 / 4 = 4 MHz x 40 = 160 MHz / 2 = 80 MHz; Flash 2 WS (Table 9: <= 90 MHz Range 1 normal, <= 102 MHz boost)
    "sysclk_80mhz_pll_hsi16_apb_div1": [_op("modify", "FLASH_ACR", mask=0xF, value=2), _pll(40),
                                        _op("set_bits", "RCC_CR", mask=CR_PLLON), _op("modify", "RCC_CFGR", mask=0b11, value=0b11)],
}

_RCC_MODELED = {"RCC_CR", "RCC_CFGR", "RCC_PLLCFGR", "RCC_CCIPR", "RCC_CCIPR2", "RCC_AHB1ENR", "RCC_AHB2ENR", "RCC_AHB3ENR",
                "RCC_APB1ENR1", "RCC_APB1ENR2", "RCC_APB2ENR"}
_CLOCK_REGS = {"RCC_CR", "RCC_CFGR", "RCC_PLLCFGR", "FLASH_ACR", "PWR_CR1", "PWR_CR5"}
_GPIO_MODELED = {"MODER", "OTYPER", "OSPEEDR", "PUPDR", "AFRL", "AFRH"}

ASSUMPTIONS = [
    "HSIRDY/HSERDY/PLLRDY (and SWS) rise immediately when the source is enabled: no start-up time is simulated; polling loops on RDY are skipped",
    "steady state: preloaded registers (PSC, ARR, CCRx) are assumed transferred to their shadow registers by an update event",
    "tim_brk / tim_brk2 break inputs are not asserted",
    "writes to a peripheral whose RCC clock enable bit is 0 are ignored (RM0440 p.285: access is 'not supported')",
]


def _short(reg) -> str:
    s = reg.rid[len(reg.peripheral) + 1:] if reg.rid.upper().startswith(reg.peripheral.upper() + "_") else reg.rid
    return re.sub(r"_(Input|Output)$", "", s)


def _is_modeled(reg) -> bool:
    per, rid = reg.peripheral, reg.rid
    if per == "RCC":
        return rid in _RCC_MODELED
    if per == "FLASH":
        return rid == "FLASH_ACR"
    if per == "PWR":
        return rid in {"PWR_CR1", "PWR_CR5"}
    if re.fullmatch(r"GPIO[A-G]", per):
        return _short(reg) in _GPIO_MODELED
    if per in tim.TIMERS:
        return _short(reg) in tim.MODELED_REGS
    if per in usart.USARTS:
        return _short(reg) in usart.MODELED_REGS
    if per in i2c.I2CS:
        return _short(reg) in i2c.MODELED_REGS
    return False


class Simulator:
    def __init__(self, chip: str, initial="reset", hse_hz: int | None = None, db_path=None):
        self.chip = chip
        self.regmap = load_regmap(chip, db_path)                      # KeyError nếu chip lạ
        self.rf = RegisterFile(self.regmap)
        self._reset_rf = RegisterFile(self.regmap)
        self.semantic = chip in SEMANTIC_CHIPS
        self.hse_hz = hse_hz
        self.violations: list[dict] = []
        self.gated: dict[str, dict] = {}
        self.notes: list[str] = []
        self.unmodeled: set[str] = set()
        self._seen: set = set()
        self._prev_source = None
        if self.semantic:
            self.limits = load_limits(chip, db_path)
            self.sigmap = gpio.signal_map(chip, db_path)
        else:
            self.limits = self.sigmap = None
            self.notes.append(f"no semantic model for {chip}: only the generic register layer (memory map, reset values, access masks) is simulated")
        self._apply_initial(initial)

    # ------------------------------------------------------------------ trạng thái ban đầu
    def _apply_initial(self, initial) -> None:
        spec = {"preset": initial} if isinstance(initial, str) else dict(initial or {})
        name = spec.get("preset", "reset")
        if name not in PRESETS or (not self.semantic and name != "reset"):
            raise ValueError(f"unknown initial state {name!r}; expected one of {', '.join(PRESETS)}")
        if spec.get("hse_hz") is not None and self.hse_hz is None:
            self.hse_hz = int(spec["hse_hz"])
        for op in [*PRESETS[name], *spec.get("ops", [])]:
            self.rf.apply(op, at_op=-1)
            if self.semantic:
                rcc.refresh_status(self.rf, self.regmap)
        self.rf.touched.clear()
        if self.semantic:
            self._prev_source = self._clock_state().sysclk_source
        self.initial = name

    # ------------------------------------------------------------------ chạy
    def run(self, ops: list[dict]) -> dict:
        for i, op in enumerate(ops):
            self._step(i, op)
        return self._result(len(ops))

    def _step(self, i: int, op: dict) -> None:
        kind = op.get("op")
        if kind not in OPS:
            raise ValueError(f"unknown op {kind!r} (expected one of {', '.join(OPS)})")
        reg, bad = self.rf.resolve(op, i)
        if reg is None:
            self.violations.append(bad)
            return
        if self.semantic and kind != "read" and rcc.clock_on(self.rf, self.regmap, reg.peripheral) is False:
            self._record_gated(reg, i)
            self._note_unmodeled(reg)
            return
        res = self.rf.apply(op, i)
        self.violations.extend(res.violations)
        if kind == "read":
            return
        self._note_unmodeled(reg)
        if self.semantic and res.applied:
            self._after_write(res, i)

    def _note_unmodeled(self, reg) -> None:
        if reg.access == "RO":
            return
        if not self.semantic or not _is_modeled(reg):
            self.unmodeled.add(reg.rid)

    def _record_gated(self, reg, i: int) -> None:
        per = reg.peripheral
        g = self.gated.get(per)
        if g is None:
            g = self.gated[per] = {"count": 0, "first_at_op": i, "ops": []}
            self.violations.append(violation(
                "SIM-CLK-GATE", "error", i,
                f"write to {reg.rid} while {rcc.enable_name(per)} = 0: ignored on real hardware "
                f"(RM0440 p.285: peripheral registers are not accessible while the clock is off)", peripheral=per, reg=reg.rid, count=0, ops=[]))
        g["count"] += 1
        g["ops"].append(i)
        v = next(v for v in self.violations if v["code"] == "SIM-CLK-GATE" and v.get("peripheral") == per)
        v["count"], v["ops"] = g["count"], list(g["ops"])

    # ------------------------------------------------------------------ hook sau ghi
    def _after_write(self, res, i: int) -> None:
        reg = res.reg
        if reg.peripheral == "RCC":
            self._rcc_write(res, i)
        if reg.rid in _CLOCK_REGS:
            rcc.refresh_status(self.rf, self.regmap)
            self._check_clocks(i)
        if reg.peripheral in usart.USARTS or reg.peripheral in i2c.I2CS:
            self._write_locks(res, i)

    def _write_locks(self, res, i: int) -> None:
        """Trường chỉ ghi được khi ngoại vi TẮT (USART: UE = 0; I2C: PE = 0). Ghi khi đang bật bị bỏ qua (mô hình hoá 'can only be written when disabled')
        và báo SIM-WRITE-LOCKED. UE/PE lấy theo giá trị TRƯỚC lệnh ghi (một lệnh ghi CR1 vừa đặt định dạng vừa bật UE là hợp lệ)."""
        reg, per = res.reg, res.reg.peripheral
        short = _short(reg)
        if per in usart.USARTS:
            lock = usart.WRITE_LOCKED.get(short)
            enable = (res.old if short == "CR1" else self.rf.value(self.regmap.get(f"{per}_CR1"))) & usart.CR1_UE
            page = {"BRR": "p.1755", "CR1": "p.1741-1742", "CR2": "p.1749"}.get(short, "")
            what = "USART is disabled (UE = 0)"
        else:
            lock = i2c.WRITE_LOCKED.get(short)
            enable = (res.old if short == "CR1" else self.rf.value(self.regmap.get(f"{per}_CR1"))) & 1
            page, what = "p.1681", "I2C peripheral is disabled (PE = 0)"
        if not lock or not enable:
            return
        changed = (res.new ^ res.old) & lock
        if changed:
            self.rf.force(reg, (res.new & ~lock) | (res.old & lock))
            self.violations.append(violation(
                "SIM-WRITE-LOCKED", "error", i,
                f"{reg.rid} bits 0x{changed:X} can only be written when the {what} (RM0440 {page}): write ignored", reg=reg.rid, peripheral=per, bits=changed))

    def _rcc_write(self, res, i: int) -> None:
        reg = res.reg
        cs = self._clock_state()
        sws = bits(self.rf.value(self.regmap.get("RCC_CFGR")), 2, 2)
        if reg.rid == "RCC_PLLCFGR" and self.rf.value(self.regmap.get("RCC_CR")) & CR_PLLON:
            protected = rcc.PLL_PROTECTED | (rcc.PLLREN if sws == 0b11 else 0)
            changed = (res.new ^ res.old) & protected
            if changed:
                self.rf.force(reg, (res.new & ~protected) | (res.old & protected))
                self.violations.append(violation(
                    "SIM-RCC-LOCKED", "error", i,
                    "RCC_PLLCFGR PLLSRC/PLLM/PLLN/PLLR can only be written while the PLL is disabled (RM0440 p.292-293): write ignored",
                    reg=reg.rid, bits=changed))
        if reg.rid == "RCC_CR":
            in_use = {CR_PLLON: sws == 0b11,
                      CR_HSION: sws == 0b01 or (sws == 0b11 and cs.pll["source"] == "HSI16"),
                      CR_HSEON: sws == 0b10 or (sws == 0b11 and cs.pll["source"] == "HSE")}
            for bit, used in in_use.items():
                if used and res.old & bit and not self.rf.value(reg) & bit:
                    self.rf.force(reg, self.rf.value(reg) | bit)
                    self.violations.append(violation(
                        "SIM-RCC-LOCKED", "error", i,
                        f"RCC_CR bit 0x{bit:X} cannot be cleared while that clock is (directly or indirectly) the system clock: write ignored",
                        reg=reg.rid, bits=bit))

    def _clock_state(self):
        g = lambda r: self.rf.value(self.regmap.get(r))                       # noqa: E731
        return decode(g("RCC_CR"), g("RCC_CFGR"), g("RCC_PLLCFGR"), self.hse_hz)

    # ------------------------------------------------------------------ giới hạn clock / Flash
    def _check_clocks(self, i: int | None) -> None:
        g = lambda r: self.rf.value(self.regmap.get(r))                       # noqa: E731
        cs, lim = self._clock_state(), self.limits
        mode = Limits.mode(bits(g("PWR_CR1"), 9, 2), bits(g("PWR_CR5"), 8, 1))
        found: list[dict] = []

        def limit(key, actual, bound, kind, msg):
            found.append({"code": "SIM-CLK-LIMIT", "severity": "error", "at_op": i, "limit": key, "actual_hz": actual, f"{kind}_hz": bound, "msg": msg})

        pll, cr = cs.pll, g("RCC_CR")
        if pll["on"]:
            src_on = (pll["source"] == "HSI16" and cr & CR_HSION) or (pll["source"] == "HSE" and cr & CR_HSEON)
            if pll["source"] == "none" or not src_on:
                found.append({"code": "SIM-CLK-NOSRC", "severity": "error", "at_op": i, "msg":
                              "PLLON = 1 but PLLSRC selects no running oscillator: the PLL never locks"})
            elif pll["vco_in_hz"] is not None:
                lo, hi = lim.pll_in
                vin, vco = pll["vco_in_hz"], pll["vco_hz"]
                if vin < lo:
                    limit("pll_in_min", vin, lo, "min", f"PLL input {vin / 1e6:g} MHz < {lo / 1e6:g} MHz (DS12288 Table 46 p.123): increase the HSI16/HSE divider is wrong, decrease PLLM")
                if vin > hi:
                    limit("pll_in_max", vin, hi, "max", f"PLL input {vin / 1e6:g} MHz > {hi / 1e6:g} MHz (DS12288 Table 46 p.123): increase PLLM")
                if pll["n"] < 8:
                    limit("plln_min", pll["n"], 8, "min", f"PLLN = {pll['n']} < 8 is a wrong configuration (RM0440 p.293)")
                vlo, vhi = lim.vco["range2" if mode == "range2" else "range1"]
                if vco < vlo:
                    limit("vco_min", vco, vlo, "min", f"VCO {vco / 1e6:g} MHz < {vlo / 1e6:g} MHz (DS12288 Table 46 p.123)")
                if vco > vhi:
                    limit("vco_max", vco, vhi, "max", f"VCO {vco / 1e6:g} MHz > {vhi / 1e6:g} MHz (DS12288 Table 46 p.123)")
        s = cs.sysclk_hz
        if s:
            if s > lim.hclk_max:
                limit("sysclk_max", s, lim.hclk_max, "max", f"SYSCLK {s / 1e6:g} MHz > {lim.hclk_max / 1e6:g} MHz (DS12288 Table 17 p.84)")
            elif mode == "normal" and s > 150e6:
                limit("hclk_max_range1_normal", s, 150e6, "max",
                      f"SYSCLK {s / 1e6:g} MHz > 150 MHz in Range 1 normal mode: clear PWR_CR5.R1MODE for boost mode (RM0440 p.232-233, Table 38)")
            elif mode == "range2" and s > 26e6:
                limit("sysclk_max_range2", s, 26e6, "max", f"SYSCLK {s / 1e6:g} MHz > 26 MHz in voltage Range 2 (RM0440 p.232)")
        if cs.hclk_hz:
            need = lim.needed_ws(cs.hclk_hz, mode)
            lat = bits(g("FLASH_ACR"), 0, 4)
            if need is not None and lat < need:
                found.append({"code": "SIM-FLASH-WS", "severity": "error", "at_op": i, "latency": lat, "required": need, "hclk_hz": cs.hclk_hz,
                              "msg": f"HCLK {cs.hclk_hz / 1e6:g} MHz needs FLASH_ACR.LATENCY >= {need} ({mode} mode, RM0440 Table 9 p.98), found {lat}"})
        if cs.sysclk_source == "PLL" and self._prev_source != "PLL" and (cs.hclk_hz or 0) > 80e6 and cs.hpre_div == 1:
            found.append({"code": "SIM-CLK-PROC", "severity": "warning", "at_op": i, "msg":
                          "switching from HSI16/HSE to the PLL with HCLK > 80 MHz: RM0440 p.279-280 requires dividing HCLK by 2 (HPRE) first and restoring it "
                          "after >= 1 us (p.233 for > 150 MHz); timing is not simulated"})
        self._prev_source = cs.sysclk_source
        for v in found:
            key = (v["code"], v.get("limit"), v.get("actual_hz"), v.get("latency"))
            if key not in self._seen:
                self._seen.add(key)
                self.violations.append(v)

    # ------------------------------------------------------------------ kết quả
    def _result(self, n_ops: int) -> dict:
        res: dict = {"chip": self.chip, "initial": self.initial, "n_ops": n_ops}
        violations = list(self.violations)
        effects: list[dict] = []
        unmodeled = set(self.unmodeled)
        assumptions: list[str] = []
        clocks: dict = {}
        if self.semantic:
            g = lambda r: self.rf.value(self.regmap.get(r))                   # noqa: E731
            cs = self._clock_state()
            enabled = rcc.enabled_peripherals(self.rf, self.regmap)
            pins = gpio.read_pins(self.rf, self.regmap, self._reset_rf)
            ctx = Ctx(self.rf, self.regmap, cs, pins, gated=self.gated, enabled=enabled, sigmap=self.sigmap)
            cfgr = g("RCC_CFGR")
            if bits(cfgr, 0, 2) != bits(cfgr, 2, 2):
                names = {0b01: "HSI16", 0b10: "HSE", 0b11: "PLL"}
                hint = (" (RCC_PLLCFGR.PLLREN = 0: the PLL R output that feeds SYSCLK is disabled)"
                        if bits(cfgr, 0, 2) == 0b11 and not g("RCC_PLLCFGR") & rcc.PLLREN else "")
                violations.append(violation("SIM-CLK-NOSRC", "error", None,
                                            f"RCC_CFGR.SW selects {names.get(bits(cfgr, 0, 2), '?')} but that clock never became ready: SYSCLK stays "
                                            f"{cs.sysclk_source}{hint}"))
            tim_e, tim_v, tim_u, tim_a = tim.effects(ctx)
            us_e, us_v, us_u = usart.effects(ctx)
            i2_e, i2_v = i2c.effects(ctx)
            effects = tim_e + us_e + i2_e
            skip = {e["pin"] for e in tim_e if e.get("pin")} | {p for e in us_e for p in (e["tx_pin"], e["rx_pin"]) if p} \
                | {p for e in i2_e for p in (e["scl_pin"], e["sda_pin"]) if p}
            effects += gpio.pin_af_effects(pins, self.sigmap, skip)
            violations += tim_v + us_v + i2_v
            unmodeled |= set(tim_u) | set(us_u)
            assumptions = list(ASSUMPTIONS) + tim_a
            clocks = {**cs.as_dict(), "hse_hz": self.hse_hz, "enabled_peripherals": sorted(enabled)}
            notes = list(self.notes) + list(cs.notes)
            if self.hse_hz is None and (cs.pll["source"] == "HSE" or cs.sysclk_source == "HSE"):
                notes.append("the board's HSE frequency (hse_hz) was not provided")
        else:
            notes = list(self.notes)
        res.update({
            "final_registers": {r.rid: f"0x{self.rf.value(r):0{r.size // 4}X}" for r in sorted(self.rf.touched.values(), key=lambda r: r.address)},
            "effects": effects, "violations": violations, "unmodeled": sorted(unmodeled), "clocks": clocks,
            "assumptions": assumptions, "notes": notes,
            "ok": not any(v["severity"] == "error" for v in violations)})
        return res


def simulate_register_writes(chip: str, ops: list[dict], initial="reset", hse_hz: int | None = None, db_path=None) -> dict:
    """ops: [{"op": "write"|"set_bits"|"clear_bits"|"modify"|"read", "reg": "TIM1_PSC" | "addr": 0x..., "value"/"mask"/"field"}].
    initial: tên preset ("reset", "sysclk_170mhz_pll_hsi16_apb_div1", ...) hoặc {"preset", "hse_hz", "ops"}."""
    return Simulator(chip, initial=initial, hse_hz=hse_hz, db_path=db_path).run(list(ops))
