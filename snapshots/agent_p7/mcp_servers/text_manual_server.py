"""Text-Manual MCP Server: tìm kiếm hybrid (BM25 + embedding, hợp nhất bằng RRF) trên text index THẬT của 6 tài liệu.

Index do `ingestion/build_text_index.py` dựng từ corpus/ (chunk theo cấu trúc mục, breadcrumb + trang). Thay thế danh sách
5 đoạn văn mô phỏng và các trích dẫn bịa (FreeRTOS v10.5.0 -> tài liệu thật là V8.2.1).
"""
import config
from mcp_servers import create_mcp

mcp = create_mcp("text-manual")
_INDEX = None
_EMBEDDER = "auto"          # "auto": nạp all-MiniLM-L6-v2 khi cần; None: chỉ BM25; callable: dùng trong test


def _embed(texts):
    global _EMBEDDER
    if _EMBEDDER == "auto":
        try:
            from ingestion.text_index import default_embedder
            _EMBEDDER = default_embedder()
        except Exception:                     # thiếu sentence-transformers/torch -> BM25-only, không làm hỏng tool
            _EMBEDDER = None
    if _EMBEDDER is None:
        raise RuntimeError("dense embedder unavailable")
    return _EMBEDDER(texts)


def _index():
    global _INDEX
    if _INDEX is None:
        from ingestion.text_index import TextIndex
        _INDEX = TextIndex(config.TEXT_INDEX_DB, config.TEXT_INDEX_EMB, embedder=_embed)
    return _INDEX


def _reset(embedder="auto") -> None:
    """Dùng trong test: mở lại index theo `config.TEXT_INDEX_*`, tuỳ chọn embedder giả."""
    global _INDEX, _EMBEDDER
    _INDEX, _EMBEDDER = None, embedder


def _search(query: str, chip, doc, k) -> dict:
    ix = _index()
    try:
        hits = ix.search(query, chip=chip, doc=doc, k=max(1, min(int(k), 20)))
        mode = "hybrid (BM25 + dense, RRF)" if ix.dense_available else "bm25-only"
    except RuntimeError:                        # embedder không khả dụng
        hits = ix.search(query, chip=chip, doc=doc, k=max(1, min(int(k), 20)), mode="bm25")
        mode = "bm25-only (embedding model unavailable)"
    return {"query": query, "chip": chip, "doc": doc, "retrieval": mode, "results": hits}


@mcp.tool()
def search_manual(query: str, chip: str | None = None, doc: str | None = None, k: int = config.TOP_K) -> dict:
    """Hybrid search (BM25 + embedding with reciprocal-rank fusion) over the real datasheets, reference manuals and the FreeRTOS reference manual (ESP32 datasheet/TRM, STM32G474 datasheet/RM0440, nRF52840 PS, FreeRTOS V8.2.1). Optional filters: chip (esp32, stm32g474, nrf52840, freertos) and doc (a doc_id from list_documents). Each result has doc, page_start/page_end, a section breadcrumb and the chunk text; cite as [doc p.N] with a page inside page_start..page_end."""
    return _search(query, chip, doc, k)


@mcp.tool()
def naive_search(query: str, k: int = config.TOP_K) -> dict:
    """Baseline unrouted text search (no chip filter)."""
    return _search(query, None, None, k)


@mcp.tool()
def get_chunk_context(chunk_id: str, window: int = 1) -> dict:
    """Return a chunk and its neighbouring chunks (same document, document order) to read the text before/after a search hit."""
    res = _index().neighbors(chunk_id, window=max(0, min(int(window), 5)))
    if not res:
        return {"chunk_id": chunk_id, "results": [], "error": f"Unknown chunk_id '{chunk_id}'"}
    return {"chunk_id": chunk_id, "results": res}


@mcp.tool()
def list_documents() -> dict:
    """List the indexed documents (doc_id, title, version, chip, pages, chunk count) taken from the corpus manifest; documents without a real PDF are listed as not indexed."""
    ix = _index()
    counts = {d["doc"]: d for d in ix.documents()}
    docs = []
    for d in ix.meta().get("docs", []):
        c = counts.get(d["doc"])
        docs.append({**d, "chunks": c["chunks"] if c else 0, "indexed": bool(c)})
    if not docs:
        docs = [{"doc": k, "chip": v["chip"], "chunks": v["chunks"], "indexed": True} for k, v in counts.items()]
    return {"count": len(docs), "documents": docs}


if __name__ == "__main__":
    mcp.run()
