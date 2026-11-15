"""Run the full RFP analysis for one or more tender documents from the command line.

    python backend/scripts/analyze.py 1          # analyse document 1
    python backend/scripts/analyze.py all        # analyse every tender
    python backend/scripts/analyze.py 1 --risks-only   # re-run only risk detection + bid score
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "_shared"))

from app.config import TENDERS_WS  # noqa: E402
from app.db import Document, Requirement, Risk, session  # noqa: E402
from app.rfp.pipeline import analyze, rerun_risks  # noqa: E402

try:
    from gpulock import gpu_lock
except ImportError:  # outside the portfolio workspace
    from contextlib import nullcontext as gpu_lock  # type: ignore[assignment]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    for noisy in ("httpx", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    risks_only = "--risks-only" in sys.argv
    arg = args[0] if args else "all"
    with session() as db:
        q = db.query(Document).filter(Document.workspace_id == TENDERS_WS, Document.status == "ready")
        ids = [d.id for d in q.all()] if arg == "all" else [int(x) for x in arg.split(",")]
    for doc_id in ids:
        with gpu_lock("dms-rfp-analysis"):
            a = rerun_risks(doc_id) if risks_only else analyze(doc_id)
        with session() as db:
            reqs = db.query(Requirement).filter(Requirement.doc_id == doc_id).all()
            risks = db.query(Risk).filter(Risk.doc_id == doc_id).all()
        print(f"doc {doc_id}: {a.status} in {a.timings.get('total')}s, {a.llm_calls} LLM calls, {len(reqs)} requirements, "
              f"{len(risks)} risks, bid score {a.bid_score.get('score')} ({a.bid_score.get('recommendation')})")
        print("  timings:", a.timings)
        if a.error:
            print("  error:", a.error)


if __name__ == "__main__":
    main()
