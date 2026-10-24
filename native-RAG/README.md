# Simple RAG System — ESP32 & FreeRTOS Q&A

A beginner-friendly **Retrieval-Augmented Generation (RAG)** project. Ask plain-English
questions about the ESP32 chip and the FreeRTOS real-time operating system, and get
answers generated from three official PDF manuals — all running **locally and for free**.

> New to RAG? Open **[guide.html](guide.html)** in your browser first. It explains
> *what* every piece is and *why* it exists, in plain language, with diagrams.

---

## The 5 core elements

| # | Element | What we use | Where in the code |
|---|---------|-------------|-------------------|
| 1 | Data source | 3 PDFs in `data/pdfs/` | `ingest.py` |
| 2 | Embedding model | `all-MiniLM-L6-v2` (free, local) | `rag_core.get_embeddings()` |
| 3 | Vector database | ChromaDB (local, on disk) | `rag_core.get_vectorstore()` |
| 4 | LLM ("brain") | `flan-t5-base` (free, local) | `rag_core.get_llm()` |
| 5 | Orchestrator | LangChain | ties it all together |

## The pipeline

```
INGEST (run once):   PDFs → text → chunks → embeddings → ChromaDB
ASK   (run anytime): question → embed → search ChromaDB → top chunks → LLM → answer
```

---

## Setup (Windows / PowerShell)

Everything is free and runs offline. You need **Python 3.9** (the ML libraries do
not yet support Python 3.14).

```powershell
# 1) go into the project
cd c:\Data\Htb_dev\RAG

# 2) create an isolated environment using Python 3.9
& "C:\Program Files\Python39\python.exe" -m venv .venv

# 3) activate it
.\.venv\Scripts\Activate.ps1

# 4) install the libraries (this downloads a few hundred MB the first time)
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Run it

```powershell
# STEP 1 — build the search index from the PDFs (do this once)
python ingest.py

# STEP 2 — ask questions
python ask.py                                  # interactive mode
python ask.py "What is a task in FreeRTOS?"    # one-off question
```

---

## Try these questions

- `What is a task in FreeRTOS?`
- `How many cores does the ESP32 have?`
- `What is vTaskDelay used for?`
- `What wireless features does the ESP32 support?`

---

## Want better answers?

The default LLM (`flan-t5-base`) is small so it runs on any laptop, but its answers
are basic. For much better answers, install **[Ollama](https://ollama.com)** (free),
then:

```powershell
ollama pull llama3.2
```

and set `LLM_BACKEND = "ollama"` in [config.py](config.py). No other code changes needed.

## Experiment

Open [config.py](config.py) and try changing:

- `CHUNK_SIZE` / `CHUNK_OVERLAP` — how the documents are cut up.
- `RETRIEVE_K` — how many chunks are fed to the LLM.
- `LLM_BACKEND` — `"openai"` (OpenAI-compatible API via `.env` / `../agent/.env`), `"huggingface"`, `"ollama"`, or `"extractive"` (no LLM, just shows
  the best-matching chunk — great for seeing what "retrieval" alone does).

After changing chunking, rebuild the index: `python ingest.py --reset`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No index found` when running `ask.py` | Run `python ingest.py` first. |
| Install fails on Python 3.14 | Use Python 3.9 for the venv (see Setup). |
| First answer is very slow | The model files download on first use; later runs are faster. |
| Answers are weak / generic | Switch to the Ollama backend (see above). |

## Project layout

```
RAG/
├── config.py          # all settings (start here to experiment)
├── rag_core.py        # the engine: embeddings, DB, LLM, query pipeline
├── ingest.py          # STEP 1: PDFs → ChromaDB
├── ask.py             # STEP 2: ask questions
├── requirements.txt   # dependencies
├── guide.html         # ← the full beginner explanation (open in a browser)
├── data/pdfs/         # the 3 source PDFs
└── chroma_db/         # the vector index (created by ingest.py)
```


---

## Evaluation mode (P0 — `eval/` harness)

This folder is the **S1 baseline** ("Native RAG") of the evaluation harness in `../eval/`.
It must stay naive: fixed 1000/150 chunks, MiniLM, top-4, one LLM call. All changes made for
evaluation are listed in [`CHANGELOG_EVAL.md`](CHANGELOG_EVAL.md).

* **Shared corpus** — PDFs are read from `../corpus/pdfs` (override with `RAG_PDF_DIR`); the
  `doc_id` of each file comes from `../corpus/manifest.yaml`. Every chunk carries `page_1based`
  and `doc_id` metadata. Re-ingest after changing the corpus: `./start.sh --ingest`
  (about 4 minutes on CPU; `EMBED_DEVICE=mps` or `cuda` is optional).
* **`eval_adapter.py`** — long-lived JSONL bridge (the harness spawns it with `.venv/bin/python`):
  ```
  stdin : {"id": "t1", "question": "...", "history": [{"user": "...", "assistant": "..."}], "seed": 0}
  stdout: {"id": "t1", "answer": "...", "sources": [{"doc_id": "...", "file": "...", "page": 12}],
           "usage": {"in": 812, "out": 40}, "latency_s": 1.23, "error": null}
  ```
  Logs go to stderr only. Multi-turn: earlier turns are folded into the QUESTION block; retrieval
  uses the current question.
* **LLM cache** — `LLM_CACHE=record` (read-through SQLite cache, keyed by prompt + model + seed) or
  `LLM_CACHE=replay` (cache only; a miss returns `"error": "cache_miss"` and never calls the API).
  Default path `../eval/.cache/native_rag_llm.sqlite` (`LLM_CACHE_PATH` to override).
