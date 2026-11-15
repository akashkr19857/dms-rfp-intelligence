"""OCR for scanned pages.

Default engine: RapidOCR (PaddleOCR PP-OCR detection + recognition models exported to ONNX, run by onnxruntime).
It gives the same PP-OCR models as PaddleOCR but runs fast on CPU on Windows, where PaddlePaddle 3.x CPU
inference hit a oneDNN bug and, with oneDNN disabled, took minutes per page on this laptop.
"""
from __future__ import annotations

import io
import threading
from typing import Any

import numpy as np
from PIL import Image

_lock = threading.Lock()
_engine: Any = None

OcrLine = tuple[str, tuple[float, float, float, float], float]


def _get_engine() -> Any:
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr import RapidOCR

            _engine = RapidOCR()
    return _engine


def rapid_ocr(png_bytes: bytes) -> list[OcrLine]:
    img = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
    engine = _get_engine()
    with _lock:
        res = engine(img)
    out: list[OcrLine] = []
    boxes = getattr(res, "boxes", None)
    if boxes is None:
        return out
    for box, text, score in zip(boxes, res.txts, res.scores):
        pts = np.asarray(box, dtype=float)
        out.append((str(text), (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())), float(score)))
    return out
