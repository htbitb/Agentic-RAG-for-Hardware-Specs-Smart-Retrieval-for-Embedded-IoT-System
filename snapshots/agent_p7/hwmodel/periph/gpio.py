"""GPIO STM32G474: MODER / AFRL / AFRH / OTYPER / OSPEEDR / PUPDR → chức năng thực tế của từng chân; bảng AF từ `pin_functions` (P1).

RM0440 §9.4: MODERy[1:0] (00 input, 01 output, 10 alternate function, 11 analog); AFSELy[3:0] nằm ở AFRL (chân 0–7) / AFRH (chân 8–15).
Bảng AF: DS12288 Table 13 p.73 (đã trích và kiểm ở P1).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .. import data

PORTS = "ABCDEFG"
MODE_NAMES = {0: "input", 1: "output", 2: "alternate function", 3: "analog"}


@dataclass
class PinState:
    pin: str                    # "PA8"
    port: str                   # "A"
    number: int
    mode: int
    af: int
    otype: int
    ospeed: int
    pupd: int
    configured: bool            # khác trạng thái reset (mode hoặc AF)


class SignalMap:
    """(pin, af) -> [signal]; signal -> [(pin, af)] — từ bảng pin_functions của DB."""

    def __init__(self, chip: str, db_path: str | Path | None = None):
        db = Path(db_path) if db_path else data.default_db()
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT pin, af, signal FROM pin_functions WHERE chip=? AND af IS NOT NULL", (chip,)).fetchall()
        finally:
            con.close()
        self.by_pin: dict[tuple[str, int], list[str]] = {}
        self.by_signal: dict[str, list[tuple[str, int]]] = {}
        for pin, af, signal in rows:
            self.by_pin.setdefault((pin, int(af)), []).append(signal)
            self.by_signal.setdefault(signal, []).append((pin, int(af)))

    def signals(self, pin: str, af: int) -> list[str]:
        return self.by_pin.get((pin, af), [])

    def candidates(self, signal: str) -> list[tuple[str, int]]:
        return sorted(self.by_signal.get(signal, []), key=lambda t: (t[0][1], int(t[0][2:]), t[1]))


_SIG_CACHE: dict = {}


def signal_map(chip: str, db_path=None) -> SignalMap:
    db = Path(db_path) if db_path else data.default_db()
    key = (chip, str(db), db.stat().st_mtime_ns)
    if key not in _SIG_CACHE:
        _SIG_CACHE[key] = SignalMap(chip, db)
    return _SIG_CACHE[key]


def read_pins(rf, regmap, reset_rf) -> dict[str, PinState]:
    """Trạng thái 16 chân của mỗi cổng có trong DB. `reset_rf`: RegisterFile ở trạng thái reset, để biết chân nào đã bị cấu hình."""
    out: dict[str, PinState] = {}
    for c in PORTS:
        moder = regmap.get(f"GPIO{c}_MODER")
        if moder is None:
            continue
        v = {k: rf.value(regmap.get(f"GPIO{c}_{k}")) for k in ("MODER", "OTYPER", "OSPEEDR", "PUPDR", "AFRL", "AFRH")}
        r = {k: reset_rf.value(regmap.get(f"GPIO{c}_{k}")) for k in ("MODER", "AFRL", "AFRH")}
        for n in range(16):
            afr = "AFRL" if n < 8 else "AFRH"
            sh = 4 * (n % 8)
            mode, af = (v["MODER"] >> (2 * n)) & 3, (v[afr] >> sh) & 0xF
            rmode, raf = (r["MODER"] >> (2 * n)) & 3, (r[afr] >> sh) & 0xF
            out[f"P{c}{n}"] = PinState(pin=f"P{c}{n}", port=c, number=n, mode=mode, af=af, otype=(v["OTYPER"] >> n) & 1,
                                        ospeed=(v["OSPEEDR"] >> (2 * n)) & 3, pupd=(v["PUPDR"] >> (2 * n)) & 3,
                                        configured=(mode != rmode) or (af != raf))
    return out


def pin_af_effects(pins: dict[str, PinState], sigs: SignalMap, skip_pins: set[str]) -> list[dict]:
    """Chân đã cấu hình ở chế độ AF: nói rõ nó thật sự mang tín hiệu nào (kể cả khi khác ý định)."""
    out = []
    for p in sorted(pins.values(), key=lambda p: (p.port, p.number)):
        if not (p.configured and p.mode == 2):
            continue
        if p.pin in skip_pins:                                       # đã được mô tả bởi effect pwm / uart / i2c
            continue
        names = sigs.signals(p.pin, p.af)
        out.append({"kind": "pin_af", "pin": p.pin, "af": p.af, "signal": names[0] if names else None,
                    "signals": names, "otype": "open-drain" if p.otype else "push-pull"})
    return out
