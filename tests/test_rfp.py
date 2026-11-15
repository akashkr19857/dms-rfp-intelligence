"""RFP intelligence pipeline + API with a scripted fake LLM (no Ollama, no GPU)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import auth, make_pdf
from docx import Document as DocxDocument

from app.llm import FakeLLM, set_llm

RFP_TEXT = [
    ("1. Introduction and Schedule", [
        "The City of Testville issues RFP No. TV-2026-01 for a records management system. Proposals are due March 3, 2026 at 2pm.",
        "All questions must be emailed to the buyer, Jane Roe, no later than February 10, 2026.",
    ]),
    ("2. Requirements", [
        "The Contractor shall host all City data within the continental United States and shall back up data daily.",
        "Proposals shall remain valid for 180 calendar days. Proposers must submit one hard copy original.",
    ]),
    ("3. Terms", [
        "Vendor shall indemnify and hold the City harmless from all claims without limitation.",
        "The contract shall be governed by the laws of the State of Testland.",
    ]),
]


def responder(messages: list[dict]) -> str:
    system, user = messages[0]["content"], messages[-1]["content"]
    if "extract key facts" in system:
        fields = [ln.split(":")[0].strip("- ").strip() for ln in user.split("Fields to extract:")[-1].splitlines() if ln.startswith("- ")]
        values = {"title": "Records management system", "rfp_number": "TV-2026-01", "issuer": "City of Testville",
                  "submission_deadline": "March 3, 2026 at 2pm", "questions_deadline": "February 10, 2026"}
        return json.dumps({f: {"value": values.get(f), "source": 1} for f in fields})
    if "evaluation criteria" in system:
        return json.dumps({"criteria": [{"criterion": "Technical approach", "weight": "60", "stage": None, "source": 1}]})
    if "extract the requirements" in system:
        reqs = []
        if "continental United States" in user:
            reqs += [{"requirement": "Contractor must host all City data within the continental United States.", "category": "security", "mandatory": True, "source": 1},
                     {"requirement": "Contractor must host all City data within the continental United States!", "category": "security", "mandatory": True, "source": 1},
                     {"requirement": "Proposals must remain valid for 180 calendar days.", "category": "commercial", "mandatory": True, "source": 1},
                     {"requirement": "Proposers must submit one hard copy original.", "category": "submission", "mandatory": True, "source": 1}]
        if "indemnify" in user:
            reqs.append({"requirement": "Vendor must indemnify the City without limitation.", "category": "legal", "mandatory": True, "source": 1})
        return json.dumps({"requirements": reqs})
    if "compliance analyst" in system:
        req = user.split("RFP requirement:")[-1]
        status = "met" if "continental" in req else "gap" if ("180" in req or "indemnify" in req) else "unknown"
        return json.dumps({"status": status, "evidence": f"KB says so ({status}).", "sources": [1], "confidence": 0.9})
    if "double-check one candidate bid risk" in system:
        keep = "Data location" not in user  # the verifier rejects the false alarm below
        return json.dumps({"keep": keep, "reason": "GovCloud is in the continental US" if not keep else "real conflict"})
    if "risk analyst" in system:
        if "Hosting" in user:
            return json.dumps({"risks": [{"title": "Data location conflict", "category": "compliance", "severity": "high",
                                          "description": "RFP needs continental US hosting; we use AWS GovCloud.",
                                          "recommendation": "Clarify.", "rfp_source": "R1", "kb_sources": ["K1"]}]})
        if "Liability" in user:
            return json.dumps({"risks": [{"title": "Uncapped indemnification", "category": "legal", "severity": "high",
                                          "description": "RFP requires indemnity without limitation; our cap is 12 months of fees.",
                                          "recommendation": "Take an exception.", "rfp_source": "R1", "kb_sources": ["K1"]}]})
        return json.dumps({"risks": []})
    if "Exceptions, Assumptions" in system:
        return "We propose the following exceptions:\n1. Indemnification (RFP p. 3): we offer a liability cap."
    if "one section of a professional proposal" in system:
        return "We host all data in the continental United States [K1]. The City needs secure records management [R1]."
    return "Answer [1]."


@pytest.fixture(scope="module")
def rfp(seeded, tmp_path_factory):
    from app.ingest.pipeline import ingest_document, register_document

    d = tmp_path_factory.mktemp("rfp")
    pdf = make_pdf(d / "testville_rfp.pdf", RFP_TEXT)
    kb = d / "kb_terms.docx"
    doc = DocxDocument()
    doc.add_heading("Standard Commercial Terms", level=0)
    doc.add_heading("Hosting", level=1)
    doc.add_paragraph("All customer data is hosted in AWS GovCloud within the continental United States and backed up daily.")
    doc.add_heading("Liability", level=1)
    doc.add_paragraph("Our total liability is limited to the fees paid in the prior 12 months. Proposals are valid for 90 days.")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Certification", "Status"
    table.rows[1].cells[0].text, table.rows[1].cells[1].text = "ISO 27001", "Certified"
    doc.save(kb)
    rid = register_document(pdf, "tenders", "Testville Records RFP")
    kid = register_document(kb, "knowledge-base")
    assert ingest_document(rid).status == "ready"
    assert ingest_document(kid).status == "ready"
    return {"rfp": rid, "kb": kid}


@pytest.fixture()
def fake():
    set_llm(FakeLLM(responder))
    yield
    set_llm(None)


def test_docx_ingestion_parts_titles_and_tables(rfp):
    from app.db import Chunk, Document, session

    with session() as db:
        d = db.get(Document, rfp["kb"])
        chunks = db.query(Chunk).filter(Chunk.doc_id == rfp["kb"]).all()
    assert d.file_type == "docx" and d.title == "Standard Commercial Terms" and d.pages >= 1
    assert d.tables == 1 and any(c.kind == "table" and "ISO 27001" in c.text for c in chunks)
    assert any("Liability" in c.section for c in chunks)


def test_requirement_helpers():
    from app.rfp.requirements import OBLIGATION, is_duplicate, _tokens

    assert OBLIGATION.search("The vendor shall provide training") and not OBLIGATION.search("The county has 92 users.")
    seen = [_tokens("Contractor must host all data within the continental United States")]
    assert is_duplicate("Contractor must host all data within the continental United States!", seen)
    assert not is_duplicate("Proposals must remain valid for 180 days", seen)


def test_full_analysis_pipeline(rfp, fake):
    from app.db import Requirement, Risk, session
    from app.rfp.pipeline import analyze

    a = analyze(rfp["rfp"])
    assert a.status == "done", a.error
    assert a.facts["rfp_number"]["value"] == "TV-2026-01" and a.facts["submission_deadline"]["page"] == 1
    assert a.evaluation_criteria[0]["weight"] == "60"
    with session() as db:
        reqs = db.query(Requirement).filter(Requirement.doc_id == rfp["rfp"]).all()
        risks = db.query(Risk).filter(Risk.doc_id == rfp["rfp"]).all()
    texts = [r.text for r in reqs]
    assert sum("continental" in t for t in texts) == 1, "near-duplicate requirement was not removed"
    by = {r.text.split()[0] + r.category: r for r in reqs}
    hosting = next(r for r in reqs if "continental" in r.text)
    assert hosting.status == "met" and hosting.kb_sources and hosting.kb_sources[0]["file_type"] == "docx"
    assert next(r for r in reqs if "hard copy" in r.text).status == "action"  # submission instruction → checklist
    assert next(r for r in reqs if "indemnify" in r.text).kind == "capability"
    assert [r.ref for r in reqs] == [f"R-{i:03d}" for i in range(1, len(reqs) + 1)]
    assert len(risks) == 1 and risks[0].severity == "high" and risks[0].page >= 1
    assert risks[0].title == "Uncapped indemnification", "the verifier should have dropped the false data-location risk"
    s = a.bid_score
    assert s["counts"]["met"] == 1 and s["counts"]["gap"] == 2 and s["high_risks"] == 1
    assert s["recommendation"] in ("Bid", "Bid with conditions", "No bid") and 0 <= s["score"] <= 100
    assert set(a.timings) >= {"facts", "requirements", "compliance", "risks", "total"} and a.llm_calls > 0
    assert by  # noqa: B018


def test_bid_score_formula(rfp, fake):
    from app.rfp.risks import bid_score

    s = bid_score(rfp["rfp"], [{"severity": "high"}, {"severity": "medium"}])
    # mandatory capability reqs: met 1, gap 2 -> compliance 33.3; exposure 11 -> 0.7*33.3 + 0.3*89
    assert s["risk_exposure"] == 11 and abs(s["score"] - round(0.7 * 100 / 3 + 0.3 * 89, 1)) < 0.11


def test_proposal_generation_and_docx_export(rfp, fake):
    from docx import Document as Read

    from app.rfp.proposal import SECTIONS, start
    from app.db import ProposalDraft, session
    import time

    p = start(rfp["rfp"])
    for _ in range(100):
        with session() as db:
            p = db.get(ProposalDraft, p.id)
        if p.status != "running":
            break
        time.sleep(0.05)
    assert p.status == "done", p.error
    assert [s["key"] for s in p.sections] == [k for k, *_ in SECTIONS]
    first = p.sections[0]
    assert {c["label"] for c in first["citations"]} == {"K1", "R1"}
    doc = Read(p.docx_path)
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "Executive Summary" in text and "Appendix A - Compliance Matrix" in text and len(doc.tables) == 2
    assert any("R-001" in c.text for c in doc.tables[0].columns[0].cells)


def test_tender_api_flow(client, rfp, fake):
    h = auth("bid-manager")
    tenders = client.get("/api/tenders", headers=h).json()
    t = next(x for x in tenders if x["document"]["id"] == rfp["rfp"])
    assert t["analysis"]["status"] == "done" and t["requirements"] >= 3 and t["high_risks"] == 1
    reqs = client.get(f"/api/tenders/{rfp['rfp']}/requirements?status=gap", headers=h).json()
    assert reqs and all(r["status"] == "gap" for r in reqs)
    r = client.patch(f"/api/requirements/{reqs[0]['id']}", headers=h, json={"status": "partial", "owner_note": "negotiable"})
    assert r.status_code == 200 and r.json()["status"] == "partial" and "manually" in r.json()["evidence"]
    assert client.patch(f"/api/requirements/{reqs[0]['id']}", headers=h, json={"status": "bogus"}).status_code == 422
    risks = client.get(f"/api/tenders/{rfp['rfp']}/risks", headers=h).json()
    assert risks[0]["severity"] == "high"
    prop = client.get(f"/api/tenders/{rfp['rfp']}/proposal", headers=h).json()
    assert prop["status"] == "done"
    dl = client.get(f"/api/proposals/{prop['id']}/docx?token=demo-bid-manager")
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    # a knowledge-base document is not a tender
    assert client.get(f"/api/tenders/{rfp['kb']}", headers=h).status_code == 404


def test_rbac_reviewer_cannot_use_knowledge_base(client, rfp):
    h = auth("reviewer")  # legal reviewer: tenders only
    assert client.get(f"/api/tenders/{rfp['rfp']}", headers=h).status_code == 200
    assert client.post(f"/api/tenders/{rfp['rfp']}/proposal", headers=h).status_code == 403
    assert client.get(f"/api/documents/{rfp['kb']}/chunks", headers=h).status_code == 404
    assert client.get("/api/tenders", headers=auth("kbuser")).status_code == 403


def test_tender_scoped_chat_uses_rfp_and_kb_only(client, rfp, seeded):
    set_llm(FakeLLM(lambda m: "Data stays in the continental United States [1]."))
    try:
        body = client.post("/api/chat", headers=auth("bid-manager"),
                           json={"question": "Where must data be hosted?", "tender_id": rfp["rfp"]}).json()
    finally:
        set_llm(None)
    assert body["sources"] and {s["doc_id"] for s in body["sources"]} <= {rfp["rfp"], rfp["kb"], seeded["sec"]}
    assert seeded["ai"] not in {s["doc_id"] for s in body["sources"]}


def test_upload_rejects_wrong_types(client):
    h = auth("bid-manager")
    r = client.post("/api/documents", headers=h, data={"workspace": "tenders"}, files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    r = client.post("/api/documents", headers=h, data={"workspace": "tenders"}, files={"file": ("x.docx", b"not a zip", "application/octet-stream")})
    assert r.status_code == 400


def test_docx_page_image_is_refused(client, rfp):
    r = client.get(f"/api/documents/{rfp['kb']}/pages/1.png?token=demo-bid-manager")
    assert r.status_code == 415


def test_answer_key_shape():
    gold = json.loads((Path(__file__).resolve().parents[1] / "backend" / "eval" / "gold_rfp.json").read_text(encoding="utf-8"))
    req_ids = {i["id"] for i in gold["requirements"]["items"]}
    assert len(req_ids) == len(gold["requirements"]["items"]) == 30
    assert {c["id"] for c in gold["compliance"]["items"]} <= req_ids
    assert all(set(c["expected"]) <= {"met", "partial", "gap", "unknown"} for c in gold["compliance"]["items"])
    assert len(gold["qa"]) == 15 and sum(q["reference"] == "NOT_FOUND" for q in gold["qa"]) == 1
