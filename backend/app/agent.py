"""Agentic RAG with LangGraph.

    rewrite ─▶ plan ─┬─▶ search ──────────┐
                     ├─▶ multi_hop (loop) ─┼─▶ synthesize
                     └─▶ compare (tool) ───┘

* rewrite   – turns a follow-up / vague question into a standalone search query (uses chat history)
* plan      – classifies the question: simple | multi_hop (decomposes into sub-questions) | compare (picks 2 docs)
* multi_hop – answers sub-questions in order, feeding each intermediate finding into the next search
* compare   – `compare_documents` tool: retrieves the same aspect from two documents separately
* synthesize– final grounded answer with [n] citations, or the "not found" answer
"""
from __future__ import annotations

import time
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from .db import Document, session
from .llm import LLMResult, get_llm, parse_json
from .rag import NOT_FOUND, SYSTEM_PROMPT, Answer, extract_citations, format_sources, is_not_found
from .retrieval.hybrid import Hit, RetrievalResult, retrieve

MAX_EVIDENCE = 8


# ---------------------------------------------------------------- tools (also unit-tested on their own)
def list_documents(workspaces: list[str]) -> list[dict]:
    with session() as db:
        docs = db.query(Document).filter(Document.workspace_id.in_(workspaces), Document.status == "ready").all()
        return [{"id": d.id, "title": d.title, "workspace": d.workspace_id, "pages": d.pages} for d in docs]


def search_documents(query: str, workspaces: list[str], k: int = 5, doc_id: int | None = None) -> RetrievalResult:
    return retrieve(query, workspaces, top_k=k, doc_ids=[doc_id] if doc_id else None)


def compare_documents(doc_a: int, doc_b: int, aspect: str, workspaces: list[str], k: int = 3) -> dict[int, list[Hit]]:
    """Retrieve evidence about `aspect` from each document separately (workspace access still enforced)."""
    allowed = {d["id"] for d in list_documents(workspaces)}
    out: dict[int, list[Hit]] = {}
    for doc in (doc_a, doc_b):
        out[doc] = search_documents(aspect, workspaces, k=k, doc_id=doc).hits if doc in allowed else []
    return out


# ---------------------------------------------------------------- graph
class AgentState(TypedDict, total=False):
    question: str
    history: list[dict]
    workspaces: list[str]
    query: str
    plan: dict
    evidence: list[Hit]
    notes: list[str]
    steps: list[dict]
    answer: str
    llm_calls: list[LLMResult]
    retrieval_ms: float
    rerank_ms: float


def _step(state: AgentState, node: str, detail: str, t0: float, **extra: Any) -> list[dict]:
    return state.get("steps", []) + [{"node": node, "detail": detail, "ms": round((time.perf_counter() - t0) * 1000, 1)} | extra]


def _llm_json(state: AgentState, system: str, user: str) -> tuple[dict, list[LLMResult]]:
    res = get_llm().chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True,
                         temperature=0.0, max_tokens=300)
    return parse_json(res.text), state.get("llm_calls", []) + [res]


def _add_evidence(state: AgentState, hits: list[Hit], r: RetrievalResult | None = None) -> dict:
    ev = list(state.get("evidence", []))
    ids = {h.chunk_id for h in ev}
    for h in hits:
        if h.chunk_id not in ids:
            ev.append(h)
            ids.add(h.chunk_id)
    upd: dict = {"evidence": ev}
    if r is not None:
        upd["retrieval_ms"] = state.get("retrieval_ms", 0.0) + r.retrieval_ms
        upd["rerank_ms"] = state.get("rerank_ms", 0.0) + r.rerank_ms
    return upd


def node_rewrite(state: AgentState) -> dict:
    t0 = time.perf_counter()
    hist = "\n".join(f"{m['role']}: {str(m['content'])[:400]}" for m in state.get("history", [])[-4:])
    data, calls = _llm_json(
        state,
        'Rewrite the user question into ONE standalone, keyword-rich search query for searching PDF documents. '
        'Resolve pronouns using the conversation. Keep document names. Reply as JSON: {"query": "..."}',
        f"Conversation:\n{hist or '(none)'}\n\nQuestion: {state['question']}")
    query = str(data.get("query") or state["question"]).strip()
    return {"query": query, "llm_calls": calls, "steps": _step(state, "rewrite", query, t0)}


