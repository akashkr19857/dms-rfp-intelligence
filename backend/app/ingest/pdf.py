"""PDF page extraction: text blocks with bounding boxes, tables as Markdown, OCR fallback for scanned pages."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import pymupdf

# A page with fewer extractable characters than this (but with an image) is treated as scanned → OCR.
MIN_TEXT_CHARS = 40
# Only run the (slow) table finder on pages that have enough vector drawings to contain a ruled table.
MIN_DRAWINGS_FOR_TABLES = 6


@dataclass
class Block:
    text: str
    bbox: tuple[float, float, float, float]
    size: float = 0.0  # dominant font size
    bold: bool = False
    kind: str = "text"  # text | table | ocr


@dataclass
class PageContent:
    number: int  # 1-based
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)
    ocr: bool = False
    tables: int = 0


_WS = re.compile(r"[ \t ]+")


def _clean(text: str) -> str:
    text = text.replace("�", "•").replace("‐", "-")
    text = _WS.sub(" ", text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _overlaps(a: tuple[float, ...], b: tuple[float, ...], min_frac: float = 0.5) -> bool:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return False
    inter = (x1 - x0) * (y1 - y0)
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return inter / area >= min_frac


def rows_to_markdown(rows: list[list[str | None]]) -> str:
    """Markdown table from raw cell rows: cleans cells, drops empty columns/rows, first row is the header."""
    cells = [[_WS.sub(" ", html.unescape(c or "").replace("\n", " ")).strip().replace("|", "/") for c in r] for r in rows]
    cells = [r for r in cells if any(r)]
    if not cells:
        return ""
    width = max(len(r) for r in cells)
    cells = [r + [""] * (width - len(r)) for r in cells]
    keep = [j for j in range(width) if any(r[j] for r in cells)]
    cells = [[r[j] for j in keep] for r in cells]
    lines = ["| " + " | ".join(cells[0]) + " |", "|" + "---|" * len(keep)]
    lines += ["| " + " | ".join(r) + " |" for r in cells[1:]]
    return "\n".join(lines)


def _table_markdown(tab) -> str:  # noqa: ANN001 - pymupdf Table
    """PyMuPDF's own Markdown keeps word spacing better than raw cell extraction, so parse it back into cells,
    then clean (HTML entities, <br>, placeholder 'ColN' headers, empty columns)."""
    try:
        md = tab.to_markdown(clean=False)
    except Exception:  # pragma: no cover - pymupdf edge cases
        return rows_to_markdown(tab.extract())
    rows: list[list[str | None]] = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        cells = [html.unescape(c).replace("<br>", " ").strip() for c in line.strip("|").split("|")]
        rows.append([("" if re.fullmatch(r"Col\d+", c) else c.replace("**", "")) for c in cells])
    return rows_to_markdown(rows)


def extract_text_page(page: pymupdf.Page, find_tables: bool = True) -> PageContent:
    pc = PageContent(number=page.number + 1, width=page.rect.width, height=page.rect.height)
    table_boxes: list[tuple[float, float, float, float]] = []
    if find_tables and len(page.get_drawings()) >= MIN_DRAWINGS_FOR_TABLES:
        try:
            for tab in page.find_tables().tables:
                if tab.row_count < 2 or tab.col_count < 2:
                    continue
                md = _table_markdown(tab)
                if len(md) < 30:
                    continue
                bbox = tuple(tab.bbox)
                table_boxes.append(bbox)
                pc.blocks.append(Block(text=md, bbox=bbox, kind="table"))
                pc.tables += 1
        except Exception:  # pragma: no cover
            pass

    data = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
    for b in data.get("blocks", []):
        if b.get("type") != 0:
            continue
        bbox = tuple(b["bbox"])
        if any(_overlaps(bbox, tb) for tb in table_boxes):
            continue
        lines, sizes, bold_chars, all_chars = [], [], 0, 0
        for ln in b.get("lines", []):
            spans = ln.get("spans", [])
            lines.append("".join(s["text"] for s in spans))
            for s in spans:
                n = len(s["text"].strip())
                all_chars += n
                sizes.append((n, s["size"]))
                if s["flags"] & 16 or "Bold" in s.get("font", ""):
                    bold_chars += n
        text = _clean("\n".join(lines))
        if not text:
            continue
        size = max(sizes, key=lambda t: t[0])[1] if sizes else 0.0
        pc.blocks.append(Block(text=text, bbox=bbox, size=size, bold=all_chars > 0 and bold_chars / all_chars > 0.6))
    # reading order: top-to-bottom, then left-to-right (tables are placed where they sit on the page)
    pc.blocks.sort(key=lambda bl: (round(bl.bbox[1] / 4), bl.bbox[0]))
    return pc


def page_needs_ocr(page: pymupdf.Page) -> bool:
    return len(page.get_text("text").strip()) < MIN_TEXT_CHARS and bool(page.get_images())


OcrFn = Callable[[bytes], list[tuple[str, tuple[float, float, float, float], float]]]


Line = tuple[str, tuple[float, float, float, float]]


def order_ocr_lines(lines: list[Line], width: float) -> list[list[Line]]:
    """Column-aware reading order for OCR lines. Full-width lines split the page into bands; inside a band the
    left column is read before the right column. Returns runs of lines that belong to the same column."""
    def col(box: tuple[float, float, float, float]) -> int:
        x0, _, x1, _ = box
        if x1 <= width * 0.56:
            return 0
        if x0 >= width * 0.44:
            return 1
        return -1  # spans both columns

    runs: list[list[Line]] = []
    left: list[Line] = []
    right: list[Line] = []

    def flush_band() -> None:
        for side in (left, right):
            if side:
                runs.append(list(side))
                side.clear()

    for line in sorted(lines, key=lambda t: (t[1][1], t[1][0])):
        c = col(line[1])
        if c == -1:
            flush_band()
            if runs and runs[-1] and col(runs[-1][-1][1]) == -1:
                runs[-1].append(line)
            else:
                runs.append([line])
        else:
            (left if c == 0 else right).append(line)
    flush_band()
    return runs


def extract_ocr_page(page: pymupdf.Page, ocr_fn: OcrFn, dpi: int = 170) -> PageContent:
    """Render the page and OCR it. ocr_fn returns (text, bbox_in_pixels, score) per line."""
    pc = PageContent(number=page.number + 1, width=page.rect.width, height=page.rect.height, ocr=True)
    pix = page.get_pixmap(dpi=dpi)
    scale = 72.0 / dpi
    lines = [(t.strip(), b) for t, b, sc in ocr_fn(pix.tobytes("png")) if sc >= 0.5 and t.strip()]

    for run in order_ocr_lines(lines, pix.width):
        current: list[Line] = []

        def flush() -> None:
            if not current:
                return
            x0 = min(b[0] for _, b in current) * scale
            y0 = min(b[1] for _, b in current) * scale
            x1 = max(b[2] for _, b in current) * scale
            y1 = max(b[3] for _, b in current) * scale
            pc.blocks.append(Block(text=chr(10).join(t for t, _ in current), bbox=(x0, y0, x1, y1), kind="ocr"))
            current.clear()

        for text, box in run:  # paragraphs: split a column run on large vertical gaps
            if current:
                prev = current[-1][1]
                if box[1] - prev[3] > 0.9 * max(prev[3] - prev[1], 1):
                    flush()
            current.append((text, box))
        flush()
    return pc


def iter_pages(path: Path, ocr_fn: OcrFn | None, find_tables: bool = True) -> Iterator[tuple[int, PageContent]]:
    """Yields (page_count, PageContent) for every page."""
    with pymupdf.open(path) as doc:
        total = len(doc)
        for page in doc:
            if ocr_fn is not None and page_needs_ocr(page):
                yield total, extract_ocr_page(page, ocr_fn)
            else:
                yield total, extract_text_page(page, find_tables=find_tables)


def pdf_title(path: Path) -> str:
    with pymupdf.open(path) as doc:
        title = (doc.metadata or {}).get("title") or ""
    return title.strip() or path.stem.replace("_", " ")
