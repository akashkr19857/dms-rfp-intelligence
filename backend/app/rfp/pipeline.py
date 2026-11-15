"""Orchestrates one full RFP analysis in a background thread and streams progress over the event bus.

    key facts → evaluation criteria → requirements → compliance vs KB → risks & gaps → bid score
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..config import TENDERS_WS
from ..db import Analysis, Document, Requirement, Risk, session
from ..events import bus
from .common import CallCounter
from .compliance import run_compliance
from .facts import extract_criteria, extract_facts
from .requirements import extract_requirements
from .risks import bid_score, detect_risks

log = logging.getLogger("rfp.analysis")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")

# share of the progress bar per stage (roughly proportional to measured time)
STAGES = [("facts", 0.08), ("criteria", 0.04), ("requirements", 0.38), ("compliance", 0.35), ("risks", 0.13), ("score", 0.02)]


def _publish(a: Analysis) -> None:
    bus.publish({"type": "analysis", "analysis": a.to_dict()})


def _set(doc_id: int, **fields) -> Analysis:
    with session() as db:
        a = db.get(Analysis, doc_id)
        if a is None:
            a = Analysis(doc_id=doc_id)
            db.add(a)
        for k, v in fields.items():
            setattr(a, k, v)
        db.commit()
        _publish(a)
        return a


def get_analysis(doc_id: int) -> Analysis | None:
    with session() as db:
        return db.get(Analysis, doc_id)


def analyze(doc_id: int) -> Analysis:
    """Synchronous full analysis (re-running replaces the previous results)."""
    with session() as db:
        doc = db.get(Document, doc_id)
        if doc is None or doc.workspace_id != TENDERS_WS or doc.status != "ready":
            raise ValueError("document is not a ready tender")
    counter = CallCounter()
    timings: dict[str, float] = {}
    _set(doc_id, status="running", stage="facts", progress=0.0, error="", started_at=datetime.now(timezone.utc),
         finished_at=None, timings={}, llm_calls=0, bid_score={}, facts={}, evaluation_criteria=[])
    base = 0.0

    def stage_progress(name: str, weight: float):
        def cb(frac: float) -> None:
            _set(doc_id, stage=name, progress=round(base + weight * frac, 3), llm_calls=counter.calls)
        return cb

    try:
        for name, weight in STAGES:
            t0 = time.perf_counter()
            _set(doc_id, stage=name, progress=round(base, 3), llm_calls=counter.calls)
            if name == "facts":
                _set(doc_id, facts=extract_facts(doc_id, counter))
            elif name == "criteria":
                _set(doc_id, evaluation_criteria=extract_criteria(doc_id, counter))
            elif name == "requirements":
                drafts = extract_requirements(doc_id, counter, stage_progress(name, weight))
                with session() as db:
                    db.query(Requirement).filter(Requirement.doc_id == doc_id).delete()
                    db.add_all(Requirement(doc_id=doc_id, ref=f"R-{i:03d}", text=d.text, category=d.category,
                                           mandatory=d.mandatory, kind=d.kind, page=d.page, section=d.section,
                                           chunk_id=d.chunk_id) for i, d in enumerate(drafts, 1))
                    db.commit()
            elif name == "compliance":
                run_compliance(doc_id, counter, stage_progress(name, weight))
            elif name == "risks":
                risks = detect_risks(doc_id, counter, stage_progress(name, weight))
                with session() as db:
                    db.query(Risk).filter(Risk.doc_id == doc_id).delete()
                    db.add_all(Risk(doc_id=doc_id, **{k: r[k] for k in ("title", "category", "severity", "description",
                                                                         "recommendation", "page", "chunk_id", "kb_sources")})
                               for r in risks)
                    db.commit()
            elif name == "score":
                with session() as db:
                    risks_d = [r.to_dict() for r in db.query(Risk).filter(Risk.doc_id == doc_id).all()]
                _set(doc_id, bid_score=bid_score(doc_id, risks_d))
            timings[name] = round(time.perf_counter() - t0, 1)
            base += weight
            _set(doc_id, timings=dict(timings), progress=round(base, 3), llm_calls=counter.calls)
        timings["total"] = round(sum(timings.values()), 1)
        return _set(doc_id, status="done", stage="done", progress=1.0, timings=timings, llm_calls=counter.calls,
                    finished_at=datetime.now(timezone.utc))
    except Exception as exc:
        log.exception("analysis failed for %s", doc_id)
        return _set(doc_id, status="failed", error=f"{type(exc).__name__}: {exc}", timings=timings,
                    finished_at=datetime.now(timezone.utc))


def analyze_async(doc_id: int) -> None:
    _set(doc_id, status="queued", stage="queued", progress=0.0, error="")
    _executor.submit(analyze, doc_id)