def node_plan(state: AgentState) -> dict:
    t0 = time.perf_counter()
    docs = list_documents(state["workspaces"])
    catalog = "\n".join(f"- id={d['id']}: {d['title']}" for d in docs)
    data, calls = _llm_json(
        state,
        "You plan how to answer a question over a document library. Choose a type:\n"
        '- "compare": the user asks to compare/contrast two specific documents in the library.\n'
        '- "multi_hop": answering needs 2-3 facts found separately, where a later lookup depends on an earlier one.\n'
        '- "simple": one lookup is enough (most questions).\n'
        'Reply as JSON: {"type": "simple|multi_hop|compare", "sub_questions": ["..."], '
        '"doc_a": <id or null>, "doc_b": <id or null>, "aspect": "what to compare"}',
        f"Library:\n{catalog}\n\nQuestion: {state['question']}\nSearch query: {state['query']}")
    ptype = data.get("type") if data.get("type") in ("simple", "multi_hop", "compare") else "simple"
    ids = {d["id"] for d in docs}
    if ptype == "compare":
        try:
            a, b = int(data.get("doc_a")), int(data.get("doc_b"))
        except (TypeError, ValueError):
            a = b = -1
        if a not in ids or b not in ids or a == b:
            ptype = "simple"
        data["doc_a"], data["doc_b"] = a, b
        data["aspect"] = str(data.get("aspect") or state["query"])
    subs = [str(q) for q in data.get("sub_questions") or [] if str(q).strip()][:3]
    if ptype == "multi_hop" and len(subs) < 2:
        ptype = "simple"
    plan = {"type": ptype, "sub_questions": subs if ptype == "multi_hop" else [],
            "doc_a": data.get("doc_a") if ptype == "compare" else None,
            "doc_b": data.get("doc_b") if ptype == "compare" else None,
            "aspect": data.get("aspect") if ptype == "compare" else None}
    detail = ptype + (f": {' → '.join(plan['sub_questions'])}" if ptype == "multi_hop" else "")
    if ptype == "compare":
        titles = {d["id"]: d["title"] for d in docs}
        detail = f"compare: {titles[plan['doc_a']]} vs {titles[plan['doc_b']]} on '{plan['aspect']}'"
    return {"plan": plan, "llm_calls": calls, "steps": _step(state, "plan", detail, t0, plan=plan)}


def node_search(state: AgentState) -> dict:
    t0 = time.perf_counter()
    r = search_documents(state["query"], state["workspaces"], k=5)
    upd = _add_evidence(state, r.hits, r)
    upd["steps"] = _step(state, "search", f"{len(r.hits)} chunks for '{state['query']}'", t0,
                         pages=[f"{h.doc_title} p.{h.page}" for h in r.hits])
    return upd


def node_multi_hop(state: AgentState) -> dict:
    t0 = time.perf_counter()
    upd: dict = {}
    notes: list[str] = []
    calls = list(state.get("llm_calls", []))
    work: AgentState = dict(state)  # type: ignore[assignment]
    for sq in state["plan"]["sub_questions"]:
        q = sq if not notes else f"{sq} (context: {notes[-1][:200]})"
        r = search_documents(q, state["workspaces"], k=3)
        upd = _add_evidence(work, r.hits, r)
        work.update(upd)  # type: ignore[typeddict-item]
        res = get_llm().chat([{"role": "system", "content": "Answer the sub-question in one sentence using only the sources. "
                                                             "If they do not contain it, say 'unknown'."},
                              {"role": "user", "content": f"Sources:\n{format_sources(r.hits)}\n\nSub-question: {sq}"}],
                             temperature=0.0, max_tokens=120)
        calls.append(res)
        notes.append(res.text.strip())
        work["steps"] = _step(work, "hop", f"{sq} → {res.text.strip()[:160]}", t0, pages=[f"{h.doc_title} p.{h.page}" for h in r.hits])
        t0 = time.perf_counter()
    return {**upd, "notes": notes, "llm_calls": calls, "steps": work["steps"]}


