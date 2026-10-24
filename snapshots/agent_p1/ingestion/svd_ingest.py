"""CMSIS-SVD -> mô hình thanh ghi -> SQLite (`data/hw_specs.sqlite`).

Parser viết ĐỘC LẬP với `eval/generators` (D05): không import, không chép code — để lỗi parser không thể "vô hình"
(test `test_svd_parity.py` so khớp hai parser). Xử lý: kế thừa mặc định (device -> peripheral -> cluster -> register
-> field) cho size/access/resetValue/resetMask, `derivedFrom` (peripheral / register / field / enumeratedValues),
`dim`+`dimIncrement`+`dimIndex` (peripheral / cluster / register / field, tên có `%s` hoặc `[%s]`), cluster lồng nhau,
`enumeratedValues` (hex, `#nhị phân` có `x`, `isDefault`), `writeConstraint`, `alternatePeripheral/Register`,
và dẫn xuất `reserved_mask` / `rw_mask` từ phần bù của các field.

SVD là dữ liệu không tin cậy: chỉ parse (không thực thi); từ chối tài liệu có khai báo ENTITY.
"""
from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

ACCESS = {"read-write": "RW", "read-only": "RO", "write-only": "WO", "writeOnce": "WO1", "read-writeOnce": "RW1"}
WRITABLE = {"RW", "WO", "WO1", "RW1"}


# --------------------------------------------------------------------------- numbers / text
def parse_number(text: str | None) -> int | None:
    """Số SVD: thập phân, `0x..`, `#nhị phân`. Trả None nếu rỗng hoặc có bit 'x' (don't care)."""
    if text is None:
        return None
    s = text.strip().replace("_", "")
    if not s:
        return None
    try:
        if s.startswith("#"):
            return int(s[1:], 2)
        if s[:2] in ("0x", "0X"):
            return int(s[2:], 16)
        if s[:2] in ("0b", "0B"):
            return int(s[2:], 2)
        return int(s, 10)
    except ValueError:
        return None


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# --------------------------------------------------------------------------- model
@dataclass
class EnumValue:
    name: str
    value: int | None
    value_raw: str
    description: str = ""
    is_default: bool = False


@dataclass
class Field:
    name: str
    bit_offset: int
    bit_width: int
    access: str
    description: str = ""
    modified_write: str | None = None
    read_action: str | None = None
    write_constraint: str | None = None
    enum_usage: str | None = None
    enums: list[EnumValue] = field(default_factory=list)

    @property
    def mask(self) -> int:
        return ((1 << self.bit_width) - 1) << self.bit_offset


@dataclass
class Register:
    name: str                       # có tiền tố cluster nếu nằm trong cluster: "PSEL.SCK"
    short_name: str
    cluster_path: str | None
    offset: int                     # so với base của peripheral (đã cộng offset cluster)
    address: int
    size: int
    access: str
    reset_value: int | None
    reset_mask: int | None
    description: str = ""
    fields: list[Field] = field(default_factory=list)
    array_base: str | None = None
    array_index: str | None = None
    alternate_register: str | None = None
    reserved_mask: int = 0
    rw_mask: int = 0
    has_fields: bool = False
    overlapping_fields: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Peripheral:
    name: str
    base_address: int
    group: str | None = None
    description: str = ""
    derived_from: str | None = None
    alternate_peripheral: str | None = None
    address_blocks: list[tuple[int, int, str]] = field(default_factory=list)
    registers: list[Register] = field(default_factory=list)
    _index: dict | None = field(default=None, repr=False, compare=False)

    def register(self, name: str) -> Register:
        if self._index is None:
            idx: dict[str, Register] = {}
            for r in self.registers:
                idx[r.name] = r
            shorts: dict[str, list[Register]] = {}
            for r in self.registers:
                shorts.setdefault(r.short_name, []).append(r)
            for s, rs in shorts.items():
                if len(rs) == 1:
                    idx.setdefault(s, rs[0])
            self._index = idx
        try:
            return self._index[name]
        except KeyError:
            raise KeyError(f"{self.name}: no register {name!r}") from None


@dataclass
class Device:
    name: str
    description: str
    peripherals: list[Peripheral]

    def peripheral(self, name: str) -> Peripheral:
        for p in self.peripherals:
            if p.name == name:
                return p
        raise KeyError(name)


