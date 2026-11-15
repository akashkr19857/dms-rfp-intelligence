"""Grounded answering with page-level citations and an explicit "not found in documents" path."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Iterator

from .config import get_settings
from .db import Trace, session
from .events import bus
from .llm import LLMResult, get_llm
from .retrieval.hybrid import Hit, RetrievalResult, retrieve

NOT_FOUND = "I could not find this in the documents you have access to."
_NOT_FOUND_MARKERS = ("could not find this in the documents", "not found in the documents", "NOT_FOUND")

SYSTEM_PROMPT = f"""You are DMS RFP Intelligence, an assistant for bid teams that answers questions strictly from the provided excerpts of RFP documents and the organisation knowledge base.
Rules:
- Use ONLY the numbered sources. Do not use outside knowledge.
- End EVERY sentence and EVERY bullet point with the citation(s) of the source(s) it uses, like [1] or [2][3]. An answer without citations is invalid.
- Be concise and specific (2-6 sentences, or a short list). Quote exact names, numbers and terms from the sources.
- If the sources do not contain the answer, reply exactly: "{NOT_FOUND}" and nothing else.
  Do not describe what the sources lack, do not answer a different question, and do not answer about a different
  document than the one asked about (e.g. a question about framework A answered with framework B's content)."""

# An answer whose FIRST sentence says the sources lack the answer is a refusal, even if the model then hedges.
_HEDGE = re.compile(
    r"^[^.!?\n]*\b(not|no)\b[^.!?\n]*\b(explicitly |directly |specifically )?"
    r"(listed|mentioned|provided|stated|specified|found|contained|included|available|given)\b[^.!?\n]*\b(sources?|documents?|excerpts?|context)\b"
    r"|^[^.!?\n]*\b(sources?|documents?|excerpts?|context)\b[^.!?\n]*\b(do|does) not (contain|mention|provide|specify|include|list|state)\b",
    re.I,
)

_CITE = re.compile(r"\[(\d{1,2})\]")


def format_sources(hits: list[Hit]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        head = f"[{i}] {h.doc_title}, page {h.page}" + (f", section: {h.section}" if h.section else "")
        parts.append(f"{head}\n{h.text}")
    return "\n\n".join(parts)


def build_messages(question: str, hits: list[Hit], history: list[dict] | None = None) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in (history or [])[-4:]:
        if m.get("role") in ("user", "assistant"):
            msgs.append({"role": m["role"], "content": str(m.get("content", ""))[:1500]})
    msgs.append({"role": "user", "content": f"Sources:\n\n{format_sources(hits)}\n\nQuestion: {question}"})
    return msgs


def is_not_found(text: str) -> bool:
    low = text.lower()
    return any(m.lower() in low for m in _NOT_FOUND_MARKERS) or bool(_HEDGE.match(text.strip()))


def extract_citations(answer: str, hits: list[Hit]) -> list[dict]:
    seen: list[int] = []
    for m in _CITE.finditer(answer):
        n = int(m.group(1))
        if 1 <= n <= len(hits) and n not in seen:
            seen.append(n)
    return [{"n": n, "chunk_id": hits[n - 1].chunk_id, "doc_id": hits[n - 1].doc_id, "doc_title": hits[n - 1].doc_title,
             "page": hits[n - 1].page, "section": hits[n - 1].section} for n in seen]


@dataclass
class Answer:
    question: str
    answer: str
    not_found: bool
    citations: list[dict]
    hits: list[Hit]
    retrieval: RetrievalResult | None
    llm: LLMResult | None
    latency_ms: float
    gate: str = ""  # why the not-found path fired: "no_hits" | "low_score" | "llm"
    steps: list[dict] = field(default_factory=list)
    trace_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "question": self.question, "answer": self.answer, "not_found": self.not_found, "gate": self.gate,
            "citations": self.citations, "sources": [h.to_dict() for h in self.hits], "latency_ms": round(self.latency_ms, 1),
            "retrieval_ms": round(self.retrieval.retrieval_ms, 1) if self.retrieval else 0,
            "rerank_ms": round(self.retrieval.rerank_ms, 1) if self.retrieval else 0,
            "llm_ms": round(self.llm.ms, 1) if self.llm else 0,
            "prompt_tokens": self.llm.prompt_tokens if self.llm else 0,
            "completion_tokens": self.llm.completion_tokens if self.llm else 0,
            "steps": self.steps, "trace_id": self.trace_id,
        }


def _gate(r: RetrievalResult) -> str:
    if not r.hits:
        return "no_hits"
    if r.config.get("reranker") and r.best_score < get_settings().not_found_threshold:
        return "low_score"
    return ""


def answer_stream(question: str, workspaces: list[str], *, history: list[dict] | None = None,
                  retrieval_kwargs: dict | None = None) -> Iterator[dict]:
    """Yields events: {"type": "sources"}, {"type": "token"}..., then {"type": "final", "answer": Answer}."""
    t0 = time.perf_counter()
    r = retrieve(question, workspaces, **(retrieval_kwargs or {}))
    gate = _gate(r)
    yield {"type": "sources", "sources": [h.to_dict(max_chars=600) for h in r.hits], "gate": gate}
    if gate:
        yield {"type": "token", "text": NOT_FOUND}
        yield {"type": "final", "answer": Answer(question, NOT_FOUND, True, [], r.hits, r, None,
                                                 (time.perf_counter() - t0) * 1000, gate)}
        return
    final: LLMResult | None = None
    for ev in get_llm().stream(build_messages(question, r.hits, history)):
        if isinstance(ev, LLMResult):
            final = ev
        else:
            yield {"type": "token", "text": ev}
    assert final is not None
    text = final.text.strip()
    nf = is_not_found(text)
    if nf:
        text = NOT_FOUND
    yield {"type": "final", "answer": Answer(question, text, nf, [] if nf else extract_citations(text, r.hits), r.hits, r,
                                             final, (time.perf_counter() - t0) * 1000, "llm" if nf else "")}


def answer(question: str, workspaces: list[str], **kw) -> Answer:
    result: Answer | None = None
    for ev in answer_stream(question, workspaces, **kw):
        if ev["type"] == "final":
            result = ev["answer"]
    assert result is not None
    return result


def record_trace(user_id: str, workspaces: list[str], mode: str, ans: Answer) -> int:
    d = ans.to_dict()
    with session() as db:
        t = Trace(user_id=user_id, workspaces=workspaces, mode=mode, question=ans.question, answer=ans.answer,
                  not_found=ans.not_found, latency_ms=d["latency_ms"], retrieval_ms=d["retrieval_ms"], rerank_ms=d["rerank_ms"],
                  llm_ms=d["llm_ms"], prompt_tokens=d["prompt_tokens"], completion_tokens=d["completion_tokens"],
                  chunks=[{"chunk_id": h.chunk_id, "doc_title": h.doc_title, "page": h.page, "rerank_score": h.rerank_score,
                           "bm25_rank": h.bm25_rank, "vector_rank": h.vector_rank} for h in ans.hits],
                  steps=ans.steps)
        db.add(t)
        db.commit()
        bus.publish({"type": "trace", "trace": t.to_dict()})
        return t.id
