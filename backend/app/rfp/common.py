"""Shared helpers for the RFP analysis stages: document chunks, KB retrieval, LLM JSON calls with call counting."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from ..config import KB_WS, TENDERS_WS, get_settings
from ..db import Chunk, Document, session
from ..llm import get_llm, parse_json
from ..retrieval.hybrid import Hit, retrieve


@dataclass
class CallCounter:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, prompt: int, completion: int) -> None:
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion


def llm_json(system: str, user: str, counter: CallCounter | None = None, max_tokens: int = 900) -> dict:
    res = get_llm().chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True,
                         temperature=0.0, max_tokens=max_tokens)
    if counter is not None:
        counter.add(res.prompt_tokens, res.completion_tokens)
    return parse_json(res.text)


def doc_chunks(doc_id: int) -> list[Chunk]:
    with session() as db:
        rows = db.query(Chunk).filter(Chunk.doc_id == doc_id).all()
    # chunk ids are d{doc}-p{page}-c{i}; sort by page then creation index for reading order
    def key(c: Chunk) -> tuple[int, int]:
        m = re.search(r"-c(\d+)$", c.id)
        return c.page, int(m.group(1)) if m else 0

    return sorted(rows, key=key)


def get_document(doc_id: int) -> Document | None:
    with session() as db:
        return db.get(Document, doc_id)


def kb_doc_ids() -> list[int]:
    with session() as db:
        return [d.id for d in db.query(Document).filter(Document.workspace_id == KB_WS, Document.status == "ready").all()]


def search_rfp(query: str, doc_id: int, k: int = 5) -> list[Hit]:
    return retrieve(query, [TENDERS_WS], top_k=k, doc_ids=[doc_id]).hits


def search_kb(query: str, k: int | None = None) -> list[Hit]:
    return retrieve(query, [KB_WS], top_k=k or get_settings().kb_evidence_k).hits


def numbered(hits: list[Hit], prefix: str = "", max_chars: int = 900) -> str:
    out = []
    for i, h in enumerate(hits, 1):
        head = f"[{prefix}{i}] {h.doc_title}, {'part' if h.file_type == 'docx' else 'page'} {h.page}"
        if h.section:
            head += f" ({h.section[:80]})"
        out.append(f"{head}\n{h.text[:max_chars]}")
    return "\n\n".join(out)


def source_ref(h: Hit) -> dict:
    return {"doc_id": h.doc_id, "doc_title": h.doc_title, "page": h.page, "chunk_id": h.chunk_id,
            "file_type": h.file_type, "text": h.text[:400]}


def pick(hits: list[Hit], refs: object, prefix: str = "") -> list[Hit]:
    """Map the model's source references ("K2", 2, "[2]") back to hits, ignoring anything out of range."""
    out: list[Hit] = []
    items = refs if isinstance(refs, list) else [refs]
    for r in items:
        m = re.search(r"(\d+)", str(r))
        if not m:
            continue
        n = int(m.group(1))
        if 1 <= n <= len(hits) and hits[n - 1] not in out:
            out.append(hits[n - 1])
    return out
