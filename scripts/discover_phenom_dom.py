#!/usr/bin/env python3
"""DOM discovery script for Snowflake (Phenom People ATS).

Navigates to the careers search page, waits for the SPA to render job cards,
identifies stable selectors, tests pagination, and saves artifacts.

Manual-only — not part of the test suite.
Usage: python scripts/discover_phenom_dom.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, ElementHandle

SEARCH_URL = "https://careers.snowflake.com/us/en/search"
OUT_DIR = Path("tests/fixtures/dom_discovery")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Selector candidates to probe (order: most specific → most generic)
JOB_CARD_CANDIDATES = [
    # Phenom People / Aurelia component names
    "ppc-job-card",
    "job-card",
    "ppc-job-list-item",
    # Common CSS class patterns
    "[class*='job-card']",
    "[class*='jobCard']",
    "[class*='job-list-item']",
    "[class*='JobListItem']",
    "[class*='position-card']",
    # data attributes
    "[data-ph-id]",
    "[data-job-id]",
    "[data-requisition-id]",
    # Generic list patterns
    "li[class*='job']",
    "article[class*='job']",
    "div[class*='job-result']",
    "[class*='search-result']",
]

TITLE_CANDIDATES = [
    "h2", "h3", "h4",
    "[class*='title']",
    "[class*='job-title']",
    "a[class*='title']",
]

LOCATION_CANDIDATES = [
    "[class*='location']",
    "[class*='city']",
    "[data-location]",
]

DEPT_CANDIDATES = [
    "[class*='department']",
    "[class*='category']",
    "[class*='dept']",
]

DATE_CANDIDATES = [
    "[class*='date']",
    "[class*='posted']",
    "time",
    "[datetime]",
]

NEXT_PAGE_CANDIDATES = [
    "button[aria-label*='Next']",
    "button[aria-label*='next']",
    "a[aria-label*='Next']",
    "[class*='pagination'] button:last-child",
    "[class*='pagination'] a:last-child",
    "button[class*='next']",
    "a[class*='next']",
    "[class*='next-page']",
    "button:has-text('Next')",
    "a:has-text('Next')",
    "[class*='load-more']",
    "button:has-text('Load more')",
    "button:has-text('Show more')",
]


def wait_for_jobs(page: Page, timeout: int = 30_000) -> str | None:
    """Try each card candidate; return first selector that yields results."""
    for sel in JOB_CARD_CANDIDATES:
        try:
            page.wait_for_selector(sel, timeout=3_000)
            count = page.locator(sel).count()
            if count > 0:
                return sel
        except Exception:
            pass
    return None


def extract_field(card: ElementHandle, candidates: list[str]) -> str:
    """Try each sub-selector within a card; return first non-empty text."""
    for sel in candidates:
        try:
            el = card.query_selector(sel)
            if el:
                text = (el.inner_text() or "").strip()
                if text:
                    return text
        except Exception:
            pass
    return ""


def extract_url(card: ElementHandle) -> str:
    """Find href from anchor tags within card."""
    try:
        anchors = card.query_selector_all("a")
        for a in anchors:
            href = a.get_attribute("href") or ""
            if href and ("/job/" in href or "/en/job" in href or "/position/" in href or href.startswith("http")):
                if href.startswith("/"):
                    href = f"https://careers.snowflake.com{href}"
                return href
    except Exception:
        pass
    return ""


def extract_cards(page: Page, card_selector: str) -> list[dict]:
    cards = page.query_selector_all(card_selector)
    jobs = []
    for card in cards:
        title = extract_field(card, TITLE_CANDIDATES)
        location = extract_field(card, LOCATION_CANDIDATES)
        dept = extract_field(card, DEPT_CANDIDATES)
        date = extract_field(card, DATE_CANDIDATES)
        url = extract_url(card)
        raw_html = card.inner_html()[:500]  # first 500 chars for selector debugging

        jobs.append({
            "title": title,
            "location": location,
            "department": dept,
            "posted_date": date,
            "url": url,
            "_raw_html_prefix": raw_html,
        })
    return jobs


def probe_selectors(page: Page, card_selector: str, label: str) -> dict:
    """For each field type, report which sub-selector works."""
    sample_card = page.query_selector(card_selector)
    if not sample_card:
        return {}
    result = {}
    for field_name, candidates in [
        ("title", TITLE_CANDIDATES),
        ("location", LOCATION_CANDIDATES),
        ("department", DEPT_CANDIDATES),
        ("date", DATE_CANDIDATES),
    ]:
        for sel in candidates:
            try:
                el = sample_card.query_selector(sel)
                if el:
                    text = (el.inner_text() or "").strip()
                    if text:
                        result[field_name] = {"selector": sel, "sample_text": text}
                        break
            except Exception:
                pass
    # URL
    url = extract_url(sample_card)
    if url:
        result["url"] = {"selector": "a[href]", "sample_value": url}
    return result


def test_pagination(page: Page, card_selector: str) -> dict:
    """Detect and test pagination/load-more controls."""
    info: dict = {
        "next_button_selector": None,
        "type": None,
        "pages_accessible": 1,
        "total_jobs_accessible": 0,
        "url_changes_on_next": False,
        "notes": [],
    }

    before_url = page.url
    before_count = page.locator(card_selector).count()
    info["total_jobs_accessible"] = before_count

    # Find pagination control
    next_sel = None
    for sel in NEXT_PAGE_CANDIDATES:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                next_sel = sel
                info["next_button_selector"] = sel
                info["type"] = "load_more" if "more" in sel.lower() or "show" in sel.lower() else "next_page"
                break
        except Exception:
            pass

    if not next_sel:
        info["notes"].append("No pagination control found — may be infinite scroll or all jobs on one page")
        # Check for infinite scroll by scrolling to bottom
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        after_count = page.locator(card_selector).count()
        if after_count > before_count:
            info["type"] = "infinite_scroll"
            info["total_jobs_accessible"] = after_count
            info["notes"].append(f"Infinite scroll: {before_count} → {after_count} jobs after scroll")
        return info

    # Try clicking Next / Load more (up to 5 pages max)
    all_jobs_seen = before_count
    for page_num in range(2, 7):
        try:
            el = page.locator(next_sel).first
            if not el.is_visible() or not el.is_enabled():
                info["notes"].append(f"Next button not clickable on page {page_num - 1}")
                break

            el.click()
            page.wait_for_load_state("networkidle", timeout=8_000)
            time.sleep(1)

            after_count = page.locator(card_selector).count()
            after_url = page.url
            info["url_changes_on_next"] = after_url != before_url
            before_url = after_url

            if after_count > all_jobs_seen:
                info["pages_accessible"] = page_num
                all_jobs_seen = after_count
                info["total_jobs_accessible"] = after_count
                info["notes"].append(f"Page {page_num}: {after_count} cards visible")
            else:
                info["notes"].append(f"Page {page_num}: card count unchanged ({after_count}) — likely last page")
                break
        except Exception as exc:
            info["notes"].append(f"Pagination click error on page {page_num}: {exc}")
            break

    return info


def main() -> None:
    print(f"[1/5] Launching Playwright and navigating to {SEARCH_URL} ...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30_000)

        # Wait for SPA hydration
        print("[2/5] Waiting for SPA to render job cards ...")
        page.wait_for_load_state("networkidle", timeout=20_000)
        time.sleep(3)  # extra settle time for Aurelia

        # Save initial HTML snapshot
        html = page.content()
        html_path = OUT_DIR / "snowflake_initial_render.html"
        html_path.write_text(html[:_DEBUG_HTML_MAX], encoding="utf-8")
        print(f"      Saved HTML snapshot: {html_path} ({len(html):,} bytes)")

        _DEBUG_HTML_MAX_LOCAL = 1_048_576

        # Probe card selectors
        print("[3/5] Probing job card selectors ...")
        working_selector = None
        selector_results = []
        for sel in JOB_CARD_CANDIDATES:
            try:
                count = page.locator(sel).count()
                if count > 0:
                    selector_results.append({"selector": sel, "count": count})
                    if working_selector is None:
                        working_selector = sel
                        print(f"      ✓ First working selector: '{sel}' → {count} cards")
            except Exception:
                pass

        if not working_selector:
            print("      ✗ No card selector matched — saving full HTML for inspection")
            print("      Check snowflake_initial_render.html for actual DOM structure")
            # Try to capture any visible text that looks like job listings
            body_text = page.inner_text("body")[:2000]
            print(f"\n--- Body text sample (first 2000 chars) ---\n{body_text}\n---")
            browser.close()
            return

        print(f"\n      All working selectors:")
        for r in selector_results:
            print(f"        '{r['selector']}': {r['count']} elements")

        # Field selector probing
        print("\n[4/5] Probing field selectors within job card ...")
        field_map = probe_selectors(page, working_selector, "field probe")
        print("      Field selector results:")
        for field_name, info in field_map.items():
            print(f"        {field_name}: selector='{info.get('selector', info.get('selector', ''))}', sample='{info.get('sample_text', info.get('sample_value', ''))[:80]}'")

        # Extract jobs from current page
        jobs_page1 = extract_cards(page, working_selector)
        print(f"\n      Extracted {len(jobs_page1)} jobs from page 1:")
        for j in jobs_page1[:3]:
            print(f"        title='{j['title'][:60]}', location='{j['location'][:40]}', url='{j['url'][:60]}'")

        # Pagination
        print("\n[5/5] Testing pagination ...")
        pagination_info = test_pagination(page, working_selector)
        print(f"      Type: {pagination_info['type']}")
        print(f"      Next button: {pagination_info['next_button_selector']}")
        print(f"      Pages accessible: {pagination_info['pages_accessible']}")
        print(f"      Total jobs accessible: {pagination_info['total_jobs_accessible']}")
        for note in pagination_info["notes"]:
            print(f"      Note: {note}")

        # Extract all visible jobs after pagination exploration
        all_jobs = extract_cards(page, working_selector)

        browser.close()

    # Save artifacts
    fixture = {
        "url": SEARCH_URL,
        "working_card_selector": working_selector,
        "all_selector_candidates": selector_results,
        "field_selectors": field_map,
        "pagination": pagination_info,
        "sample_jobs": all_jobs,
    }
    fixture_path = OUT_DIR / "snowflake_dom_fixture.json"
    fixture_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(f"\nSaved fixture: {fixture_path}")

    # Print summary for plan writing
    print("\n=== SUMMARY FOR IMPLEMENTATION PLAN ===")
    print(f"Card selector:    {working_selector}")
    print(f"Field map:        {json.dumps(field_map, indent=2)}")
    print(f"Pagination type:  {pagination_info['type']}")
    print(f"Pagination ctrl:  {pagination_info['next_button_selector']}")
    print(f"Total accessible: {pagination_info['total_jobs_accessible']} jobs")
    print(f"URL changes:      {pagination_info['url_changes_on_next']}")
    print(f"\nFirst 5 extracted jobs:")
    for j in all_jobs[:5]:
        print(f"  {j}")


_DEBUG_HTML_MAX = 1_048_576

if __name__ == "__main__":
    main()
