"""Sidecar `data/svd_attrs.json`: tác dụng phụ khi ghi/đọc (modifiedWriteValues / readAction) mà DB P1 không lưu ở mức thanh ghi.

DB `hw_specs.sqlite` chỉ có `fields.modified_write`; SVD của nRF52840 khai báo ở mức THANH GHI (P0.OUTSET `oneToSet`,
P0.OUTCLR `oneToClear`, ERRORSRC `oneToClear`...) nên W1C bị mất. Đổi lược đồ DB sẽ buộc dựng lại cả DB (gắn trang PDF) nên
P2 giữ phần này trong một file JSON nhỏ, kèm sha256 của SVD nguồn (đối chiếu với corpus/manifest.yaml).

    agent/.venv/bin/python -m ingestion.svd_attrs [--out agent/data/svd_attrs.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from . import hwdb, pdfdocs
from .svd_ingest import SVD_CHIPS, Device, parse_number, parse_svd

DEFAULT_OUT = hwdb.ROOT / "data" / "svd_attrs.json"


def extract(device: Device) -> dict:
    """{"PERIPH.REGISTER": {"modified_write"?, "read_action"?, "fields"?: {FIELD: {"modified_write"?, "read_action"?}}}}.
    Chỉ ghi thanh ghi có ít nhất một thuộc tính."""
    out: dict[str, dict] = {}
    for per in device.peripherals:
        for reg in per.registers:
            entry: dict = {}
            if reg.modified_write:
                entry["modified_write"] = reg.modified_write
            if reg.read_action:
                entry["read_action"] = reg.read_action
            fields = {}
            for f in reg.fields:
                attrs = {k: v for k, v in (("modified_write", f.modified_write), ("read_action", f.read_action)) if v}
                if attrs:
                    fields[f.name] = attrs
            if fields:
                entry["fields"] = fields
            if entry:
                out[f"{per.name}.{reg.name}"] = entry
    return out


def extract_interrupts(xml_bytes: bytes) -> dict[str, int]:
    """{tên ngắt: số IRQ} từ các phần tử <interrupt> của SVD (dùng cho enum IRQn_Type của header sinh tự động)."""
    if b"<!ENTITY" in xml_bytes or b"<!DOCTYPE" in xml_bytes:
        raise ValueError("SVD with DOCTYPE/ENTITY declarations is rejected (untrusted input)")
    out: dict[str, int] = {}
    for el in ET.fromstring(xml_bytes).iter("interrupt"):
        name, value = (el.findtext("name") or "").strip(), parse_number(el.findtext("value"))
        if name and value is not None:
            out.setdefault(name, value)
    return out


def build(corpus: Path | None = None) -> dict:
    corpus = Path(corpus) if corpus is not None else pdfdocs.CORPUS
    chips: dict[str, dict] = {}
    for chip, doc_id in SVD_CHIPS.items():
        entry = pdfdocs.manifest_entry(doc_id)
        path = corpus / entry["file"]
        data = path.read_bytes()                            # FileNotFoundError nếu thiếu SVD
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"{doc_id}: sha256 does not match corpus/manifest.yaml")
        chips[chip] = {"svd_file": entry["file"], "svd_sha256": digest, "registers": extract(parse_svd(path)),
                       "interrupts": extract_interrupts(data)}
    return {"version": 1, "chips": chips}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    data = build()
    a.out.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{a.out}: " + ", ".join(f"{c}={len(v['registers'])} registers" for c, v in data["chips"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
