"""Ingestion pipeline: PDF → pages (text / tables / OCR) → chunks with page+section metadata → embeddings → Qdrant + SQLite."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import PROJECT_ROOT, get_settings
from ..db import Chunk, Document, session
from ..events import bus
from ..retrieval.bm25 import bm25_registry
from ..retrieval.embedder import get_embedder
from ..retrieval.hybrid import get_store
from .chunker import chunk_pages
from .docx_parser import docx_title, iter_docx_parts
from .pdf import OcrFn, PageContent, iter_pages, pdf_title

log = logging.getLogger("rfp.ingest")
SUPPORTED = (".pdf", ".docx")


def file_type(path: Path) -> str:
    return "docx" if Path(path).suffix.lower() == ".docx" else "pdf"


def doc_title(path: Path) -> str:
    return docx_title(path) if file_type(path) == "docx" else pdf_title(path)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")


def default_ocr() -> OcrFn:
    from .ocr import rapid_ocr

    return rapid_ocr


def _update(doc_id: int, **fields) -> None:
    with session() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        for k, v in fields.items():
            setattr(doc, k, v)
        db.commit()
        bus.publish({"type": "document", "document": doc.to_dict()})


def register_document(path: Path, workspace_id: str, title: str | None = None, source: str = "") -> int:
    path = Path(path).resolve()
    try:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = str(path)
    with session() as db:
        doc = Document(workspace_id=workspace_id, title=title or doc_title(path), filename=path.name, path=rel, source=source,
                       file_type=file_type(path))
        db.add(doc)
        db.commit()
        return doc.id


def resolve_path(doc: Document) -> Path:
    p = Path(doc.path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def ingest_document(doc_id: int, ocr_fn: OcrFn | None = None, use_ocr: bool = True) -> Document:
    """Synchronous ingestion of a registered document. Safe to re-run (replaces old chunks)."""
    s = get_settings()
    t0 = time.perf_counter()
    with session() as db:
        doc = db.get(Document, doc_id)
        assert doc is not None, f"unknown document {doc_id}"
        path, workspace = resolve_path(doc), doc.workspace_id
    _update(doc_id, status="processing", progress=0.0, error="")
    try:
        ocr = (ocr_fn or default_ocr()) if use_ocr else None
        pages: list[PageContent] = []
        source_iter = iter_docx_parts(path) if file_type(path) == "docx" else iter_pages(path, ocr)
        for total, pc in source_iter:
            pages.append(pc)
            if pc.number % 4 == 0 or pc.number == total:
                _update(doc_id, pages=total, progress=round(0.7 * pc.number / total, 3))
        drafts = chunk_pages(pages, s.chunk_chars, s.chunk_overlap_chars)
        chunk_ids = [f"d{doc_id}-p{d.page}-c{i}" for i, d in enumerate(drafts)]
        _update(doc_id, progress=0.75)
        embedder = get_embedder()
        vectors = embedder.embed_documents([f"{d.section}\n{d.text}" if d.section else d.text for d in drafts])
        store = get_store()
        store.delete_doc(doc_id)
        store.upsert(chunk_ids, vectors, [{"doc_id": doc_id, "workspace_id": workspace, "page": d.page} for d in drafts])
        with session() as db:
            db.query(Chunk).filter(Chunk.doc_id == doc_id).delete()
            db.add_all(Chunk(id=cid, doc_id=doc_id, workspace_id=workspace, page=d.page, section=d.section, kind=d.kind,
                             text=d.text, bboxes=d.bboxes) for cid, d in zip(chunk_ids, drafts))
            db.commit()
        bm25_registry.invalidate(workspace)
        _update(doc_id, status="ready", progress=1.0, pages=len(pages), n_chunks=len(drafts),
                ocr_pages=sum(p.ocr for p in pages), tables=sum(p.tables for p in pages),
                ingest_seconds=round(time.perf_counter() - t0, 2))
    except Exception as exc:  # surface any failure on the document row
        log.exception("ingestion failed for %s", doc_id)
        _update(doc_id, status="failed", error=f"{type(exc).__name__}: {exc}")
    with session() as db:
        return db.get(Document, doc_id)


def ingest_async(doc_id: int) -> None:
    _executor.submit(ingest_document, doc_id)


def delete_document(doc_id: int) -> None:
    with session() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        ws = doc.workspace_id
        db.query(Chunk).filter(Chunk.doc_id == doc_id).delete()
        db.delete(doc)
        db.commit()
    get_store().delete_doc(doc_id)
    bm25_registry.invalidate(ws)
