"""DMS RFP Intelligence FastAPI app (port 8200)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import pymupdf
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .config import PROJECT_ROOT, get_settings
from .config import KB_WS, TENDERS_WS
from .db import Analysis, Chunk, Document, EvalRun, ProposalDraft, Requirement, Risk, Trace, User, Workspace, session
from .events import bus
from .ingest.pipeline import SUPPORTED, delete_document, ingest_document, register_document, resolve_path
from .rag import answer_stream, record_trace

log = logging.getLogger("rfp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _import_eval_history() -> None:
    """Eval results are committed as JSON files (backend/eval/results); rebuild the run history from them."""
    results = PROJECT_ROOT / "backend" / "eval" / "results"
    if not results.exists():
        return
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
    from eval.run_eval import import_result

    for f in sorted(results.glob("*.json")):
        try:
            import_result(f)
        except Exception:  # a malformed file must not stop the API
            log.exception("could not import eval result %s", f.name)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from .seed import seed_identities

    seed_identities()
    _import_eval_history()
    if get_settings().rerank_provider != "overlap":  # load the reranker now so the first question isn't slow
        from .retrieval.reranker import get_reranker

        threading.Thread(target=get_reranker, daemon=True).start()
    yield
    from .retrieval.hybrid import close_store

    close_store()


app = FastAPI(title="DMS RFP Intelligence API", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ auth / RBAC
def user_from_token(token: str | None) -> User:
    if not token:
        raise HTTPException(401, "missing token")
    with session() as db:
        user = db.query(User).filter(User.token == token).first()
    if user is None:
        raise HTTPException(401, "invalid token")
    return user


def current_user(authorization: str | None = Header(default=None)) -> User:
    token = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else authorization
    return user_from_token(token)


def scope(user: User, workspace: str | None) -> list[str]:
    """Workspaces a request may read. Asking for a workspace you are not a member of is a 403, never a silent widen."""
    allowed = user.workspace_ids
    if workspace in (None, "", "all"):
        return allowed
    if workspace not in allowed:
        raise HTTPException(403, f"no access to workspace '{workspace}'")
    return [workspace]


def get_doc_checked(user: User, doc_id: int) -> Document:
    with session() as db:
        doc = db.get(Document, doc_id)
    if doc is None or doc.workspace_id not in user.workspace_ids:
        raise HTTPException(404, "document not found")
    return doc


def user_dict(u: User) -> dict:
    return {"id": u.id, "name": u.name, "role": u.role, "workspaces": u.workspace_ids}


class LoginIn(BaseModel):
    user_id: str


@app.post("/api/login")
def login(body: LoginIn) -> dict:
    """Demo login: choose one of the seeded demo users (no passwords in this demo)."""
    with session() as db:
        u = db.get(User, body.user_id)
    if u is None:
        raise HTTPException(404, "unknown user")
    return {"token": u.token, "user": user_dict(u)}


@app.get("/api/users")
def demo_users() -> list[dict]:
    with session() as db:
        return [user_dict(u) for u in db.query(User).order_by(User.id).all()]


@app.get("/api/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_dict(user)


@app.get("/api/health")
def health() -> dict:
    s = get_settings()
    ollama = "down"
    try:
        import httpx

        tags = httpx.get(f"{s.ollama_url}/api/tags", timeout=3).json()
        names = {m["name"] for m in tags.get("models", [])}
        ollama = "ok" if any(n.startswith(s.llm_model) for n in names) else "model missing"
    except Exception:
        pass
    return {"status": "ok", "version": __version__, "llm": s.llm_model, "embed": s.embed_model, "reranker": s.reranker_model,
            "retrieval": s.retrieval_mode, "ollama": ollama}


# ------------------------------------------------------------------ workspaces & documents
@app.get("/api/workspaces")
def workspaces(user: User = Depends(current_user)) -> list[dict]:
    with session() as db:
        out = []
        for w in db.query(Workspace).filter(Workspace.id.in_(user.workspace_ids)).all():
            n = db.query(Document).filter(Document.workspace_id == w.id).count()
            out.append({"id": w.id, "name": w.name, "description": w.description, "documents": n})
        return out


@app.get("/api/documents")
def documents(workspace: str | None = None, user: User = Depends(current_user)) -> list[dict]:
    wss = scope(user, workspace)
    with session() as db:
        return [d.to_dict() for d in db.query(Document).filter(Document.workspace_id.in_(wss)).order_by(Document.id).all()]


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


_ingest_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")


def _ingest_then_analyze(doc_id: int, analyze_after: bool) -> None:
    doc = ingest_document(doc_id)
    if analyze_after and doc is not None and doc.status == "ready" and doc.workspace_id == TENDERS_WS:
        from .rfp.pipeline import analyze_async

        analyze_async(doc_id)


@app.post("/api/documents", status_code=202)
async def upload(file: UploadFile = File(...), workspace: str = Form(...), title: str = Form(""),
                 analyze: bool = Form(True), user: User = Depends(current_user)) -> dict:
    scope(user, workspace)
    name = (file.filename or "").lower()
    if not name.endswith(SUPPORTED):
        raise HTTPException(400, "only PDF and DOCX files are supported")
    data = await file.read()
    if name.endswith(".pdf") and not data.startswith(b"%PDF"):
        raise HTTPException(400, "file is not a PDF")
    if name.endswith(".docx") and not data.startswith(b"PK"):
        raise HTTPException(400, "file is not a DOCX")
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "file larger than 50 MB")
    dest_dir = get_settings().upload_dir / workspace
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _SAFE.sub("_", Path(file.filename or "upload.pdf").name)
    i = 1
    while dest.exists():
        dest = dest.with_name(f"{dest.stem}-{i}{dest.suffix}")
        i += 1
    dest.write_bytes(data)
    doc_id = register_document(dest, workspace, title or None, source=f"uploaded by {user.id}")
    _ingest_pool.submit(_ingest_then_analyze, doc_id, analyze)
    with session() as db:
        return db.get(Document, doc_id).to_dict()


@app.delete("/api/documents/{doc_id}")
def remove(doc_id: int, user: User = Depends(current_user)) -> dict:
    get_doc_checked(user, doc_id)
    delete_document(doc_id)
    bus.publish({"type": "document_deleted", "id": doc_id})
    return {"deleted": doc_id}


@app.get("/api/documents/{doc_id}/file")
def doc_file(doc_id: int, token: str | None = None, authorization: str | None = Header(default=None)) -> FileResponse:
    user = current_user(authorization) if authorization else user_from_token(token)
    doc = get_doc_checked(user, doc_id)
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document" if doc.file_type == "docx"
             else "application/pdf")
    return FileResponse(resolve_path(doc), media_type=media, filename=doc.filename)


@app.get("/api/documents/{doc_id}/pages/{page}.png")
def page_image(doc_id: int, page: int, chunk_id: str | None = None, token: str | None = None, zoom: float = 1.6,
               authorization: str | None = Header(default=None)) -> Response:
    """Render one PDF page; if chunk_id is given, highlight that chunk's text boxes (used by the source preview)."""
    user = current_user(authorization) if authorization else user_from_token(token)
    doc = get_doc_checked(user, doc_id)
    if doc.file_type != "pdf":
        raise HTTPException(415, "page images are only available for PDF documents")
    boxes: list = []
    if chunk_id:
        with session() as db:
            ch = db.get(Chunk, chunk_id)
        if ch is not None and ch.doc_id == doc_id and ch.page == page:
            boxes = ch.bboxes
    with pymupdf.open(resolve_path(doc)) as pdf:
        if not 1 <= page <= len(pdf):
            raise HTTPException(404, "page out of range")
        p = pdf[page - 1]
        for b in boxes:
            r = pymupdf.Rect(b) + (-2, -2, 2, 2)
            p.draw_rect(r, color=(0.96, 0.62, 0.04), fill=(1.0, 0.85, 0.2), fill_opacity=0.28, width=1.2, overlay=True)
        png = p.get_pixmap(matrix=pymupdf.Matrix(min(zoom, 3.0), min(zoom, 3.0))).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/documents/{doc_id}/chunks")
