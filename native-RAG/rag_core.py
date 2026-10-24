"""
rag_core.py
===========
The shared "engine room". Both ingest.py and ask.py import from here, so the
important building blocks are each defined exactly ONCE.

Mapping to the 5 core elements:
    Element 2 (embedding model) -> get_embeddings()
    Element 3 (vector database) -> get_vectorstore()
    Element 4 (the LLM / brain) -> get_llm()
    Element 5 (orchestration)   -> answer_question()  (ties it all together)

Notice that heavy libraries (torch, transformers, chromadb...) are imported
INSIDE the functions, not at the top of the file. This keeps start-up fast:
ingest.py never loads the LLM, and ask.py in "extractive" mode never loads torch.
"""

from __future__ import annotations
import os
from pathlib import Path

import config


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 2 — EMBEDDING MODEL
# ─────────────────────────────────────────────────────────────────────────────
def get_embeddings():
    """Return the embedding model that converts text -> vectors.

    We wrap sentence-transformers with LangChain's HuggingFaceEmbeddings so it
    plugs straight into the vector store. `normalize_embeddings=True` scales
    every vector to length 1, which makes cosine-similarity search behave nicely.
    """
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=config.EMBEDDING_MODEL_NAME,
        model_kwargs={"device": config.EMBED_DEVICE},
        encode_kwargs={"normalize_embeddings": True},
    )


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 3 — VECTOR DATABASE (ChromaDB)
# ─────────────────────────────────────────────────────────────────────────────
def get_vectorstore(embeddings=None):
    """Open (or create) the persistent Chroma database on disk.

    Passing the same `embeddings` object used at ingest time is important: the
    database must embed your *question* with the exact same model it used for the
    documents, otherwise the vectors would not be comparable.
    """
    from langchain_chroma import Chroma

    if embeddings is None:
        embeddings = get_embeddings()

    return Chroma(
        collection_name=config.COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(config.CHROMA_DIR),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 4 — THE LLM (the brain)
# ─────────────────────────────────────────────────────────────────────────────
def get_llm():
    """Return the language model chosen in config.LLM_BACKEND.

    Returns None for the "extractive" backend, because that mode uses no LLM.
    """
    backend = config.LLM_BACKEND.lower()

    if backend == "extractive":
        return None

    if backend in {"openai", "openai-compatible", "openai_compatible"}:
        from langchain_openai import ChatOpenAI

        if not config.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY / LLM_API_KEY is empty. "
                "Set it in .env or ../agent/.env."
            )
        return ChatOpenAI(
            model=config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
            temperature=config.OPENAI_TEMPERATURE,
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),   # [eval] harness đặt 0 để tự điều tiết tốc độ gọi API
        )

    if backend == "ollama":
        # Talks to the local Ollama app over HTTP. You must install Ollama and
        # run e.g. `ollama pull llama3.2` first.
        from langchain_ollama import OllamaLLM

        return OllamaLLM(model=config.OLLAMA_MODEL, base_url=config.OLLAMA_BASE_URL)
    if backend == "huggingface":
        # Runs a model locally with the transformers library. flan-t5 is a
        # "text2text" (sequence-to-sequence) model, so we use that pipeline type.
        from transformers import (
            AutoModelForSeq2SeqLM,
            AutoTokenizer,
            pipeline,
        )
        from langchain_huggingface import HuggingFacePipeline

        tokenizer = AutoTokenizer.from_pretrained(config.HF_LLM_MODEL)
        model = AutoModelForSeq2SeqLM.from_pretrained(config.HF_LLM_MODEL)
        pipe = pipeline(
            "text2text-generation",
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=config.HF_MAX_NEW_TOKENS,
            truncation=True,  # flan-t5 only accepts 512 input tokens; trim extra
        )
        return HuggingFacePipeline(pipeline=pipe)

    raise ValueError(
        f"Unknown LLM_BACKEND '{config.LLM_BACKEND}'. "
        "Use 'openai', 'huggingface', 'ollama', or 'extractive'."
    )


