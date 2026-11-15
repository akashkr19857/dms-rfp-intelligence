"""Scripted evaluation metrics + LLM-as-judge prompts (local qwen2.5:7b via Ollama)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = PROJECT_ROOT / "data" / "pdfs"
# The scanned sample has no text layer; gold pages are located in the original it was rendered from (same page numbers).
TEXT_SOURCE = {"NIST.SP.1300-scanned.pdf": "NIST.SP.1300.pdf"}


def norm(text: str) -> str:
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("’", "'").replace("‐", "-")
    text = re.sub(r"-\s*\n\s*", "", text)  # de-hyphenate line breaks
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@lru_cache(maxsize=16)
def _page_texts(filename: str) -> tuple[str, ...]:
    with pymupdf.open(PDF_DIR / TEXT_SOURCE.get(filename, filename)) as doc:
        return tuple(norm(p.get_text()) for p in doc)


def find_pages(filename: str, evidence: str) -> list[int]:
    """1-based pages whose text contains the evidence phrase (whitespace/punctuation-insensitive)."""
    needle = norm(evidence)
    pages = _page_texts(filename)
    hits = [i + 1 for i, t in enumerate(pages) if needle in t]
    if not hits:  # phrase broken across a page boundary: try page i + i+1
        hits = [i + 1 for i in range(len(pages) - 1) if needle in pages[i] + " " + pages[i + 1]]
    return hits


def gold_targets(item: dict) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for g in item.get("gold", []):
        for p in find_pages(g["doc"], g["evidence"]):
            out.add((g["doc"], p))
    return out


def hit_rank(retrieved: list[tuple[str, int]], targets: set[tuple[str, int]]) -> int | None:
    """1-based rank of the first retrieved (filename, page) that is a gold page."""
    for i, key in enumerate(retrieved, 1):
        if key in targets:
            return i
    return None


def context_recall(context: str, key_facts: list[str]) -> float | None:
    if not key_facts:
        return None
    c = norm(context)
    return sum(norm(f) in c for f in key_facts) / len(key_facts)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


CORRECTNESS_PROMPT = """You grade answers to questions about documents.
Compare the CANDIDATE answer with the REFERENCE answer. Judge only factual agreement with the reference, not style.
Score 1 if the candidate contains the key facts of the reference and nothing contradicting it.
Score 0.5 if it is partially correct (some key facts missing or slightly imprecise) without contradicting the reference.
Score 0 if it is wrong, contradicts the reference, or does not answer.
Reply as JSON: {"score": 0 | 0.5 | 1, "reason": "<one sentence>"}"""

FAITHFULNESS_PROMPT = """You check whether an answer is supported by source excerpts.
Split the ANSWER into its distinct factual claims (ignore citation markers like [1]).
For each claim decide if the SOURCES state or directly imply it. Do not use outside knowledge.
Reply as JSON: {"claims": [{"claim": "...", "supported": true | false}]}"""