def doc_chunks(doc_id: int, page: int | None = None, user: User = Depends(current_user)) -> list[dict]:
    get_doc_checked(user, doc_id)
    with session() as db:
        q = db.query(Chunk).filter(Chunk.doc_id == doc_id)
        if page:
            q = q.filter(Chunk.page == page)
        return [{"id": c.id, "page": c.page, "section": c.section, "kind": c.kind, "text": c.text}
                for c in q.order_by(Chunk.page).limit(500).all()]


# ------------------------------------------------------------------ chat
class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    mode: Literal["rag", "agent"] = "rag"
    workspace: str | None = None
    tender_id: int | None = None  # scope retrieval to this RFP + the knowledge base
    history: list[dict] = Field(default_factory=list)


def run_chat(user: User, body: ChatIn, emit=None) -> dict:  # noqa: ANN001
    wss = scope(user, body.workspace)
    if body.mode == "agent":
        from .agent import run_agent

        ans = run_agent(body.question, wss, body.history, on_step=(lambda s: emit({"type": "step", "step": s})) if emit else None)
        if emit:
            emit({"type": "sources", "sources": [h.to_dict(max_chars=600) for h in ans.hits]})
            emit({"type": "token", "text": ans.answer})
    else:
        ans = None
        kwargs = None
        if body.tender_id:
            get_doc_checked(user, body.tender_id)
            from .rfp.common import kb_doc_ids

            kwargs = {"doc_ids": [body.tender_id] + (kb_doc_ids() if KB_WS in wss else [])}
        for ev in answer_stream(body.question, wss, history=body.history, retrieval_kwargs=kwargs):
            if ev["type"] == "final":
                ans = ev["answer"]
            elif emit:
                emit(ev)
        assert ans is not None
    ans.trace_id = record_trace(user.id, wss, body.mode, ans)
    return ans.to_dict()