# ─────────────────────────────────────────────────────────────────────────────
# THE PROMPT — the instructions we wrap around the retrieved context.
# This is where we tell the LLM to answer ONLY from the documents. Forcing the
# model to stick to the provided context is what stops it "hallucinating".
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_TEMPLATE = """You are a helpful technical assistant for embedded hardware questions: ESP32, STM32G474, nRF52840 and FreeRTOS.
Answer the QUESTION using ONLY the CONTEXT below.
If the answer is not contained in the context, reply exactly:
"I could not find this in the documents."

CONTEXT:
{context}

QUESTION: {question}

ANSWER:"""


# [eval] helpers used by ingest.py and eval_adapter.py -----------------------------
def load_doc_index(manifest_path=None) -> dict:
    """Map PDF file name -> doc_id using corpus/manifest.yaml (entries with file: null are skipped)."""
    import yaml

    path = Path(manifest_path or config.MANIFEST_PATH)
    if not path.is_file():
        return {}
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {Path(e["file"]).name: e["doc_id"] for e in entries if e.get("file") and e.get("kind", "pdf") == "pdf"}


def enrich_metadata(metadata: dict, doc_index: dict) -> dict:
    """Add 1-based page number and doc_id (PyPDFDirectoryLoader's `page` is 0-based)."""
    name = Path(metadata.get("source", "")).name
    out = dict(metadata)
    out["page_1based"] = int(metadata.get("page", 0)) + 1
    out["doc_id"] = doc_index.get(name) or Path(name).stem
    return out


def split_message(msg) -> tuple[str, dict]:
    """AIMessage -> (text, {"in": prompt_tokens, "out": completion_tokens})."""
    um = getattr(msg, "usage_metadata", None) or {}
    return (msg.content or "").strip(), {"in": int(um.get("input_tokens", 0)), "out": int(um.get("output_tokens", 0))}


def format_docs(docs) -> str:
    """Join the retrieved chunks into a single block of context text."""
    return "\n\n---\n\n".join(d.page_content for d in docs)


def _extractive_answer(docs) -> str:
    """Fallback 'answer' when no LLM is used: just show the best-matching chunk."""
    if not docs:
        return "I could not find anything relevant in the documents."
    return docs[0].page_content.strip()


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 5 — ORCHESTRATION: retrieve -> build prompt -> generate
# This single function is the whole "query pipeline".
# ─────────────────────────────────────────────────────────────────────────────
def answer_question_ex(question: str, vectorstore=None, llm=None, k: int | None = None) -> dict:
    """Same pipeline as answer_question, but also returns the token usage.

    Returns {"answer": str, "docs": [Document], "usage": {"in": int, "out": int}}.
    The chain is `prompt | llm` (not `| StrOutputParser()`) so the AIMessage's
    usage_metadata is still available; the answer is its `.content`.
    """
    k = k or config.RETRIEVE_K
    if vectorstore is None:
        vectorstore = get_vectorstore()

    # Step 1 — retrieval
    retriever = vectorstore.as_retriever(search_kwargs={"k": k})
    docs = retriever.invoke(question)

    # No-LLM mode: return the best chunk directly (proves retrieval works).
    if config.LLM_BACKEND.lower() == "extractive":
        return {"answer": _extractive_answer(docs), "docs": docs, "usage": {"in": 0, "out": 0}}

    # Steps 2-4 — build prompt and generate, using LangChain's pipe (|) syntax.
    if llm is None:
        llm = get_llm()

    from langchain_core.prompts import PromptTemplate

    prompt = PromptTemplate.from_template(PROMPT_TEMPLATE)
    out = (prompt | llm).invoke({"context": format_docs(docs), "question": question})
    if isinstance(out, str):  # text-completion backends (ollama / huggingface) return plain strings
        return {"answer": out.strip(), "docs": docs, "usage": {"in": 0, "out": 0}}
    text, usage = split_message(out)
    return {"answer": text, "docs": docs, "usage": usage}


def answer_question(question: str, vectorstore=None, llm=None, k: int | None = None):
    """Answer one question and also return the source chunks used.

    Steps (this IS the RAG query pipeline):
        1. embed the question and search Chroma for the k most similar chunks
        2. glue those chunks together into a "context"
        3. fill the prompt template with context + question
        4. send it to the LLM and read back the answer
    """
    r = answer_question_ex(question, vectorstore, llm, k)
    return r["answer"], r["docs"]
