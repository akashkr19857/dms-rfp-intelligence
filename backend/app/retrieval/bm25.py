"""In-memory BM25 (rank_bm25) built per workspace from the chunk table and invalidated on ingest/delete."""
from __future__ import annotations

import re
import threading

from rank_bm25 import BM25Okapi

STOPWORDS = frozenset(
    "a an the and or of to in on for with by from as at is are was were be been being this that these those it its "
    "into than then there their them they which who whom what when where why how do does did can could should would "
    "may might must will shall not no nor so such if about over under between within across also any all each".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    toks = _TOKEN.findall(text.lower())
    return [t for t in toks if t not in STOPWORDS and len(t) > 1]


class BM25Index:
    def __init__(self, ids: list[str], texts: list[str], doc_ids: list[int]) -> None:
        self.ids = ids
        self.doc_ids = doc_ids
        self.bm25 = BM25Okapi([tokenize(t) for t in texts]) if ids else None

    def search(self, query: str, limit: int, doc_filter: set[int] | None = None) -> list[tuple[str, float]]:
        if self.bm25 is None:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        order = scores.argsort()[::-1]
        out: list[tuple[str, float]] = []
        for i in order:
            if scores[i] <= 0:
                break
            if doc_filter and self.doc_ids[i] not in doc_filter:
                continue
            out.append((self.ids[i], float(scores[i])))
            if len(out) >= limit:
                break
        return out


class BM25Registry:
    def __init__(self) -> None:
        self._cache: dict[str, BM25Index] = {}
        self._lock = threading.Lock()

    def get(self, workspace: str) -> BM25Index:
        with self._lock:
            idx = self._cache.get(workspace)
            if idx is None:
                from ..db import Chunk, session

                with session() as db:
                    rows = db.query(Chunk.id, Chunk.text, Chunk.section, Chunk.doc_id).filter(Chunk.workspace_id == workspace).all()
                idx = BM25Index([r[0] for r in rows], [f"{r[2]}\n{r[1]}" for r in rows], [r[3] for r in rows])
                self._cache[workspace] = idx
            return idx

    def invalidate(self, workspace: str | None = None) -> None:
        with self._lock:
            if workspace is None:
                self._cache.clear()
            else:
                self._cache.pop(workspace, None)


bm25_registry = BM25Registry()