@app.post("/api/chat")
def chat(body: ChatIn, user: User = Depends(current_user)) -> dict:
    return run_chat(user, body)


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, token: str = Query(...)) -> None:
    try:
        user = user_from_token(token)
    except HTTPException:
        await ws.close(code=4401)
        return
    await ws.accept()
    loop = asyncio.get_running_loop()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                body = ChatIn(**json.loads(raw))
            except Exception as exc:
                await ws.send_json({"type": "error", "error": f"bad request: {exc}"})
                continue
            queue: asyncio.Queue = asyncio.Queue()

            def emit(ev: dict) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, ev)

            def worker() -> None:
                try:
                    emit({"type": "final", "result": run_chat(user, body, emit)})
                except HTTPException as exc:
                    emit({"type": "error", "error": exc.detail})
                except Exception as exc:  # pragma: no cover - surfaced to the UI
                    log.exception("chat failed")
                    emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})

            threading.Thread(target=worker, daemon=True).start()
            while True:
                ev = await queue.get()
                await ws.send_json(ev)
                if ev["type"] in ("final", "error"):
                    break
    except WebSocketDisconnect:
        return


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket, token: str = Query(...)) -> None:
    """Live document-ingestion progress and new query traces (filtered to the user's workspaces)."""
    try:
        user = user_from_token(token)
    except HTTPException:
        await ws.close(code=4401)
        return
    await ws.accept()
    q = bus.subscribe()
    allowed = set(user.workspace_ids)
    try:
        while True:
            ev = await q.get()
            if ev["type"] == "document" and ev["document"]["workspace_id"] not in allowed:
                continue
            if ev["type"] == "trace" and user.role != "admin" and ev["trace"]["user_id"] != user.id:
                continue
            if ev["type"] in ("analysis", "proposal") and TENDERS_WS not in allowed:
                continue
            await ws.send_json(ev)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)


# ------------------------------------------------------------------ observability
def _visible_traces(db, user: User):  # noqa: ANN001
    q = db.query(Trace)
    return q if user.role == "admin" else q.filter(Trace.user_id == user.id)


@app.get("/api/traces")
def traces(limit: int = 50, user: User = Depends(current_user)) -> list[dict]:
    with session() as db:
        return [t.to_dict() for t in _visible_traces(db, user).order_by(Trace.id.desc()).limit(min(limit, 500)).all()]


