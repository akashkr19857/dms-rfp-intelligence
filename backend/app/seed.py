"""Demo workspaces, users and the sample documents (see data/SOURCES.md)."""
from __future__ import annotations

import json
import logging

from .config import KB_WS, PROJECT_ROOT, TENDERS_WS
from .db import Document, User, Workspace, session

log = logging.getLogger("rfp.seed")

WORKSPACES = [
    (TENDERS_WS, "Tenders", "Incoming RFP / tender documents to analyse"),
    (KB_WS, "Knowledge Base", "Organisational knowledge: company profile, policies, past performance, personnel"),
]
# Demo users. Tokens are demo-only bearer tokens (no passwords); production would plug in SSO/OIDC here.
USERS = [
    ("bid-manager", "Priya (Bid Manager)", "demo-bid-manager", "admin", [TENDERS_WS, KB_WS]),
    ("presales", "Arjun (Pre-sales Engineer)", "demo-presales", "member", [TENDERS_WS, KB_WS]),
    ("reviewer", "Meera (Legal Reviewer, tenders only)", "demo-reviewer", "member", [TENDERS_WS]),
]
MANIFEST = PROJECT_ROOT / "data" / "manifest.json"


def seed_identities() -> None:
    with session() as db:
        for wid, name, desc in WORKSPACES:
            if db.get(Workspace, wid) is None:
                db.add(Workspace(id=wid, name=name, description=desc))
        db.flush()
        for uid, name, token, role, wss in USERS:
            if db.get(User, uid) is None:
                u = User(id=uid, name=name, token=token, role=role)
                u.workspaces = [db.get(Workspace, w) for w in wss]
                db.add(u)
        db.commit()


def seed_documents(ingest: bool = True) -> list[int]:
    """Register (and optionally ingest) every document in data/manifest.json that is not in the DB yet."""
    from .ingest.pipeline import ingest_document, register_document

    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    new_ids: list[int] = []
    for e in entries:
        path = PROJECT_ROOT / e["path"]
        if not path.exists():
            log.warning("missing %s - run data/download_data.py", path)
            continue
        with session() as db:
            existing = db.query(Document).filter(Document.path == e["path"]).first()
            if existing is not None and existing.status == "ready":
                continue
            doc_id = existing.id if existing else register_document(path, e["workspace"], e.get("title"), e.get("source", ""))
        if ingest:
            doc = ingest_document(doc_id)
            log.info("ingested %s: %s chunks, %s pages, %.1fs", doc.title, doc.n_chunks, doc.pages, doc.ingest_seconds)
        new_ids.append(doc_id)
    return new_ids
