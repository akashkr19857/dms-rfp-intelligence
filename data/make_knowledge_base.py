"""Generate the demo organisational knowledge base: a FICTIONAL vendor, "Nimbus JusticeTech Solutions, Inc.".

The documents are written so that, against the real public Champaign County CCMS RFP, the vendor clearly meets some
requirements, partly meets others and has real gaps (e.g. no jury module, 90-day offer validity vs 180 required,
30-day data return vs 15, liability cap vs uncapped indemnification). This gives the compliance and risk analysis
known ground truth (see backend/eval/gold_rfp.json).

    python data/make_knowledge_base.py      # writes data/knowledge_base/*.docx|*.pdf
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
from docx import Document
from docx.shared import Pt

OUT = Path(__file__).resolve().parent / "knowledge_base"
NOTICE = ("FICTIONAL SAMPLE COMPANY - created for the DMS RFP Intelligence demo. Nimbus JusticeTech Solutions, its products, "
          "customers and staff are invented. Not a real vendor.")

# Each document: (filename, title, [(heading, [paragraphs or ("table", rows)])])
DOCS: list[tuple[str, str, list[tuple[str, list]]]] = [
    ("01_Company_Profile.docx", "Nimbus JusticeTech Solutions - Company Profile", [
        ("Company Overview", [
            "Nimbus JusticeTech Solutions, Inc. was founded in 2011 and is headquartered in Columbus, Ohio, USA. The company has "
            "140 employees, of whom 62 work in implementation and customer success. Nimbus is privately held and profitable, with "
            "annual revenue of approximately US$31 million in fiscal year 2025.",
            "Nimbus builds NimbusCourt, a court case management system (CCMS) used by 23 state and county courts in 9 US states. "
            "Our customers range from single-judge municipal courts to county circuit courts with 150 users.",
            "Nimbus has delivered 31 court software implementations since 2012, including 6 replacements of IBM iSeries (AS400) "
            "based legacy court systems.",
        ]),
        ("Products and Modules", [
            "NimbusCourt includes the following modules: Case Management, Calendar and Scheduling, Document Management, Judicial "
            "Tools (judge dashboard and bench view), Public Portal, Reporting (ad hoc, statistical and scheduled reports), "
            "Financials (fees, fines, bonds, restitution, trust accounting) and Probation (supervision, risk assessment, "
            "appointment reminders by text message).",
            "NimbusCourt does NOT include a jury management module. For courts that require jury management, Nimbus partners with "
            "JuryWorks LLC (fictional), whose jury system is integrated with NimbusCourt through a certified interface. In a joint "
            "proposal Nimbus acts as Prime Vendor and JuryWorks as subcontractor.",
            "NimbusCourt maintains a central master person index, so one person can be linked across cases, aliases and "
            "identifiers (driver licence, state ID, booking number).",
        ]),
        ("Deployment Models", [
            "NimbusCourt is offered as Software as a Service (SaaS, annual subscription) hosted on AWS GovCloud (US-East and "
            "US-West regions). All customer data is stored and processed only within the continental United States.",
            "NimbusCourt is also available for on-premise deployment at the customer site with perpetual licences and annual "
            "maintenance. Nimbus does not offer a vendor-hosted perpetual licence model.",
        ]),
        ("Integrations", [
            "NimbusCourt has a production bidirectional integration with Tyler Technologies Odyssey eFile and Serve, live at 4 courts.",
            "Payment processing is integrated with Paymentus and Authorize.net. An integration with PayIt does not exist yet; Nimbus "
            "estimates 6 to 8 weeks of development for a new payment processor integration.",
            "Integrations with computer-aided dispatch (CAD) systems, including Tyler Enterprise CAD, are delivered through the "
            "NimbusCourt REST API as custom interface work.",
            "Document barcode scanning is supported through TWAIN and Kofax capture. Microsoft Access reports are typically replaced "
            "by the built-in NimbusCourt report designer.",
        ]),
        ("Licensing and Users", [
            "NimbusCourt is licensed per named user. Public portal users (attorneys, members of the public) are not licensed and are "
            "unlimited.",
        ]),
    ]),
    ("02_Security_Hosting_and_DR.docx", "Security, Hosting and Disaster Recovery Policy", [
        ("Certifications and Compliance", [
            "Nimbus holds a SOC 2 Type II report, renewed annually (latest report period ending March 2025), and ISO/IEC 27001:2022 "
            "certification for its SaaS operations. NimbusCourt SaaS is operated in line with the FBI CJIS Security Policy, and all "
            "Nimbus staff with access to customer data complete CJIS security awareness training and fingerprint-based background checks.",
        ]),
        ("Hosting Location", [
            "SaaS production runs on AWS GovCloud US-East, with disaster recovery in AWS GovCloud US-West. Customer data never leaves "
            "the continental United States.",
        ]),
        ("Data Protection", [
            "Data is encrypted at rest with AES-256 and in transit with TLS 1.2 or higher. Access uses single sign-on (SAML 2.0 / "
            "Azure AD) with multi-factor authentication, and role-based security down to field level. All access is audit-logged "
            "and logs are kept for 7 years.",
        ]),
        ("Backup and Disaster Recovery", [
            "Nimbus maintains a documented disaster recovery plan that is tested twice a year. Recovery point objective (RPO) is "
            "1 hour and recovery time objective (RTO) is 4 hours.",
            "All customer data is backed up daily, and backups are replicated to a separate, hardened offsite facility (AWS GovCloud "
            "US-West) and kept for 35 days.",
        ]),
        ("Service Levels", [
            "The SaaS service level is 99.9% monthly availability, excluding scheduled maintenance announced 7 days in advance. "
            "Priority 1 incidents are supported 24x7 with a 1-hour response time.",
        ]),
    ]),
    ("04_Implementation_Methodology.docx", "NimbusCourt Implementation Methodology", [
        ("Approach", [
            "Nimbus implements NimbusCourt with a phased methodology: Initiate, Discover and Design, Configure, Convert and Integrate, "
            "Test, Train, Go-Live and Stabilise. Business process reviews in Discover and Design use Lean Six Sigma techniques to "
            "simplify and standardise court processes before configuration.",
            "A typical full CCMS implementation for a court with 90 to 150 users takes 14 to 18 months from kickoff to go-live of all "
            "modules. The fastest Nimbus implementation of a comparable scope took 13 months.",
        ]),
        ("Project Management Deliverables", [
            "Every Nimbus project delivers a Project Management Plan (objectives, deliverables and milestones, schedule, resource, "
            "scope and schedule management, risk management, quality management, communication management, organisational change "
            "management and status reporting), a Data Conversion Plan, a Training Plan, a System Interface Plan, a Testing and "
            "Quality Assurance Plan, a Pre- and Post-Implementation Support Plan, system documentation and a Risk Register.",
        ]),
        ("Customer Resource Commitment", [
            "Nimbus estimates customer effort at about 0.5 FTE per functional area during configuration and testing, plus a part-time "
            "customer project manager (about 50%). Nimbus provides resource-hour estimates by phase in every proposal.",
        ]),
        ("Data Conversion and Legacy Archive", [
            "Nimbus has converted data from IBM iSeries (AS400) DB2 court systems six times. Legacy cases are classified by status and "
            "age: active and recently closed cases are fully migrated; older closed cases are moved to the read-only NimbusCourt "
            "Legacy Archive, which is fully searchable, linked to the person index and can be reactivated into a live case in one "
            "workflow step.",
        ]),
        ("Testing and Training", [
            "Testing includes unit, integration, data conversion validation, user acceptance and parallel testing. Training uses a "
            "train-the-trainer model plus role-based end-user sessions and an online learning library.",
        ]),
        ("Ongoing Support and Upgrades", [
            "Customers with an active SaaS subscription or maintenance agreement receive all new versions and upgrades of NimbusCourt "
            "at no additional cost. Nimbus holds quarterly business reviews with every customer covering service levels, support "
            "tickets, delivery performance and roadmap.",
        ]),
    ]),
    ("05_Key_Personnel.docx", "Key Proposed Personnel (standard bid team)", [
        ("Project Manager - Sarah Thompson (fictional)", [
            "PMP certified, 14 years of experience, has managed 9 court case management implementations, including 2 AS400 "
            "replacements for county circuit courts.",
        ]),
        ("Solution Architect - Daniel Okafor (fictional)", [
            "12 years of experience designing court and justice integrations, including Odyssey eFile and CAD interfaces.",
        ]),
        ("Data Conversion Lead - Priya Raman (fictional)", [
            "10 years of experience in legacy data migration, specialised in IBM DB2/400 and RPG systems; led 5 court conversions.",
        ]),
        ("Business Process and Training Lead - Mark Ellis (fictional)", [
            "Lean Six Sigma Black Belt with 8 years of court business process optimisation and training experience.",
        ]),
        ("Personnel Replacement", [
            "If a customer finds any Nimbus team member unsuitable, Nimbus replaces that person with an equally qualified resource "
            "within 10 business days at no cost to the customer.",
        ]),
    ]),
    ("06_Standard_Commercial_Terms.docx", "Standard Commercial Terms and Bid Policies", [
        ("Proposal Validity", [
            "Nimbus proposals are valid for 90 days from the submission date unless the bid team obtains written approval from the "
            "CFO for a longer validity period.",
        ]),
        ("Limitation of Liability and Indemnification", [
            "Nimbus's total liability under any agreement is limited to the fees paid by the customer in the 12 months before the "
            "claim. Nimbus indemnifies customers against third-party intellectual property infringement claims. Uncapped "
            "indemnification for other matters requires legal review and executive approval.",
        ]),
        ("Data Ownership and Return", [
            "Customer data always belongs to the customer. On termination or expiry, Nimbus provides a full export of customer data "
            "in CSV and JSON formats within 30 days of the request, at no cost, and assists with migration to another vendor at "
            "standard hourly rates.",
        ]),
        ("Records Retention and Audit", [
            "Nimbus keeps project and billing records for 7 years after final payment and allows customer audits with 30 days notice.",
        ]),
        ("Insurance", [
            "Nimbus carries commercial general liability insurance of US$2 million per occurrence, professional liability (errors and "
            "omissions) of US$5 million and cyber liability of US$5 million.",
        ]),
        ("Governing Law", [
            "Nimbus standard contracts are governed by the laws of the State of Ohio. Nimbus has accepted the customer's state law "
            "and venue in 18 of 23 public sector contracts.",
        ]),
        ("Travel and Expenses", [
            "Travel and expenses are billed at actual cost following US GSA per diem rates, with no mark-up.",
        ]),
        ("Warranty and Escrow", [
            "NimbusCourt carries a 12-month warranty after go-live. For on-premise customers, source code is held in escrow with "
            "NCC Group.",
        ]),
    ]),
]

PDFS: list[tuple[str, str, list[tuple[str, list[str]]]]] = [
    ("03_Past_Performance_and_References.pdf", "Past Performance and References", [
        ("Reference 1 - Riverbend County Circuit Court, Ohio (fictional)", [
            "Scope: full NimbusCourt CCMS (case management, calendar, document management, judicial tools, portal, reporting, "
            "financials, probation) for 118 users. Replaced an IBM AS400 system running a DB2 database. Kickoff March 2021, go-live "
            "June 2022 (15 months). 4.1 million docket entries converted; cases closed before 2010 moved to the Legacy Archive.",
            "Contact: Court Administrator, Riverbend County (fictional contact details available on request).",
        ]),
        ("Reference 2 - Lakeshore County Courts, Michigan (fictional)", [
            "Scope: NimbusCourt SaaS for circuit and district courts, 96 users, with Odyssey eFile and Serve integration and jury "
            "management delivered with partner JuryWorks. Kickoff January 2023, go-live May 2024 (16 months).",
        ]),
        ("Reference 3 - Prairie Hills Judicial District, Kansas (fictional)", [
            "Scope: NimbusCourt Probation and Case Management for 64 users, including text-message appointment reminders and a "
            "public portal. Kickoff September 2023, go-live October 2024 (13 months).",
        ]),
    ]),
    ("07_NimbusCourt_Product_Capabilities.pdf", "NimbusCourt Product Capabilities Overview", [
        ("Reporting", [
            "NimbusCourt Reporting provides an ad hoc report designer, more than 300 standard statistical reports, and configurable "
            "scheduled reports delivered by email. Daily court calendars can be printed or published to the public portal.",
        ]),
        ("Judicial Tools", [
            "The judge dashboard shows the daily docket, case summaries, pending motions and orders to sign, with e-signature of orders "
            "on the bench.",
        ]),
        ("Search", [
            "Global search covers parties, cases, documents (full-text OCR) and financial records, with saved filters per user.",
        ]),
        ("User Experience", [
            "NimbusCourt uses role-based workspaces so every clerk, judge and probation officer performs a function the same way, "
            "with guided workflows for new users.",
        ]),
    ]),
]


def write_docx(path: Path, title: str, sections: list[tuple[str, list]]) -> None:
    doc = Document()
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(title, level=0)
    p = doc.add_paragraph(NOTICE)
    p.runs[0].italic = True
    for heading, paras in sections:
        doc.add_heading(heading, level=1)
        for para in paras:
            doc.add_paragraph(para)
    doc.save(path)


def write_pdf(path: Path, title: str, sections: list[tuple[str, list[str]]]) -> None:
    html = [f"<h1>{title}</h1><p><i>{NOTICE}</i></p>"]
    for heading, paras in sections:
        html.append(f"<h2>{heading}</h2>" + "".join(f"<p>{p}</p>" for p in paras))
    story = pymupdf.Story(html="".join(html), user_css="body{font-family:sans-serif;font-size:11pt} h1{font-size:20pt} h2{font-size:14pt;margin-top:14pt}")
    writer = pymupdf.DocumentWriter(str(path))
    mediabox = pymupdf.paper_rect("letter")
    where = mediabox + (54, 54, -54, -54)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    with pymupdf.open(path) as d:  # set the title metadata so ingestion shows a clean name
        d.set_metadata({"title": title, "author": "Nimbus JusticeTech Solutions (fictional)"})
        d.saveIncr()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, title, sections in DOCS:
        write_docx(OUT / name, title, sections)
    for name, title, sections in PDFS:
        write_pdf(OUT / name, title, sections)
    print(f"wrote {len(DOCS) + len(PDFS)} knowledge-base documents to {OUT}")


if __name__ == "__main__":
    main()
