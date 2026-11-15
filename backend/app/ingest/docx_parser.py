"""DOCX extraction into the same PageContent structure as PDFs.

Word files have no fixed pages, so each top-level heading (Heading 1 / Title) starts a new numbered *part*; citations to a
DOCX show "part N" instead of "page N". Tables become Markdown table blocks; heading styles become bold, larger blocks so
the shared chunker detects sections exactly as it does for PDFs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from docx import Document as DocxDocument
from docx.document import Document as _Doc
from docx.table import Table
from docx.text.paragraph import Paragraph

from .pdf import Block, PageContent, rows_to_markdown

BODY_SIZE = 11.0
PART_CHAR_BUDGET = 3500  # long sections are split into several parts so citations stay precise


def _iter_body(doc: _Doc) -> Iterator[Paragraph | Table]:
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def _heading_level(p: Paragraph) -> int:
    name = (p.style.name if p.style is not None else "") or ""
    if name == "Title":
        return 0
    if name.startswith("Heading"):
        try:
            return int(name.split()[-1])
        except ValueError:
            return 1
    return -1


def iter_docx_parts(path: Path) -> Iterator[tuple[int, PageContent]]:
    doc = DocxDocument(str(path))
    parts: list[PageContent] = []
    cur = PageContent(number=1, width=612, height=792)
    y = 60.0

    def new_part() -> None:
        nonlocal cur, y
        if cur.blocks:
            parts.append(cur)
            cur = PageContent(number=len(parts) + 1, width=612, height=792)
            y = 60.0

    def add(block: Block) -> None:
        nonlocal y
        # synthetic boxes stay inside the page body so the chunker never mistakes them for headers/footers
        block.bbox = (54.0, y, 558.0, y + 14.0)
        y = 60.0 if y >= 660.0 else y + 16.0
        cur.blocks.append(block)

    for item in _iter_body(doc):
        if isinstance(item, Table):
            md = rows_to_markdown([[c.text for c in row.cells] for row in item.rows])
            if md:
                add(Block(text=md, bbox=(0, 0, 0, 0), kind="table"))
                cur.tables += 1
            continue
        text = item.text.strip()
        if not text:
            continue
        level = _heading_level(item)
        if level in (0, 1) and cur.blocks and sum(len(b.text) for b in cur.blocks) > 200:
            new_part()
        elif sum(len(b.text) for b in cur.blocks) > PART_CHAR_BUDGET:
            new_part()
        if level >= 0:
            add(Block(text=text, bbox=(0, 0, 0, 0), size=BODY_SIZE * (1.6 if level <= 1 else 1.3), bold=True))
        else:
            add(Block(text=text, bbox=(0, 0, 0, 0), size=BODY_SIZE))
    if cur.blocks:
        parts.append(cur)
    for p in parts:
        yield len(parts), p


def docx_title(path: Path) -> str:
    doc = DocxDocument(str(path))
    title = (doc.core_properties.title or "").strip()
    if title:
        return title
    for item in _iter_body(doc):
        if isinstance(item, Paragraph) and _heading_level(item) in (0, 1) and item.text.strip():
            return item.text.strip()[:200]
    return path.stem.replace("_", " ")
