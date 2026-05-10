#!/usr/bin/env python3
"""Diagnostic: boot careers.snowflake.com, capture XHR or DOM data, validate evaluate_fetch.

Manual-only — not part of the test suite. Run after browser.py Task 1 changes.
Usage: python scripts/discover_phenom_fixture.py

IMPORTANT FINDINGS (2026-05-10):
  Snowflake's Phenom People SPA (SNCOUS tenant) uses server-side rendering for the
  initial job listing. The searchJobs XHR endpoint only fires on client-side filter/sort
  interactions — NOT on page load. As a result, this script captures job data from the
  SSR DOM rather than intercepting an XHR response.

  API endpoint identified:
    https://content-us.phenompeople.com/api/SNCOUS/searchJobs
    Method: GET
    Pagination: ?from=0&size=10 query params
    Field schema (from jobwidgetsettings):
      - title          (job title)
      - location       (single location string; multi-location jobs list all)
      - category       (department/category)
      - reqId          (Required Id, e.g. REQ18172 or ASHREQ-5077)
      - descriptionTeaser (short description blurb)

  evaluate_fetch: CORS-blocked from the browser page context. The
  content-us.phenompeople.com domain does not allow cross-origin fetch from
  careers.snowflake.com. Pagination must use URL navigation, not evaluate_fetch.

  The fixtures in tests/fixtures/phenom_snowflake_{request,response}.json were
  constructed from DOM extraction of the SSR page on 2026-05-10.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.browser import BrowserClient

SEARCH_URL = "https://careers.snowflake.com/us/en/search-results"
# NOTE: Snowflake's Phenom SPA is SSR — searchJobs XHR does not fire on page load.
# The WAIT_FOR pattern is kept for logging/debug; capture will fall back to DOM.
WAIT_FOR = "**/api/SNCOUS/searchJobs**"
OUT_DIR = Path("tests/fixtures")
OUT_DIR.mkdir(exist_ok=True)

# Playwright JS to extract job data from SSR DOM
_EXTRACT_JOBS_JS = r"""
() => {
    const cards = document.querySelectorAll('[data-ph-at-id="jobs-list-item"]');
    const results = [];
    for (const card of cards) {
        const linkEl = card.querySelector('a[href*="/job/"]');
        const url = linkEl ? linkEl.href : null;
        let jobSeqNo = null;
        if (url) {
            const m = url.match(/\/job\/(SNCOUS[A-Z0-9]+)\//);
            if (m) jobSeqNo = m[1];
        }
        const titleEl = card.querySelector('[data-ph-at-id="job-link"]');
        const title = titleEl ? titleEl.textContent.trim() : null;
        const descEl = card.querySelector('[data-ph-at-id="jobdescription-text"]');
        const descriptionTeaser = descEl ? descEl.textContent.trim() : null;
        const multiList = card.querySelector('[data-ph-at-id="job-multi-locations-list"]');
        let location = null;
        let multi_location = null;
        if (multiList) {
            const lines = multiList.textContent.split('\n').map(s => s.trim()).filter(Boolean);
            multi_location = lines;
            location = lines.join('; ');
        } else {
            const jobInfoEl = card.querySelector('[data-ph-at-id="job-info"]');
            if (jobInfoEl) {
                const lines = jobInfoEl.textContent.split('\n').map(s => s.trim()).filter(Boolean);
                const catIdx = lines.indexOf('Category');
                if (catIdx > 0) location = lines[catIdx - 1];
                else if (lines.length > 0 && lines[0] !== 'Category') location = lines[0];
            }
        }
        const jobInfo = card.querySelector('[data-ph-at-id="job-info"]');
        let category = null;
        if (jobInfo) {
            const lines = jobInfo.textContent.split('\n').map(s => s.trim()).filter(Boolean);
            const catIdx = lines.indexOf('Category');
            if (catIdx >= 0 && catIdx + 1 < lines.length) category = lines[catIdx + 1];
        }
        const cardText = card.textContent;
        const reqMatch = cardText.match(/(REQ\d+|ASHREQ-\d+)/);
        const reqId = reqMatch ? reqMatch[1] : null;
        const dateEl = card.querySelector('time');
        const postedDate = dateEl ? (dateEl.getAttribute('datetime') || dateEl.textContent.trim()) : null;
        results.push({
            jobSeqNo, title, location, multi_location,
            category, reqId, descriptionTeaser, postedDate,
            detailUrl: url,
        });
    }
    return results;
}
"""

_COUNT_JS = r"""
() => {
    const el = document.querySelector('.result-jobs-count, [class*="jobs-count"]');
    return el ? el.textContent.trim() : null;
}
"""


def main() -> None:
    with BrowserClient() as browser:
        print(f"[1/3] Navigating to {SEARCH_URL} ...")
        session = browser.bootstrap_session(
            SEARCH_URL,
            company="Snowflake",
            wait_for_response_url=WAIT_FOR,
            timeout_seconds=45,
        )

        print(f"      captured_request_method : {session.captured_request_method}")
        print(f"      captured_request_url    : {session.captured_request_url}")
        print(f"      has_request_body        : {session.captured_request_body is not None}")
        print(f"      has_first_response      : {session.captured_first_response is not None}")

        if session.captured_first_response:
            print("\n      [XHR captured via network intercept]")
            _write_fixtures_from_session(session)
        else:
            print(
                "\n      [searchJobs XHR not captured — Phenom SPA is SSR for initial load]"
                "\n      [Falling back to DOM extraction]"
            )
            jobs, total_hits = _extract_from_dom(browser)
            _write_fixtures_from_dom(session, jobs, total_hits)

        # ------------------------------------------------------------------
        # Validate evaluate_fetch (must run inside the 'with' block)
        # ------------------------------------------------------------------
        print("\n[2/3] Testing evaluate_fetch (page 2 / next offset) ...")
        api_url, eval_fetch_ok = _test_evaluate_fetch(browser, session)

    # Context closed
    print("\n[3/3] Fixtures ready. Reading for inspection ...")

    print("\nDone.\n")
    print("=== Field inspection ===")
    response_data = json.loads(
        (OUT_DIR / "phenom_snowflake_response.json").read_text()
    )
    print("Top-level response keys:", list(response_data.keys()))
    jobs_list = _find_jobs(response_data)
    total = _find_total(response_data)
    print(f"Total hits (from response): {total}")
    print(f"Jobs in fixture: {len(jobs_list)}")
    if jobs_list:
        print("\nFirst job record (identify field names for phenom_people.py):")
        print(json.dumps(jobs_list[0], indent=2))

    print("\n=== Request info ===")
    req = json.loads((OUT_DIR / "phenom_snowflake_request.json").read_text())
    print(f"Method: {req['method']}")
    print(f"URL: {req['url']}")
    if req.get("_query_params"):
        print(f"Query params: {req['_query_params']}")
    if req["body"]:
        print("Request body keys:", list(req["body"].keys()))
        print(json.dumps(req["body"], indent=2))
        print("\nIdentify the pagination field path")
    else:
        print("GET request — pagination via 'from' and 'size' query params")

    if not eval_fetch_ok:
        print("\nWARNING: evaluate_fetch failed (CORS-blocked — expected for this tenant).")
        print("         The adapter must paginate via URL navigation, not evaluate_fetch.")


def _extract_from_dom(browser: "BrowserClient") -> tuple[list, int | None]:
    """Extract job records and total count from the SSR DOM."""
    if browser._page is None:
        raise RuntimeError("No active page for DOM extraction")
    page = browser._page
    jobs = page.evaluate(_EXTRACT_JOBS_JS)
    count_text = page.evaluate(_COUNT_JS) or ""
    # Parse "(12)jobs" or "12 jobs" patterns
    m = re.search(r"(\d+)", count_text)
    total_hits = int(m.group(1)) if m else None
    print(f"      DOM extraction: {len(jobs)} jobs visible, total_hits={total_hits}")
    return jobs, total_hits


def _write_fixtures_from_dom(session, jobs: list, total_hits: int | None) -> None:
    """Write request/response fixtures from DOM-extracted data."""
    request_data = {
        "method": "GET",
        "url": "https://content-us.phenompeople.com/api/SNCOUS/searchJobs",
        "headers": _sanitize_headers(dict(session.captured_request_headers)) or {
            "accept": "application/json, text/plain, */*",
            "origin": "https://careers.snowflake.com",
            "referer": "https://careers.snowflake.com/us/en/search-results",
        },
        "body": None,
        "_note": (
            "Phenom People API for Snowflake (SNCOUS). GET endpoint; "
            "pagination via 'from' and 'size' query params. "
            "The searchJobs XHR only fires on client-side interactions; "
            "initial page is SSR. Captured via DOM extraction."
        ),
        "_query_params": {
            "locale": "en_us",
            "siteType": "external",
            "deviceType": "desktop",
            "from": "0",
            "size": "10",
        },
    }
    (OUT_DIR / "phenom_snowflake_request.json").write_text(
        json.dumps(request_data, indent=2), encoding="utf-8"
    )

    response_data = {
        "searchJobs": {
            "status": "success",
            "errorCode": None,
            "errorMsg": None,
            "data": {
                "totalHits": total_hits,
                "from": 0,
                "size": len(jobs),
                "jobs": jobs,
            },
            "reqData": None,
        }
    }
    (OUT_DIR / "phenom_snowflake_response.json").write_text(
        json.dumps(response_data, indent=2), encoding="utf-8"
    )
    print(f"      Saved to {OUT_DIR}/")


def _write_fixtures_from_session(session) -> None:
    """Write fixtures from captured XHR session (happy path)."""
    request_data = {
        "method": session.captured_request_method,
        "url": session.captured_request_url,
        "headers": _sanitize_headers(dict(session.captured_request_headers)),
        "body": (
            json.loads(session.captured_request_body)
            if session.captured_request_body
            else None
        ),
    }
    (OUT_DIR / "phenom_snowflake_request.json").write_text(
        json.dumps(request_data, indent=2), encoding="utf-8"
    )
    response_data = json.loads(session.captured_first_response)
    (OUT_DIR / "phenom_snowflake_response.json").write_text(
        json.dumps(response_data, indent=2), encoding="utf-8"
    )
    print(f"      Saved to {OUT_DIR}/")


def _test_evaluate_fetch(browser: "BrowserClient", session) -> tuple[str, bool]:
    """Call evaluate_fetch for offset 1 page and report success/failure."""
    raw_url = session.captured_request_url
    if raw_url:
        parsed = urlparse(raw_url)
        api_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    else:
        api_url = "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"

    method = session.captured_request_method or "GET"
    try:
        if method == "POST" and session.captured_request_body:
            body = json.loads(session.captured_request_body)
            for candidate in ("from", "start", "page", "offset"):
                if candidate in body:
                    body[candidate] = 20
                    break
            result = browser.evaluate_fetch(api_url, {}, method="POST", body=body)
        else:
            result = browser.evaluate_fetch(api_url, {"from": "20", "size": "10"})
        jobs = _find_jobs(result)
        print(f"      evaluate_fetch OK — jobs on this page: {len(jobs)}")
        return api_url, True
    except Exception as exc:
        print(f"      evaluate_fetch FAILED: {exc}")
        return api_url, False


_SENSITIVE_HEADER_PREFIXES = (
    "cookie", "authorization", "x-csrf", "x-session",
    "x-visitor", "x-tracking", "x-request-id",
)


def _sanitize_headers(headers: dict) -> dict:
    """Strip per-session secrets; keep safe diagnostic headers only."""
    return {
        k: v for k, v in headers.items()
        if not any(k.lower().startswith(p) for p in _SENSITIVE_HEADER_PREFIXES)
    }


def _find_jobs(data: dict) -> list:
    for key in ("jobs", "positions", "results"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    sub = data.get("searchJobs") or data.get("data") or {}
    if isinstance(sub, dict):
        sub_data = sub.get("data") or sub
        if isinstance(sub_data, dict):
            for key in ("jobs", "positions", "results"):
                val = sub_data.get(key)
                if isinstance(val, list):
                    return val
    return []


def _find_total(data: dict) -> int | None:
    sub = data.get("searchJobs", {}).get("data", {})
    return sub.get("totalHits")


if __name__ == "__main__":
    main()
