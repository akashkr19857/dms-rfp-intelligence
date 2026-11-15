"""Evaluate DMS RFP Intelligence against the hand-labelled answer key (backend/eval/gold_rfp.json).

    python backend/eval/run_eval.py --release v1.0.0 --label "baseline"            # uses the stored analyses
    python backend/eval/run_eval.py --release v1.0.0 --label "baseline" --reanalyze  # re-runs the analysis first

Measures (local models only, on this machine):
* key-fact extraction accuracy (Champaign + Detroit RFPs)
* requirement extraction recall (30 labelled Champaign requirements, page must match +/- 1) and extraction volume
* compliance-status accuracy against the fictional knowledge base (17 labelled requirements)
* risk detection recall (7 labelled risks)
* grounded Q&A: retrieval hit@5 of the gold page, answer correctness (LLM judge), not-found handling, latency
* analysis wall-clock time and LLM calls per RFP
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0]))
sys.path.insert(0, str(HERE.parents[2] / "_shared"))

from app.config import KB_WS, PROJECT_ROOT, TENDERS_WS, get_settings  # noqa: E402
from app.db import Analysis, Document, EvalRun, Requirement, Risk, session  # noqa: E402
from app.llm import get_llm, parse_json  # noqa: E402
from eval.metrics import CORRECTNESS_PROMPT, percentile  # noqa: E402

try:
    from gpulock import gpu_lock
except ImportError:
    from contextlib import nullcontext as gpu_lock  # type: ignore[assignment]

log = logging.getLogger("eval")
GOLD = json.loads((HERE / "gold_rfp.json").read_text(encoding="utf-8"))
RESULTS_DIR = HERE / "results"
OWNER = "dms-rfp-eval"


def hardware() -> str:
    try:
        import torch

        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no GPU"
    except Exception:
        gpu = "unknown GPU"
    s = get_settings()
    return (f"{gpu}, {platform.processor() or platform.machine()}, {platform.system()} {platform.release()}; "
            f"LLM {s.llm_model} (Ollama), embeddings {s.embed_model}, reranker {s.reranker_model}")


def matches(text: str, alternatives: list[list[str]]) -> bool:
    low = (text or "").lower()
    return any(all(k.lower() in low for k in alt) for alt in alternatives)


def docs_by_file() -> dict[str, int]:
    with session() as db:
        return {d.filename: d.id for d in db.query(Document).all()}


# ---------------------------------------------------------------- analysis-based metrics
def eval_facts(ids: dict[str, int]) -> dict:
    rows = []
    for fname, fields in GOLD["facts"].items():
        with session() as db:
            a = db.get(Analysis, ids[fname])
        facts = a.facts if a else {}
        for field, alts in fields.items():
            value = (facts.get(field) or {}).get("value") or ""
            rows.append({"doc": fname, "field": field, "value": value, "correct": matches(value, alts)})
    return {"accuracy": sum(r["correct"] for r in rows) / len(rows), "n": len(rows), "items": rows}


def find_requirement(reqs: list[Requirement], item: dict) -> Requirement | None:
    for r in reqs:
        if matches(r.text, item["any"]) and abs(r.page - item["page"]) <= 1:
            return r
    return None


def eval_requirements_and_compliance(ids: dict[str, int]) -> tuple[dict, dict]:
    doc_id = ids[GOLD["requirements"]["doc"]]
    with session() as db:
        reqs = db.query(Requirement).filter(Requirement.doc_id == doc_id).all()
    found: dict[str, Requirement] = {}
    rows = []
    for item in GOLD["requirements"]["items"]:
        r = find_requirement(reqs, item)
        if r is not None:
            found[item["id"]] = r
        rows.append({"id": item["id"], "page": item["page"], "found": r is not None, "match": r.text if r else None,
                     "match_ref": r.ref if r else None})
    req = {"recall": sum(x["found"] for x in rows) / len(rows), "n": len(rows), "extracted_total": len(reqs),
           "capability": sum(1 for r in reqs if r.kind == "capability"), "submission": sum(1 for r in reqs if r.kind == "submission"),
           "items": rows}
    crow = []
    for item in GOLD["compliance"]["items"]:
        r = found.get(item["id"])
        if r is None:
            crow.append({"id": item["id"], "expected": item["expected"], "predicted": None, "correct": None})
            continue
        crow.append({"id": item["id"], "expected": item["expected"], "predicted": r.status, "requirement": r.text,
                     "evidence": r.evidence, "correct": r.status in item["expected"]})
    judged = [c for c in crow if c["correct"] is not None]
    comp = {"accuracy": sum(c["correct"] for c in judged) / len(judged) if judged else None, "judged": len(judged),
            "n": len(crow), "items": crow}
    return req, comp


def eval_risks(ids: dict[str, int]) -> dict:
    doc_id = ids[GOLD["risks"]["doc"]]
    with session() as db:
        risks = db.query(Risk).filter(Risk.doc_id == doc_id).all()
    rows = []
    for item in GOLD["risks"]["items"]:
        hit = next((r for r in risks if matches(f"{r.title} {r.description}", item["any"])), None)
        rows.append({"id": item["id"], "found": hit is not None, "match": hit.title if hit else None,
                     "severity": hit.severity if hit else None})
    return {"recall": sum(r["found"] for r in rows) / len(rows), "n": len(rows), "detected_total": len(risks),
            "high": sum(1 for r in risks if r.severity == "high"), "items": rows}


def analysis_stats() -> list[dict]:
    with session() as db:
        out = []
        for d in db.query(Document).filter(Document.workspace_id == TENDERS_WS).all():
            a = db.get(Analysis, d.id)
            if a is None or a.status != "done":
                continue
            out.append({"doc": d.filename, "pages": d.pages, "chunks": d.n_chunks, "seconds": a.timings.get("total"),
                        "timings": a.timings, "llm_calls": a.llm_calls,
                        "requirements": db.query(Requirement).filter(Requirement.doc_id == d.id).count(),
                        "risks": db.query(Risk).filter(Risk.doc_id == d.id).count(),
                        "bid_score": a.bid_score.get("score"), "recommendation": a.bid_score.get("recommendation")})
        return out


# ---------------------------------------------------------------- grounded Q&A
def judge(q: str, reference: str, answer: str) -> tuple[float, str]:
    res = get_llm().chat([{"role": "system", "content": CORRECTNESS_PROMPT},
                          {"role": "user", "content": f"QUESTION: {q}\nREFERENCE: {reference}\nCANDIDATE: {answer}"}],
                         json_mode=True, temperature=0.0, max_tokens=200)
    d = parse_json(res.text)
    try:
        return min(max(float(d.get("score", 0)), 0.0), 1.0), str(d.get("reason", ""))
    except (TypeError, ValueError):
        return 0.0, "unparseable judge output"


def eval_qa(ids: dict[str, int]) -> dict:
    from app.rag import answer
    from app.rfp.common import kb_doc_ids

    rows = []
    for it in GOLD["qa"]:
        if it["doc"] == "kb":
            scope = {"doc_ids": kb_doc_ids()}
        else:
            scope = {"doc_ids": [ids[it["doc"]]] + kb_doc_ids()}
        with gpu_lock(OWNER):
            t0 = time.perf_counter()
            ans = answer(it["question"], [TENDERS_WS, KB_WS], retrieval_kwargs=scope)
            latency = (time.perf_counter() - t0) * 1000
            unanswerable = it["reference"] == "NOT_FOUND"
            if unanswerable:
                score, reason = (1.0, "correctly refused") if ans.not_found else (0.0, "answered an unanswerable question")
            else:
                score, reason = (0.0, "false refusal") if ans.not_found else judge(it["question"], it["reference"], ans.answer)
        hit = None
        if it["pages"]:
            target = ids[it["doc"]]
            hit = any(h.doc_id == target and h.page in it["pages"] for h in ans.hits[:5])
        rows.append({"id": it["id"], "question": it["question"], "reference": it["reference"], "answer": ans.answer,
                     "not_found": ans.not_found, "score": score, "reason": reason, "hit@5": hit,
                     "citations": [{"doc": c["doc_title"], "page": c["page"]} for c in ans.citations], "latency_ms": round(latency)})
        log.info("%s score=%.1f hit=%s %.0fms", it["id"], score, hit, latency)
    answerable = [r for r in rows if r["reference"] != "NOT_FOUND"]
    lat = [r["latency_ms"] for r in rows]
    with_pages = [r for r in rows if r["hit@5"] is not None]
    return {"correctness": statistics.mean(r["score"] for r in answerable),
            "fully_correct": sum(1 for r in answerable if r["score"] == 1.0) / len(answerable),
            "retrieval_hit@5": sum(1 for r in with_pages if r["hit@5"]) / len(with_pages),
            "not_found_accuracy": statistics.mean(r["score"] for r in rows if r["reference"] == "NOT_FOUND"),
            "false_refusals": sum(1 for r in answerable if r["not_found"]),
            "latency_p50_ms": percentile(lat, 0.5), "latency_p95_ms": percentile(lat, 0.95), "n": len(rows), "items": rows}


# ---------------------------------------------------------------- persistence
def import_result(path: Path) -> None:
    """Load a results JSON into the eval history (idempotent)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    with session() as db:
        if db.query(EvalRun).filter(EvalRun.results_file == rel).first():
            return
        db.add(EvalRun(release=data["release"], label=data["label"], config=data.get("config", {}), metrics=data["metrics"],
                       n_questions=data["metrics"].get("qa", {}).get("n", 0), hardware=data.get("hardware", ""), results_file=rel))
        db.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default=get_settings().release)
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--reanalyze", action="store_true")
    ap.add_argument("--skip-qa", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    for noisy in ("httpx", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ids = docs_by_file()
    if args.reanalyze:
        from app.rfp.pipeline import analyze

        for fname in ("champaign_CCMS.pdf", "detroit_RFP184578.pdf"):
            with gpu_lock(OWNER):
                analyze(ids[fname])
    facts = eval_facts(ids)
    reqs, comp = eval_requirements_and_compliance(ids)
    risks = eval_risks(ids)
    qa = None if args.skip_qa else eval_qa(ids)
    metrics = {
        "facts": {k: v for k, v in facts.items() if k != "items"},
        "requirements": {k: v for k, v in reqs.items() if k != "items"},
        "compliance": {k: v for k, v in comp.items() if k != "items"},
        "risks": {k: v for k, v in risks.items() if k != "items"},
        "qa": {k: v for k, v in qa.items() if k != "items"} if qa else {},
        "analysis": analysis_stats(),
    }
    s = get_settings()
    out = {"release": args.release, "label": args.label, "created_at": datetime.now(timezone.utc).isoformat(),
           "hardware": hardware(), "config": {"llm": s.llm_model, "embed": s.embed_model, "reranker": s.reranker_model,
                                              "retrieval": s.retrieval_mode, "top_k": s.top_k},
           "metrics": metrics, "details": {"facts": facts["items"], "requirements": reqs["items"], "compliance": comp["items"],
                                           "risks": risks["items"], "qa": qa["items"] if qa else []}}
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{args.release}_{args.label.replace(' ', '-')}_{stamp}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    import_result(path)
    print(json.dumps(metrics, indent=1))
    print(f"saved {path}")


if __name__ == "__main__":
    main()
