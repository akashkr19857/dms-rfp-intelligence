"""Risk & gap detection: for each risk theme, compare what the RFP demands with our standard position in the
knowledge base, and ask the LLM for concrete, cited risks with severity and a recommendation."""
from __future__ import annotations

from typing import Callable

from ..db import Requirement, session
from .common import CallCounter, llm_json, numbered, pick, search_kb, search_rfp, source_ref

# (theme, query inside the RFP, query in our knowledge base or None)
RISK_THEMES: list[tuple[str, str, str | None]] = [
    ("Liability & indemnification", "indemnification hold harmless liability limitation of remedies warranties",
     "limitation of liability indemnification"),
    ("Proposal validity", "proposals valid offer held firm calendar days withdrawn", "proposal validity days"),
    ("Data ownership & exit", "termination data ownership return county data machine-readable format days transition",
     "data return export termination days"),
    ("Schedule", "implementation begin target go-live date timeline phasing schedule", "typical implementation duration months go-live"),
    ("Scope coverage", "functional areas modules subset of functionality best of breed partnerships prime vendor",
     "modules not included partner jury"),
    ("Hosting, security & DR", "hosting location United States data privacy security disaster recovery backup offsite",
     "hosting location disaster recovery backups certifications"),
    ("Governing law & disputes", "governing law laws of the State litigation venue court", "governing law contracts state"),
    ("Pricing & evaluation", "cost evaluation total cost of ownership ten-year price adjustments change orders not-to-exceed",
     "licensing pricing named user"),
    ("Insurance & penalties", "insurance certificates liquidated damages penalties performance bond", "insurance coverage"),
    ("Submission logistics", "hard copy original binders electronic USB file format naming mailing address deadline", None),
]

RISK_SYSTEM = """You are a bid/no-bid risk analyst. Compare the RFP excerpts [R#] with our company's standard position in
the knowledge-base excerpts [K#] for ONE risk theme.
Report only concrete risks a bid team must act on: obligations that CONFLICT with our standard terms or capabilities,
onerous or unusual clauses, tight deadlines, disqualification traps, or requirements we cannot evidence.
If our knowledge base shows we already satisfy the RFP clause (e.g. we already host in the required country, already
have a disaster recovery plan), that is NOT a risk: return no risk for it. Standard issuer rights (right to reject,
no obligation to award, force majeure) are not risks unless they are unusual.
Each risk needs: "title" (max 10 words), "category" (legal|commercial|schedule|technical|compliance|submission),
"severity" (high = would disqualify us or create uncapped financial/legal exposure; medium = conflicts with our
standard terms or needs negotiation or extra cost; low = needs attention). Use "high" sparingly, "description" (1-2 sentences quoting the exact numbers/terms from both sides),
"recommendation" (1 sentence: what the bid team should do), "rfp_source" (R number), "kb_sources" (K numbers, may be empty).
Return at most 2 risks. If there is no real risk for this theme, return an empty list.
Reply as JSON: {"risks": [ ... ]}"""

def cross_check(doc_id: int, risks: list[dict], min_overlap: float = 0.5) -> list[dict]:
    """Drop risks that the compliance stage already disproved.

    A risk is matched to the extracted requirements on the same RFP page that share most of their words with it. If
    every matched requirement was judged "met" against the knowledge base, the risk is a false alarm (e.g. "data
    storage conflict" when our hosting already satisfies the continental-US requirement). Risks without a matching
    requirement (boilerplate, deadlines, terms the extractor kept elsewhere) are kept.
    """
    from .requirements import _tokens

    with session() as db:
        reqs = [r for r in db.query(Requirement).filter(Requirement.doc_id == doc_id).all() if r.kind == "capability"]
    kept: list[dict] = []
    for risk in risks:
        rt = _tokens(f"{risk['title']} {risk['description']}")
        matched = []
        for r in reqs:
            if r.page != risk["page"]:
                continue
            qt = _tokens(r.text)
            if qt and len(rt & qt) / len(qt) >= min_overlap:
                matched.append(r)
        if matched and all(r.status == "met" for r in matched):
            continue
        kept.append(risk)
    return kept


SEVERITIES = ("high", "medium", "low")
CATS = ("legal", "commercial", "schedule", "technical", "compliance", "submission")


def detect_risks(doc_id: int, counter: CallCounter | None = None,
                 on_progress: Callable[[float], None] | None = None) -> list[dict]:
    risks: list[dict] = []
    titles: set[str] = set()
    for i, (theme, rq, kq) in enumerate(RISK_THEMES):
        rhits = search_rfp(rq, doc_id, k=3)
        if not rhits:
            continue
        khits = search_kb(kq, k=2) if kq else []
        user = f"Risk theme: {theme}\n\nRFP excerpts:\n\n{numbered(rhits, 'R')}\n\n"
        user += f"Knowledge-base excerpts (our standard position):\n\n{numbered(khits, 'K')}" if khits else "No knowledge-base excerpts."
        data = llm_json(RISK_SYSTEM, user, counter, max_tokens=700)
        for r in data.get("risks", []) if isinstance(data.get("risks"), list) else []:
            if not isinstance(r, dict) or not r.get("title"):
                continue
            title = str(r["title"]).strip()[:140]
            if title.lower() in titles:
                continue
            titles.add(title.lower())
            src = pick(rhits, r.get("rfp_source")) or rhits[:1]
            sev = str(r.get("severity", "medium")).lower()
            cat = str(r.get("category", "compliance")).lower()
            risks.append({"title": title, "theme": theme, "category": cat if cat in CATS else "compliance",
                          "severity": sev if sev in SEVERITIES else "medium",
                          "description": str(r.get("description", ""))[:800],
                          "recommendation": str(r.get("recommendation", ""))[:500],
                          "page": src[0].page, "chunk_id": src[0].chunk_id,
                          "kb_sources": [source_ref(h) for h in pick(khits, r.get("kb_sources", []))]})
        if on_progress:
            on_progress((i + 1) / len(RISK_THEMES))
    return cross_check(doc_id, risks)


SEV_WEIGHT = {"high": 8, "medium": 3, "low": 1}
STATUS_WEIGHT = {"met": 1.0, "partial": 0.5, "unknown": 0.25, "gap": 0.0}


def bid_score(doc_id: int, risks: list[dict]) -> dict:
    """Deterministic bid/no-bid score: 70% compliance of mandatory capability requirements, 30% risk exposure."""
    with session() as db:
        reqs = db.query(Requirement).filter(Requirement.doc_id == doc_id, Requirement.kind == "capability").all()
    mand = [r for r in reqs if r.mandatory] or reqs
    counts = {s: sum(1 for r in reqs if r.status == s) for s in ("met", "partial", "gap", "unknown")}
    compliance = 100.0 * sum(STATUS_WEIGHT.get(r.status, 0.25) for r in mand) / len(mand) if mand else 0.0
    exposure = min(100, sum(SEV_WEIGHT.get(r["severity"], 3) for r in risks))
    score = round(0.7 * compliance + 0.3 * (100 - exposure), 1)
    rec = "Bid" if score >= 70 else "Bid with conditions" if score >= 50 else "No bid"
    return {"score": score, "recommendation": rec, "compliance_pct": round(compliance, 1), "risk_exposure": exposure,
            "counts": counts, "mandatory_total": len(mand),
            "high_risks": sum(1 for r in risks if r["severity"] == "high"),
            "method": "0.7 x weighted compliance of mandatory capability requirements (met 1, partial 0.5, unknown 0.25, gap 0)"
                      " + 0.3 x (100 - risk exposure; high 8, medium 3, low 1 points, capped at 100)"}
