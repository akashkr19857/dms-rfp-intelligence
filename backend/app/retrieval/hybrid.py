"""Hybrid retrieval: BM25 + dense vectors fused with Reciprocal Rank Fusion, then cross-encoder reranking."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field

from ..config import get_settings
from ..db import Chunk, Document, session
from .bm25 import bm25_registry
from .embedder import get_embedder
from .reranker import get_reranker
from .vectorstore import VectorStore


@dataclass
class Hit:
    chunk_id: str
    doc_id: int
    doc_title: str
    workspace_id: str
    page: int
    section: str
    kind: str
    text: str
    bboxes: list
    bm25_rank: int | None = None
    vector_rank: int | None = None
    fused_score: float = 0.0
    rerank_score: float | None = None
    file_type: str = "pdf"

    def to_dict(self, max_chars: int | None = None) -> dict:
        d = asdict(self)
        if max_chars:
            d["text"] = d["text"][:max_chars]
        return d


@dataclass
class RetrievalResult:
    hits: list[Hit]
    retrieval_ms: float
    rerank_ms: float
    candidates: int
    config: dict = field(default_factory=dict)

    @property
    def best_score(self) -> float:
        if not self.hits:
            return 0.0
        scored = [h.rerank_score for h in self.hits if h.rerank_score is not None]
        return max(scored) if scored else 1.0


_store: VectorStore | None = None
_store_lock = threading.Lock()


def get_store() -> VectorStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = VectorStore(get_settings().qdrant_path, get_embedder().dim)
    return _store


def close_store() -> None:
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None


def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _load_hits(ids: list[str]) -> dict[str, Hit]:
    if not ids:
        return {}
    with session() as db:
        rows = (db.query(Chunk, Document.title, Document.file_type).join(Document, Document.id == Chunk.doc_id)
                .filter(Chunk.id.in_(ids)).all())
    return {c.id: Hit(c.id, c.doc_id, title, c.workspace_id, c.page, c.section, c.kind, c.text, c.bboxes, file_type=ft)
            for c, title, ft in rows}


def retrieve(query: str, workspaces: list[str], *, top_k: int | None = None, mode: str | None = None,
             use_reranker: bool | None = None, doc_ids: list[int] | None = None, candidates: int | None = None) -> RetrievalResult:
    s = get_settings()
    top_k = top_k or s.top_k
    mode = mode or s.retrieval_mode
    use_reranker = s.use_reranker if use_reranker is None else use_reranker
    n = candidates or s.candidates
    if not workspaces:
        return RetrievalResult([], 0.0, 0.0, 0, {"mode": mode})

    t0 = time.perf_counter()
    bm25_ids: list[str] = []
    vec_ids: list[str] = []
    if mode in ("bm25", "hybrid"):
        doc_filter = set(doc_ids) if doc_ids else None
        merged: list[tuple[str, float]] = []
        for ws in workspaces:
            merged.extend(bm25_registry.get(ws).search(query, n, doc_filter))
        bm25_ids = [cid for cid, _ in sorted(merged, key=lambda t: -t[1])[:n]]
    if mode in ("vector", "hybrid"):
        qv = get_embedder().embed_query(query)
        vec_ids = [cid for cid, _ in get_store().search(qv, workspaces, n, doc_ids)]
    fused = rrf([r for r in (bm25_ids, vec_ids) if r], s.rrf_k)
    order = sorted(fused, key=lambda c: -fused[c])
    hits_by_id = _load_hits(order)
    hits: list[Hit] = []
    for cid in order:
        h = hits_by_id.get(cid)
        if h is None or h.workspace_id not in workspaces:  # defence in depth for RBAC
            continue
        h.fused_score = fused[cid]
        h.bm25_rank = bm25_ids.index(cid) + 1 if cid in bm25_ids else None
        h.vector_rank = vec_ids.index(cid) + 1 if cid in vec_ids else None
        hits.append(h)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    rerank_ms = 0.0
    if use_reranker and hits:
        t1 = time.perf_counter()
        scores = get_reranker().score(query, [f"{h.section}\n{h.text}" if h.section else h.text for h in hits])
        for h, sc in zip(hits, scores):
            h.rerank_score = sc
        hits.sort(key=lambda h: -(h.rerank_score or 0.0))
        rerank_ms = (time.perf_counter() - t1) * 1000
    return RetrievalResult(hits[:top_k], retrieval_ms, rerank_ms, len(order),
                           {"mode": mode, "reranker": use_reranker, "top_k": top_k, "candidates": n})