@app.get("/api/traces/{trace_id}")
def trace(trace_id: int, user: User = Depends(current_user)) -> dict:
    with session() as db:
        t = _visible_traces(db, user).filter(Trace.id == trace_id).first()
    if t is None:
        raise HTTPException(404, "trace not found")
    return t.to_dict()


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


@app.get("/api/usage")
def usage(days: int = 14, user: User = Depends(current_user)) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with session() as db:
        rows = _visible_traces(db, user).filter(Trace.created_at >= since).all()
    lat = [t.latency_ms for t in rows]
    by_day: dict[str, dict] = {}
    for t in rows:
        d = t.created_at.strftime("%Y-%m-%d")
        e = by_day.setdefault(d, {"day": d, "queries": 0, "tokens": 0, "not_found": 0, "lat": []})
        e["queries"] += 1
        e["tokens"] += t.prompt_tokens + t.completion_tokens
        e["not_found"] += int(t.not_found)
        e["lat"].append(t.latency_ms)
    daily = [{k: v for k, v in e.items() if k != "lat"} | {"p50_ms": _pct(e["lat"], 0.5), "p95_ms": _pct(e["lat"], 0.95)}
             for e in sorted(by_day.values(), key=lambda x: x["day"])]
    by_mode: dict[str, int] = {}
    by_user: dict[str, int] = {}
    for t in rows:
        by_mode[t.mode] = by_mode.get(t.mode, 0) + 1
        by_user[t.user_id] = by_user.get(t.user_id, 0) + 1
    stage = {k: round(statistics.mean(getattr(t, k) for t in rows), 1) if rows else 0.0
             for k in ("retrieval_ms", "rerank_ms", "llm_ms")}
    return {
        "queries": len(rows), "p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95),
        "prompt_tokens": sum(t.prompt_tokens for t in rows), "completion_tokens": sum(t.completion_tokens for t in rows),
        "not_found_rate": round(sum(t.not_found for t in rows) / len(rows), 3) if rows else 0.0,
        "stage_avg_ms": stage, "daily": daily, "by_mode": by_mode, "by_user": by_user,
    }


# ------------------------------------------------------------------ evaluation
@app.get("/api/eval/runs")
def eval_runs(user: User = Depends(current_user)) -> list[dict]:
    with session() as db:
        return [r.to_dict() for r in db.query(EvalRun).order_by(EvalRun.id).all()]


