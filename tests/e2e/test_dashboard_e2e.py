"""End-to-end test of the real running app (API :8200 + dashboard :3200 + Ollama), driven by Playwright.

Start the app first (run_demo.bat) and analyse the Champaign County RFP, then:
    python -m pytest tests/e2e -q -p no:cacheprovider
Skipped automatically when the app is not running.
"""
from __future__ import annotations

import os
import urllib.request

import pytest

WEB = os.environ.get("RFP_WEB", "http://localhost:3200")
API = os.environ.get("RFP_API", "http://localhost:8200")


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not (_up(WEB) and _up(f"{API}/api/health")), reason="app is not running on :3200/:8200")


def test_tender_analysis_flow():
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(WEB)
        page.evaluate("localStorage.clear()")
        page.reload()

        page.get_by_test_id("login-bid-manager").click()
        expect(page.get_by_test_id("current-user")).to_contain_text("Bid Manager")
        expect(page.get_by_test_id("tender-list")).to_contain_text("Champaign County")

        page.locator("[data-testid=tender-1] a").first.click()
        expect(page.get_by_test_id("key-facts")).to_contain_text("2025")
        expect(page.get_by_test_id("bid-score")).to_be_visible()
        page.get_by_test_id("key-facts").get_by_test_id("page-link").first.click()
        expect(page.get_by_test_id("page-image")).to_be_visible()

        page.get_by_test_id("tab-requirements").click()
        rows = page.locator("[data-testid=req-table] tbody tr")
        expect(rows.first).to_be_visible()
        assert rows.count() >= 30
        page.get_by_test_id("status-filter").select_option("gap")
        expect(page.locator("[data-testid=req-table] [data-testid=status-gap]").first).to_be_visible()

        page.get_by_test_id("tab-risks").click()
        expect(page.get_by_test_id("risk-list")).to_contain_text("ndemnif")

        page.get_by_test_id("tab-ask").click()
        page.get_by_test_id("ask-input").fill("How long must proposals remain valid?")
        page.get_by_test_id("ask-send").click()
        answer = page.get_by_test_id("ask-answer")
        expect(answer).to_contain_text("180", timeout=240_000)
        expect(answer.get_by_test_id("citation").first).to_be_visible()

        # RBAC: the legal reviewer sees tenders but cannot draft proposals (no knowledge-base access)
        page.goto(WEB)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.get_by_test_id("login-reviewer").click()
        page.locator("[data-testid=tender-1] a").first.click()
        page.get_by_test_id("tab-proposal").click()
        expect(page.get_by_test_id("generate-proposal")).to_be_disabled()
        browser.close()
