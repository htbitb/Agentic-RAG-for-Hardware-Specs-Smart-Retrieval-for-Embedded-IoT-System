"""
ask.py  —  STEP 2 of the pipeline  (run this to actually ask questions)
=======================================================================

    question → embed → search ChromaDB → top chunks → LLM → answer

Usage:
    python ask.py                       # interactive: keep asking questions
    python ask.py "What is a task in FreeRTOS?"   # answer one question and exit

Make sure you have run  `python ingest.py`  at least once first, otherwise the
database is empty and there is nothing to search.
"""

import sys
from pathlib import Path

import config
from rag_core import answer_question, get_llm, get_vectorstore


def print_answer(answer: str, docs) -> None:
    """Pretty-print the answer plus the sources it came from.

    Showing sources is a core RAG feature: you can always check WHERE the
    answer came from, page by page, instead of blindly trusting the model.
    """
    print("\n" + "=" * 70)
    print("ANSWER")
    print("=" * 70)
    print(answer)

    print("\n" + "-" * 70)
    print("SOURCES (the chunks the answer was based on)")
    print("-" * 70)
    for i, d in enumerate(docs, 1):
        name = Path(d.metadata.get("source", "?")).name
        # [eval] page_1based is added by ingest.py (PyPDFDirectoryLoader's `page` is 0-based)
        page = d.metadata.get("page_1based", d.metadata.get("page", "?"))
        preview = " ".join(d.page_content.split())[:110]
        print(f"[{i}] {name} (page {page})")
        print(f"    {preview}...")


def main():
    # --- Make sure the index exists before we try to search it. ---
    if not config.CHROMA_DIR.exists():
        print("[ERROR] No index found. Run this first:\n\n    python ingest.py\n")
        sys.exit(1)

    print(f"LLM backend: {config.LLM_BACKEND}")
    print("Loading the database and model (this can take a moment)...")

    # Load these ONCE and reuse them for every question, so each question is fast.
    vectorstore = get_vectorstore()
    llm = get_llm()  # returns None in "extractive" mode

    # --- One-shot mode: a question was passed on the command line. ---
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        answer, docs = answer_question(question, vectorstore, llm)
        print_answer(answer, docs)
        return

    # --- Interactive mode: loop until the user types quit. ---
    print("\nReady! Ask a question about ESP32 or FreeRTOS.")
    print("Type 'quit' (or press Ctrl+C) to exit.\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in {"quit", "exit", "q"}:
            break
        answer, docs = answer_question(question, vectorstore, llm)
        print_answer(answer, docs)

    print("Goodbye!")


if __name__ == "__main__":
    main()
