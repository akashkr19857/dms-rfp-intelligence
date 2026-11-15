"""Test setup: isolated temp data dir + deterministic fake embedder / reranker / LLM (no Ollama, no GPU needed)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

_TMP = Path(tempfile.mkdtemp(prefix="rfp-test-"))
os.environ.update({
    "RFP_DATA_DIR": str(_TMP),
    "RFP_LLM_PROVIDER": "fake",
    "RFP_EMBED_PROVIDER": "fake",
    "RFP_RERANK_PROVIDER": "overlap",
})

import pymupdf  # noqa: E402
import pytest  # noqa: E402

AI_TEXT = [
    ("1. Governance of AI", [
        "The GOVERN function is a cross-cutting function that cultivates a culture of risk management.",
        "Organizations should inventory their AI systems and assign accountability for model risk.",
    ]),
    ("2. Measuring AI risk", [
        "The MEASURE function uses quantitative and qualitative tools to analyze and monitor AI risk.",
        "Test sets must be representative of conditions of expected use for accuracy measurements.",
    ]),
]
SEC_TEXT = [
    ("1. Protecting systems", [
        "Enable multi-factor authentication on all accounts and change default manufacturer passwords.",
        "Back up data regularly and verify the integrity of backups before restoring them.",
    ]),
]


def make_pdf(path: Path, sections: list[tuple[str, list[str]]], table: list[list[str]] | None = None,
             scanned_page: bool = False) -> Path:
    doc = pymupdf.open()
    for heading, paras in sections:
        page = doc.new_page()
        y = 72
        page.insert_text((72, y), heading, fontsize=16, fontname="hebo")
        y += 30
        for p in paras:
            page.insert_textbox(pymupdf.Rect(72, y, 520, y + 60), p, fontsize=10)
            y += 70
    if table:
        page = doc.new_page()
        page.insert_text((72, 60), "Table 1. Function identifiers", fontsize=10)
        x0, y0, cw, rh = 72, 80, 150, 22
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                rect = pymupdf.Rect(x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)
                page.draw_rect(rect, color=(0, 0, 0), width=0.8)
                page.insert_textbox(rect + (4, 4, -2, 0), cell, fontsize=9)
    if scanned_page:
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
        pix.set_rect(pix.irect, (255, 255, 255))
        page.insert_image(pymupdf.Rect(72, 72, 472, 272), pixmap=pix)
    doc.save(path)
    return path


def fake_ocr(_png: bytes):
    # two lines in the left column, one in the right column (pixel coords of a 170-dpi render)
    return [
        ("Incident response plan: name a business champion.", (100.0, 200.0, 600.0, 230.0), 0.98),
        ("List who to call during an incident.", (100.0, 240.0, 600.0, 270.0), 0.97),
        ("Right column sidebar note", (1000.0, 205.0, 1300.0, 235.0), 0.95),
    ]


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    """Seed users/workspaces and ingest two small synthetic PDFs (one per workspace)."""
    from app.db import Document, session
    from app.ingest.pipeline import ingest_document, register_document
    from app.seed import seed_identities

    seed_identities()
    _add_kb_only_user()
    d = tmp_path_factory.mktemp("pdfs")
    ai = make_pdf(d / "ai.pdf", AI_TEXT, table=[["Function", "Identifier"], ["Govern", "GV"], ["Measure", "MS"]])
    sec = make_pdf(d / "sec.pdf", SEC_TEXT, scanned_page=True)
    ids = {
        "ai": register_document(ai, "tenders", "AI Risk Test Doc"),
        "sec": register_document(sec, "knowledge-base", "Security Test Doc"),
    }
    ingest_document(ids["ai"], ocr_fn=fake_ocr)
    ingest_document(ids["sec"], ocr_fn=fake_ocr)
    with session() as db:
        for i in ids.values():
            assert db.get(Document, i).status == "ready", db.get(Document, i).error
    return ids


def _add_kb_only_user() -> None:
    """Test-only user who can read the knowledge base but not tenders (mirror image of the seeded legal reviewer)."""
    from app.db import User, Workspace, session

    with session() as db:
        if db.get(User, "kbuser") is None:
            u = User(id="kbuser", name="KB Only (test)", token="demo-kbuser", role="member")
            u.workspaces = [db.get(Workspace, "knowledge-base")]
            db.add(u)
            db.commit()


@pytest.fixture()
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def auth(user: str) -> dict:
    return {"Authorization": f"Bearer demo-{user}"}
