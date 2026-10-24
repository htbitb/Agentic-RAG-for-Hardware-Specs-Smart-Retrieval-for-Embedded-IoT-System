"""Công cụ đóng băng snapshot của agent: quy tắc loại trừ, SNAPSHOT.md, checksum cùng công thức với eval.run."""
import pytest

from eval import run as R
from eval.tools import freeze_snapshot as F


def make_agent(root):
    for rel, text in {
        "config.py": "X = 1\n", "agent/__init__.py": "", "agent/llm.py": "SYSTEM_PROMPT = 'p'\n",
        "ingestion/hwdb.py": "Y = 2\n", "README.md": "# readme\n", "start.sh": "#!/bin/sh\n",
        ".env": "LLM_API_KEY=SECRET\n", ".env.example.txt": "LLM_API_KEY=\n", ".DS_Store": "x",
        "logs/audit.jsonl": "{}\n", "workspace_out/a.h": "h\n", "agent/__pycache__/llm.cpython-311.pyc": "pyc",
        ".venv/bin/python": "x", ".venv.py314.bak/bin/python": "x", ".pytest_cache/v/cache": "x",
        "data/memory.sqlite": "private", "data/hw_specs.sqlite": "DB", "data/text_index.npy": "NPY",
        "data/text_index.sqlite": "IDX",
        # P4: trạng thái chạy của runtime v3 không được đóng băng cùng mã
        "data/board_state.sqlite": "board-private", "data/checkpoints.sqlite": "ckpt-private", "data/traces/run1.jsonl": "trace-private",
        "data/traces/sub/run2.jsonl": "trace-private", "data/board_state.sqlite-wal": "wal", "data/checkpoints.sqlite-shm": "shm",
        "data/memory.sqlite-journal": "journal", "agent/runtime/trace.py": "T = 1\n", "docs/traces/notes.md": "# notes\n",
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


@pytest.fixture()
def frozen(tmp_path):
    src, dst = tmp_path / "agent", tmp_path / "snapshots" / "agent_x"
    make_agent(src)
    info = F.freeze(src, dst, title="Agent P1 (S2D)", reason="test", date="2026-10-22", known_issues=["issue A"])
    return src, dst, info


def test_excluded_paths_are_not_copied_and_data_files_are_kept(frozen):
    _, dst, _ = frozen
    got = {p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()}
    assert {"config.py", "agent/llm.py", "ingestion/hwdb.py", "README.md", "start.sh", "SNAPSHOT.md",
            "data/hw_specs.sqlite", "data/text_index.npy", "data/text_index.sqlite"} <= got
    for banned in (".env", ".env.example.txt", ".DS_Store", "logs/audit.jsonl", "workspace_out/a.h", "data/memory.sqlite"):
        assert banned not in got
    assert not any("__pycache__" in g or g.startswith((".venv", ".pytest_cache")) for g in got)


def test_snapshot_md_records_checksums_data_hashes_and_the_exclusions(frozen):
    _, dst, info = frozen
    md = (dst / "SNAPSHOT.md").read_text()
    assert info["checksum"] in md and R.snapshot_checksum(dst) == info["checksum"]
    assert "agent/llm.py" in md and "data/hw_specs.sqlite" in md and "issue A" in md and "2026-10-22" in md
    assert "SECRET" not in md and "private" not in md
    assert ".env" in md and "memory.sqlite" in md                       # nêu rõ cái gì bị loại trừ


def test_freeze_refuses_to_overwrite_an_existing_snapshot_and_the_v1_snapshot(frozen, tmp_path):
    src, dst, _ = frozen
    with pytest.raises(FileExistsError):
        F.freeze(src, dst, title="t", reason="r")
    with pytest.raises(ValueError, match="agent_v1"):
        F.freeze(src, tmp_path / "x" / "agent_v1", title="t", reason="r")


def test_checksum_changes_when_a_python_file_changes(frozen):
    _, dst, info = frozen
    (dst / "config.py").write_text("X = 2\n")
    assert R.snapshot_checksum(dst) != info["checksum"]


def test_data_checksum_covers_sqlite_and_npy_files_and_is_recorded_in_snapshot_md(frozen):
    _, dst, info = frozen
    assert info["data_checksum"] == R.snapshot_data_checksum(dst)
    assert info["data_checksum"] in (dst / "SNAPSHOT.md").read_text()
    (dst / "data" / "hw_specs.sqlite").write_text("TAMPERED")
    assert R.snapshot_data_checksum(dst) != info["data_checksum"]          # trước đây chỉ *.py được ghim, dữ liệu thì không


def test_data_checksum_is_none_for_a_snapshot_without_data_files(tmp_path):
    (tmp_path / "config.py").write_text("X=1\n")
    assert R.snapshot_data_checksum(tmp_path) is None


def test_runtime_state_files_and_traces_are_excluded_but_trace_code_and_other_traces_dirs_are_kept(frozen):
    _, dst, _ = frozen
    got = {p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()}
    for banned in ("data/board_state.sqlite", "data/checkpoints.sqlite", "data/traces/run1.jsonl", "data/traces/sub/run2.jsonl",
                   "data/board_state.sqlite-wal", "data/checkpoints.sqlite-shm", "data/memory.sqlite-journal"):
        assert banned not in got, banned
    assert not (dst / "data" / "traces").exists()                                 # cả thư mục rỗng cũng không được tạo
    assert "agent/runtime/trace.py" in got and "docs/traces/notes.md" in got        # chỉ data/traces bị loại, không phải mọi thứ tên 'trace'
    assert "data/hw_specs.sqlite" in got and "data/text_index.sqlite" in got


def test_state_files_never_reach_the_data_checksum(frozen):
    src, dst, info = frozen
    assert not [p for p in dst.rglob("*") if p.name.startswith(("board_state", "checkpoints"))]
    (src / "data" / "board_state.sqlite").write_text("changed after the freeze")
    from eval import run as R
    assert R.snapshot_data_checksum(dst) == info["data_checksum"]


def test_snapshot_md_lists_the_p4_exclusions(frozen):
    md = (frozen[1] / "SNAPSHOT.md").read_text()
    assert "board_state.sqlite" in md and "checkpoints.sqlite" in md and "data/traces/" in md
    assert "trace-private" not in md and "board-private" not in md