# --------------------------------------------------------------------------- inherited properties
@dataclass(frozen=True)
class _Props:
    size: int = 32
    access: str = "RW"
    reset_value: int | None = 0
    reset_mask: int | None = 0xFFFFFFFF

    def over(self, el: ET.Element) -> "_Props":
        p = self
        v = parse_number(el.findtext("size"))
        if v is not None:
            p = replace(p, size=v)
        a = _clean(el.findtext("access"))
        if a in ACCESS:
            p = replace(p, access=ACCESS[a])
        v = parse_number(el.findtext("resetValue"))
        if v is not None:
            p = replace(p, reset_value=v)
        v = parse_number(el.findtext("resetMask"))
        if v is not None:
            p = replace(p, reset_mask=v)
        return p


@dataclass
class _PeriphDef:
    props: _Props
    group: str | None
    description: str
    items: list[ET.Element]
    address_blocks: list[tuple[int, int, str]]
    derived_from: str | None = None


# --------------------------------------------------------------------------- dim
def _dim_indices(el: ET.Element) -> list[str] | None:
    dim = parse_number(el.findtext("dim"))
    if dim is None:
        return None
    raw = _clean(el.findtext("dimIndex"))
    if not raw:
        return [str(i) for i in range(dim)]
    if "," in raw:
        return [x.strip() for x in raw.split(",")]
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", raw)
    if m:
        return [str(i) for i in range(int(m.group(1)), int(m.group(2)) + 1)]
    m = re.fullmatch(r"([A-Za-z])\s*-\s*([A-Za-z])", raw)
    if m:
        return [chr(c) for c in range(ord(m.group(1)), ord(m.group(2)) + 1)]
    return [raw] if dim == 1 else [str(i) for i in range(dim)]


def _expand(el: ET.Element) -> list[tuple[ET.Element, str | None, int, str | None]]:
    """Mở mảng `dim`: [(phần tử đã thay tên, chỉ số, độ lệch dimIncrement*i, tên gốc dạng mảng)]. Không có dim -> 1 phần tử."""
    idx = _dim_indices(el)
    if idx is None:
        return [(el, None, 0, None)]
    inc = parse_number(el.findtext("dimIncrement")) or 0
    base = _clean(el.findtext("name"))
    out = []
    for i, label in enumerate(idx):
        e = copy.deepcopy(el)
        for tag in ("dim", "dimIncrement", "dimIndex", "dimName", "dimArrayIndex"):
            for x in e.findall(tag):
                e.remove(x)
        e.find("name").text = base.replace("%s", label)
        out.append((e, label, inc * i, re.sub(r"\[?%s\]?", "", base)))
    return out


def _merge(base: ET.Element, own: ET.Element) -> ET.Element:
    """derivedFrom: phần tử `own` ghi đè từng thẻ con của `base`; `fields`/`registers` hợp nhất theo tên."""
    out = copy.deepcopy(base)
    for k, v in own.attrib.items():
        if k != "derivedFrom":
            out.set(k, v)
    for child in own:
        old = out.find(child.tag)
        if old is None:
            out.append(copy.deepcopy(child))
        elif child.tag in ("fields", "registers"):
            names = {_clean(c.findtext("name")): c for c in old}
            for c in child:
                n = _clean(c.findtext("name"))
                if n in names:
                    old.remove(names[n])
                old.append(copy.deepcopy(c))
        else:
            out.remove(old)
            out.append(copy.deepcopy(child))
    return out


