"""
ingest.py  —  STEP 1 of the pipeline  (run this ONCE, before asking questions)
==============================================================================

    ┌────────┐   ┌────────┐   ┌────────┐   ┌────────────┐   ┌──────────┐
    │  PDFs  │ → │  text  │ → │ chunks │ → │ embeddings │ → │ ChromaDB │
    └────────┘   └────────┘   └────────┘   └────────────┘   └──────────┘
       load        extract      split        (vectors)         store

Usage:
    python ingest.py            # build the index
    python ingest.py --reset    # delete the old index first, then rebuild

The first run downloads the embedding model (~90 MB) and then reads every PDF,
so it takes a little while. After that the index lives in ./chroma_db and you
never need to run this again unless your PDFs change.
"""

import shutil
import sys
import time

import config
from rag_core import enrich_metadata, get_embeddings, get_vectorstore, load_doc_index

# How many chunks to embed per batch. Batching gives us a progress read-out and
# keeps memory use low on big documents like the ESP32 technical reference.
BATCH_SIZE = 200


def load_pdfs():
    """Read every PDF in the data folder into a list of page 'documents'."""
    from langchain_community.document_loaders import PyPDFDirectoryLoader

    loader = PyPDFDirectoryLoader(str(config.PDF_DIR))
    pages = loader.load()
    # [eval] PyPDFDirectoryLoader's `page` is 0-based; add `page_1based` and the corpus `doc_id`
    # so retrieved sources can be checked against corpus/manifest.yaml.
    doc_index = load_doc_index()
    for p in pages:
        p.metadata = enrich_metadata(p.metadata, doc_index)
    return pages


def split_documents(pages):
    """Cut the pages into overlapping, fixed-size chunks.

    RecursiveCharacterTextSplitter tries to break on natural boundaries first
    (paragraphs, then lines, then words) so chunks stay readable.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        add_start_index=True,  # remember where in the page each chunk started
    )
    return splitter.split_documents(pages)


def main():
    # --- Safety check: are the PDFs actually there? ---
    pdfs = list(config.PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"[ERROR] No PDFs found in {config.PDF_DIR}")
        print("        Put your .pdf files there and run again.")
        sys.exit(1)
    print(f"Found {len(pdfs)} PDF(s):")
    for p in pdfs:
        print(f"  - {p.name}")

    # --- Always rebuild from scratch so we never store duplicate chunks. ---
    if config.CHROMA_DIR.exists():
        print(f"\nRemoving old index at {config.CHROMA_DIR} ...")
        shutil.rmtree(config.CHROMA_DIR)

    # --- Load + split ---
    print("\n[1/4] Loading PDFs (extracting text from every page)...")
    t0 = time.time()
    pages = load_pdfs()
    print(f"      Loaded {len(pages)} pages in {time.time() - t0:.1f}s")

    print("[2/4] Splitting pages into chunks...")
    chunks = split_documents(pages)
    print(f"      Produced {len(chunks)} chunks "
          f"(size={config.CHUNK_SIZE}, overlap={config.CHUNK_OVERLAP})")

    # --- Embed + store ---
    print("[3/4] Loading embedding model "
          f"({config.EMBEDDING_MODEL_NAME})...")
    print("      (first run downloads ~90 MB — please wait)")
    embeddings = get_embeddings()
    vectorstore = get_vectorstore(embeddings)

    print(f"[4/4] Embedding {len(chunks)} chunks and saving to ChromaDB...")
    t0 = time.time()
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        vectorstore.add_documents(batch)
        done = min(i + BATCH_SIZE, len(chunks))
        print(f"      {done}/{len(chunks)} chunks embedded", end="\r")
    print()  # newline after the progress line

    print(f"\nDone in {time.time() - t0:.1f}s.")
    print(f"Index saved to: {config.CHROMA_DIR}")
    print("\nNext step:  python ask.py")


if __name__ == "__main__":
    main()
