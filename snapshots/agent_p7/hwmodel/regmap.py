"""Lớp thanh ghi CHUNG cho cả 3 chip, dựng từ `hw_specs.sqlite` (SVD + giá trị manual của P1).

* `RegMap`        — memory map bất biến: thanh ghi vật lý (một địa chỉ = một thanh ghi; cách nhìn Input/Output của CCMR gộp lại).
* `RegisterFile`  — trạng thái giá trị + thực thi op (write / set_bits / clear_bits / modify / read) kèm mặt nạ access.

Mã vi phạm của lớp này: SIM-BADADDR (error), SIM-RO, SIM-RESERVED, SIM-SVDONLY (warning).
Các lớp ngữ nghĩa (RCC/GPIO/TIM/...) đặt hook TRƯỚC `apply` (cổng clock) và SAU `apply` (tác dụng phụ); lớp này không biết ngữ nghĩa.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import data, errata

OPS = ("write", "set_bits", "clear_bits", "toggle_bits", "modify", "rmw", "read")
MODIFIED_WRITE = {"oneToClear", "oneToSet", "oneToToggle", "zeroToClear", "zeroToSet", "zeroToToggle", "clear", "set", "modify"}


@dataclass
class Field:
    name: str
    bit_offset: int
    bit_width: int
    access: str
    view: str = ""                     # "Input" / "Output" cho thanh ghi có hai cách nhìn (TIMx_CCMRy)
    modified_write: str | None = None

    @property
    def mask(self) -> int:
        return ((1 << self.bit_width) - 1) << self.bit_offset


@dataclass
class Register:
    chip: str
    peripheral: str
    name: str                          # tên trong DB (có thể đã có tiền tố, vd RCC_CR)
    rid: str                           # tên chuẩn "PERIPH_REG" (RCC_CR, TIM1_PSC, TIM1_CCMR1_Output...)
    address: int
    size: int
    access: str                        # RW | RO | WO
    reset: int
    reset_source: str                  # manual | svd | unknown
    rw_mask: int                       # bit ghi được
    reserved_mask: int                 # bit reserved (phải giữ nguyên giá trị reset)
    svd_only: bool
    page: int | None
    doc: str
    fields: list[Field] = field(default_factory=list)
    views: list[str] = field(default_factory=list)
    address_alias: int | None = None
    modified_write: str | None = None  # mức thanh ghi (sidecar svd_attrs)
    read_action: str | None = None
    errata: str | None = None          # id mục hiệu chỉnh đã áp dụng (hwmodel.errata)

    @property
    def mask_all(self) -> int:
        return (1 << self.size) - 1

    def field(self, name: str) -> Field | None:
        for f in self.fields:
            if f.name.upper() == name.upper():
                return f
        return None


def _norm(s: str) -> str:
    return re.sub(r"[\s.\-]+", "_", s.strip()).upper().replace("->", "_")


class RegMap:
    def __init__(self, chip: str, registers: list[Register]):
        self.chip = chip
        self.registers = registers
        self._by_name: dict[str, Register] = {}
        self._by_addr: dict[int, Register] = {}
        for r in registers:
            for key in {r.rid, *r.views}:
                self._by_name.setdefault(_norm(key), r)
            self._by_addr.setdefault(r.address, r)
            if r.address_alias is not None:
                self._by_addr.setdefault(r.address_alias, r)
        self._spans = sorted(((r.address, r.address + r.size // 8, r) for r in registers), key=lambda t: t[0])

    def get(self, name: str) -> Register | None:
        return self._by_name.get(_norm(name))

    def by_address(self, addr: int) -> Register | None:
        return self._by_addr.get(addr)

    def containing(self, addr: int) -> Register | None:
        """Thanh ghi mà [address, address+size/8) chứa `addr` (truy cập không thẳng hàng)."""
        for lo, hi, r in self._spans:
            if lo <= addr < hi:
                return r
        return None

    def names(self) -> list[str]:
        return sorted({r.rid for r in self.registers})


# ------------------------------------------------------------------------------------------ nạp từ DB
_CACHE: dict[tuple, RegMap] = {}


def _rid(peripheral: str, name: str) -> str:
    return name if name.upper().startswith(peripheral.upper() + "_") else f"{peripheral}_{name}"


def load_regmap(chip: str, db_path: str | Path | None = None, attrs_path: str | Path | None = None) -> RegMap:
    db = Path(db_path) if db_path else data.default_db()
    attrs = Path(attrs_path) if attrs_path else data.default_attrs()
    st = db.stat()
    ast = attrs.stat() if attrs.is_file() else None
    key = (chip, str(db), st.st_mtime_ns, st.st_size, str(attrs), ast.st_mtime_ns if ast else 0)
    if key not in _CACHE:
        _CACHE[key] = _build(chip, db, attrs if ast else None)
    return _CACHE[key]


def _build(chip: str, db: Path, attrs: Path | None) -> RegMap:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if con.execute("SELECT 1 FROM chips WHERE chip=?", (chip,)).fetchone() is None:
            raise KeyError(f"unknown chip {chip!r}")
        side = {}
        if attrs is not None:
            side = (json.loads(attrs.read_text(encoding="utf-8")).get("chips", {}).get(chip, {}) or {}).get("registers", {})
        fixes = errata.for_chip(chip)
        fields_by_reg: dict[int, list[sqlite3.Row]] = {}
        for f in con.execute("SELECT * FROM fields WHERE chip=? ORDER BY register_id, bit_offset", (chip,)):
            fields_by_reg.setdefault(f["register_id"], []).append(f)
        merged: dict[int, Register] = {}
        order: list[Register] = []
        for row in con.execute("SELECT * FROM registers WHERE chip=? ORDER BY id", (chip,)):
            size = int(row["size"] or 32)
            full = (1 << size) - 1
            rm_reset, svd_reset = row["rm_reset_value"], row["reset_value"]
            reset, source = (rm_reset, "manual") if rm_reset is not None else ((svd_reset, "svd") if svd_reset is not None else (0, "unknown"))
            access = {"RW": "RW", "RO": "RO", "WO": "WO"}.get(row["access"] or "RW", "RW")
            rid = _rid(row["peripheral"], row["name"])
            fl = [Field(name=f["name"], bit_offset=int(f["bit_offset"]), bit_width=int(f["bit_width"]),
                        access=(f["access"] or access), modified_write=(f["modified_write"] or None)) for f in fields_by_reg.get(row["id"], [])]
            sd = side.get(f"{row['peripheral']}.{row['name']}", {})
            for f in fl:
                fa = (sd.get("fields") or {}).get(f.name)
                if fa and fa.get("modified_write"):
                    f.modified_write = fa["modified_write"]
            reg = Register(
                chip=chip, peripheral=row["peripheral"], name=row["name"], rid=rid, address=int(row["address"]), size=size,
                access=access, reset=int(reset) & full, reset_source=source,
                rw_mask=int(row["rw_mask"] or 0) & full, reserved_mask=int(row["reserved_mask"] or 0) & full,
                svd_only=bool(row["svd_only"]), page=row["page"], doc=row["doc"], fields=fl, views=[rid],
                address_alias=(int(row["address_alias"]) if row["address_alias"] is not None else None),
                modified_write=sd.get("modified_write"), read_action=sd.get("read_action"))
            fix = fixes.get(rid.upper())
            if fix is not None:
                if fix.rw_mask is not None:
                    reg.rw_mask = fix.rw_mask & full
                    reg.reserved_mask = full & ~fix.rw_mask
                reg.errata = fix.id
            prev = merged.get(reg.address)
            if prev is not None and prev.peripheral == reg.peripheral and prev.size == reg.size:
                # hai cách nhìn của cùng một địa chỉ (TIMx_CCMR1_Input / _Output): gộp trường, bit ghi được = hợp, reserved = giao
                prev.views.append(rid)
                prev.rw_mask |= reg.rw_mask
                prev.reserved_mask &= reg.reserved_mask
                seen = {(f.name, f.bit_offset, f.bit_width) for f in prev.fields}
                for f in reg.fields:
                    if (f.name, f.bit_offset, f.bit_width) not in seen:
                        f.view = rid.rsplit("_", 1)[-1]
                        prev.fields.append(f)
                prev.svd_only = prev.svd_only and reg.svd_only
                continue
            merged[reg.address] = reg
            order.append(reg)
        # thanh ghi có hai cách nhìn (TIM1_CCMR1_Input / _Output): tên chuẩn bỏ hậu tố => TIM1_CCMR1; hai tên đầy đủ vẫn tra được
        for reg in order:
            if len(reg.views) > 1:
                base = re.sub(r"_(Input|Output)$", "", reg.views[0])
                reg.rid = base
                reg.views.append(base)
        return RegMap(chip, order)
    finally:
        con.close()


# ------------------------------------------------------------------------------------------ thực thi
def _int(v, what: str) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v.replace("_", ""), 0)
        except ValueError:
            pass
    raise ValueError(f"{what}: expected an integer or a hex string, got {v!r}")


def violation(code: str, severity: str, at_op: int | None, msg: str, **extra) -> dict:
    d = {"code": code, "severity": severity, "at_op": at_op, "msg": msg}
    d.update(extra)
    return d


@dataclass
class OpResult:
    op: dict
    reg: Register | None
    old: int = 0
    new: int = 0
    written: int | None = None         # giá trị chương trình đưa vào bus (sau RMW), trước mặt nạ access
    applied: bool = False
    violations: list[dict] = field(default_factory=list)


class RegisterFile:
    def __init__(self, regmap: RegMap):
        self.map = regmap
        self._state: dict[int, int] = {}
        self.touched: dict[int, Register] = {}          # thanh ghi đã bị ghi (cho final_registers)

    # ---- trạng thái
    def _reg(self, ref) -> Register | None:
        if isinstance(ref, Register):
            return ref
        if isinstance(ref, int):
            return self.map.by_address(ref)
        return self.map.get(ref)

    def value(self, ref) -> int:
        """Giá trị lưu trong thanh ghi (kể cả bit trạng thái RO). Không áp ngữ nghĩa đọc của WO."""
        reg = self._reg(ref)
        if reg is None:
            raise KeyError(f"no such register {ref!r}")
        return self._state.get(reg.address, reg.reset)

    def read_value(self, ref) -> int:
        reg = self._reg(ref)
        return 0 if reg.access == "WO" else self.value(reg)

    def force(self, ref, value: int) -> None:
        """Cập nhật do PHẦN CỨNG (vd cờ RDY): bỏ qua mặt nạ access."""
        reg = self._reg(ref)
        self._state[reg.address] = value & reg.mask_all

    def set_state(self, ref, value: int) -> None:
        """Nạp trạng thái ban đầu (preset) — không sinh vi phạm, không đánh dấu 'touched'."""
        self.force(ref, value)

    # ---- op
    def apply(self, op: dict, at_op: int = 0) -> OpResult:
        kind = op.get("op")
        if kind not in OPS:
            raise ValueError(f"unknown op {kind!r} (expected one of {', '.join(OPS)})")
        reg, bad = self.resolve(op, at_op)
        if reg is None:
            return OpResult(op=op, reg=None, violations=[bad])
        old = self.value(reg)
        rd = self.read_value(reg)
        if kind == "read":
            return OpResult(op=op, reg=reg, old=old, new=rd, applied=False)
        if kind == "write":
            written = _int(op["value"], "value") & reg.mask_all
        elif kind == "set_bits":
            written = (rd | _int(op.get("mask", op.get("value")), "mask")) & reg.mask_all
        elif kind == "clear_bits":
            written = rd & ~_int(op.get("mask", op.get("value")), "mask") & reg.mask_all
        elif kind == "rmw":                                              # một lệnh ghi: ((đọc & and) | or) ^ xor
            written = (((rd & _int(op.get("and", 0xFFFF_FFFF), "and")) | _int(op.get("or", 0), "or")) ^ _int(op.get("xor", 0), "xor")) & reg.mask_all
        elif kind == "toggle_bits":
            written = (rd ^ _int(op.get("mask", op.get("value")), "mask")) & reg.mask_all
        else:                                                           # modify
            if "field" in op:
                f = reg.field(op["field"])
                if f is None:
                    raise ValueError(f"{reg.rid}: no field {op['field']!r}")
                mask, val = f.mask, (_int(op["value"], "value") << f.bit_offset) & f.mask
            else:
                mask, val = _int(op["mask"], "mask"), _int(op["value"], "value")
            written = ((rd & ~mask) | (val & mask)) & reg.mask_all
        return self._store(op, reg, old, written, at_op)

    def resolve(self, op: dict, at_op: int = 0):
        """(Register, None) hoặc (None, violation SIM-BADADDR)."""
        if "reg" in op:
            reg = self.map.get(str(op["reg"]))
            if reg is None:
                return None, violation("SIM-BADADDR", "error", at_op, f"unknown register {op['reg']!r} on {self.map.chip}; write ignored", reg=str(op["reg"]))
            return reg, None
        if "addr" in op:
            addr = _int(op["addr"], "addr")
            reg = self.map.by_address(addr)
            if reg is None:
                inner = self.map.containing(addr)
                why = (f"inside {inner.rid} (partial/unaligned access is not modeled)" if inner else "no register is mapped there")
                return None, violation("SIM-BADADDR", "error", at_op, f"write to 0x{addr:08X}: {why}; ignored", addr=addr)
            return reg, None
        raise ValueError("op needs 'reg' or 'addr'")

    def _store(self, op, reg: Register, old: int, written: int, at_op: int) -> OpResult:
        vs: list[dict] = []
        if reg.svd_only:
            vs.append(violation("SIM-SVDONLY", "warning", at_op,
                                f"{reg.rid} exists only in the SVD (not found in the reference manual): the model is a guess", reg=reg.rid))
        if reg.access == "RO":
            vs.append(violation("SIM-RO", "warning", at_op, f"{reg.rid} is read-only: write ignored", reg=reg.rid))
            return OpResult(op=op, reg=reg, old=old, new=old, written=written, applied=False, violations=vs)
        bad = (written ^ old) & reg.reserved_mask
        if bad:
            vs.append(violation("SIM-RESERVED", "warning", at_op,
                                f"{reg.rid}: write changes reserved bits 0x{bad:X} (must be kept at reset value); they are ignored",
                                reg=reg.rid, bits=bad))
        new = old
        special = 0
        for f in reg.fields:
            if f.modified_write and f.modified_write != "modify":
                new, special = self._side_effect(new, special, written, f.mask & reg.rw_mask, f.modified_write)
        if reg.modified_write and reg.modified_write != "modify":
            new, special = self._side_effect(new, special, written, reg.rw_mask & ~special, reg.modified_write)
        plain = reg.rw_mask & ~special & ~reg.reserved_mask
        new = (new & ~plain) | (written & plain)
        self._state[reg.address] = new & reg.mask_all
        self.touched[reg.address] = reg
        return OpResult(op=op, reg=reg, old=old, new=new & reg.mask_all, written=written, applied=True, violations=vs)

    @staticmethod
    def _side_effect(new: int, special: int, written: int, mask: int, kind: str):
        w = written & mask
        z = ~written & mask
        if kind == "oneToClear":
            new &= ~w
        elif kind == "oneToSet":
            new |= w
        elif kind == "oneToToggle":
            new ^= w
        elif kind == "zeroToClear":
            new &= ~z
        elif kind == "zeroToSet":
            new |= z
        elif kind == "zeroToToggle":
            new ^= z
        elif kind == "clear":
            new &= ~mask
        elif kind == "set":
            new |= mask
        return new, special | mask