# --------------------------------------------------------------------------- builder
class _Builder:
    def __init__(self, root: ET.Element):
        self.root = root
        self.dev = _Props().over(root)
        # phần tử peripheral (đã mở dim) theo tên
        self.pel: dict[str, ET.Element] = {}
        self.order: list[str] = []
        pers = root.find("peripherals")
        for p in (pers if pers is not None else []):
            for e, _label, delta, _base in _expand(p):
                if delta:
                    bt = e.find("baseAddress")
                    bt.text = str((parse_number(bt.text) or 0) + delta)
                n = _clean(e.findtext("name"))
                self.pel[n] = e
                self.order.append(n)
        self._defs: dict[str, _PeriphDef] = {}
        self._enum_index = self._index_enums()

    # ----- peripherals
    def peripheral_def(self, name: str, stack: tuple = ()) -> _PeriphDef:
        if name in self._defs:
            return self._defs[name]
        el = self.pel[name]
        reg_el = el.find("registers")
        own_items = list(reg_el) if reg_el is not None else []
        blocks = [(parse_number(b.findtext("offset")) or 0, parse_number(b.findtext("size")) or 0,
                   _clean(b.findtext("usage"))) for b in el.findall("addressBlock")]
        base_name = el.get("derivedFrom")
        if base_name:
            if base_name not in self.pel:
                raise ValueError(f"peripheral {name}: derivedFrom {base_name!r} not found")
            if name in stack:
                raise ValueError(f"peripheral {name}: derivedFrom cycle")
            b = self.peripheral_def(base_name, stack + (name,))
            items = list(b.items)
            for it in own_items:  # phần tử của peripheral dẫn xuất thay thế mục cùng tên của base
                n = _clean(it.findtext("name"))
                items = [x for x in items if _clean(x.findtext("name")) != n]
                items.append(it)
            d = _PeriphDef(b.props.over(el), _clean(el.findtext("groupName")) or b.group,
                           _clean(el.findtext("description")) or b.description, items,
                           blocks or b.address_blocks, base_name)
        else:
            d = _PeriphDef(self.dev.over(el), _clean(el.findtext("groupName")) or None,
                           _clean(el.findtext("description")), own_items, blocks)
        self._defs[name] = d
        return d

    def build(self) -> list[Peripheral]:
        out = []
        for name in self.order:
            d = self.peripheral_def(name)
            el = self.pel[name]
            base = parse_number(el.findtext("baseAddress")) or 0
            per = Peripheral(name=name, base_address=base, group=d.group, description=d.description,
                             derived_from=d.derived_from,
                             alternate_peripheral=_clean(el.findtext("alternatePeripheral")) or None,
                             address_blocks=d.address_blocks)
            self._registers(per, d.items, d.props, base, d.items, "", 0)
            out.append(per)
        return out

    # ----- registers / clusters
    def _find_register_el(self, ref: str, siblings: list[ET.Element], current: str) -> ET.Element:
        parts = ref.split(".")
        for s in siblings:
            if s.tag == "register" and _clean(s.findtext("name")) == ref:
                return s
        if len(parts) >= 2 and parts[0] in self.pel:
            items = list(self.peripheral_def(parts[0]).items)
            for part in parts[1:-1]:
                items = [c for it in items if it.tag == "cluster" and _clean(it.findtext("name")) == part for c in it]
            for it in items:
                if it.tag == "register" and _clean(it.findtext("name")) == parts[-1]:
                    return it
        raise ValueError(f"{current}: register derivedFrom {ref!r} not found")

    def _registers(self, per: Peripheral, items: list[ET.Element], props: _Props, base: int,
                   siblings: list[ET.Element], prefix: str, offset_acc: int) -> None:
        for it in items:
            if it.tag == "register":
                src = it
                ref = it.get("derivedFrom")
                if ref:
                    src = _merge(self._find_register_el(ref, siblings, per.name), it)
                for e, label, delta, arr in _expand(src):
                    self._one_register(per, e, props, prefix, offset_acc + delta, label, arr)
            elif it.tag == "cluster":
                for e, label, delta, _arr in _expand(it):
                    cprops = props.over(e)
                    off = offset_acc + delta + (parse_number(e.findtext("addressOffset")) or 0)
                    name = _clean(e.findtext("name"))
                    self._registers(per, list(e), cprops, base, list(e), f"{prefix}{name}.", off)

    def _one_register(self, per: Peripheral, el: ET.Element, props: _Props, prefix: str, delta: int,
                      label: str | None, arr: str | None) -> None:
        rprops = props.over(el)
        short = _clean(el.findtext("name"))
        offset = delta + (parse_number(el.findtext("addressOffset")) or 0)
        fields = self._fields(per, el, rprops)
        full = (1 << rprops.size) - 1
        cover = 0
        rw = 0
        overlaps: list[tuple[str, str]] = []
        for i, f in enumerate(fields):
            for g in fields[:i]:
                if f.mask & g.mask:
                    overlaps.append((g.name, f.name))
            cover |= f.mask
            if f.access in WRITABLE:
                rw |= f.mask
        if fields:
            reserved, rwm = full & ~cover, rw & full
        else:
            reserved, rwm = 0, (full if rprops.access in WRITABLE else 0)
        per.registers.append(Register(
            name=prefix + short, short_name=short, cluster_path=prefix[:-1] or None, offset=offset,
            address=per.base_address + offset, size=rprops.size, access=rprops.access,
            reset_value=rprops.reset_value, reset_mask=rprops.reset_mask, description=_clean(el.findtext("description")),
            fields=fields, array_base=(prefix + arr) if arr else None, array_index=label,
            alternate_register=_clean(el.findtext("alternateRegister")) or None,
            reserved_mask=reserved, rw_mask=rwm, has_fields=bool(fields), overlapping_fields=overlaps))

    # ----- fields / enums
    def _fields(self, per: Peripheral, reg_el: ET.Element, rprops: _Props) -> list[Field]:
        fs = reg_el.find("fields")
        if fs is None:
            return []
        out: list[Field] = []
        raw = list(fs)
        for f in raw:
            src = f
            ref = f.get("derivedFrom")
            if ref:
                tgt = next((x for x in raw if _clean(x.findtext("name")) == ref.split(".")[-1]), None)
                if tgt is None:
                    raise ValueError(f"{per.name}: field derivedFrom {ref!r} not found")
                src = _merge(tgt, f)
            for e, _label, delta, _arr in _expand(src):
                off, width = self._bit_range(e)
                acc = _clean(e.findtext("access"))
                out.append(Field(
                    name=_clean(e.findtext("name")), bit_offset=off + delta, bit_width=width,
                    access=ACCESS.get(acc, rprops.access), description=_clean(e.findtext("description")),
                    modified_write=_clean(e.findtext("modifiedWriteValues")) or None,
                    read_action=_clean(e.findtext("readAction")) or None,
                    write_constraint=self._write_constraint(e), **self._enums(e, per.name, reg_el)))
        return out

    @staticmethod
    def _bit_range(e: ET.Element) -> tuple[int, int]:
        bo, bw = parse_number(e.findtext("bitOffset")), parse_number(e.findtext("bitWidth"))
        if bo is not None:
            return bo, bw if bw is not None else 1
        br = _clean(e.findtext("bitRange"))
        m = re.fullmatch(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", br)
        if m:
            msb, lsb = int(m.group(1)), int(m.group(2))
            return lsb, msb - lsb + 1
        lsb, msb = parse_number(e.findtext("lsb")), parse_number(e.findtext("msb"))
        if lsb is not None and msb is not None:
            return lsb, msb - lsb + 1
        raise ValueError(f"field {_clean(e.findtext('name'))}: no bit position")

    @staticmethod
    def _write_constraint(e: ET.Element) -> str | None:
        wc = e.find("writeConstraint")
        if wc is None:
            return None
        if _clean(wc.findtext("writeAsRead")).lower() == "true":
            return "write as read"
        if _clean(wc.findtext("useEnumeratedValues")).lower() == "true":
            return "enumerated values only"
        rng = wc.find("range")
        if rng is not None:
            return f"range {parse_number(rng.findtext('minimum'))}..{parse_number(rng.findtext('maximum'))}"
        return None

    def _index_enums(self) -> dict[str, ET.Element]:
        """Chỉ mục enumeratedValues có tên theo đường dẫn 'P.R.F.E' (thô, trước khi mở dim) để giải `derivedFrom`."""
        idx: dict[str, ET.Element] = {}
        for pname, p in self.pel.items():
            for reg in p.iter("register"):
                for f in reg.iter("field"):
                    for ev in f.findall("enumeratedValues"):
                        en = _clean(ev.findtext("name"))
                        if en:
                            key = ".".join([pname, _clean(reg.findtext("name")), _clean(f.findtext("name")), en])
                            idx[key] = ev
        return idx

    def _enum_ref(self, ref: str) -> ET.Element:
        if ref in self._enum_index:
            return self._enum_index[ref]
        tail = "." + ref
        hits = [v for k, v in self._enum_index.items() if k.endswith(tail)]
        if len(hits) >= 1:
            return hits[0]
        raise ValueError(f"enumeratedValues derivedFrom {ref!r} not found")

    def _enums(self, f: ET.Element, pname: str, reg_el: ET.Element) -> dict:
        usage = None
        values: list[EnumValue] = []
        for ev in f.findall("enumeratedValues"):
            src = ev
            if ev.get("derivedFrom"):
                src = self._enum_ref(ev.get("derivedFrom"))
            usage = usage or _clean(src.findtext("usage")) or None
            for v in src.findall("enumeratedValue"):
                raw = _clean(v.findtext("value"))
                values.append(EnumValue(
                    name=_clean(v.findtext("name")), value=parse_number(raw), value_raw=raw,
                    description=_clean(v.findtext("description")),
                    is_default=_clean(v.findtext("isDefault")).lower() == "true"))
        return {"enums": values, "enum_usage": usage}


# --------------------------------------------------------------------------- public API
def parse_svd_text(text: str | bytes) -> Device:
    data = text.encode("utf-8") if isinstance(text, str) else text
    if b"<!ENTITY" in data or b"<!DOCTYPE" in data:
        raise ValueError("SVD with DOCTYPE/ENTITY declarations is rejected (untrusted input)")
    root = ET.fromstring(data)
    b = _Builder(root)
    return Device(name=_clean(root.findtext("name")), description=_clean(root.findtext("description")),
                  peripherals=b.build())


def parse_svd(path: str | Path) -> Device:
    return parse_svd_text(Path(path).read_bytes())


# =========================================================================== SQLite
CORE_PERIPHERALS = {"NVIC", "NVIC_STIR", "SCB", "SCB_ACTLR", "STK", "MPU", "FPU", "FPU_CPACR"}


def _svd_only_note(chip: str, p: Peripheral) -> str:
    if chip == "stm32g474" and p.name in CORE_PERIPHERALS:
        return ("Arm Cortex-M4 core peripheral: documented in the Arm/ST programming manual (PM0214), "
                "which is not part of the indexed corpus; values come from the vendor SVD only.")
    return ("Defined in the vendor SVD but no matching register description was found in the indexed manual "
            "(automatic matching). Treat address/fields as SVD-derived and unverified; may be an SVD superset or error.")


def ingest_device(conn, chip: str, device: Device, locate, *, alias_fn=None, svd_file: str | None = None,
                  svd_sha256: str | None = None, svd_doc: str | None = None) -> dict:
    """Ghi `device` vào các bảng SVD của `conn` cho `chip` (xoá dữ liệu cũ của chip trước).

    locate(peripheral, register) -> register_pages.PageRef | None.  alias_fn(address) -> địa chỉ ở cửa sổ khác | None.
    """
    import datetime
    import json

    for t in ("enum_values", "fields", "registers", "peripherals", "data_anomalies", "chips"):
        conn.execute(f"DELETE FROM {t} WHERE chip = ?", (chip,))
    conn.execute("INSERT INTO chips(chip, device, svd_file, svd_sha256, built_at) VALUES (?,?,?,?,?)",
                 (chip, device.name, svd_file, svd_sha256, datetime.datetime.now(datetime.timezone.utc).isoformat()))
    stats = {"peripherals": 0, "registers": 0, "fields": 0, "enum_values": 0, "svd_only": 0}
    svd_doc = svd_doc or f"{chip}_SVD"
    for p in device.peripherals:
        conn.execute("INSERT INTO peripherals VALUES (?,?,?,?,?,?,?)",
                     (chip, p.name, p.base_address, p.group, p.description, p.derived_from, p.alternate_peripheral))
        stats["peripherals"] += 1
        for r in p.registers:
            ref = locate(p, r)
            note = None
            if ref is None:
                note = _svd_only_note(chip, p)
                stats["svd_only"] += 1
                conn.execute("INSERT INTO data_anomalies VALUES (?,?,?,?)",
                             (chip, "svd_only_register", f"{p.name}.{r.name}", note))
            elif ref.confidence == "offset_mismatch":
                conn.execute("INSERT INTO data_anomalies VALUES (?,?,?,?)",
                             (chip, "offset_mismatch", f"{p.name}.{r.name}",
                              f"SVD offset {r.offset:#x}; manual {ref.rm_name} prints {[hex(x) for x in ref.rm_offsets or []]} (p.{ref.page})"))
            elif ref.confidence == "offset":
                conn.execute("INSERT INTO data_anomalies VALUES (?,?,?,?)",
                             (chip, "name_mismatch", f"{p.name}.{r.name}", ref.note or ""))
            if ref and ref.rm_reset is not None and r.reset_value is not None and ref.rm_reset != r.reset_value:
                conn.execute("INSERT INTO data_anomalies VALUES (?,?,?,?)",
                             (chip, "reset_mismatch", f"{p.name}.{r.name}",
                              f"SVD reset {r.reset_value:#x}; manual {ref.rm_name} prints {ref.rm_reset:#x} (p.{ref.page})"))
            if r.overlapping_fields:
                conn.execute("INSERT INTO data_anomalies VALUES (?,?,?,?)",
                             (chip, "overlapping_fields", f"{p.name}.{r.name}",
                              ", ".join(f"{a}/{b}" for a, b in r.overlapping_fields)))
            cur = conn.execute(
                "INSERT INTO registers(chip, peripheral, name, short_name, cluster_path, array_base, array_index, offset,"
                " address, address_alias, size, access, reset_value, rm_reset_value, reset_mask, reserved_mask, rw_mask,"
                " description, has_fields, alternate_register, doc, page, alt_pages, page_confidence, rm_name, svd_only,"
                " note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (chip, p.name, r.name, r.short_name, r.cluster_path, r.array_base, r.array_index, r.offset, r.address,
                 alias_fn(r.address) if alias_fn else None, r.size, r.access, r.reset_value,
                 ref.rm_reset if ref else None, r.reset_mask, r.reserved_mask, r.rw_mask, r.description, int(r.has_fields), r.alternate_register,
                 ref.doc if ref else svd_doc, ref.page if ref else None,
                 json.dumps(ref.alt_pages) if ref and ref.alt_pages else None, ref.confidence if ref else None,
                 ref.rm_name if ref else None, 0 if ref else 1, note))
            rid = cur.lastrowid
            stats["registers"] += 1
            for f in r.fields:
                fc = conn.execute(
                    "INSERT INTO fields(register_id, chip, peripheral, register, name, bit_offset, bit_width, access,"
                    " description, modified_write, read_action, write_constraint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, chip, p.name, r.name, f.name, f.bit_offset, f.bit_width, f.access, f.description,
                     f.modified_write, f.read_action, f.write_constraint))
                stats["fields"] += 1
                for e in f.enums:
                    conn.execute("INSERT INTO enum_values VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (fc.lastrowid, chip, p.name, r.name, f.name, e.name, e.value, e.value_raw,
                                  e.description, int(e.is_default)))
                    stats["enum_values"] += 1
    conn.commit()
    return stats


