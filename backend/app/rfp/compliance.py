"""Compliance analysis: judge each capability requirement against the organisational knowledge base (RAG over KB),
with evidence and KB citations. Submission instructions become checklist actions (no LLM call)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..db import Requirement, session
from .common import CallCounter, llm_json, numbered, pick, search_kb, source_ref

STATUSES = ("met", "partial", "gap", "unknown")

COMPLIANCE_SYSTEM = """You are a bid compliance analyst. Decide whether OUR COMPANY meets one RFP requirement, using ONLY the
numbered excerpts from our company knowledge base (company profile, policies, past performance, personnel, terms).
Status:
- "met": the excerpts clearly show we meet the requirement as written.
- "partial": we meet part of it, only with conditions or extra work, or our standard position differs in degree
  (e.g. a shorter or longer period, a different amount).
- "gap": the excerpts show we do not offer it or our standard terms conflict with it.
- "unknown": the excerpts do not address the requirement.
Compare numbers, durations and named systems exactly: exceeding a minimum (e.g. keeping records 7 years when 3 are
required, more frequent backups, more insurance) is "met"; falling short of it (e.g. 30 days when 15 are required,
90-day validity when 180 are required) is "gap" or "partial". Do not assume capabilities that are not stated.
Reply as JSON: {"status": "met|partial|gap|unknown", "evidence": "<one sentence citing the facts that decide it>",
"sources": [<excerpt numbers used>], "confidence": <0.0-1.0>}"""


def assess(req_text: str, counter: CallCounter | None = None) -> dict:
    hits = search_kb(req_text)
    if not hits:
        return {"status": "unknown", "evidence": "No knowledge-base content found.", "kb_sources": [], "confidence": 0.0}
    data = llm_json(COMPLIANCE_SYSTEM, f"Knowledge-base excerpts:\n\n{numbered(hits, 'K')}\n\nRFP requirement: {req_text}",
                    counter, max_tokens=300)
    status = str(data.get("status", "unknown")).lower().strip()
    if status not in STATUSES:
        status = "unknown"
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    used = pick(hits, data.get("sources", []))
    if status != "unknown" and not used:
        used = hits[:1]
    return {"status": status, "evidence": str(data.get("evidence", ""))[:600], "kb_sources": [source_ref(h) for h in used],
            "confidence": conf}


def run_compliance(doc_id: int, counter: CallCounter | None = None, on_progress: Callable[[float], None] | None = None,
                   workers: int = 2) -> None:
    with session() as db:
        reqs = db.query(Requirement).filter(Requirement.doc_id == doc_id).all()
    todo = [r for r in reqs if r.kind == "capability"]
    with session() as db:
        for r in reqs:
            if r.kind == "submission":
                row = db.get(Requirement, r.id)
                row.status, row.evidence, row.confidence = "action", "Submission instruction: add to the bid checklist.", 1.0
        db.commit()
    done = 0

    def work(r: Requirement) -> tuple[int, dict]:
        return r.id, assess(r.text, counter)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rid, res in pool.map(work, todo):
            with session() as db:
                row = db.get(Requirement, rid)
                row.status, row.evidence, row.kb_sources, row.confidence = (res["status"], res["evidence"], res["kb_sources"],
                                                                            res["confidence"])
                db.commit()
            done += 1
            if on_progress:
                on_progress(done / max(len(todo), 1))
