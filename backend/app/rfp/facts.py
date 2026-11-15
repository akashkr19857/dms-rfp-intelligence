"""Key-fact extraction: targeted retrieval inside one RFP, then a JSON-mode LLM call per field group.
Every value keeps the page (and chunk) it came from, so the UI can show the exact source."""
from __future__ import annotations

import re

from .common import CallCounter, llm_json, numbered, pick, search_rfp

FIELD_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("request for proposals title solicitation number issuing agency introduction purpose", [
        ("title", "Title of the solicitation / what is being procured"),
        ("rfp_number", "Explicit solicitation/RFP/bid number exactly as printed, e.g. 'RFP No. 184578-2'. Never the title. null if no number is printed"),
        ("issuer", "Organisation issuing the RFP"),
    ]),
    ("schedule of events proposal due date deadline time questions deadline pre-proposal conference", [
        ("submission_deadline", "Date and time proposals are due"),
        ("questions_deadline", "Deadline for questions from vendors"),
        ("pre_proposal_meeting", "Pre-proposal meeting / conference: date, time, mandatory or not"),
    ]),
    ("questions inquiries contact email submit proposals mailing address delivery hard copy electronic", [
        ("contact", "Person or office to contact with questions, with email"),
        ("submission_method", "How proposals must be submitted (hard copy, electronic, portal, email) and where"),
    ]),
    ("budget contract term duration offer held firm proposal valid days payment terms contract type", [
        ("budget", "Budget or estimated contract value (null if not stated)"),
        ("contract_term", "Contract type / term / duration"),
        ("proposal_validity", "How long proposals must remain valid"),
    ]),
    ("project scope objectives functional areas implementation go-live target date timeline", [
        ("scope_summary", "One-sentence summary of the scope of work"),
        ("target_go_live", "Target start / go-live / completion dates"),
    ]),
    ("deployment model preference software as a service SaaS on premise hosted hosting location", [
        ("deployment_model", "Required or preferred deployment / hosting model, including any hosting-location requirement"),
    ]),
]

FACTS_SYSTEM = """You extract key facts from excerpts of a public RFP (request for proposals) document.
Use ONLY the numbered excerpts. For each requested field return a short value (max 30 words, keep exact dates, times,
numbers and names) and the number of the excerpt it came from. If the excerpts do not state the field, use null.
Reply as JSON: {"<field>": {"value": "<text or null>", "source": <excerpt number or null>}, ...}"""

CRITERIA_SYSTEM = """You extract the proposal evaluation criteria from excerpts of an RFP.
Use ONLY the excerpts. List each scored criterion with its points or weight exactly as written (null if not given).
Reply as JSON: {"criteria": [{"criterion": "...", "weight": "<points or % or null>", "stage": "<e.g. short-list, finalist, cost, or null>", "source": <excerpt number>}]}"""


def best_support(value: str, hits):  # noqa: ANN001, ANN201
    """When the model omits the source number, cite the excerpt that shares the most words with the value."""
    words = {w for w in re.findall(r"[a-z0-9]+", value.lower()) if len(w) > 2}
    scored = [(len(words & set(re.findall(r"[a-z0-9]+", h.text.lower()))), h) for h in hits]
    best = max(scored, key=lambda t: t[0], default=(0, None))
    return best[1] if best[0] >= max(1, len(words) // 3) else None


def extract_facts(doc_id: int, counter: CallCounter | None = None) -> dict[str, dict]:
    facts: dict[str, dict] = {}
    for query, fields in FIELD_GROUPS:
        hits = search_rfp(query, doc_id, k=5)
        if not hits:
            continue
        spec = "\n".join(f"- {name}: {desc}" for name, desc in fields)
        data = llm_json(FACTS_SYSTEM, f"Excerpts:\n\n{numbered(hits)}\n\nFields to extract:\n{spec}", counter, max_tokens=500)
        for name, _ in fields:
            item = data.get(name)
            value = item.get("value") if isinstance(item, dict) else item
            if value in (None, "", "null", "None") or not isinstance(value, (str, int, float)):
                facts[name] = {"value": None, "page": None, "chunk_id": None}
                continue
            src = pick(hits, item.get("source") if isinstance(item, dict) else None)
            h = src[0] if src else best_support(str(value), hits)
            facts[name] = {"value": str(value).strip(), "page": h.page if h else None, "chunk_id": h.chunk_id if h else None}
    return facts


def extract_criteria(doc_id: int, counter: CallCounter | None = None) -> list[dict]:
    hits = search_rfp("evaluation criteria points weighting scoring award basis of selection", doc_id, k=6)
    if not hits:
        return []
    data = llm_json(CRITERIA_SYSTEM, f"Excerpts:\n\n{numbered(hits, max_chars=1400)}", counter, max_tokens=700)
    out: list[dict] = []
    seen: set[str] = set()
    for c in data.get("criteria", []) if isinstance(data.get("criteria"), list) else []:
        if not isinstance(c, dict) or not c.get("criterion"):
            continue
        name = str(c["criterion"]).strip()
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        src = pick(hits, c.get("source"))
        out.append({"criterion": name, "weight": None if c.get("weight") in (None, "null") else str(c.get("weight")),
                    "stage": c.get("stage") if c.get("stage") not in ("null", "") else None,
                    "page": src[0].page if src else None, "chunk_id": src[0].chunk_id if src else None})
    return out