# --------------------------------------------------------------------------- CLI
SVD_CHIPS = {"stm32g474": "STM32G474_SVD", "esp32": "ESP32_SVD", "nrf52840": "nRF52840_SVD"}


def _locator(chip: str, device: Device):
    from . import register_pages as rp
    if chip == "stm32g474":
        blocks, bases = rp.stm32_blocks(), rp.group_bases(device)
        return lambda p, r: rp.locate_stm32(chip, p, r, blocks, bases)
    if chip == "nrf52840":
        blocks = rp.nrf_blocks()
        return lambda p, r: rp.locate_nrf(p, r, blocks)
    if chip == "esp32":
        idx = rp.esp32_index()
        return lambda p, r: rp.locate_esp32(p, r, idx)
    raise KeyError(chip)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import hashlib

    from . import hwdb, pdfdocs
    from .register_pages import ahb_alias

    ap = argparse.ArgumentParser(description="SVD -> data/hw_specs.sqlite (kèm gắn trang RM/TRM/PS)")
    ap.add_argument("--db", default=str(hwdb.DEFAULT_DB))
    ap.add_argument("--chips", nargs="*", default=list(SVD_CHIPS))
    a = ap.parse_args(argv)
    conn = hwdb.connect(a.db)
    hwdb.init_schema(conn)
    for chip in a.chips:
        doc_id = SVD_CHIPS[chip]
        entry = pdfdocs.manifest_entry(doc_id)
        path = pdfdocs.CORPUS / entry["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"{doc_id}: sha256 does not match corpus/manifest.yaml")
        device = parse_svd(path)
        stats = ingest_device(conn, chip, device, _locator(chip, device), svd_file=entry["file"], svd_sha256=digest,
                              svd_doc=doc_id, alias_fn=ahb_alias if chip == "esp32" else None)
        print(f"{chip}: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
