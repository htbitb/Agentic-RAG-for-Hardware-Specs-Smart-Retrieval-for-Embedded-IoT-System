import pytest

from ingestion import build_all, hwdb, pdfdocs

pytestmark = pytest.mark.skipif(not pdfdocs.CORPUS.joinpath("manifest.yaml").is_file(), reason="corpus not present")


def test_build_all_creates_every_table_from_scratch_and_is_repeatable(tmp_path):
    db = tmp_path / "hw.sqlite"
    db.write_text("garbage that is not a database")                # --fresh phải xoá file cũ, kể cả khi hỏng
    assert build_all.main(["--db", str(db), "--skip-index", "--fresh"]) == 0
    c = hwdb.connect(db, readonly=True)
    counts = {t: c.execute(f"select count(*) from {t}").fetchone()[0] for t in
              ("peripherals", "registers", "fields", "pins", "pin_functions", "pin_flags", "chip_notes", "electrical_limits", "clock_limits")}
    assert all(v > 0 for v in counts.values()), counts
    assert counts["registers"] == 1585 + 2613 + 2140
    assert build_all.main(["--db", str(db), "--skip-index"]) == 0         # chạy lại không nhân đôi dữ liệu
    c2 = hwdb.connect(db, readonly=True)
    assert c2.execute("select count(*) from registers").fetchone()[0] == counts["registers"]
    assert c2.execute("select count(*) from electrical_limits").fetchone()[0] == counts["electrical_limits"]
