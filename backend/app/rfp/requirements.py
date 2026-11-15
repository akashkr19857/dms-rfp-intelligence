"""Requirement extraction: read the whole RFP in batches of obligation-bearing chunks and turn them into a clean,
de-duplicated, categorised requirement list with page references."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from ..config import get_settings
from ..db import Chunk
from .common import CallCounter, doc_chunks, llm_json

CATEGORIES = ["functional", "technical", "security", "data", "implementation", "staffing", "commercial", "legal",
              "submission", "timeline"]

# Chunks without any obligation language are background (statistics, definitions) and are skipped to save LLM calls.
OBLIGATION = re.compile(
    r"\b(shall|must|required?|requirements?|will be required|is expected|expects?|minimum|mandatory|should|need to|"
    r"are to|is to|responsible for|agrees? to|will provide|to be submitted|no later than)\b", re.I)

REQ_SYSTEM = f"""You extract the requirements that an RFP (request for proposals) places on the PROPOSER (vendor/contractor).
Read the numbered excerpts and list every distinct obligation, expectation or condition the proposer must meet, either
in the proposal or in the delivered solution/services.
For each requirement return:
- "requirement": a concise, self-contained statement (max 40 words) starting with the subject, e.g. "Proposer must ..."
  or "Solution must ...". Keep exact numbers, dates, durations and named systems.
- "category": one of {CATEGORIES}. Use "submission" ONLY for instructions about preparing, formatting, signing or
  delivering the proposal document itself (deadlines, copies, file formats, tabs, forms). Contract terms the
  proposer must accept (indemnity, records, insurance, data, law) are "legal" or "commercial", never "submission".
- "mandatory": true if worded with shall / must / required / will; false if should / may / preferred / encouraged
- "source": the excerpt number [C#] it comes from
Do NOT list: background facts, statistics, definitions, the issuer's own rights or obligations, or legal boilerplate
that places no obligation on the proposer.
Reply as JSON: {{"requirements": [ ... ]}}  (an empty list if the excerpts contain no proposer requirements)"""


@dataclass
class ReqDraft:
    text: str
    category: str
    mandatory: bool
    kind: str
    page: int
    section: str
    chunk_id: str


def candidate_chunks(chunks: list[Chunk]) -> list[Chunk]:
    return [c for c in chunks if OBLIGATION.search(c.text) and len(c.text) >= 80]


def batches(chunks: list[Chunk], max_chars: int) -> list[list[Chunk]]:
    out: list[list[Chunk]] = []
    cur: list[Chunk] = []
    size = 0
    for c in chunks:
        if cur and size + len(c.text) > max_chars:
            out.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += len(c.text)
    if cur:
        out.append(cur)
    return out


_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "for", "must", "shall", "proposer", "proposers", "vendor",
         "contractor", "solution", "be", "is", "are", "with", "by", "on", "all", "any", "its", "their", "will"}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def is_duplicate(text: str, existing: list[set[str]], threshold: float = 0.75) -> bool:
    t = _tokens(text)
    if not t:
        return True
    for e in existing:
        inter = len(t & e)
        if inter and inter / min(len(t), len(e)) >= threshold:
            return True
    return False


def extract_requirements(doc_id: int, counter: CallCounter | None = None,
                         on_progress: Callable[[float], None] | None = None) -> list[ReqDraft]:
    s = get_settings()
    groups = batches(candidate_chunks(doc_chunks(doc_id)), s.req_batch_chars)
    drafts: list[ReqDraft] = []
    seen: list[set[str]] = []
    for gi, group in enumerate(groups):
        excerpt = "\n\n".join(f"[C{i}] (page {c.page}{', ' + c.section[:70] if c.section else ''})\n{c.text}"
                              for i, c in enumerate(group, 1))
        data = llm_json(REQ_SYSTEM, f"Excerpts:\n\n{excerpt}", counter, max_tokens=1400)
        items = data.get("requirements", [])
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            text = str(it.get("requirement") or "").strip()
            if len(text) < 15 or is_duplicate(text, seen):
                continue
            m = re.search(r"(\d+)", str(it.get("source", "")))
            idx = int(m.group(1)) if m else 1
            c = group[idx - 1] if 1 <= idx <= len(group) else group[0]
            cat = str(it.get("category", "")).lower().strip()
            kind = "submission" if cat == "submission" else "capability"
            drafts.append(ReqDraft(text=text[:400], category=cat if cat in CATEGORIES else "functional",
                                   mandatory=bool(it.get("mandatory", True)), kind=kind, page=c.page,
                                   section=c.section, chunk_id=c.id))
            seen.append(_tokens(text))
        if on_progress:
            on_progress((gi + 1) / len(groups))
    return drafts
