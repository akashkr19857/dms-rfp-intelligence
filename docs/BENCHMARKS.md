# Benchmarks and evaluation method

All numbers come from `python backend/eval/run_eval.py --release v1.0.0 --label baseline`
(results file in `backend/eval/results/`) on an **NVIDIA RTX 4060 Laptop GPU (8 GB), Intel i5-12450H, 16 GB RAM,
Windows 11**, with `qwen2.5:7b` and `nomic-embed-text` served by Ollama and `BAAI/bge-reranker-base` on the GPU.
Nothing is estimated.

Hardware: **NVIDIA RTX 4060 Laptop GPU (8 GB)**, Intel i5-12450H, Windows 11 · LLM `qwen2.5:7b` via Ollama (local) ·
answer key hand-labelled from the real RFP text ([`backend/eval/gold_rfp.json`](backend/eval/gold_rfp.json)).

| What | Result | Measured on |
|---|---|---|
| Key-fact extraction accuracy | **100%** (15/15) | deadlines, contacts, validity, deployment, timeline, 2 RFPs |
| Requirement extraction recall | **87%** (26/30) | 30 labelled Champaign County requirements, page must match ±1 |
| Compliance status accuracy | **93%** (13/14) | labelled met / partial / gap statuses vs the knowledge base |
| Risk detection recall | **86%** (6/7) | labelled risks (uncapped indemnity, 180-day validity, 15-day data exit, ...) |
| Grounded Q&A correctness | **86%** (LLM judge; 11/14 fully correct) | 14 answerable questions |
| Retrieval hit@5 (gold page in top 5) | **92%** (11/12) | questions with a known source page |
| Unanswerable question correctly refused | **100%** (1/1), 1 false refusal | |
| Q&A latency | **0.9 s** median, 9.5 s p95 | warm models |

| Full analysis per RFP | Pages | Time | LLM calls | Requirements | Risks | Bid score |
|---|---|---|---|---|---|---|
| Champaign County, Court Case Management System | 30 | 8.3 min | 118 | 90 | 11 | 57.8 · Bid with conditions |
| City of Detroit, Records Management Software | 17 | 7.6 min | 110 | 86 | 12 | 55.9 · Bid with conditions |
| City of Tacoma, FERC Document Management System | 53 | 15.7 min | 246 | 207 | 12 | 46.1 · No bid |

## How each metric is computed

* **Answer key**: written by hand from the public RFP text, with PDF page numbers ([gold_rfp.json](../backend/eval/gold_rfp.json)).
  Matching is keyword based: an item counts as found when all keywords of one alternative appear in the system output
  and (for requirements) the cited page is within ±1 of the labelled page.
* **Key facts**: 9 fields of the Champaign County RFP + 6 of the Detroit RFP.
* **Requirement recall**: 30 obligations labelled from the Champaign County RFP (hosting, submission format, validity,
  plans, upgrades, reviews, personnel, indemnity, records, confidentiality, data return, DR, backups, ...).
  The system extracted 90 requirements in total; precision was not labelled.
* **Compliance accuracy**: expected status of the *fictional* company for 17 of those requirements (designed into
  `data/make_knowledge_base.py`); 14 could be judged because their requirement was extracted.
* **Risk recall**: 7 labelled risks. Missed: the hard-copy/USB submission-format risk (the system reported a
  "no email proposals" risk on the same page instead).
* **Q&A**: 15 questions (12 on the RFPs, 2 on the knowledge base, 1 unanswerable). Correctness is judged by the same
  local LLM against a reference answer (1 / 0.5 / 0); hit@5 checks whether the labelled page is among the top 5 sources.
* **Timing**: wall-clock time of the full analysis (facts, criteria, requirements, compliance, risks, score), one RFP
  at a time; LLM calls counted per analysis.

## What changed during development (and why it is measured)

| Version | Change | Effect |
|---|---|---|
| first run | single-pass risk detection | 14 risks on Champaign, incl. false alarms (e.g. "data storage conflict" although the company hosts in the US) |
| verifier | second LLM call to double-check each risk | removed false alarms but also real ones: risk recall fell to 29% |
| v1.0.0 | drop a risk only if the requirement it refers to was judged *met* by the compliance stage | risk recall 86%, both false alarms removed |

## Known limitations

* The answer key is small (one person, three RFPs); treat the numbers as indicative, not as a benchmark.
* LLM outputs vary slightly between runs; requirement counts differed by a few items across runs.
* The LLM judge for Q&A is the same 7B model that generates answers.
