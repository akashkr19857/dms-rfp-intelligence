"""Cross-encoder reranker (BAAI/bge-reranker-base). Providers: "cross-encoder" (PyTorch, GPU if available),
"onnx" (edge/reranker.onnx on ONNX Runtime), "overlap" (token overlap, tests only). Scores are sigmoid probabilities."""
from __future__ import annotations

import logging
import threading
from typing import Protocol

from ..config import get_settings


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str, device: str = "auto") -> None:
        import torch

        self.model_name = model_name
        self.device = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        self.model = self._load(self.device)
        self._lock = threading.Lock()

    def _load(self, device: str):  # noqa: ANN202
        import torch
        from sentence_transformers import CrossEncoder

        kwargs = {"model_kwargs": {"torch_dtype": torch.float16}} if device == "cuda" else {}
        return CrossEncoder(self.model_name, device=device, max_length=512, **kwargs)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        import torch

        pairs = [(query, p) for p in passages]
        with self._lock:
            try:
                scores = self.model.predict(pairs, batch_size=16, activation_fn=torch.nn.Sigmoid(), show_progress_bar=False)
            except (RuntimeError, torch.AcceleratorError if hasattr(torch, "AcceleratorError") else RuntimeError) as exc:
                if self.device != "cuda" or "CUDA" not in str(exc):
                    raise
                # the GPU was reset (laptop TDR); CUDA is unusable in this process now, so continue on CPU
                logging.getLogger("rfp.reranker").warning("CUDA failure in reranker, switching to CPU: %s", exc)
                self.device = "cpu"
                self.model = self._load("cpu")
                scores = self.model.predict(pairs, batch_size=16, activation_fn=torch.nn.Sigmoid(), show_progress_bar=False)
        return [float(s) for s in scores]


class OnnxReranker:
    """Same cross-encoder exported to ONNX (edge/export_reranker_onnx.py); runs on ONNX Runtime (CPU or GPU EP)."""

    def __init__(self, model_name: str, onnx_path: str) -> None:
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.sess = ort.InferenceSession(onnx_path, providers=ort.get_available_providers())
        self._lock = threading.Lock()

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        import numpy as np

        enc = self.tok([query] * len(passages), passages, padding=True, truncation=True, max_length=512, return_tensors="np")
        with self._lock:
            logits = self.sess.run(None, {"input_ids": enc["input_ids"].astype("int64"),
                                          "attention_mask": enc["attention_mask"].astype("int64")})[0].reshape(-1)
        return [float(v) for v in 1.0 / (1.0 + np.exp(-logits))]


class OverlapReranker:
    """Token-overlap scorer used in unit tests (no model)."""

    def score(self, query: str, passages: list[str]) -> list[float]:
        from .bm25 import tokenize

        q = set(tokenize(query))
        return [len(q & set(tokenize(p))) / (len(q) or 1) for p in passages]


_reranker: Reranker | None = None
_lock = threading.Lock()


def get_reranker() -> Reranker:
    global _reranker
    with _lock:
        if _reranker is None:
            s = get_settings()
            if s.rerank_provider == "cross-encoder":
                _reranker = CrossEncoderReranker(s.reranker_model, s.rerank_device)
            elif s.rerank_provider == "onnx":
                from ..config import PROJECT_ROOT

                _reranker = OnnxReranker(s.reranker_model, str(PROJECT_ROOT / "edge" / "reranker.onnx"))
            else:
                _reranker = OverlapReranker()
    return _reranker


def set_reranker(r: Reranker | None) -> None:
    global _reranker
    _reranker = r
