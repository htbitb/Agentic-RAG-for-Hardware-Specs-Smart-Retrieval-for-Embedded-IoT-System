"""Công cụ đóng băng hwmodel cho grader (D19): sao chép nguyên văn, VENDOR.md có sha256, từ chối ghi đè, phát hiện lệch so với agent/hwmodel."""
import hashlib

import pytest

from eval.tools import freeze_hwmodel as F


def make_src(root):
    for rel, text in {
        "hwmodel/__init__.py": "'''pkg'''\n", "hwmodel/sim.py": "X = 1\n", "hwmodel/periph/__init__.py": "", "hwmodel/periph/tim.py": "Y = 2\n",
        "hwmodel/__pycache__/sim.cpython-311.pyc": "pyc", "hwmodel/notes.md": "not code\n",
        "data/hw_specs.sqlite": "DB", "data/svd_attrs.json": "{}", "data/text_index.npy": "NPY", "data/memory.sqlite": "private",
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


@pytest.fixture()
def frozen(tmp_path):
    src, dst = tmp_path / "agent", tmp_path / "eval" / "vendor"
    make_src(src)
    info = F.freeze(src / "hwmodel", src / "data", dst, date="2026-10-22", reason="test")
    return src, dst, info


def test_only_python_sources_and_the_two_data_files_are_copied(frozen):
    _, dst, _ = frozen
    got = {p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()}
    assert got == {"hwmodel/__init__.py", "hwmodel/sim.py", "hwmodel/periph/__init__.py", "hwmodel/periph/tim.py", "hwmodel/VENDOR.md",
                   "hwmodel_data/hw_specs.sqlite", "hwmodel_data/svd_attrs.json"}


def test_copies_are_byte_identical(frozen):
    src, dst, _ = frozen
    for rel in ("hwmodel/sim.py", "hwmodel/periph/tim.py"):
        assert (src / rel).read_bytes() == (dst / rel).read_bytes()


def test_vendor_md_records_sources_date_and_checksums(frozen):
    _, dst, info = frozen
    md = (dst / "hwmodel" / "VENDOR.md").read_text()
    assert "2026-10-22" in md and "test" in md
    assert f"hwmodel_vendor_sha256: {info['vendor_sha256']}" in md and f"hwmodel_data_sha256: {info['data_sha256']}" in md
    assert "sim.py" in md and "hw_specs.sqlite" in md
    assert F.vendor_checksum(dst / "hwmodel") == info["vendor_sha256"] == F.recorded_checksum(dst / "hwmodel")
    assert F.data_checksum(dst / "hwmodel_data") == info["data_sha256"]
    assert "private" not in md and "NPY" not in md


def test_checksum_formula_is_sha256_of_the_sorted_file_listing(frozen):
    _, dst, info = frozen
    files = sorted((dst / "hwmodel").rglob("*.py"), key=lambda p: "./" + p.relative_to(dst / "hwmodel").as_posix())
    listing = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(dst / 'hwmodel').as_posix()}\n" for p in files)
    assert hashlib.sha256(listing.encode()).hexdigest() == info["vendor_sha256"]


def test_freeze_refuses_to_overwrite(frozen):
    src, dst, _ = frozen
    with pytest.raises(FileExistsError):
        F.freeze(src / "hwmodel", src / "data", dst, reason="again")
    F.freeze(src / "hwmodel", src / "data", dst, reason="again", force=True)             # --force được phép, có chủ đích


def test_check_reports_drift_between_agent_and_vendor(frozen):
    src, dst, _ = frozen
    assert F.drift(src / "hwmodel", src / "data", dst) == []
    (src / "hwmodel" / "sim.py").write_text("X = 99\n")
    (src / "hwmodel" / "new.py").write_text("Z = 1\n")
    assert sorted(F.drift(src / "hwmodel", src / "data", dst)) == ["changed: sim.py", "new in agent: new.py"]
    (src / "data" / "hw_specs.sqlite").write_text("DB2")
    assert "changed data: hw_specs.sqlite" in F.drift(src / "hwmodel", src / "data", dst)


def test_tampering_with_the_vendor_copy_is_detected(frozen):
    _, dst, _ = frozen
    (dst / "hwmodel" / "sim.py").write_text("X = 666\n")
    assert F.vendor_checksum(dst / "hwmodel") != F.recorded_checksum(dst / "hwmodel")
    assert F.verify(dst) is False


def test_the_real_vendor_copy_is_untampered_and_matches_the_p1_snapshot_data():
    from pathlib import Path
    vendor = Path(__file__).resolve().parents[1] / "vendor"
    if not (vendor / "hwmodel" / "VENDOR.md").exists():
        pytest.skip("vendor copy not created yet")
    assert F.verify(vendor), "eval/vendor/hwmodel was modified after freezing (D19): fix agent/hwmodel and re-freeze"


def test_agent_only_modules_are_not_frozen_and_do_not_count_as_drift(tmp_path):
    """P3: board_state.py / drc.py (Board State, DRC) chỉ dành cho agent; grader không import chúng nên không đưa vào bản vendor (D19)."""
    src, dst = tmp_path / "agent", tmp_path / "eval" / "vendor"
    make_src(src)
    for name in F.AGENT_ONLY:
        (src / "hwmodel" / name).write_text("Q = 1\n")
    F.freeze(src / "hwmodel", src / "data", dst, date="2026-10-22", reason="test")
    assert not any((dst / "hwmodel" / name).exists() for name in F.AGENT_ONLY)
    assert F.drift(src / "hwmodel", src / "data", dst) == []
    (src / "hwmodel" / "drc.py").write_text("Q = 2\n")                         # sửa module agent-only: vẫn không phải lệch
    assert F.drift(src / "hwmodel", src / "data", dst) == []
    (src / "hwmodel" / "periph" / "board_state.py").write_text("Q = 3\n")      # cùng tên nhưng ở thư mục con: KHÔNG được miễn
    assert F.drift(src / "hwmodel", src / "data", dst) == ["new in agent: periph/board_state.py"]
