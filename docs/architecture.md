# Architecture: Agentic RAG for Hardware Specs

## 1. System overview

```mermaid
flowchart LR
    U["User<br/>CLI / Web UI"] --> ENTRY["main.py / ui/server.py"]
    ENTRY --> AGENT["ReAct agent<br/>agent/react_agent.py"]

    subgraph ONLINE ["Online: answering a question"]
        AGENT --> TOOLHUB["ToolHub (MCP client)<br/>agent/tools.py"]
        AGENT --> VERIFY["Verifier<br/>agent/verifier.py"]
        AGENT --> MEM["Episodic memory<br/>agent/memory.py"]
        AGENT --> AUDIT["Audit log<br/>agent/audit.py"]
        AGENT --> LLM["LLM (Gemini via OpenAI SDK)<br/>agent/llm.py"]
        TOOLHUB --> TM["Text-Manual MCP server<br/>mcp_servers/text_manual_server.py"]
        TOOLHUB --> TR["Table/Register MCP server<br/>mcp_servers/table_register_server.py"]
        TOOLHUB --> APPROVAL["Approval gate + sandbox<br/>agent/approval.py"]
    end

    subgraph STORES ["Stores (built offline)"]
        CHROMA[("ChromaDB<br/>evidence_chunks, naive_chunks")]
        SQLITE[("SQLite fact store<br/>facts.db")]
        EPI[("episodic_memory.db")]
    end

    TM --> CHROMA
    TR --> SQLITE
    MEM --> EPI
    AUDIT --> LOG[("logs/audit.jsonl")]
```

## 2. Offline pipeline (ingestion)

Run with `python -m ingestion.build_index`.

```mermaid
flowchart LR
    PDF["PDFs + simulated corpus<br/>datasheet, TRM, FreeRTOS, .md"] --> PARSE["pdf_parser.py<br/>pages, headings, header/footer removal"]
    PARSE --> CHUNK["chunker.py<br/>1200 chars, 180 overlap"]
    CHUNK --> EMB["MiniLM-L6-v2 embeddings<br/>(via ChromaDB)"]
    EMB --> CHROMA[("ChromaDB<br/>evidence_chunks")]
    CHUNK --> NAIVE["800-char windows<br/>(baseline only)"]
    NAIVE --> CHROMA2[("ChromaDB<br/>naive_chunks")]

    PARSE --> TABLE["table_extractor.py<br/>IO_MUX, registers, electrical tables"]
    TABLE --> NORM["unit_normalizer.py<br/>mV to V, uA to A, VDD expressions"]
    NORM --> SQLITE[("SQLite facts.db")]
```

## 3. Online agent loop

```mermaid
flowchart TD
    Q["User question"] --> IG["Input guardrail<br/>direct injection filter"]
    IG -->|blocked| END1(["END: blocked"])
    IG -->|ok| MC["Memory context<br/>resolve follow-ups"]
    MC --> HW["Hardware safety pre-check<br/>react_agent.py: e.g. apply 5 V vs abs-max"]
    HW -->|limit exceeded| END2(["END: refused, cites abs-max page"])
    HW -->|ok| LOOP

    subgraph LOOP ["ReAct loop (max 8 steps)"]
        L1["LLM step"] -->|tool_calls| T1["ToolHub.call<br/>permission, timeout, retry"]
        T1 --> OBS["Observation sanitizer<br/>indirect injection removal"]
        OBS --> L1
    end

    LOOP -->|no tool calls| DRAFT["Draft answer"]
    DRAFT --> V{"Verifier<br/>values, addresses, citations"}
    V -->|pass| MW["Memory write (verified only)"]
    MW --> END3(["END: verified answer + citations"])
    V -->|fail, first time| REFL["Append VERIFICATION FAILED<br/>reflection"]
    REFL --> LOOP
    V -->|fail again| END4(["END: insufficient evidence"])
```

## 4. Sequence of one tool call

```mermaid
sequenceDiagram
    participant A as ReAct agent
    participant H as ToolHub
    participant S as MCP server
    participant D as Store (Chroma / SQLite)
    participant L as audit.jsonl

    A->>H: call search_manual(query, chip, doc_type)
    H->>H: check tool exists and permission
    H->>S: MCP tools/call (timeout 30 s, retry read-only only)
    S->>D: embed query, top-k search with filters
    D-->>S: chunks + cosine scores
    S-->>H: results with flags
    H->>H: sanitize observation
    H->>L: write audit record (latency)
    H-->>A: observation
```

## 5. Safety layers

| Layer | Where | Purpose |
|---|---|---|
| Input guardrail | `agent/guardrail.py` | Blocks direct prompt injection |
| Hardware pre-check | `agent/react_agent.py` | Refuses values beyond absolute maximum |
| Least privilege | `agent/tools.py` | Only read-only tools run automatically |
| Observation sanitizer | `agent/guardrail.py` | Removes indirect injection from tool output |
| Approval gate | `agent/approval.py` | Human approval for the only write tool |
| Verifier | `agent/verifier.py` | Every number and citation must match evidence |
| Audit | `agent/audit.py` | JSONL trail of every tool call |

## 6. Folder map

```
hw_agentic_rag/
  config.py                    settings, paths, chunk sizes, LLM config
  main.py  run_all.py          CLI and one-command pipeline
  ingestion/                   parse, chunk, extract tables, normalize units
  stores/                      ChromaDB vector store, SQLite fact store
  mcp_servers/                 text-manual and table-register MCP servers
  agent/                       ReAct loop, LLM, tools, guardrail, verifier, memory, audit, approval
  ui/                          HTTP server and web page
  eval/                        benchmark, attacks, baselines, evaluation runner
  docs/                        explanation.html, architecture.md
```
