"""Record the demo video of the real running app (start it with run_demo.bat and analyse the RFPs first).

    python demo/record_demo.py        → demo/demo.mp4, demo/demo.gif, demo/screenshots/*.png

Uses the shared recorder (Playwright video + ffmpeg) in ../_shared/record_demo.py. Everything shown is the live app:
real public RFPs, real analysis results stored by the local LLM, a live Q&A call.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "_shared"))
from record_demo import record  # noqa: E402

WEB = "http://localhost:3200"
SHOTS = HERE / "screenshots"
TENDER = 1  # Champaign County CCMS RFP


async def shot(page, name: str) -> None:
    await page.screenshot(path=str(SHOTS / f"{name}.png"))


async def steps(page, caption) -> None:
    SHOTS.mkdir(exist_ok=True)
    await page.goto(WEB)
    await page.evaluate("localStorage.clear()")
    await page.goto(WEB)
    await caption("DMS RFP Intelligence: GenAI tender analysis that runs on a local LLM")
    await page.wait_for_selector("[data-testid=login-bid-manager]")
    await page.wait_for_timeout(2500)
    await page.click("[data-testid=login-bid-manager]")
    await page.wait_for_selector("[data-testid=tender-list] [data-testid=bid-score]")
    await caption("Tender pipeline: 3 real public government RFPs, each analysed end to end", 4500)
    await shot(page, "01_tenders")

    await page.click(f"[data-testid=tender-{TENDER}] a")
    await page.wait_for_selector("[data-testid=key-facts]")
    await caption("Bid / no-bid score + key facts extracted from a 30-page RFP", 4000)
    await shot(page, "02_overview")
    await caption("Every fact is source-grounded: click a page to see the exact highlighted passage")
    await page.locator("[data-testid=key-facts] [data-testid=page-link]").first.click()
    await page.wait_for_selector("[data-testid=page-image]")
    await page.wait_for_timeout(4000)
    await page.mouse.wheel(0, 650)
    await caption("Evaluation criteria and timing, measured on an RTX 4060 laptop GPU", 3500)
    await page.mouse.wheel(0, -2000)

    await page.click("[data-testid=tab-requirements]")
    await page.wait_for_selector("[data-testid=req-table]")
    await caption("Requirement extraction: every bidder obligation, categorised, with its RFP page", 4000)
    await shot(page, "03_requirements")
    await page.select_option("[data-testid=status-filter]", "gap")
    await caption("Compliance vs the company knowledge base: gaps found automatically, with evidence", 3500)
    links = page.locator("[data-testid=req-table] tr").nth(1).locator("[data-testid=page-link]")
    if await links.count() > 1:
        await links.nth(1).click()
        await caption("Evidence comes from the organisation's own documents (Word + PDF)", 4000)
    await shot(page, "04_compliance_gaps")

    await page.click("[data-testid=tab-risks]")
    await page.wait_for_selector("[data-testid=risk-list]")
    await caption("Risk & gap detection: RFP clauses compared with our standard terms", 4500)
    await shot(page, "05_risks")

    await page.click("[data-testid=tab-proposal]")
    await page.wait_for_selector("[data-testid=proposal-section]")
    await caption("Automated proposal response, drafted from the reusable knowledge base", 3500)
    await caption("K = knowledge-base citation, R = RFP citation, yellow = needs the bid team's input", 4000)
    await page.mouse.wheel(0, 700)
    await page.wait_for_timeout(1500)
    await caption("Exports to Word with a compliance matrix and risk register appended", 3000)
    await shot(page, "06_proposal")
    await page.mouse.wheel(0, -3000)

    await page.click("[data-testid=tab-ask]")
    await page.fill("[data-testid=ask-input]", "Where must County data be stored, and do we comply?")
    await caption("Ask anything: RAG over the RFP + knowledge base (hybrid search + reranker)")
    await page.click("[data-testid=ask-send]")
    await page.wait_for_selector("[data-testid=ask-answer]", timeout=240_000)
    await caption("Grounded answer with page-level citations, generated locally", 4500)
    await shot(page, "07_ask")

    await page.goto(f"{WEB}/evaluation")
    await page.wait_for_selector("[data-testid=eval-metric]")
    await caption("Measured accuracy against a hand-labelled answer key, nothing estimated", 5000)
    await shot(page, "08_evaluation")
    await page.goto(f"{WEB}/knowledge")
    await page.wait_for_selector("[data-testid=doc-table]")
    await caption("Knowledge base: company profile, policies, past performance (PDF + DOCX)", 3500)
    await caption("")


if __name__ == "__main__":
    record(steps, out_dir=HERE, title="DMS RFP Intelligence System",
           subtitle="GenAI-powered RFP / tender intelligence · RAG · local LLM")
