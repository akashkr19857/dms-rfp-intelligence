from __future__ import annotations

from app.db import Chunk, Document, session
from app.ingest.chunker import _split_long, chunk_pages, split_table
from app.ingest.pdf import Block, PageContent, order_ocr_lines, rows_to_markdown


def test_rows_to_markdown_cleans_cells_and_drops_empty_columns():
    md = rows_to_markdown([["Tier", None, "Governance"], ["Tier 1:\nPartial", "", "ad hoc &amp; informal"], [None, None, None]])
    assert md.splitlines()[0] == "| Tier | Governance |"
    assert "| Tier 1: Partial | ad hoc & informal |" in md
    assert len(md.splitlines()) == 3  # header, separator, one data row (empty row dropped)


def test_split_table_repeats_header():
    rows = "\n".join(f"| row {i} | {'x' * 40} |" for i in range(30))
    md = "| A | B |\n|---|---|\n" + rows
    pieces = split_table(md, 400)
    assert len(pieces) > 1
    assert all(p.startswith("| A | B |\n|---|---|") for p in pieces)
    assert sum(p.count("| row ") for p in pieces) == 30


def test_split_long_respects_size_and_keeps_text():
    text = " ".join(f"Sentence number {i} is here." for i in range(100))
    parts = _split_long(text, 300, 50)
    assert all(len(p) <= 360 for p in parts)
    assert "Sentence number 99" in parts[-1]


def test_chunks_never_cross_pages_and_track_sections():
    pages = [
        PageContent(1, 600, 800, [Block("1. Intro", (50, 50, 200, 70), size=16), Block("Body text one " * 10, (50, 100, 500, 200), size=10)]),
        PageContent(2, 600, 800, [Block("More body text " * 10, (50, 100, 500, 200), size=10)]),
    ]
    chunks = chunk_pages(pages, size=1100)
    assert {c.page for c in chunks} == {1, 2}
    assert all(c.section == "1. Intro" for c in chunks)  # section carries over to the next page
    assert chunks[0].text.startswith("1. Intro")


def test_ocr_reading_order_is_column_aware():
    lines = [("left-1", (10, 10, 400, 30)), ("right-1", (600, 12, 990, 32)), ("left-2", (10, 40, 400, 60)),
             ("FULL WIDTH TITLE", (10, 100, 990, 120)), ("left-3", (10, 140, 400, 160))]
    runs = order_ocr_lines(lines, 1000)
    flat = [t for run in runs for t, _ in run]
    assert flat == ["left-1", "left-2", "right-1", "FULL WIDTH TITLE", "left-3"]


def test_ingested_documents_have_text_table_and_ocr_chunks(seeded):
    with session() as db:
        ai = db.get(Document, seeded["ai"])
        sec = db.get(Document, seeded["sec"])
        assert ai.pages == 3 and ai.tables == 1 and ai.ocr_pages == 0
        assert sec.ocr_pages == 1
        kinds = {c.kind for c in db.query(Chunk).filter(Chunk.doc_id == seeded["ai"])}
        assert kinds == {"text", "table"}
        ocr = db.query(Chunk).filter(Chunk.doc_id == seeded["sec"], Chunk.kind == "ocr").all()
        assert ocr and "business champion" in ocr[0].text
        table = db.query(Chunk).filter(Chunk.doc_id == seeded["ai"], Chunk.kind == "table").one()
        assert "| Govern | GV |" in table.text
        for c in db.query(Chunk).all():
            assert c.bboxes and all(len(b) == 4 for b in c.bboxes)
            assert c.workspace_id in ("tenders", "knowledge-base")