def node_compare(state: AgentState) -> dict:
    t0 = time.perf_counter()
    p = state["plan"]
    found = compare_documents(int(p["doc_a"]), int(p["doc_b"]), str(p["aspect"]), state["workspaces"])
    hits = [h for doc_hits in found.values() for h in doc_hits]
    upd = _add_evidence(state, hits)
    upd["steps"] = _step(state, "compare_documents", f"{len(hits)} chunks from 2 documents", t0,
                         pages=[f"{h.doc_title} p.{h.page}" for h in hits])
    return upd


def node_synthesize(state: AgentState) -> dict:
    t0 = time.perf_counter()
    ev: list[Hit] = state.get("evidence", [])
    ev = sorted(ev, key=lambda h: -(h.rerank_score or 0))[:MAX_EVIDENCE] if state["plan"]["type"] == "simple" else ev[:MAX_EVIDENCE]
    if not ev:
        return {"answer": NOT_FOUND, "evidence": [], "steps": _step(state, "synthesize", "no evidence", t0)}
    extra = ""
    if state["plan"]["type"] == "compare":
        extra = "\nStructure the answer as a comparison: similarities, then differences, naming each document."
    if state.get("notes"):
        extra += "\nIntermediate findings (verify against sources):\n" + "\n".join(f"- {n}" for n in state["notes"])
    res = get_llm().chat([{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": f"Sources:\n\n{format_sources(ev)}\n{extra}\n\nQuestion: {state['question']}"}],
                         max_tokens=700)
    text = res.text.strip()
    if is_not_found(text):
        text = NOT_FOUND
    return {"answer": text, "evidence": ev, "llm_calls": state.get("llm_calls", []) + [res],
            "steps": _step(state, "synthesize", f"{len(ev)} sources", t0)}


def _route(state: AgentState) -> str:
    return {"multi_hop": "multi_hop", "compare": "compare"}.get(state["plan"]["type"], "search")


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("rewrite", node_rewrite)
    g.add_node("plan", node_plan)
    g.add_node("search", node_search)
    g.add_node("multi_hop", node_multi_hop)
    g.add_node("compare", node_compare)
    g.add_node("synthesize", node_synthesize)
    g.set_entry_point("rewrite")
    g.add_edge("rewrite", "plan")
    g.add_conditional_edges("plan", _route, {"search": "search", "multi_hop": "multi_hop", "compare": "compare"})
    for n in ("search", "multi_hop", "compare"):
        g.add_edge(n, "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


_graph = None


def run_agent(question: str, workspaces: list[str], history: list[dict] | None = None,
              on_step: Callable[[dict], None] | None = None) -> Answer:
    global _graph
    if _graph is None:
        _graph = build_graph()
    t0 = time.perf_counter()
    state: AgentState = {"question": question, "workspaces": workspaces, "history": history or [], "steps": [],
                         "evidence": [], "llm_calls": [], "retrieval_ms": 0.0, "rerank_ms": 0.0}
    final: dict = dict(state)
    for update in _graph.stream(state, stream_mode="updates"):
        for _node, delta in update.items():
            if not delta:
                continue
            prev_steps = len(final.get("steps", []))
            final.update(delta)
            if on_step:
                for s in final.get("steps", [])[prev_steps:]:
                    on_step(s)
    calls: list[LLMResult] = final.get("llm_calls", [])
    total = LLMResult(final.get("answer", ""), sum(c.prompt_tokens for c in calls), sum(c.completion_tokens for c in calls),
                      sum(c.ms for c in calls))
    hits: list[Hit] = final.get("evidence", [])
    text = final.get("answer", NOT_FOUND)
    nf = text == NOT_FOUND
    r = RetrievalResult(hits, final.get("retrieval_ms", 0.0), final.get("rerank_ms", 0.0), len(hits), {"mode": "agent"})
    return Answer(question, text, nf, [] if nf else extract_citations(text, hits), hits, r, total,
                  (time.perf_counter() - t0) * 1000, "llm" if nf else "", steps=final.get("steps", []))
