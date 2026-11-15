# Architecture

```mermaid
flowchart LR
  subgraph Ingestion
    U[Upload RFP / KB document<br/>PDF or DOCX] --> P[Parse<br/>PyMuPDF text + tables + OCR<br/>python-docx parts + tables]
    P --> C[Section-aware chunking<br/>page / part metadata + highlight boxes]
    C --> E[Embeddings<br/>nomic-embed-text]
    E --> Q[(Qdrant<br/>vectors)]
    C --> S[(SQLite<br/>chunks, BM25 corpus)]
  end

  subgraph Retrieval["Hybrid retrieval (shared by every stage)"]
    B[BM25] --> F[Reciprocal Rank Fusion]
    V[Vector search] --> F
    F --> R[Cross-encoder reranker<br/>bge-reranker-base]
  end

  subgraph Analysis["RFP analysis pipeline (background job, live progress over WebSocket)"]
    A1[Key facts + evaluation criteria] --> A2[Requirement extraction<br/>obligation filter → batched JSON LLM calls → de-dup]
    A2 --> A3[Compliance vs knowledge base<br/>RAG over KB per requirement]
    A3 --> A4[Risk & gap detection<br/>RFP clause vs our standard position]
    A4 --> A5[Bid / no-bid score]
  end

  subgraph Generation
    G1[Proposal writer<br/>8 sections, K/R citations] --> G2[Word export<br/>+ compliance matrix + risk register]
    G3[Ask: grounded Q&A<br/>page citations or explicit not-found]
  end

  Q --> V
  S --> B
  R --> Analysis
  R --> Generation
  LLM[[qwen2.5:7b via Ollama<br/>local, JSON mode]] -.-> Analysis
  LLM -.-> Generation
  Analysis --> DB[(SQLite: analyses, requirements, risks, proposals)]
  DB --> API[FastAPI :8200<br/>REST + WebSocket, role-based access]
  API --> UI[Next.js dashboard :3200]
```

## Why it is built this way

| Decision | Reason |
|---|---|
| Hybrid BM25 + vectors + reranker | RFPs are full of exact terms (section numbers, "180 calendar days", system names) that pure vector search misses; BM25 catches them, the reranker orders the fused list. |
| Chunks never cross a page | Every requirement, fact, risk and answer can cite one exact page and highlight the passage. |
| Obligation-language pre-filter | Only chunks with "shall / must / required / ..." go to requirement extraction, cutting LLM calls on background pages (statistics, definitions). |
| JSON-mode LLM calls with source numbers | Each LLM output names the excerpt it used; the code maps it back to page + chunk, so citations are produced by the system, not trusted from free text. |
| Compliance = RAG over the knowledge base | Each requirement retrieves its own evidence from company documents, so the status is explainable ("met because ... [Security policy, part 3]"). |
| Risks compare both sides | The risk prompt sees the RFP clause and our standard position side by side, so it reports conflicts (e.g. 15-day vs 30-day data return) rather than generic clauses. |
| Deterministic bid score | The score is a transparent formula over compliance and risk severity, not an LLM opinion. |
| Missing facts become placeholders | The proposal writer must write "[Bid team to confirm: ...]" instead of inventing numbers. |
| Local LLM (Ollama) | Tender documents are confidential; nothing leaves the machine and there is no per-token cost. |

## Data model

`documents` (workspace = tenders | knowledge-base) → `chunks` · per tender: `analyses` (facts, criteria, timings, bid score),
`requirements` (status, evidence, KB sources, manual override), `risks`, `proposals` (sections + citations, DOCX path) ·
`traces` (every Q&A query) · `eval_runs`.

## Roles (demo)

| User | Tenders | Knowledge base | Notes |
|---|---|---|---|
| Bid Manager (admin) | ✓ | ✓ | sees all traces |
| Pre-sales Engineer | ✓ | ✓ | |
| Legal Reviewer | ✓ | ✗ | can review risks; cannot draft proposals (no KB access) |
