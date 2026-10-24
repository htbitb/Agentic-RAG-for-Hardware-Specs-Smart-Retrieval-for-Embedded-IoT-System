"""Phân tích CMSIS-SVD -> peripherals / registers / fields với địa chỉ tuyệt đối.

Xử lý: giá trị mặc định kế thừa (device -> peripheral -> cluster -> register), `derivedFrom` (peripheral
và register), `dim`/`dimIncrement`/`dimIndex` (peripheral, cluster, register, field), cluster lồng nhau, ba cách
ghi vị trí bit (bitOffset+bitWidth, bitRange, lsb+msb). Dùng làm nguồn ground truth cho task C1.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

_ACCESS = {"read-write": "rw", "read-only": "ro", "write-only": "wo", "writeOnce": "wo", "read-writeOnce": "rw"}


@dataclass
class Field:
    name: str
    lsb: int
    msb: int
    access: str | None = None
    description: str = ""


@dataclass
class Register:
    name: str
    offset: int            # so với địa chỉ gốc của peripheral (đã cộng offset cluster)
    address: int           # địa chỉ tuyệt đối
    size: int
    access: str | None
    reset_value: int | None
    description: str = ""
    fields: list[Field] = field(default_factory=list)


@dataclass
class Peripheral:
    name: str
    base: int
    description: str = ""
    registers: list[Register] = field(default_factory=list)


@dataclass
class Device:
    name: str
    version: str
    peripherals: list[Peripheral]


def _int(text: str | None) -> int | None:
    if text is None:
        return None
    t = text.strip().replace("_", "")
    if t.startswith("#"):                      # nhị phân kiểu SVD: #0101
        return int(t[1:], 2)
    return int(t, 0)


def _txt(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _dim_indices(el: ET.Element) -> list[str] | None:
    dim = _txt(el, "dim")
    if dim is None:
        return None
    n = _int(dim)
    idx = _txt(el, "dimIndex")
    if not idx:
        return [str(i) for i in range(n)]
    if "," in idx:
        return [s.strip() for s in idx.split(",")]
    m = re.fullmatch(r"([A-Za-z]|\d+)-([A-Za-z]|\d+)", idx)
    if m:
        a, b = m.groups()
        if a.isdigit():
            return [str(i) for i in range(int(a), int(b) + 1)]
        return [chr(c) for c in range(ord(a), ord(b) + 1)]
    return [str(i) for i in range(n)]


def _subst(name: str, idx: str) -> str:
    return name.replace("[%s]", idx).replace("%s", idx)


def _norm_access(a: str | None) -> str | None:
    return _ACCESS.get(a) if a else None


class _Defaults:
    def __init__(self, size=None, access=None, reset=None):
        self.size, self.access, self.reset = size, access, reset

    def child(self, el: ET.Element) -> "_Defaults":
        return _Defaults(_int(_txt(el, "size")) or self.size,
                         _norm_access(_txt(el, "access")) or self.access,
                         _int(_txt(el, "resetValue")) if _txt(el, "resetValue") is not None else self.reset)


def _fields(reg_el: ET.Element) -> list[Field]:
    out = []
    for f in reg_el.findall("./fields/field"):
        name = _txt(f, "name") or "?"
        if _txt(f, "bitRange"):
            msb, lsb = (int(x) for x in re.findall(r"\d+", _txt(f, "bitRange")))
        elif _txt(f, "lsb") is not None and _txt(f, "msb") is not None:
            lsb, msb = _int(_txt(f, "lsb")), _int(_txt(f, "msb"))
        else:
            lsb = _int(_txt(f, "bitOffset")) or 0
            msb = lsb + (_int(_txt(f, "bitWidth")) or 1) - 1
        idxs = _dim_indices(f)
        access = _norm_access(_txt(f, "access"))
        desc = re.sub(r"\s+", " ", _txt(f, "description") or "")
        if idxs:
            inc = _int(_txt(f, "dimIncrement")) or 0
            for i, ix in enumerate(idxs):
                out.append(Field(_subst(name, ix), lsb + i * inc, msb + i * inc, access, desc))
        else:
            out.append(Field(name, lsb, msb, access, desc))
    return out


def _registers(parent: ET.Element, defaults: _Defaults, base_offset: int, prefix: str = "") -> list[tuple]:
    """Trả về [(tên, offset, size, access, reset, mô_tả, fields)] cho register + cluster lồng nhau."""
    out: list[tuple] = []
    for el in parent:
        if el.tag not in ("register", "cluster"):
            continue
        d = defaults.child(el)
        name = _txt(el, "name") or "?"
        off = _int(_txt(el, "addressOffset")) or 0
        idxs = _dim_indices(el) or [None]
        inc = _int(_txt(el, "dimIncrement")) or 0
        for i, ix in enumerate(idxs):
            nm = _subst(name, ix) if ix is not None else name
            o = base_offset + off + (i * inc if ix is not None else 0)
            if el.tag == "cluster":
                out += _registers(el, d, o, prefix + nm + "_")
            else:
                out.append((prefix + nm, o, d.size or 32, d.access, d.reset,
                            re.sub(r"\s+", " ", _txt(el, "description") or ""), _fields(el), el.get("derivedFrom")))
    return out


def parse_svd(path) -> Device:
    root = ET.parse(str(path)).getroot()
    dev_defaults = _Defaults(_int(_txt(root, "size")) or 32, _norm_access(_txt(root, "access")),
                             _int(_txt(root, "resetValue")))
    elems = {p.find("name").text.strip(): p for p in root.findall("./peripherals/peripheral")}
    cache: dict[str, list[tuple]] = {}

    def templ(name: str, stack=()) -> list[tuple]:
        """Danh sách register (tuple) của một peripheral, đã áp derivedFrom."""
        if name in cache:
            return cache[name]
        el = elems[name]
        base_regs: list[tuple] = []
        d = dev_defaults.child(el)
        parent = el.get("derivedFrom")
        if parent:
            if parent in stack or parent not in elems:
                raise ValueError(f"bad derivedFrom {parent!r} in {name}")
            base_regs = templ(parent, stack + (name,))
            d = dev_defaults.child(elems[parent]).child(el)
        own = _registers(el.find("registers"), d, 0) if el.find("registers") is not None else []
        merged = {r[0]: r for r in base_regs}
        for r in own:
            merged[r[0]] = r
        for r in list(merged.values()):                    # derivedFrom ở mức register: mượn fields của register nguồn
            if r[7]:
                src = merged.get(r[7].split(".")[-1])
                if src and not r[6]:
                    merged[r[0]] = (*r[:6], src[6], r[7])
        cache[name] = list(merged.values())
        return cache[name]

    peripherals: list[Peripheral] = []
    for name, el in elems.items():
        base = _int(_txt(el, "baseAddress")) or 0
        idxs = _dim_indices(el) or [None]
        inc = _int(_txt(el, "dimIncrement")) or 0
        for i, ix in enumerate(idxs):
            pname = _subst(name, ix) if ix is not None else name
            pbase = base + (i * inc if ix is not None else 0)
            regs = [Register(n, o, pbase + o, size, access, reset, desc, fields)
                    for (n, o, size, access, reset, desc, fields, _d) in templ(name)]
            regs.sort(key=lambda r: (r.offset, r.name))
            peripherals.append(Peripheral(pname, pbase, re.sub(r"\s+", " ", _txt(el, "description") or ""), regs))
    return Device(_txt(root, "name") or Path(path).stem, _txt(root, "version") or "", peripherals)
