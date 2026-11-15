"""Embeddings: nomic-embed-text through Ollama (default) or a deterministic hashing embedder for unit tests."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx
import numpy as np

from ..config import get_settings
from ..retry import post_with_retry


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """nomic-embed-text expects task prefixes: 'search_document: ' for passages, 'search_query: ' for queries."""

    dim = 768

    def __init__(self, url: str, model: str, batch: int = 32) -> None:
        self.url, self.model, self.batch = url.rstrip("/"), model, batch
        self._client = httpx.Client(timeout=120)

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(inputs), self.batch):
            r = post_with_retry(self._client, f"{self.url}/api/embed", {"model": self.model, "input": inputs[i:i + self.batch],
                                                                        "truncate": True, "keep_alive": "30m"})
            out.extend(r.json()["embeddings"])
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([f"search_document: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"search_query: {text}"])[0]


class HashEmbedder:
    """Bag-of-words feature hashing (unit tests only; no model download, no network)."""

    dim = 256

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = math.sqrt(float((v * v).sum())) or 1.0
        return (v / n).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        s = get_settings()
        _embedder = HashEmbedder() if s.embed_provider == "fake" else OllamaEmbedder(s.ollama_url, s.embed_model)
    return _embedder


def set_embedder(e: Embedder | None) -> None:
    global _embedder
    _embedder = e
