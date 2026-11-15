"""Create demo workspaces/users and ingest the public sample PDFs listed in data/manifest.json.

    python backend/scripts/seed.py            # ingest whatever is not ingested yet
    python backend/scripts/seed.py --reset    # wipe runtime data first
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete data/runtime before seeding")
    ap.add_argument("--reingest", default="", help="comma-separated document ids to re-ingest in place")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    for noisy in ("httpx", "RapidOCR"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    s = get_settings()
    if args.reset and s.data_dir.exists():
        shutil.rmtree(s.data_dir)
        get_settings.cache_clear()
        get_settings()
    from app.seed import seed_documents, seed_identities

    seed_identities()
    if args.reingest:
        from app.ingest.pipeline import ingest_document

        ids = [int(x) for x in args.reingest.split(",")]
        for i in ids:
            ingest_document(i)
    else:
        ids = seed_documents(ingest=True)
    from app.db import Document, session

    with session() as db:
        for d in db.query(Document).all():
            print(f"{d.id:>3} {d.status:<8} {d.workspace_id:<14} pages={d.pages:<3} chunks={d.n_chunks:<4} "
                  f"tables={d.tables:<3} ocr_pages={d.ocr_pages:<2} {d.ingest_seconds:>6.1f}s  {d.title}")
    print(f"ingested {len(ids)} document(s)")


if __name__ == "__main__":
    main()
