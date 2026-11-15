"""Section-aware chunking. Chunks never cross a page boundary, so every chunk has an exact page citation and
highlight boxes. Tables become their own chunks (kept whole up to 2x the chunk size)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median

from .pdf import Block, PageContent

_HEADING_NUM = re.compile(r"^(\d+(\.\d+)*\.?|appendix [a-z]|[A-Z]\.)\s+\S")
_PAGE_FURNITURE = re.compile(r"^(page \d+|\d+|nist (ai|cswp|sp) [\d.\-]+.*|https?://doi\.org/\S+)$", re.I)


@dataclass
class ChunkDraft:
    page: int
    section: str
    kind: str
    text: str
    bboxes: list[list[float]] = field(default_factory=list)


def body_font_size(pages: list[PageContent]) -> float:
    sizes = [b.size for p in pages for b in p.blocks if b.kind == "text" and b.size > 0 for _ in range(max(1, len(b.text) // 80))]
    return median(sizes) if sizes else 10.0


_CAPTION = re.compile(r"^(table|fig\.?|figure)\s+\d+", re.I)


def is_heading(block: Block, body_size: float) -> bool:
    if block.kind != "text":
        return False
    text = block.text.strip()
    if _CAPTION.match(text):  # figure/table captions are not section headings
        return False
    if len(text) > 120 or "\n" in text.strip() and len(text.splitlines()) > 2:
        return False
    if text.endswith((".", ",", ";")) and not _HEADING_NUM.match(text):
        return False
    bigger = block.size >= body_size * 1.15
    return bigger or (block.bold and len(text) < 90) or (bool(_HEADING_NUM.match(text)) and block.bold)


def _is_furniture(block: Block, page: PageContent) -> bool:
    """Running headers/footers and page numbers."""
    text = block.text.strip()
    in_margin = block.bbox[1] < page.height * 0.06 or block.bbox[3] > page.height * 0.94
    return in_margin and (len(text) < 80 or bool(_PAGE_FURNITURE.match(text)))


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    sentences = re.split(r"(?<=[.!?;:])\s+|\n", text)
    parts: list[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > size:
            parts.append(cur.strip())
            cur = cur[-overlap:] + " " + s if overlap else s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur.strip():
        parts.append(cur.strip())
    return parts


def split_table(md: str, size: int) -> list[str]:
    """Split a Markdown table by rows, repeating the header row in every piece."""
    if len(md) <= size:
        return [md]
    lines = md.splitlines()
    nl = "\n"
    header = nl.join(lines[:2]) if len(lines) > 1 and set(lines[1]) <= set("|-: ") else ""
    body = lines[2:] if header else lines
    pieces: list[str] = []
    cur: list[str] = []
    for row in body:
        if cur and len(header) + sum(len(r) + 1 for r in cur) + len(row) > size:
            pieces.append(nl.join(([header] if header else []) + cur))
            cur = []
        if len(row) > size:  # a single huge cell: fall back to sentence splitting
            pieces.extend(_split_long(row, size, 0))
            continue
        cur.append(row)
    if cur:
        pieces.append(nl.join(([header] if header else []) + cur))
    return pieces


def chunk_pages(pages: list[PageContent], size: int = 1100, overlap: int = 150) -> list[ChunkDraft]:
    body = body_font_size(pages)
    section = ""
    out: list[ChunkDraft] = []
    for page in pages:
        buf: list[Block] = []

        def flush() -> None:
            if not buf:
                return
            text = "\n".join(b.text for b in buf).strip()
            kind = "ocr" if page.ocr else "text"
            boxes = [list(map(float, b.bbox)) for b in buf]
            for piece in _split_long(text, size, overlap):
                if len(piece) >= 40:
                    out.append(ChunkDraft(page.number, section, kind, piece, boxes))
            buf.clear()

        for block in page.blocks:
            if _is_furniture(block, page):
                continue
            if block.kind == "table":
                flush()
                for piece in split_table(block.text, size * 2):
                    out.append(ChunkDraft(page.number, section, "table", piece, [list(map(float, block.bbox))]))
                continue
            if is_heading(block, body):
                flush()
                section = block.text.replace("\n", " ").strip()[:160]
                buf.append(block)  # keep the heading text inside the chunk for retrieval
                continue
            if buf and sum(len(b.text) for b in buf) + len(block.text) > size:
                tail = buf[-1] if overlap and len(buf[-1].text) <= overlap * 2 else None
                flush()
                if tail is not None:
                    buf.append(tail)
            buf.append(block)
        flush()
    return out
