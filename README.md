# DMS RFP Intelligence System

**GenAI-powered RFP / tender intelligence.** Upload a tender and get its key facts, every bidder requirement, a compliance
matrix checked against your own company knowledge base, a risk & gap register, a bid/no-bid score and a cited first draft
of the proposal response. Every finding links to the exact page it came from. Runs fully on a local LLM.

![demo](demo/demo.gif)

▶ **Full demo video:** [`demo/demo.mp4`](demo/demo.mp4)

## The problem

Bid teams spend days reading 30–200 page RFPs to find what is required, whether they can comply, and what could
disqualify them, then copy-paste old proposals into a new response. Generic chatbots hallucinate and can't show where
an answer came from, which is unacceptable for documents with legal and financial consequences.

## What it does

| Feature | How |
|---|---|
| **Document intelligence** | PDF (text, tables, scanned pages via OCR) and DOCX parsing; section-aware chunks that never cross a page, so every citation is page-exact |
| **Key facts** | Issuer, deadlines, pre-proposal meeting, contact, submission method, validity, deployment, timeline, with source page |
| **Evaluation criteria** | Scoring criteria and points, with source page |
| **Requirement extraction** | Every obligation on the bidder: categorised (functional, technical, security, data, legal, commercial, submission, ...), mandatory vs desirable, de-duplicated, with page |
| **Compliance / eligibility analysis** | Each requirement checked against the organisational knowledge base with RAG: *met / partial / gap / unknown* + evidence + KB citation; bid team can override |
| **Risk & gap detection** | RFP clauses compared with our standard terms (liability, validity, data exit, schedule, scope, hosting, law, pricing, insurance, submission); false alarms removed by cross-checking against the compliance results |
| **Bid / no-bid score** | Transparent formula: 70% weighted compliance of mandatory requirements + 30% risk exposure |
| **Proposal response generation** | 8 sections drafted from the reusable knowledge base with `[K#]` / `[R#]` citations; missing facts become `[Bid team to confirm: ...]` instead of being invented; Word export with compliance matrix and risk register |
| **Ask the RFP** | Grounded Q&A over the RFP + knowledge base with page citations, or an explicit "not found" |
| **Role-based access** | Bid manager / pre-sales / legal reviewer (reviewer cannot see the knowledge base or draft proposals) |
| **Evaluation built in** | Hand-labelled answer key from the real RFP text; results shown in the dashboard |

## Architecture

```mermaid
flowchart LR
  U[RFP / KB upload<br/>PDF · DOCX] --> P[Parse + chunk<br/>page-exact] --> I[(BM25 + Qdrant vectors)]
  I --> H[Hybrid retrieval<br/>RRF fusion + cross-encoder reranker]
  H --> A[Analysis pipeline<br/>facts → requirements → compliance → risks → score]
  H --> G[Proposal writer + Ask]
  L[[qwen2.5:7b · Ollama · JSON mode]] -.-> A & G
  A & G --> API[FastAPI + WebSocket] --> UI[Next.js dashboard]
```

Details and design decisions: [docs/architecture.md](docs/architecture.md).

**RAG pipeline:** document parsing → chunking → embeddings (`nomic-embed-text`) → vector indexing (Qdrant) + BM25 →
retrieval (reciprocal rank fusion) → reranking (`BAAI/bge-reranker-base`) → LLM response generation with source-grounded,
page-level references.

## Results (measured)

RESULTS_TABLE

Full per-item results (every requirement, status, risk and answer): **Evaluation** page in the app, or
[`backend/eval/results/`](backend/eval/results). Method and caveats: [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Tech stack

Python 3.11 · FastAPI · SQLAlchemy/SQLite · Qdrant · rank-bm25 · sentence-transformers (cross-encoder) · PyMuPDF ·
RapidOCR · python-docx · LangGraph · Ollama (`qwen2.5:7b`, `nomic-embed-text`) · Next.js 15 · React 19 · Tailwind ·
Recharts · Playwright · pytest · Docker.

## Quick start

**Windows (one click):** install [Ollama](https://ollama.com), Python 3.11 and Node 22, then

```bat
pip install -r requirements.txt
python -m playwright install chromium
run_demo.bat
```

It pulls the models, downloads the public RFPs, builds the sample knowledge base, indexes everything and opens
http://localhost:3200. Sign in as **Priya (Bid Manager)**, open a tender and click **Analyse RFP**.

**Linux / macOS:**

```bash
pip install -r requirements.txt
ollama pull qwen2.5:7b && ollama pull nomic-embed-text
python data/download_data.py && python backend/scripts/seed.py
python backend/scripts/analyze.py all            # optional: analyse all tenders up front
uvicorn app.main:app --app-dir backend --port 8200 &
cd frontend && npm install && npm run build && npm run start
```

**Docker:** `docker compose up --build` (API :8200, dashboard :3200, Ollama with GPU). The compose file is written and
syntax-checked but was not run on the development laptop, which has no Docker.

## Tests

```bash
python -m pytest                      # 52 tests: parsing, DOCX, retrieval, RAG, RFP pipeline, proposal export, API, RBAC, retry
python -m pytest tests/e2e            # Playwright end-to-end test against the running app
python backend/eval/run_eval.py --release v1.0.0 --label baseline   # accuracy evaluation (local LLM)
```

Unit tests use a scripted fake LLM, embedder and reranker, so they run in seconds without a GPU.

## Data

* **RFPs:** three real public solicitations from US local governments (Champaign County IL, City of Detroit, City of
  Tacoma), see [data/SOURCES.md](data/SOURCES.md).
* **Knowledge base:** a **fictional** vendor ("Nimbus JusticeTech Solutions") generated by
  [`data/make_knowledge_base.py`](data/make_knowledge_base.py), designed to meet some requirements and miss others so the
  compliance and risk analysis has known ground truth. Replace it with your own company documents.

## Screenshots

| | |
|---|---|
| ![tenders](demo/screenshots/01_tenders.png) | ![overview](demo/screenshots/02_overview.png) |
| ![requirements](demo/screenshots/03_requirements.png) | ![risks](demo/screenshots/05_risks.png) |
| ![proposal](demo/screenshots/06_proposal.png) | ![evaluation](demo/screenshots/08_evaluation.png) |

## Limitations & roadmap

* A 7B local model is fast and private but not perfect: about 1 in 8 labelled requirements is missed and compliance
  needs human review, which is why every status can be overridden. A larger model (or an API model behind the same
  interface) improves recall.
* Analysis takes ~9 minutes for a 30-page RFP on a laptop GPU; batching on a server GPU or vLLM would cut this sharply.
* Next: Excel requirement-matrix import/export (many RFPs ship Attachment B as .xlsx), clause library for past answers,
  SSO, multi-tenant workspaces.

---

Built by **Akash Kumar**: AI engineer for computer vision, GenAI, RAG and AI agents.
Need this for your business? **akashkr19857@gmail.com** · [LinkedIn](https://www.linkedin.com/in/akash-kumar-883220192)
· [GitHub](https://github.com/akashkr19857)
