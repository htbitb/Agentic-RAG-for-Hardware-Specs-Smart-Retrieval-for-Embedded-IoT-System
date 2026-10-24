"""
config.py
=========
ALL the settings for the RAG system live in this one file.

Why a single config file?  So that when you want to experiment (try a different
embedding model, bigger chunks, another LLM...) you change ONE line here instead
of hunting through the whole codebase. Every other file imports from here.

Each setting below is grouped by which of the "5 core elements" it belongs to.
Read the comments — they explain WHAT the setting does and WHY it matters.
"""

import os
from pathlib import Path

# The folder that contains THIS file. We build every other path relative to it,
# so the project works no matter which directory you run it from.
ROOT = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Load environment variables from .env (local or ../agent/.env)."""
    for candidate in (ROOT / ".env", ROOT.parent / "agent" / ".env"):
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            elif " #" in val:
                val = val.split(" #", 1)[0].strip()
            if key and (key not in os.environ or (not os.environ[key] and val)):
                os.environ[key] = val


_load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 1 — DATA SOURCE
# The raw knowledge we want the system to be able to answer questions about.
# Here: the shared corpus (../corpus/pdfs): ESP32, STM32G474, nRF52840, FreeRTOS.
# [eval] PDF_DIR can be overridden with the RAG_PDF_DIR env var; MANIFEST_PATH maps
# each file name to the doc_id used by every system under evaluation.
# ─────────────────────────────────────────────────────────────────────────────
PDF_DIR = Path(os.getenv("RAG_PDF_DIR", "").strip() or (ROOT.parent / "corpus" / "pdfs"))
MANIFEST_PATH = Path(os.getenv("RAG_MANIFEST", "").strip() or (ROOT.parent / "corpus" / "manifest.yaml"))


# ─────────────────────────────────────────────────────────────────────────────
# CHUNKING — how we cut the PDFs into bite-sized pieces before embedding.
# An LLM (and an embedding model) can only look at a limited amount of text at
# once, and searching works best on small, focused pieces. So we split every
# document into overlapping "chunks".
#   CHUNK_SIZE     = how many characters per chunk (~200-250 words here).
#   CHUNK_OVERLAP  = characters shared between neighbouring chunks so a sentence
#                    that sits on a boundary is not cut in half and lost.
# ─────────────────────────────────────────────────────────────────────────────
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 2 — EMBEDDING MODEL
# Turns a piece of text into a list of numbers (a "vector") that captures its
# meaning. Similar meanings -> similar vectors. This is what makes "search by
# meaning" possible.
#
# all-MiniLM-L6-v2 is a small (~90 MB), fast, FREE model that runs on your CPU.
# It outputs 384-number vectors and is the classic "hello world" of embeddings.
# The model is downloaded automatically the first time you run ingest.py.
# ─────────────────────────────────────────────────────────────────────────────
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# [eval] device the embedding model runs on: cpu | mps | cuda (default cpu).
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "").strip().lower() or "cpu"


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 3 — VECTOR DATABASE (ChromaDB)
# A special database that stores the vectors from element 2 and can very quickly
# find the vectors most similar to a query vector. Runs locally, no server, no
# account. It saves its files on disk in CHROMA_DIR so you only have to build the
# index once.
# ─────────────────────────────────────────────────────────────────────────────
CHROMA_DIR = ROOT / "chroma_db"
COLLECTION_NAME = "esp32_rtos"   # a "collection" is like a table inside Chroma


# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVAL — at question time, how many chunks do we pull from the database?
# These become the "context" we hand to the LLM. More chunks = more context but
# also more noise (and can exceed the LLM's input limit). 4 is a good start.
# ─────────────────────────────────────────────────────────────────────────────
RETRIEVE_K = 4


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 4 — THE LLM (the "brain" that writes the final answer)
# You can switch backends here without touching any other file:
#
#   "openai"      : uses any OpenAI-compatible API endpoint (Gemini, OpenAI,
#                   vLLM, LM Studio, etc.) configured via .env / ../agent/.env.
#   "huggingface" : runs a small model on YOUR computer, fully offline & free.
#                   Default = google/flan-t5-base (~1 GB, downloaded once).
#   "ollama"      : uses the Ollama app if you install it (better answers).
#                   Install from https://ollama.com then run: ollama pull llama3.2
#   "extractive"  : NO language model at all — just returns the most relevant
#                   chunk text. Great for testing that retrieval works, and it
#                   needs zero extra downloads.
# ─────────────────────────────────────────────────────────────────────────────
LLM_BACKEND = "openai"

# --- settings for the "openai" (OpenAI-compatible API) backend ---
OPENAI_API_KEY = (
    os.getenv("LLM_API_KEY", "").strip()
    or os.getenv("OPENAI_API_KEY", "").strip()
    or os.getenv("GEMINI_API_KEY", "").strip()
)
OPENAI_BASE_URL = (
    os.getenv("LLM_BASE_URL", "").strip()
    or os.getenv("OPENAI_BASE_URL", "").strip()
    or "https://generativelanguage.googleapis.com/v1beta/openai/"
)
OPENAI_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
OPENAI_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0") or 0.0)

# --- settings for the "huggingface" backend ---
HF_LLM_MODEL = "google/flan-t5-base"   # try "google/flan-t5-small" for speed
HF_MAX_NEW_TOKENS = 256                 # max length of the generated answer

# --- settings for the "ollama" backend ---
OLLAMA_MODEL = "llama3.2"
OLLAMA_BASE_URL = "http://localhost:11434"

# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT 5 — ORCHESTRATION FRAMEWORK
# We use LangChain to glue elements 1-4 together. There is no setting to change
# here; it is the library the other files import. See rag_core.py to watch the
# pieces being connected.
# ─────────────────────────────────────────────────────────────────────────────
