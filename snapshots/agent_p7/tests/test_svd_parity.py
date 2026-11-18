"""Parity (D05): parser SVD của agent (ingestion/svd_ingest.py) so với parser ĐỘC LẬP của eval (eval/generators/svd.py).

Chỉ import eval từ phía test. Hai parser phải đồng ý trên toàn bộ peripheral / thanh ghi / địa chỉ / size / reset / field.

Khác biệt đã giải thích (kết quả phân tích 2026-10-22, ghi ở plan/P1_progress.md):
  * Tên thanh ghi trong cluster/mảng: agent giữ dạng SVD/PS ("ACL[0].ADDR", "PSEL.SCL"), eval nối bằng '_' ("ACL0_ADDR").
    -> so khớp theo tên đã chuẩn hoá (chỉ chữ + số, hoa).
  * `access`: parser eval để trống khi SVD không ghi access ở mức thanh ghi/peripheral (không kế thừa mặc định của
    device); agent kế thừa device -> peripheral -> register -> field theo CMSIS-SVD. Bên bị thiếu: eval (hạn chế vô hại
    với grader vì nhãn C1 chỉ hỏi access khi SVD ghi rõ). Test: khi eval có giá trị thì phải bằng agent; khi eval trống
    thì agent phải bằng access mặc định của device.
"""
import importlib.util
import re
import sys

import pytest

from ingestion import pdfdocs
from ingestion.svd_ingest import SVD_CHIPS, parse_svd

EVAL_SVD = pdfdocs.CORPUS.parent / "eval" / "generators" / "svd.py"
pytestmark = pytest.mark.skipif(not EVAL_SVD.is_file(), reason="eval parser not present")

_ACCESS = {"read-write": "rw", "read-only": "ro", "write-only": "wo", "writeOnce": "wo", "read-writeOnce": "rw"}


def _eval_parser():
    spec = importlib.util.spec_from_file_location("eval_generators_svd_for_parity", EVAL_SVD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _key(periph: str, name: str) -> tuple[str, str]:
    return periph, re.sub(r"[^A-Za-z0-9]", "", name).upper()


def _agent_view(path):
    dev = parse_svd(path)
    out = {}
    for p in dev.peripherals:
        for r in p.registers:
            k = _key(p.name, r.name)
            assert k not in out, f"agent: normalized-name collision {k}"
            out[k] = dict(address=r.address, size=r.size, reset=r.reset_value, access=(r.access or "").lower().replace("1", ""),
                          fields=sorted((f.name, f.bit_offset, f.bit_offset + f.bit_width - 1) for f in r.fields))
    return {p.name for p in dev.peripherals}, out


def _eval_view(path):
    dev = _eval_parser().parse_svd(path)
    out = {}
    for p in dev.peripherals:
        for r in p.registers:
            k = _key(p.name, r.name)
            assert k not in out, f"eval: normalized-name collision {k}"
            out[k] = dict(address=r.address, size=r.size, reset=r.reset_value, access=(r.access or "").lower(),
                          fields=sorted((f.name, f.lsb, f.msb) for f in r.fields))
    return {p.name for p in dev.peripherals}, out


def _device_default_access(path) -> str:
    head = path.read_text(encoding="utf-8").split("<peripherals>")[0]
    m = re.search(r"<access>\s*([A-Za-z-]+)\s*</access>", head)
    return _ACCESS[m.group(1)] if m else "rw"


@pytest.mark.parametrize("chip", list(SVD_CHIPS))
def test_parsers_agree_on_every_peripheral_register_and_field(chip):
    path = pdfdocs.CORPUS / pdfdocs.manifest_entry(SVD_CHIPS[chip])["file"]
    a_per, a = _agent_view(path)
    e_per, e = _eval_view(path)
    assert a_per == e_per and set(a) == set(e) and len(a) > 0
    default = _device_default_access(path)
    problems = []
    for key in sorted(a):
        for f in ("address", "size", "reset", "fields"):
            if a[key][f] != e[key][f]:
                problems.append((key, f, a[key][f], e[key][f]))
        if e[key]["access"]:
            if a[key]["access"] != e[key]["access"]:
                problems.append((key, "access", a[key]["access"], e[key]["access"]))
        elif a[key]["access"] != default:
            problems.append((key, "access(inherited)", a[key]["access"], default))
    assert not problems, f"{chip}: {len(problems)} unexplained differences, first: {problems[:5]}"
