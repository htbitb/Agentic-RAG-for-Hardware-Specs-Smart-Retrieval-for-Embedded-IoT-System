"""Text index hybrid (W1): BM25 bằng SQLite FTS5 + embedding all-MiniLM-L6-v2 (numpy) hợp nhất bằng Reciprocal Rank Fusion.

D08: SQLite + numpy thay LanceDB; D09: cùng mô hình embedding với baseline S1 để so sánh công bằng.
File: `text_index.sqlite` (bảng `chunks`, `chunks_fts`, `meta`) và `text_index.npy` (float32 N×D, đã chuẩn hoá, hàng i ↔ chunks.id = i+1).
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "text_index.sqlite"
DEFAULT_EMB = ROOT / "data" / "text_index.npy"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
RRF_K = 60

_STOP = set("""a an the of for to in on at and or is are was were be been what which who whom whose how does do did can could
should would will shall may might must i me my we our you your it its this that these those with from by as about into than
then there their they them value values give show tell please using use used when where why""".split())
_WORD = re.compile(r"[A-Za-z0-9_]+")

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE NOT NULL, doc_id TEXT NOT NULL, chip TEXT,
  page_start INTEGER NOT NULL, page_end INTEGER NOT NULL, breadcrumb TEXT NOT NULL, section TEXT, text TEXT NOT NULL, ord INTEGER);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(doc_id, ord);
CREATE INDEX IF NOT EXISTS ix_chunks_chip ON chunks(chip);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(breadcrumb, body, tokenize = "unicode61 tokenchars '_'");
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def rrf(rankings: Iterable[list], k: int = RRF_K) -> list[tuple[object, float]]:
    """Reciprocal Rank Fusion: score(x) = Σ 1/(k + rank_i(x)), rank từ 1. Trả [(x, score)] giảm dần (ổn định)."""
    score: dict = {}
    first: dict = {}
    for ranking in rankings:
        for r, x in enumerate(ranking, start=1):
            score[x] = score.get(x, 0.0) + 1.0 / (k + r)
            first.setdefault(x, len(first))
    return sorted(score.items(), key=lambda kv: (-kv[1], first[kv[0]]))


def _identifier_parts(text: str) -> str:
    """Thêm các mảnh của định danh (RCC_AHB2ENR -> RCC AHB2ENR) để truy vấn theo mảnh cũng khớp."""
    parts = set()
    for tok in _WORD.findall(text):
        if "_" in tok:
            parts.update(p for p in tok.split("_") if len(p) > 1)
    return " ".join(sorted(parts))


def _fts_query(query: str) -> str | None:
    toks = []
    for t in _WORD.findall(query):
        if t.lower() in _STOP or len(t) < 2:
            continue
        toks.append(t)
        if "_" in t:
            toks.extend(p for p in t.split("_") if len(p) > 1 and p.lower() not in _STOP)
    toks = list(dict.fromkeys(toks))
    return " OR ".join(f'"{t}"' for t in toks) if toks else None


def build_index(chunks, db_path, emb_path, *, embedder: Callable[[list[str]], np.ndarray] | None, meta: dict | None = None,
                batch: int = 128) -> dict:
    db_path, emb_path = Path(db_path), Path(emb_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    rows = list(chunks)
    for i, c in enumerate(rows, start=1):
        conn.execute("INSERT INTO chunks(id, chunk_id, doc_id, chip, page_start, page_end, breadcrumb, section, text, ord)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (i, c.chunk_id, c.doc_id, c.chip, c.page_start, c.page_end, c.breadcrumb, c.section, c.text, c.ord))
        conn.execute("INSERT INTO chunks_fts(rowid, breadcrumb, body) VALUES (?,?,?)",
                     (i, c.breadcrumb, c.text + "\n" + _identifier_parts(c.breadcrumb + " " + c.text)))
    dim = 0
    if embedder is not None:
        mats = [np.asarray(embedder([f"{c.breadcrumb}\n{c.text}" for c in rows[i:i + batch]]), dtype=np.float32)
                for i in range(0, len(rows), batch)]
        emb = np.vstack(mats) if mats else np.zeros((0, 1), dtype=np.float32)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        emb = emb / np.where(norms == 0, 1, norms)
        np.save(emb_path, emb)
        dim = emb.shape[1]
    info = {"n_chunks": len(rows), "dim": dim, **(meta or {})}
    for k, v in info.items():
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v)))
    conn.commit()
    conn.close()
    return info


class TextIndex:
    def __init__(self, db_path=DEFAULT_DB, emb_path=DEFAULT_EMB, embedder: Callable[[list[str]], np.ndarray] | None = None):
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        n = self.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        self.n = n
        self._embedder = embedder
        self.emb: np.ndarray | None = None
        if Path(emb_path).is_file():
            emb = np.load(emb_path)
            if emb.shape[0] != n:
                raise ValueError(f"embeddings rows ({emb.shape[0]}) do not match chunk table ({n})")
            self.emb = emb
        cols = self.conn.execute("SELECT id, doc_id, chip FROM chunks ORDER BY id").fetchall()
        self._chip = np.array([r["chip"] or "" for r in cols])
        self._doc = np.array([r["doc_id"] for r in cols])

    @property
    def dense_available(self) -> bool:
        return self.emb is not None and self._embedder is not None

    def meta(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.conn.execute("SELECT key, value FROM meta")}

    # ------------------------------------------------------------------ truy xuất
    def _bm25(self, query: str, chip, doc, pool: int) -> list[int]:
        q = _fts_query(query)
        if q is None:
            return []
        sql = ("SELECT c.id FROM chunks_fts f JOIN chunks c ON c.id = f.rowid WHERE chunks_fts MATCH ?"
               + (" AND c.chip = ?" if chip else "") + (" AND c.doc_id = ?" if doc else "")
               + " ORDER BY bm25(chunks_fts, 2.0, 1.0) LIMIT ?")
        args = [q] + ([chip] if chip else []) + ([doc] if doc else []) + [pool]
        try:
            return [r[0] for r in self.conn.execute(sql, args)]
        except sqlite3.OperationalError:
            return []

    def _dense(self, query: str, chip, doc, pool: int) -> tuple[list[int], dict[int, float]]:
        if not self.dense_available:
            return [], {}
        qv = np.asarray(self._embedder([query]), dtype=np.float32)[0]
        qv = qv / (np.linalg.norm(qv) or 1.0)
        sims = self.emb @ qv
        mask = np.ones(self.n, dtype=bool)
        if chip:
            mask &= self._chip == chip
        if doc:
            mask &= self._doc == doc
        idx = np.where(mask)[0]
        if idx.size == 0:
            return [], {}
        top = idx[np.argsort(-sims[idx])[:pool]]
        return [int(i) + 1 for i in top], {int(i) + 1: float(sims[i]) for i in top}

    def search(self, query: str, *, chip: str | None = None, doc: str | None = None, k: int = 5, pool: int = 40,
               mode: str = "hybrid") -> list[dict]:
        chip = chip.lower() if chip else None
        bm = self._bm25(query, chip, doc, pool) if mode in ("hybrid", "bm25") else []
        dn, sims = self._dense(query, chip, doc, pool) if mode in ("hybrid", "dense") else ([], {})
        fused = rrf([r for r in (bm, dn) if r])
        bm_rank = {x: i for i, x in enumerate(bm, start=1)}
        dn_rank = {x: i for i, x in enumerate(dn, start=1)}
        out = []
        for cid, score in fused[:k]:
            r = self.conn.execute("SELECT * FROM chunks WHERE id = ?", (cid,)).fetchone()
            out.append(self._row(r, score=round(score, 6), bm25_rank=bm_rank.get(cid), dense_rank=dn_rank.get(cid),
                                 dense_sim=round(sims[cid], 4) if cid in sims else None))
        return out

    @staticmethod
    def _row(r: sqlite3.Row, **extra) -> dict:
        return {"chunk_id": r["chunk_id"], "doc": r["doc_id"], "chip": r["chip"], "page": r["page_start"],
                "page_start": r["page_start"], "page_end": r["page_end"], "breadcrumb": r["breadcrumb"],
                "section": r["section"], "text": r["text"], **extra}

    def get(self, chunk_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return self._row(r) if r else None

    def neighbors(self, chunk_id: str, window: int = 1) -> list[dict]:
        r = self.conn.execute("SELECT doc_id, ord FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        if r is None:
            return []
        rows = self.conn.execute("SELECT * FROM chunks WHERE doc_id = ? AND ord BETWEEN ? AND ? ORDER BY ord",
                                 (r["doc_id"], r["ord"] - int(window), r["ord"] + int(window))).fetchall()
        return [self._row(x) for x in rows]

    def documents(self) -> list[dict]:
        rows = self.conn.execute("SELECT doc_id, chip, count(*) n, min(page_start) p0, max(page_end) p1 FROM chunks "
                                 "GROUP BY doc_id ORDER BY doc_id").fetchall()
        return [{"doc": r["doc_id"], "chip": r["chip"], "chunks": r["n"], "page_min": r["p0"], "page_max": r["p1"]} for r in rows]


def default_embedder() -> Callable[[list[str]], np.ndarray]:
    """all-MiniLM-L6-v2 (cùng mô hình baseline S1, D09); dùng MPS nếu có."""
    import torch
    from sentence_transformers import SentenceTransformer

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    try:                                           # ưu tiên bản đã cache: không gọi mạng, chạy tất định/offline
        model = SentenceTransformer(MODEL_NAME, device=device, local_files_only=True)
    except Exception:
        model = SentenceTransformer(MODEL_NAME, device=device)
    return lambda texts: model.encode(texts, batch_size=128, normalize_embeddings=True, show_progress_bar=False)
