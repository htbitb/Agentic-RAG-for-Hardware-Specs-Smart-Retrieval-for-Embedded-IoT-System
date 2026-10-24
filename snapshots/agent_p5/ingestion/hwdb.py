"""Lược đồ SQLite `data/hw_specs.sqlite` (D08: SQLite thay DuckDB/LanceDB) dùng chung cho các script ingest và MCP server.

Mỗi script ingest chịu trách nhiệm bảng của nó (xoá & dựng lại theo chip) nên có thể chạy độc lập:
  svd_ingest      -> chips, peripherals, registers, fields, enum_values, data_anomalies
  pinout_extract  -> pins, pin_functions
  limits_curate   -> electrical_limits, clock_limits
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "hw_specs.sqlite"
SCHEMA_VERSION = 2      # tăng khi đổi lược đồ: DB là sản phẩm dẫn xuất nên init_schema dựng lại khi lệch phiên bản

SCHEMA = """
CREATE TABLE IF NOT EXISTS chips(
  chip TEXT PRIMARY KEY, device TEXT, svd_file TEXT, svd_sha256 TEXT, built_at TEXT);
CREATE TABLE IF NOT EXISTS peripherals(
  chip TEXT NOT NULL, name TEXT NOT NULL, base_address INTEGER, group_name TEXT, description TEXT,
  derived_from TEXT, alternate_peripheral TEXT, PRIMARY KEY(chip, name));
CREATE TABLE IF NOT EXISTS registers(
  id INTEGER PRIMARY KEY, chip TEXT NOT NULL, peripheral TEXT NOT NULL, name TEXT NOT NULL, short_name TEXT,
  cluster_path TEXT, array_base TEXT, array_index TEXT, offset INTEGER, address INTEGER, address_alias INTEGER,
  size INTEGER, access TEXT, reset_value INTEGER, rm_reset_value INTEGER, reset_mask INTEGER, reserved_mask INTEGER, rw_mask INTEGER,
  description TEXT, has_fields INTEGER, alternate_register TEXT,
  doc TEXT NOT NULL, page INTEGER, alt_pages TEXT, page_confidence TEXT, rm_name TEXT,
  svd_only INTEGER NOT NULL DEFAULT 0, note TEXT, UNIQUE(chip, peripheral, name));
CREATE INDEX IF NOT EXISTS ix_reg_lookup ON registers(chip, peripheral, name);
CREATE INDEX IF NOT EXISTS ix_reg_addr ON registers(chip, address);
CREATE TABLE IF NOT EXISTS fields(
  id INTEGER PRIMARY KEY, register_id INTEGER NOT NULL, chip TEXT NOT NULL, peripheral TEXT NOT NULL,
  register TEXT NOT NULL, name TEXT NOT NULL, bit_offset INTEGER, bit_width INTEGER, access TEXT, description TEXT,
  modified_write TEXT, read_action TEXT, write_constraint TEXT);
CREATE INDEX IF NOT EXISTS ix_field_reg ON fields(register_id);
CREATE TABLE IF NOT EXISTS enum_values(
  field_id INTEGER NOT NULL, chip TEXT NOT NULL, peripheral TEXT NOT NULL, register TEXT NOT NULL, field TEXT NOT NULL,
  name TEXT, value INTEGER, value_raw TEXT, description TEXT, is_default INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_enum_field ON enum_values(field_id);
CREATE TABLE IF NOT EXISTS data_anomalies(
  chip TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT, detail TEXT);

CREATE TABLE IF NOT EXISTS pins(
  chip TEXT NOT NULL, pin TEXT NOT NULL, port TEXT, number INTEGER, pad_name TEXT, io_structure TEXT,
  is_5v_tolerant INTEGER, input_only INTEGER, strapping TEXT, notes TEXT, packages TEXT,
  doc TEXT NOT NULL, page INTEGER, source TEXT NOT NULL, quote TEXT, PRIMARY KEY(chip, pin));
CREATE TABLE IF NOT EXISTS pin_flags(
  chip TEXT NOT NULL, pin TEXT NOT NULL, kind TEXT NOT NULL, note TEXT, doc TEXT NOT NULL, page INTEGER NOT NULL,
  quote TEXT NOT NULL, source TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_pflag_pin ON pin_flags(chip, pin);
CREATE TABLE IF NOT EXISTS chip_notes(
  chip TEXT NOT NULL, topic TEXT NOT NULL, value TEXT NOT NULL, doc TEXT, page INTEGER, quote TEXT, source TEXT NOT NULL,
  PRIMARY KEY(chip, topic));
CREATE TABLE IF NOT EXISTS pin_functions(
  chip TEXT NOT NULL, pin TEXT NOT NULL, af INTEGER, signal TEXT NOT NULL, peripheral TEXT, kind TEXT, notes TEXT,
  doc TEXT NOT NULL, page INTEGER, source TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_pf_pin ON pin_functions(chip, pin);
CREATE INDEX IF NOT EXISTS ix_pf_signal ON pin_functions(chip, signal);

CREATE TABLE IF NOT EXISTS electrical_limits(
  id INTEGER PRIMARY KEY, chip TEXT NOT NULL, parameter TEXT NOT NULL, category TEXT NOT NULL, field_type TEXT,
  symbol TEXT, min TEXT, typ TEXT, max TEXT, unit TEXT, condition TEXT, applies_to TEXT,
  doc TEXT NOT NULL, page INTEGER NOT NULL, quote TEXT NOT NULL, source TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS clock_limits(
  id INTEGER PRIMARY KEY, chip TEXT NOT NULL, parameter TEXT NOT NULL, symbol TEXT, min TEXT, typ TEXT, max TEXT,
  unit TEXT, condition TEXT, doc TEXT NOT NULL, page INTEGER NOT NULL, quote TEXT NOT NULL, source TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0);
"""


def connect(path: str | Path = DEFAULT_DB, readonly: bool = False) -> sqlite3.Connection:
    p = Path(path)
    if readonly:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            conn.execute(f"DROP TABLE IF EXISTS {name}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.executescript(SCHEMA)
    conn.commit()
