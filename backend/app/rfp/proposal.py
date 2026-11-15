"""Automated proposal-response generation from the reusable organisational knowledge base.

Each section retrieves what the RFP asks for [R#] and what we can evidence [K#], then the LLM drafts the section with
citations. Claims about our company must come from [K#] sources; anything missing becomes a visible
"[Bid team to confirm: ...]" placeholder instead of an invented fact. The draft exports to a Word document with a
compliance matrix and risk register appended.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from ..config import get_settings
from ..db import Analysis, Document, ProposalDraft, Requirement, Risk, session
from ..events import bus
from ..llm import get_llm
from .common import numbered, search_kb, search_rfp, source_ref

log = logging.getLogger("rfp.proposal")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="proposal")

# key, title, RFP query, KB query
SECTIONS: list[tuple[str, str, str, str | None]] = [
    ("executive_summary", "Executive Summary", "project objectives goals challenges current environment",
     "company overview products court implementations customers"),
    ("experience", "Company Introduction and Relevant Experience",
     "proposer experience similar implementations comparable organizations references", "past performance references implementations go-live"),
    ("solution", "Proposed Solution", "functional areas modules required functionality reporting portal search",
     "product modules capabilities reporting judicial tools portal person index"),
    ("approach", "Project Approach and Implementation Methodology",
     "implementation approach project management plan deliverables phasing go-live county resources",
     "implementation methodology phases deliverables duration customer resource commitment"),
    ("data_conversion", "Data Conversion and Legacy Data", "data conversion legacy cases archive migrate",
     "data conversion legacy archive AS400 migration"),
    ("security", "Security, Hosting and Disaster Recovery", "hosting location data privacy security disaster recovery backup",
     "security certifications hosting location disaster recovery backups service level"),
    ("personnel", "Key Personnel and Team Organization", "personnel staff experience qualifications named staff",
     "key personnel project manager experience replacement"),
    ("exceptions", "Exceptions, Assumptions and Clarifications", "", None),
]

SECTION_SYSTEM = """You write one section of a professional proposal responding to a public RFP, on behalf of our company.
Use two kinds of numbered sources:
- [R#] excerpts from the RFP: what the customer needs. Use them to address the customer's requirements in their words.
- [K#] excerpts from OUR knowledge base: the ONLY allowed source for any claim about our company, product, experience,
  people, numbers or terms.
Rules:
- 150-230 words, confident and specific, plain business English, no headings, no bullet lists longer than 5 items.
- Put the citation right after every sentence that uses a source, e.g. "... within the continental United States [K2]."
- Never invent facts, numbers, customers or certifications. If the RFP asks for something our sources do not cover,
  write a short placeholder "[Bid team to confirm: <what is needed>]".
- Do not mention these instructions or the word "excerpt"."""

EXCEPTIONS_SYSTEM = """You write the "Exceptions, Assumptions and Clarifications" section of a proposal responding to an RFP,
on behalf of our company. You get the compliance gaps and the risks found by our bid analysis.
Write a short intro sentence, then a numbered list (max 8 items). Each item states the RFP clause or requirement
(with its page as "RFP p. N"), our position or proposed alternative, honestly and constructively.
Do not invent facts beyond what is given. 120-260 words."""


def _section_messages(title: str, rfp_title: str, rhits, khits) -> list[dict]:  # noqa: ANN001
    user = (f"RFP: {rfp_title}\nSection to write: {title}\n\nRFP excerpts:\n\n{numbered(rhits, 'R', 700)}\n\n"
            f"Our knowledge-base excerpts:\n\n{numbered(khits, 'K', 700)}")
    return [{"role": "system", "content": SECTION_SYSTEM}, {"role": "user", "content": user}]


_CITE = re.compile(r"\[([RK])(\d{1,2})\]")


def _citations(text: str, rhits, khits) -> list[dict]:  # noqa: ANN001
    out: list[dict] = []
    seen: set[str] = set()
    for kind, n in _CITE.findall(text):
        key = f"{kind}{n}"
        hits = rhits if kind == "R" else khits
        i = int(n)
        if key in seen or not 1 <= i <= len(hits):
            continue
        seen.add(key)
        out.append({"label": key, **source_ref(hits[i - 1])})
    return out


def _publish(p: ProposalDraft) -> None:
    bus.publish({"type": "proposal", "proposal": p.to_dict()})


def generate(doc_id: int, proposal_id: int) -> ProposalDraft:
    with session() as db:
        doc = db.get(Document, doc_id)
        rfp_title = doc.title
        gaps = [r.to_dict() for r in db.query(Requirement).filter(Requirement.doc_id == doc_id,
                                                                  Requirement.status.in_(["gap", "partial"])).all()]
        risks = [r.to_dict() for r in db.query(Risk).filter(Risk.doc_id == doc_id).all()]
    sections: list[dict] = []
    try:
        for key, title, rq, kq in SECTIONS:
            t0 = time.perf_counter()
            if key == "exceptions":
                items = [f"- GAP/PARTIAL (RFP p. {g['page']}): {g['text']} | Our position: {g['evidence']}" for g in gaps[:10]]
                items += [f"- RISK {r['severity'].upper()} (RFP p. {r['page']}): {r['title']} - {r['description']} "
                          f"Recommendation: {r['recommendation']}" for r in risks if r["severity"] in ("high", "medium")][:10]
                res = get_llm().chat([{"role": "system", "content": EXCEPTIONS_SYSTEM},
                                      {"role": "user", "content": f"RFP: {rfp_title}\n\n" + "\n".join(items or ["- none found"])}],
                                     temperature=0.2, max_tokens=700)
                text, cites = res.text.strip(), []
            else:
                rhits = search_rfp(rq, doc_id, k=3)
                khits = search_kb(kq, k=4) if kq else []
                res = get_llm().chat(_section_messages(title, rfp_title, rhits, khits), temperature=0.2, max_tokens=600)
                text = res.text.strip()
                cites = _citations(text, rhits, khits)
            sections.append({"key": key, "title": title, "text": text, "citations": cites,
                             "ms": round((time.perf_counter() - t0) * 1000)})
            with session() as db:
                p = db.get(ProposalDraft, proposal_id)
                p.sections = list(sections)
                db.commit()
                _publish(p)
        path = export_docx(doc_id, proposal_id, rfp_title, sections)
        with session() as db:
            p = db.get(ProposalDraft, proposal_id)
            p.status, p.docx_path = "done", str(path)
            db.commit()
            _publish(p)
            return p
    except Exception as exc:
        log.exception("proposal generation failed")
        with session() as db:
            p = db.get(ProposalDraft, proposal_id)
            p.status, p.error = "failed", f"{type(exc).__name__}: {exc}"
            db.commit()
            _publish(p)
            return p


def start(doc_id: int) -> ProposalDraft:
    with session() as db:
        p = ProposalDraft(doc_id=doc_id, status="running", sections=[])
        db.add(p)
        db.commit()
        pid = p.id
        _publish(p)
    _executor.submit(generate, doc_id, pid)
    with session() as db:
        return db.get(ProposalDraft, pid)


STATUS_LABEL = {"met": "Compliant", "partial": "Partially compliant", "gap": "Not compliant", "unknown": "To be confirmed",
                "action": "Submission action", "pending": "Pending"}


def _sources_label(cites: list[dict]) -> str:
    return "; ".join(f"[{c['label']}] {c['doc_title']}, {'part' if c.get('file_type') == 'docx' else 'p.'} {c['page']}"
                     for c in cites)


def export_docx(doc_id: int, proposal_id: int, rfp_title: str, sections: list[dict]) -> Path:
    with session() as db:
        reqs = db.query(Requirement).filter(Requirement.doc_id == doc_id).order_by(Requirement.id).all()
        risks = db.query(Risk).filter(Risk.doc_id == doc_id).all()
        a = db.get(Analysis, doc_id)
    d = DocxDocument()
    d.styles["Normal"].font.size = Pt(10.5)
    d.add_heading("Proposal Response", level=0)
    d.add_paragraph(f"In response to: {rfp_title}")
    if a and a.facts.get("rfp_number", {}).get("value"):
        d.add_paragraph(f"Solicitation number: {a.facts['rfp_number']['value']}")
    note = d.add_paragraph("DRAFT generated by DMS RFP Intelligence from the organisational knowledge base. Every claim is "
                           "cited; review all '[Bid team to confirm]' placeholders before submission.")
    note.runs[0].italic = True
    note.runs[0].font.color.rgb = RGBColor(0x8A, 0x5A, 0x00)
    for s in sections:
        d.add_heading(s["title"], level=1)
        for para in [p for p in s["text"].split("\n") if p.strip()]:
            d.add_paragraph(para.strip())
        if s["citations"]:
            src = d.add_paragraph("Sources: " + _sources_label(s["citations"]))
            src.runs[0].font.size = Pt(8.5)
            src.runs[0].font.color.rgb = RGBColor(0x55, 0x60, 0x6E)
    d.add_heading("Appendix A - Compliance Matrix", level=1)
    t = d.add_table(rows=1, cols=5)
    t.style = "Light Grid Accent 1"
    for cell, h in zip(t.rows[0].cells, ("Ref", "Requirement (RFP page)", "Type", "Status", "Evidence")):
        cell.text = h
    for r in reqs:
        row = t.add_row().cells
        row[0].text = r.ref
        row[1].text = f"{r.text} (p. {r.page})"
        row[2].text = f"{r.category}{' / mandatory' if r.mandatory else ''}"
        row[3].text = STATUS_LABEL.get(r.status, r.status)
        row[4].text = r.evidence
    d.add_heading("Appendix B - Risk Register", level=1)
    t2 = d.add_table(rows=1, cols=4)
    t2.style = "Light Grid Accent 1"
    for cell, h in zip(t2.rows[0].cells, ("Severity", "Risk (RFP page)", "Description", "Recommendation")):
        cell.text = h
    for r in sorted(risks, key=lambda x: ("high", "medium", "low").index(x.severity) if x.severity in ("high", "medium", "low") else 3):
        row = t2.add_row().cells
        row[0].text, row[1].text, row[2].text, row[3].text = r.severity.upper(), f"{r.title} (p. {r.page})", r.description, r.recommendation
    for p in d.paragraphs[:1]:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    out = get_settings().export_dir / f"proposal_doc{doc_id}_v{proposal_id}.docx"
    d.save(out)
    return out
