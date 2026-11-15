"""Qdrant in embedded/local mode (no server). Every point carries workspace_id and doc_id so searches are
always filtered to the caller's workspaces (role-based access is enforced in the store query itself)."""
from __future__ import annotations

import threading
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models

COLLECTION = "chunks"
_NS = uuid.UUID("6f1d3c52-8a7e-4d4b-9a51-0c6a3c0d0b06")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NS, chunk_id))


class VectorStore:
    def __init__(self, path: Path, dim: int) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(path))
        self.dim = dim
        self._lock = threading.Lock()
        if not self.client.collection_exists(COLLECTION):
            self.client.create_collection(COLLECTION, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))

    def upsert(self, chunk_ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None:
        points = [models.PointStruct(id=point_id(c), vector=v, payload=p | {"chunk_id": c})
                  for c, v, p in zip(chunk_ids, vectors, payloads)]
        with self._lock:
            for i in range(0, len(points), 256):
                self.client.upsert(COLLECTION, points=points[i:i + 256])

    def delete_doc(self, doc_id: int) -> None:
        with self._lock:
            self.client.delete(COLLECTION, points_selector=models.FilterSelector(filter=models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])))

    def search(self, vector: list[float], workspaces: list[str], limit: int, doc_ids: list[int] | None = None) -> list[tuple[str, float]]:
        must: list[models.Condition] = [models.FieldCondition(key="workspace_id", match=models.MatchAny(any=workspaces))]
        if doc_ids:
            must.append(models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids)))
        with self._lock:
            res = self.client.query_points(COLLECTION, query=vector, query_filter=models.Filter(must=must), limit=limit)
        return [(p.payload["chunk_id"], float(p.score)) for p in res.points]

    def count(self) -> int:
        return self.client.count(COLLECTION).count

    def close(self) -> None:
        self.client.close()