@app.get("/api/eval/runs/{run_id}")
def eval_run(run_id: int, user: User = Depends(current_user)) -> dict:
    with session() as db:
        r = db.get(EvalRun, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    d = r.to_dict()
    path = PROJECT_ROOT / r.results_file if r.results_file else None
    d["details"] = json.loads(path.read_text(encoding="utf-8")).get("details", {}) if path and path.exists() else {}
    return d


# ------------------------------------------------------------------ RFP intelligence
def _tender(user: User, doc_id: int) -> Document:
    doc = get_doc_checked(user, doc_id)
    if doc.workspace_id != TENDERS_WS:
        raise HTTPException(404, "not a tender document")
    return doc


def _tender_summary(doc: Document, a: Analysis | None, db) -> dict:  # noqa: ANN001
    reqs = db.query(Requirement).filter(Requirement.doc_id == doc.id).all()
    risks = db.query(Risk).filter(Risk.doc_id == doc.id).all()
    counts: dict[str, int] = {}
    for r in reqs:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {"document": doc.to_dict(), "analysis": a.to_dict() if a else None, "requirements": len(reqs),
            "status_counts": counts, "risks": len(risks), "high_risks": sum(1 for r in risks if r.severity == "high")}


@app.get("/api/tenders")
def tenders(user: User = Depends(current_user)) -> list[dict]:
    scope(user, TENDERS_WS)
    with session() as db:
        docs = db.query(Document).filter(Document.workspace_id == TENDERS_WS).order_by(Document.id).all()
        return [_tender_summary(d, db.get(Analysis, d.id), db) for d in docs]


@app.get("/api/tenders/{doc_id}")
def tender(doc_id: int, user: User = Depends(current_user)) -> dict:
    doc = _tender(user, doc_id)
    with session() as db:
        return _tender_summary(doc, db.get(Analysis, doc_id), db)


@app.post("/api/tenders/{doc_id}/analyze", status_code=202)
def tender_analyze(doc_id: int, user: User = Depends(current_user)) -> dict:
    doc = _tender(user, doc_id)
    if doc.status != "ready":
        raise HTTPException(409, "document is still being ingested")
    from .rfp.pipeline import analyze_async, get_analysis

    a = get_analysis(doc_id)
    if a is not None and a.status in ("queued", "running"):
        raise HTTPException(409, "analysis already running")
    analyze_async(doc_id)
    return {"queued": doc_id}


@app.get("/api/tenders/{doc_id}/requirements")
def tender_requirements(doc_id: int, status: str | None = None, category: str | None = None,
                        user: User = Depends(current_user)) -> list[dict]:
    _tender(user, doc_id)
    with session() as db:
        q = db.query(Requirement).filter(Requirement.doc_id == doc_id)
        if status:
            q = q.filter(Requirement.status == status)
        if category:
            q = q.filter(Requirement.category == category)
        return [r.to_dict() for r in q.order_by(Requirement.id).all()]


class RequirementPatch(BaseModel):
    status: Literal["met", "partial", "gap", "unknown", "action"] | None = None
    owner_note: str | None = Field(default=None, max_length=2000)


@app.patch("/api/requirements/{req_id}")
def patch_requirement(req_id: int, body: RequirementPatch, user: User = Depends(current_user)) -> dict:
    with session() as db:
        r = db.get(Requirement, req_id)
        if r is None:
            raise HTTPException(404, "requirement not found")
        _tender(user, r.doc_id)
        if body.status and body.status != r.status:
            r.status = body.status
            r.evidence = (r.evidence + f" [status set manually by {user.id}]").strip()
        if body.owner_note is not None:
            r.owner_note = body.owner_note
        db.commit()
        return r.to_dict()


@app.get("/api/tenders/{doc_id}/risks")
def tender_risks(doc_id: int, user: User = Depends(current_user)) -> list[dict]:
    _tender(user, doc_id)
    order = {"high": 0, "medium": 1, "low": 2}
    with session() as db:
        rows = db.query(Risk).filter(Risk.doc_id == doc_id).all()
        return [r.to_dict() for r in sorted(rows, key=lambda r: (order.get(r.severity, 3), r.page))]


@app.post("/api/tenders/{doc_id}/proposal", status_code=202)
def proposal_start(doc_id: int, user: User = Depends(current_user)) -> dict:
    _tender(user, doc_id)
    scope(user, KB_WS)  # drafting needs the knowledge base
    from .rfp.pipeline import get_analysis
    from .rfp.proposal import start

    a = get_analysis(doc_id)
    if a is None or a.status != "done":
        raise HTTPException(409, "run the RFP analysis first")
    with session() as db:
        running = db.query(ProposalDraft).filter(ProposalDraft.doc_id == doc_id, ProposalDraft.status == "running").first()
    if running is not None:
        raise HTTPException(409, "a proposal draft is already being generated")
    return start(doc_id).to_dict()


@app.get("/api/tenders/{doc_id}/proposal")
def proposal_latest(doc_id: int, user: User = Depends(current_user)) -> dict | None:
    _tender(user, doc_id)
    with session() as db:
        p = db.query(ProposalDraft).filter(ProposalDraft.doc_id == doc_id).order_by(ProposalDraft.id.desc()).first()
        return p.to_dict() if p else None


@app.get("/api/proposals/{proposal_id}/docx")
def proposal_docx(proposal_id: int, token: str | None = None, authorization: str | None = Header(default=None)) -> FileResponse:
    user = current_user(authorization) if authorization else user_from_token(token)
    with session() as db:
        p = db.get(ProposalDraft, proposal_id)
    if p is None or not p.docx_path:
        raise HTTPException(404, "proposal document not ready")
    doc = _tender(user, p.doc_id)
    safe = _SAFE.sub("_", doc.title)[:60]
    return FileResponse(p.docx_path, filename=f"Proposal_{safe}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
