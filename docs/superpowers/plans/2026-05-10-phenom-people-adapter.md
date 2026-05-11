# Phenom People Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic `phenom_people` adapter that fetches job listings from Phenom People ATS sites via Playwright, piloted with Snowflake (tenant `SNCOUS`).

**Architecture:** Three phases per run: (1) SPA boot + XHR intercept captures page 1 response plus the raw request shape (method, URL, body/params); (2) parse page 1 from the intercepted response if valid; (3) paginate remaining pages via `browser.evaluate_fetch()` with `mode: "cors", credentials: "include"`. Fixture discovery runs before the normalizer is written to lock in real Phenom API field names — including the exact pagination field path (which may be nested). The adapter is fully generic by tenant/URL config; Snowflake is the only enabled pilot.

**Tech Stack:** Python 3.12, Playwright (sync via existing `BrowserClient`), `src.filtering.make_job_id` (`src/filtering.py:342`), `src.models.Job`, `unittest.mock` for tests.

---

## Files

| Action | Path |
|--------|------|
| Modify | `src/browser.py` — 3 new fields on `BrowserSessionContext`; extend `bootstrap_session` capture; GET/POST `evaluate_fetch` |
| Create | `src/adapters/phenom_people.py` — `PhenomPeopleAdapter` + `_parse_phenom_job` + `_set_nested` |
| Modify | `src/adapters/__init__.py` — register `"phenom_people": PhenomPeopleAdapter` |
| Modify | `companies.yaml` — switch Snowflake to `adapter: phenom_people, enabled: true` |
| Create | `scripts/discover_phenom_fixture.py` — manual diagnostic script; keep permanently |
| Create | `tests/fixtures/phenom_snowflake_request.json` — captured real SPA request |
| Create | `tests/fixtures/phenom_snowflake_response.json` — captured real SPA response (one page) |
| Create | `tests/test_phenom_people_adapter.py` — all unit tests for parser and adapter |
| Modify | `tests/test_browser.py` — new-field defaults + evaluate_fetch GET/POST tests |

---

### Task 1: browser.py extensions

**Files:**
- Modify: `src/browser.py:37-45` — `BrowserSessionContext` dataclass
- Modify: `src/browser.py:111-115` — local vars before `handle_response` closure
- Modify: `src/browser.py:123-141` — `handle_response` closure body
- Modify: `src/browser.py:174-181` — `BrowserSessionContext` return statement
- Modify: `src/browser.py:190-212` — `evaluate_fetch` method
- Modify: `tests/test_browser.py` — two new test classes

---

- [ ] **Step 1: Write failing tests for new BrowserSessionContext fields**

Append to `tests/test_browser.py` after the `TestBrowserSessionContextV3` class:

```python
class TestBrowserSessionContextPhenom:
    def test_new_fields_have_defaults(self):
        ctx = BrowserSessionContext(
            cookies={},
            headers={},
            final_url="https://example.com",
            captured_urls=(),
        )
        assert ctx.captured_request_method == "GET"
        assert ctx.captured_request_url == ""
        assert ctx.captured_request_body is None

    def test_new_fields_can_be_set(self):
        ctx = BrowserSessionContext(
            cookies={},
            headers={},
            final_url="https://example.com",
            captured_urls=(),
            captured_request_method="POST",
            captured_request_url="https://content-us.phenompeople.com/api/SNCOUS/searchJobs",
            captured_request_body='{"from":0,"size":20}',
        )
        assert ctx.captured_request_method == "POST"
        assert ctx.captured_request_url == "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
        assert ctx.captured_request_body == '{"from":0,"size":20}'
```

- [ ] **Step 2: Run to verify fails**

```
pytest tests/test_browser.py::TestBrowserSessionContextPhenom -v
```

Expected: FAIL — `BrowserSessionContext` has no `captured_request_method`.

- [ ] **Step 3: Add three fields to BrowserSessionContext**

In `src/browser.py`, find the `BrowserSessionContext` dataclass and add three fields immediately after `captured_first_response`:

```python
@dataclass(frozen=True)
class BrowserSessionContext:
    cookies: dict[str, str]
    headers: dict[str, str]
    final_url: str
    captured_urls: tuple[str, ...]
    captured_request_headers: dict[str, str] = field(default_factory=dict)
    captured_first_response: str | None = None
    captured_request_method: str = "GET"
    captured_request_url: str = ""
    captured_request_body: str | None = None
```

- [ ] **Step 4: Run to verify new-fields tests pass**

```
pytest tests/test_browser.py::TestBrowserSessionContextPhenom -v
```

Expected: PASS.

---

- [ ] **Step 5: Write failing test for bootstrap_session method/url/body capture**

Append inside `TestBootstrapSessionXHRInterception` in `tests/test_browser.py`:

```python
    def test_captures_request_method_url_body(self):
        client, mock_page = _make_mock_browser_for_intercept()
        captured_handler = None

        def fake_on(event, handler):
            nonlocal captured_handler
            if event == "response":
                captured_handler = handler

        mock_page.on.side_effect = fake_on

        def fake_goto(*args, **kwargs):
            if captured_handler:
                mock_resp = MagicMock()
                mock_resp.url = "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
                mock_resp.status = 200
                mock_resp.request.method = "POST"
                mock_resp.request.headers = {"Content-Type": "application/json"}
                mock_resp.request.post_data = '{"from":0,"size":20}'
                mock_resp.text.return_value = '{"jobs":[],"total":0}'
                captured_handler(mock_resp)

        mock_page.goto.side_effect = fake_goto
        mock_page.wait_for_load_state = MagicMock()

        session = client.bootstrap_session(
            "https://careers.snowflake.com/us/en/search",
            wait_for_response_url="**/api/SNCOUS/searchJobs**",
        )

        assert session.captured_request_method == "POST"
        assert session.captured_request_url == "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
        assert session.captured_request_body == '{"from":0,"size":20}'
```

- [ ] **Step 6: Run to verify fails**

```
pytest "tests/test_browser.py::TestBootstrapSessionXHRInterception::test_captures_request_method_url_body" -v
```

Expected: FAIL — session fields stay at defaults ("GET", "", None).

- [ ] **Step 7: Extend bootstrap_session to capture method/url/body**

In `src/browser.py`, inside `bootstrap_session`, find the block where local capture vars are declared:

```python
captured_urls: list[str] = []
captured_request_headers: dict[str, str] = {}
captured_first_response: str | None = None
```

Add three more vars immediately after:

```python
captured_urls: list[str] = []
captured_request_headers: dict[str, str] = {}
captured_first_response: str | None = None
captured_request_method: str = "GET"
captured_request_url: str = ""
captured_request_body: str | None = None
```

Update `handle_response` to declare them as `nonlocal` and populate them on first XHR match:

```python
def handle_response(resp) -> None:
    nonlocal captured_request_headers, captured_first_response
    nonlocal captured_request_method, captured_request_url, captured_request_body
    # Log all non-asset responses at DEBUG for adapter development
    if not resp.url.lower().split("?")[0].endswith(_ASSET_EXTS):
        logger.debug(
            "bootstrap_session[%s]: %s %s",
            company, resp.status, resp.url[:160],
        )
    if needle in resp.url:
        captured_urls.append(resp.url)
        if not captured_request_headers:  # first match only
            captured_request_headers = _filter_request_headers(
                dict(resp.request.headers)
            )
            captured_request_method = resp.request.method
            captured_request_url = resp.url
            captured_request_body = resp.request.post_data
            try:
                captured_first_response = resp.text()
            except Exception:
                pass
```

Update the `BrowserSessionContext(...)` return to include the three new fields:

```python
return BrowserSessionContext(
    cookies=cookies,
    headers=headers,
    final_url=final_url,
    captured_urls=tuple(captured_urls),
    captured_request_headers=captured_request_headers,
    captured_first_response=captured_first_response,
    captured_request_method=captured_request_method,
    captured_request_url=captured_request_url,
    captured_request_body=captured_request_body,
)
```

- [ ] **Step 8: Run bootstrap capture test**

```
pytest "tests/test_browser.py::TestBootstrapSessionXHRInterception::test_captures_request_method_url_body" -v
```

Expected: PASS.

---

- [ ] **Step 9: Write failing tests for evaluate_fetch GET/POST**

Append to `tests/test_browser.py` after `TestEvaluateFetch`:

```python
class TestEvaluateFetchGetPost:
    def test_evaluate_fetch_post_calls_correct_js(self):
        client, mock_page = _make_mock_browser_for_intercept()
        client._page = mock_page
        mock_page.evaluate.return_value = {"jobs": [], "total": 0}

        client.evaluate_fetch(
            "https://content-us.phenompeople.com/api/SNCOUS/searchJobs",
            {},
            method="POST",
            body={"from": 0, "size": 20},
        )

        call_args = mock_page.evaluate.call_args
        js = call_args[0][0]
        passed = call_args[0][1]
        assert "POST" in js
        assert "JSON.stringify" in js
        assert passed["method"] == "POST"
        assert passed["body"] == {"from": 0, "size": 20}

    def test_evaluate_fetch_get_uses_query_params(self):
        client, mock_page = _make_mock_browser_for_intercept()
        client._page = mock_page
        mock_page.evaluate.return_value = {"jobs": [], "total": 0}

        client.evaluate_fetch(
            "https://content-us.phenompeople.com/api/SNCOUS/searchJobs",
            {"from": "0", "size": "20"},
        )

        call_args = mock_page.evaluate.call_args
        js = call_args[0][0]
        passed = call_args[0][1]
        assert "URLSearchParams" in js
        assert passed["params"]["from"] == "0"

    def test_evaluate_fetch_includes_cors_and_credentials(self):
        client, mock_page = _make_mock_browser_for_intercept()
        client._page = mock_page
        mock_page.evaluate.return_value = {}

        client.evaluate_fetch("https://example.com/api", {})

        js = mock_page.evaluate.call_args[0][0]
        assert "cors" in js
        assert "credentials" in js
        assert "include" in js
```

- [ ] **Step 10: Run to verify fails**

```
pytest tests/test_browser.py::TestEvaluateFetchGetPost -v
```

Expected: FAIL — `evaluate_fetch` does not accept `method`/`body` kwargs and JS lacks `"cors"`.

- [ ] **Step 11: Replace evaluate_fetch with GET/POST implementation**

In `src/browser.py`, replace the entire `evaluate_fetch` method:

```python
def evaluate_fetch(
    self,
    url: str,
    params: dict,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> dict:
    """Run a fetch() call inside the live Playwright page. Returns parsed JSON.

    Supports GET (query params) and POST (JSON body).
    Uses mode: 'cors', credentials: 'include' for cross-origin SPA APIs.
    Requires bootstrap_session to have been called first.
    """
    if self._page is None:
        raise RuntimeError(
            "No active page — bootstrap_session must be called before evaluate_fetch"
        )
    js = """
    async (args) => {
        let resp;
        if (args.method === "POST") {
            resp = await fetch(args.url, {
                method: "POST",
                mode: "cors",
                credentials: "include",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(args.body)
            });
        } else {
            const p = new URLSearchParams(args.params);
            resp = await fetch(args.url + "?" + p.toString(), {
                mode: "cors",
                credentials: "include"
            });
        }
        if (!resp.ok) {
            throw new Error("fetch failed: " + resp.status + " " + resp.statusText);
        }
        return resp.json();
    }
    """
    return self._page.evaluate(
        js,
        {
            "url": url,
            "params": {k: str(v) for k, v in params.items()},
            "method": method,
            "body": body,
        },
    )
```

- [ ] **Step 12: Run all evaluate_fetch tests**

```
pytest tests/test_browser.py::TestEvaluateFetchGetPost tests/test_browser.py::TestEvaluateFetch -v
```

Expected: PASS all. The existing GET test (`test_calls_page_evaluate_with_correct_args`) still passes because `method` defaults to `"GET"`.

- [ ] **Step 13: Run full browser test suite**

```
pytest tests/test_browser.py -v
```

Expected: PASS all (existing + new).

- [ ] **Step 14: Commit**

```bash
git add src/browser.py tests/test_browser.py
git commit -m "feat: extend BrowserSessionContext and evaluate_fetch for Phenom People adapter"
```

---

### Task 2: Fixture discovery

**Files:**
- Create: `scripts/discover_phenom_fixture.py` — keep permanently as a manual diagnostic
- Create: `tests/fixtures/phenom_snowflake_request.json`
- Create: `tests/fixtures/phenom_snowflake_response.json`

This task requires Playwright + Chromium installed locally. The captured fixtures drive all field-name decisions in Tasks 3 and 4 — including whether the pagination field is flat (`body["from"]`) or nested (`body["pagination"]["from"]`). The script also validates that cross-origin `evaluate_fetch` works from inside the browser context.

---

- [ ] **Step 1: Create the discovery script**

Create `scripts/discover_phenom_fixture.py`:

```python
#!/usr/bin/env python3
"""Diagnostic: boot careers.snowflake.com, capture XHR, validate evaluate_fetch.

Manual-only — not part of the test suite. Run after browser.py Task 1 changes.
Usage: python scripts/discover_phenom_fixture.py
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.browser import BrowserClient

SEARCH_URL = "https://careers.snowflake.com/us/en/search"
WAIT_FOR = "**/api/SNCOUS/searchJobs**"
OUT_DIR = Path("tests/fixtures")
OUT_DIR.mkdir(exist_ok=True)


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

        if not session.captured_first_response:
            print("\nERROR: XHR not captured — check WAIT_FOR pattern vs actual URL in logs")
            sys.exit(1)

        # ------------------------------------------------------------------
        # Validate evaluate_fetch (must run inside the 'with' block)
        # ------------------------------------------------------------------
        print("\n[2/3] Testing evaluate_fetch (page 2 / next offset) ...")
        api_url, eval_fetch_ok = _test_evaluate_fetch(browser, session)

    # Context closed; fixtures and eval result already captured above
    print("\n[3/3] Writing fixtures ...")
    _write_fixtures(session)

    print("\nDone.\n")
    print("=== Field inspection ===")
    response_data = json.loads(session.captured_first_response)
    print("Top-level response keys:", list(response_data.keys()))
    jobs = _find_jobs(response_data)
    print(f"Jobs on page 1: {len(jobs)}")
    if jobs:
        print("\nFirst job record (identify field names for phenom_people.py):")
        print(json.dumps(jobs[0], indent=2))
    else:
        print("No jobs found — full response:")
        print(json.dumps(response_data, indent=2))

    print("\n=== Request body and Content-Type ===")
    req = json.loads((OUT_DIR / "phenom_snowflake_request.json").read_text())
    content_type = (
        req["headers"].get("content-type")
        or req["headers"].get("Content-Type")
        or "(not captured — check raw headers before sanitization)"
    )
    print(f"Content-Type: {content_type}")
    if "json" not in content_type.lower() and req["method"] == "POST":
        print("WARNING: Content-Type is not application/json.")
        print("         evaluate_fetch assumes JSON — adapt if Phenom uses a different encoding.")
    if req["body"]:
        print("Request body keys:", list(req["body"].keys()))
        print(json.dumps(req["body"], indent=2))
        print("\nIdentify the pagination field path (flat e.g. ['from'] or nested e.g. ['pagination','from'])")
    else:
        print("GET request — pagination is in URL query params")
        print("Captured URL:", req["url"])

    if not eval_fetch_ok:
        print("\nWARNING: evaluate_fetch failed — check log above for CORS / auth details")
        print("         The adapter's paginate-via-evaluate_fetch path may not work.")


def _test_evaluate_fetch(browser: "BrowserClient", session) -> tuple[str, bool]:
    """Call evaluate_fetch for offset 1 page and report success/failure."""
    # Derive API URL from captured URL (strip query string)
    raw_url = session.captured_request_url
    if raw_url:
        parsed = urlparse(raw_url)
        api_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    else:
        api_url = "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"

    method = session.captured_request_method
    try:
        if method == "POST" and session.captured_request_body:
            body = json.loads(session.captured_request_body)
            # Update pagination: try flat first; fixture inspection will confirm path
            for candidate in ("from", "start", "page", "offset"):
                if candidate in body:
                    body[candidate] = 20
                    break
            result = browser.evaluate_fetch(api_url, {}, method="POST", body=body)
        else:
            result = browser.evaluate_fetch(api_url, {"from": "20", "size": "20"})
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


def _write_fixtures(session) -> None:
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
    response_data = json.loads(session.captured_first_response)  # type: ignore[arg-type]
    (OUT_DIR / "phenom_snowflake_response.json").write_text(
        json.dumps(response_data, indent=2), encoding="utf-8"
    )
    print(f"      Saved to {OUT_DIR}/")


def _find_jobs(data: dict) -> list:
    for key in ("jobs", "positions", "results"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    sub = data.get("data") or {}
    if isinstance(sub, dict):
        for key in ("jobs", "positions", "results"):
            val = sub.get(key)
            if isinstance(val, list):
                return val
    return []


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the discovery script**

```
python scripts/discover_phenom_fixture.py
```

Expected output: fixture files written, first job record printed, evaluate_fetch result printed.

If XHR not captured, enable DEBUG logging and re-run:

```
PYTHONPATH=. python -c "
import logging; logging.basicConfig(level=logging.DEBUG)
exec(open('scripts/discover_phenom_fixture.py').read())
"
```

Look for `searchJobs` URLs in the DEBUG log and adjust `WAIT_FOR` if tenant slug differs.

If `evaluate_fetch` fails with a CORS/auth error, note it — this affects Task 4's pagination path and may require additional CORS investigation before the adapter will work end-to-end.

- [ ] **Step 3: Inspect fixtures and record field names**

Open `tests/fixtures/phenom_snowflake_response.json`. From the first job record, identify and write down:

| Field purpose | Actual field name in JSON |
|---|---|
| Top-level container key (list of jobs) | (e.g., `"jobs"`) |
| Total count field | (e.g., `"total"`, `"count"`) |
| Job ID field | (e.g., `"id"`) |
| Title field | (e.g., `"title"`, `"jobTitle"`) |
| Location field / path | (e.g., `"city"`, or nested `"location.city"`) |
| Department / category field | (e.g., `"category"`, `"department"`) |
| Apply URL field | (e.g., `"applyUrl"`, `"jobUrl"`) |
| Posted date field | (e.g., `"datePosted"`, absent) |

Open `tests/fixtures/phenom_snowflake_request.json`. Record:

| Field purpose | Value |
|---|---|
| Request method | (e.g., `"POST"`) |
| Pagination field path | **flat** `["from"]` or **nested** `["pagination", "from"]` |
| Page size field path | (e.g., `["size"]` or `["pagination", "size"]`) |

The pagination path is the key input for `_PAGE_PATH` and `_PAGE_SIZE_PATH` in `phenom_people.py`. If the request body is `{"from": 0, "size": 20}`, the path is `["from"]`. If it's `{"pagination": {"from": 0, "size": 20}}`, the path is `["pagination", "from"]`.

- [ ] **Step 4: Commit fixtures and script**

```bash
git add scripts/discover_phenom_fixture.py \
        tests/fixtures/phenom_snowflake_request.json \
        tests/fixtures/phenom_snowflake_response.json
git commit -m "chore: add Phenom People discovery script and Snowflake fixture data"
```

---

### Task 3: `_parse_phenom_job` normalizer

**Files:**
- Create: `src/adapters/phenom_people.py`
- Create: `tests/test_phenom_people_adapter.py`

**Prerequisite:** Task 2 must be complete and field names identified.

---

- [ ] **Step 1: Write parser tests**

Create `tests/test_phenom_people_adapter.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load fixtures (written by Task 2)
# ---------------------------------------------------------------------------
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_RAW_RESPONSE = json.loads((_FIXTURE_DIR / "phenom_snowflake_response.json").read_text())
_RAW_REQUEST = json.loads((_FIXTURE_DIR / "phenom_snowflake_request.json").read_text())


def _find_jobs_in_fixture(data: dict) -> list:
    for key in ("jobs", "positions", "results"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    sub = data.get("data") or {}
    if isinstance(sub, dict):
        for key in ("jobs", "positions", "results"):
            val = sub.get(key)
            if isinstance(val, list):
                return val
    return []


_FIXTURE_JOBS = _find_jobs_in_fixture(_RAW_RESPONSE)
_SAMPLE_JOB = _FIXTURE_JOBS[0] if _FIXTURE_JOBS else {}


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------
class TestPhenomPeopleParser:
    _DETECTED = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_valid_job(self):
        if not _SAMPLE_JOB:
            pytest.skip("No job records in fixture")
        from src.adapters.phenom_people import _parse_phenom_job
        job = _parse_phenom_job(_SAMPLE_JOB, "Snowflake", "phenom_people", self._DETECTED)
        assert job is not None
        assert job.company == "Snowflake"
        assert job.source_platform == "phenom_people"
        assert job.title
        assert job.detected_at == self._DETECTED

    def test_parse_missing_title_returns_none(self):
        from src.adapters.phenom_people import _parse_phenom_job, _TITLE_KEY
        record = dict(_SAMPLE_JOB) if _SAMPLE_JOB else {"id": "x"}
        record.pop(_TITLE_KEY, None)
        for alt in ("name", "jobTitle", "job_title"):
            record.pop(alt, None)
        assert _parse_phenom_job(record, "Snowflake", "phenom_people", self._DETECTED) is None

    def test_parse_location_is_non_empty_string(self):
        if not _SAMPLE_JOB:
            pytest.skip("No job records in fixture")
        from src.adapters.phenom_people import _parse_phenom_job
        job = _parse_phenom_job(_SAMPLE_JOB, "Snowflake", "phenom_people", self._DETECTED)
        assert job is not None
        assert isinstance(job.location, str) and job.location

    def test_parse_posted_at_is_datetime_or_none(self):
        if not _SAMPLE_JOB:
            pytest.skip("No job records in fixture")
        from src.adapters.phenom_people import _parse_phenom_job
        job = _parse_phenom_job(_SAMPLE_JOB, "Snowflake", "phenom_people", self._DETECTED)
        assert job is not None
        assert job.posted_at is None or isinstance(job.posted_at, datetime)

    def test_parse_url_present(self):
        if not _SAMPLE_JOB:
            pytest.skip("No job records in fixture")
        from src.adapters.phenom_people import _parse_phenom_job
        job = _parse_phenom_job(_SAMPLE_JOB, "Snowflake", "phenom_people", self._DETECTED)
        assert job is not None
        assert job.url

    def test_parse_missing_location_falls_back_to_not_specified(self):
        from src.adapters.phenom_people import _parse_phenom_job, _LOCATION_KEY
        record = {"id": "99", **{k: v for k, v in (_SAMPLE_JOB or {}).items()}}
        record.pop(_LOCATION_KEY, None)
        for alt in ("city", "location", "locationName", "location_name"):
            record.pop(alt, None)
        if not record.get("title") and not record.get("name"):
            record["title"] = "Test Job"
        job = _parse_phenom_job(record, "Snowflake", "phenom_people", self._DETECTED)
        if job is not None:
            assert job.location == "Not specified"
```

- [ ] **Step 2: Run to verify fails**

```
pytest tests/test_phenom_people_adapter.py::TestPhenomPeopleParser -v
```

Expected: FAIL with `ModuleNotFoundError` — `phenom_people.py` does not exist yet.

- [ ] **Step 3: Create adapter file with field constants and parser**

Create `src/adapters/phenom_people.py`. **Fill in the constant values from your Task 2 fixture inspection before saving.** In particular, `_PAGE_PATH` must match the actual nesting in the request body (e.g., `["from"]` for flat, `["pagination", "from"]` for nested).

```python
# src/adapters/phenom_people.py
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urlparse

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field name constants — set from fixture inspection in Task 2.
# Update any that differ from the real Phenom People response.
# ---------------------------------------------------------------------------
_JOBS_KEY = "jobs"          # top-level key holding the list of job records
_TOTAL_KEY = "total"        # total count field (int)
_ID_KEY = "id"              # job ID field
_TITLE_KEY = "title"        # job title field; update if fixture uses "jobTitle" etc.
_LOCATION_KEY = "city"      # location field; update if nested dict or different key
_DEPT_KEY = "category"      # department / category field
_URL_KEY = "applyUrl"       # direct apply / job detail URL field
_POSTED_KEY = "datePosted"  # posted date field; set to None/empty if absent in fixture

# Pagination path: list of keys to reach the offset field in the request body.
# Flat example:   ["from"]              →  body["from"] = offset
# Nested example: ["pagination", "from"] →  body["pagination"]["from"] = offset
# Determined from phenom_snowflake_request.json inspection in Task 2.
_PAGE_PATH: list[str] = ["from"]
_PAGE_SIZE = 20  # results per page; update if fixture shows a different default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_auth_failure(payload: dict) -> bool:
    return payload.get("status") == "failure" or bool(payload.get("errorMsg"))


def _set_nested(d: dict, path: list[str], value: object) -> dict:
    """Return a shallow-copy of d with path set to value (no mutation)."""
    if not path:
        return d
    result = dict(d)
    if len(path) == 1:
        result[path[0]] = value
    else:
        result[path[0]] = _set_nested(dict(d.get(path[0]) or {}), path[1:], value)
    return result


def _extract_location(record: dict) -> str:
    loc = record.get(_LOCATION_KEY)
    if isinstance(loc, str):
        return loc.strip() or "Not specified"
    if isinstance(loc, dict):
        city = loc.get("city") or loc.get("name") or ""
        state = loc.get("state") or loc.get("stateCode") or ""
        parts = [p for p in (city, state) if p]
        return ", ".join(parts) or "Not specified"
    return "Not specified"


def _parse_posted_at(record: dict) -> datetime | None:
    raw = record.get(_POSTED_KEY)
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def _extract_jobs_list(payload: dict) -> list:
    val = payload.get(_JOBS_KEY)
    if isinstance(val, list):
        return val
    data = payload.get("data")
    if isinstance(data, dict):
        for key in (_JOBS_KEY, "positions", "jobs"):
            sub = data.get(key)
            if isinstance(sub, list):
                return sub
    return []


def _extract_total(payload: dict) -> int | None:
    val = payload.get(_TOTAL_KEY)
    if isinstance(val, int):
        return val
    data = payload.get("data")
    if isinstance(data, dict):
        for key in (_TOTAL_KEY, "count", "totalCount"):
            sub = data.get(key)
            if isinstance(sub, int):
                return sub
    return None


def _parse_phenom_job(
    record: dict,
    company: str,
    source_platform: str,
    detected_at: datetime,
) -> Job | None:
    """Parse one Phenom People job record into a Job. Returns None if title missing."""
    official_id = str(record.get(_ID_KEY) or "").strip()
    title = (record.get(_TITLE_KEY) or "").strip()
    if not title:
        return None

    location = _extract_location(record)
    department = (record.get(_DEPT_KEY) or "").strip() or None
    url = (record.get(_URL_KEY) or "").strip()
    posted_at = _parse_posted_at(record)
    raw_text = " ".join(filter(None, [title, location, department])).lower()

    job_id = make_job_id(
        company=company,
        source_platform=source_platform,
        title=title,
        location=location,
        official_id=official_id if official_id else None,
    )

    return Job(
        id=job_id,
        company=company,
        title=title,
        location=location,
        department=department,
        category=None,
        url=url,
        source_platform=source_platform,
        posted_at=posted_at,
        detected_at=detected_at,
        raw_text=raw_text,
        role_type="unknown",
        priority="normal",
        matched_keywords=(),
    )


class PhenomPeopleAdapter(BaseAdapter):
    source_platform = "phenom_people"

    def fetch(self) -> Iterator[Job]:
        yield from ()  # stub — implemented in Task 4
```

- [ ] **Step 4: Run parser tests**

```
pytest tests/test_phenom_people_adapter.py::TestPhenomPeopleParser -v
```

Expected: PASS all. If any fail due to wrong field names (e.g., fixture uses `"jobTitle"` not `"title"`), update the matching constant in `phenom_people.py` and rerun until all pass.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/phenom_people.py tests/test_phenom_people_adapter.py
git commit -m "feat: add phenom_people adapter stub with fixture-validated parser"
```

---

### Task 4: PhenomPeopleAdapter.fetch() implementation

**Files:**
- Modify: `src/adapters/phenom_people.py` — replace stub `fetch()` with full implementation
- Modify: `tests/test_phenom_people_adapter.py` — add `TestPhenomPeopleAdapter` + `TestSetNested`

**Prerequisite:** Task 3 complete (field constants confirmed correct).

---

- [ ] **Step 1: Write adapter unit tests**

Append to `tests/test_phenom_people_adapter.py`:

```python
# ---------------------------------------------------------------------------
# _set_nested tests
# ---------------------------------------------------------------------------
class TestSetNested:
    def test_flat_path(self):
        from src.adapters.phenom_people import _set_nested
        result = _set_nested({"from": 0, "size": 20, "keyword": "intern"}, ["from"], 20)
        assert result["from"] == 20
        assert result["keyword"] == "intern"  # other keys preserved

    def test_nested_path(self):
        from src.adapters.phenom_people import _set_nested
        original = {"pagination": {"from": 0, "size": 20}, "keyword": "intern"}
        result = _set_nested(original, ["pagination", "from"], 20)
        assert result["pagination"]["from"] == 20
        assert result["pagination"]["size"] == 20  # sibling preserved
        assert result["keyword"] == "intern"

    def test_no_mutation_of_original(self):
        from src.adapters.phenom_people import _set_nested
        original = {"from": 0}
        _set_nested(original, ["from"], 99)
        assert original["from"] == 0  # original untouched


# ---------------------------------------------------------------------------
# Adapter tests (all BrowserClient calls mocked — no Chromium needed)
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock
from src.browser import BrowserClient, BrowserSessionContext
from src.adapters.phenom_people import (
    PhenomPeopleAdapter,
    _JOBS_KEY, _TOTAL_KEY, _ID_KEY, _TITLE_KEY, _LOCATION_KEY, _URL_KEY,
    _PAGE_PATH, _PAGE_SIZE,
)
from src.http import HTTPClient

_SNOWFLAKE_CONFIG = {
    "tenant": "SNCOUS",
    "base_url": "https://careers.snowflake.com",
    "search_url": "https://careers.snowflake.com/us/en/search",
    "api_base_url": "https://content-us.phenompeople.com",
    "api_path": "/api/{tenant}/searchJobs",
    "use_playwright": True,
    "browser_timeout_seconds": 30,
}

_CAPTURED_URL = "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"


def _make_session(
    *,
    method: str = "POST",
    captured_body: str | None = None,
    captured_response: str | None = None,
    captured_url: str = _CAPTURED_URL,
) -> BrowserSessionContext:
    from src.adapters.phenom_people import _set_nested
    if captured_body is None:
        if len(_PAGE_PATH) == 1:
            default_body = {_PAGE_PATH[0]: 0, "size": _PAGE_SIZE}
        else:
            default_body = {_PAGE_PATH[0]: {_PAGE_PATH[-1]: 0, "size": _PAGE_SIZE}}
        captured_body = json.dumps(default_body)
    if captured_response is None:
        captured_response = json.dumps(_one_page(0, total=1))
    return BrowserSessionContext(
        cookies={"sid": "abc"},
        headers={"Origin": "https://careers.snowflake.com"},
        final_url="https://careers.snowflake.com/us/en/search",
        captured_urls=(captured_url,),
        captured_request_headers={},
        captured_first_response=captured_response,
        captured_request_method=method,
        captured_request_url=captured_url,
        captured_request_body=captured_body,
    )


def _one_page(offset: int, *, total: int, size: int = 1) -> dict:
    jobs = [
        {
            _ID_KEY: str(offset + i),
            _TITLE_KEY: f"Software Engineering Intern {offset + i}",
            _LOCATION_KEY: "San Mateo, CA",
            _URL_KEY: f"https://careers.snowflake.com/job/{offset + i}",
        }
        for i in range(size)
    ]
    return {_JOBS_KEY: jobs, _TOTAL_KEY: total}


def _make_adapter(session: BrowserSessionContext) -> tuple[PhenomPeopleAdapter, MagicMock]:
    mock_browser = MagicMock(spec=BrowserClient)
    mock_browser.available = True
    mock_browser.bootstrap_session.return_value = session
    adapter = PhenomPeopleAdapter(
        company="Snowflake",
        config=_SNOWFLAKE_CONFIG,
        http=MagicMock(spec=HTTPClient),
        browser=mock_browser,
    )
    return adapter, mock_browser


class TestPhenomPeopleAdapter:
    def test_browser_none_yields_nothing(self):
        adapter = PhenomPeopleAdapter(
            company="Snowflake",
            config=_SNOWFLAKE_CONFIG,
            http=MagicMock(spec=HTTPClient),
            browser=None,
        )
        assert list(adapter.fetch()) == []

    def test_browser_unavailable_yields_nothing(self):
        mock_browser = MagicMock(spec=BrowserClient)
        mock_browser.available = False
        adapter = PhenomPeopleAdapter(
            company="Snowflake",
            config=_SNOWFLAKE_CONFIG,
            http=MagicMock(spec=HTTPClient),
            browser=mock_browser,
        )
        assert list(adapter.fetch()) == []
        mock_browser.bootstrap_session.assert_not_called()

    def test_bootstrap_failure_yields_nothing_and_captures_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        adapter, mock_browser = _make_adapter(_make_session())
        mock_browser.bootstrap_session.side_effect = RuntimeError("timeout")
        assert list(adapter.fetch()) == []
        mock_browser.capture_debug_artifacts.assert_called_once()

    def test_happy_path_single_page(self):
        session = _make_session(captured_response=json.dumps(_one_page(0, total=1)))
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {_JOBS_KEY: [], _TOTAL_KEY: 1}
        jobs = list(adapter.fetch())
        assert len(jobs) == 1
        assert jobs[0].title == "Software Engineering Intern 0"
        assert jobs[0].company == "Snowflake"
        assert jobs[0].source_platform == "phenom_people"

    def test_adapter_prefers_captured_url(self):
        """API URL comes from captured_request_url, not config api_base_url + api_path."""
        custom_url = "https://content-us.phenompeople.com/api/SNCOUS/searchJobs?extra=1"
        session = _make_session(captured_url=custom_url, captured_response=json.dumps(_one_page(0, total=1)))
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {_JOBS_KEY: [], _TOTAL_KEY: 1}
        list(adapter.fetch())
        # When evaluate_fetch is called for page 2, the URL must be the captured URL
        # (without query string). If page 1 total==1, evaluate_fetch is never called.
        # With total=_PAGE_SIZE*2, page 2 is needed.
        page1 = _one_page(0, total=_PAGE_SIZE * 2, size=_PAGE_SIZE)
        session2 = _make_session(captured_url=custom_url, captured_response=json.dumps(page1))
        adapter2, mock_browser2 = _make_adapter(session2)
        mock_browser2.evaluate_fetch.return_value = {_JOBS_KEY: [], _TOTAL_KEY: _PAGE_SIZE * 2}
        list(adapter2.fetch())
        called_url = mock_browser2.evaluate_fetch.call_args[0][0]
        assert called_url == "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
        assert "?" not in called_url  # query string stripped

    def test_no_xhr_captured_falls_to_evaluate_fetch(self):
        session = _make_session(captured_response=None)
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.side_effect = [
            _one_page(0, total=1),
            {_JOBS_KEY: [], _TOTAL_KEY: 1},
        ]
        jobs = list(adapter.fetch())
        assert len(jobs) == 1
        mock_browser.evaluate_fetch.assert_called()

    def test_auth_failure_on_captured_response_falls_to_evaluate_fetch(self):
        session = _make_session(captured_response='{"status":"failure"}')
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.side_effect = [
            _one_page(0, total=1),
            {_JOBS_KEY: [], _TOTAL_KEY: 1},
        ]
        assert len(list(adapter.fetch())) == 1

    def test_auth_failure_on_evaluate_fetch_stops_and_captures_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _make_session(captured_response=None)
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {"status": "failure"}
        assert list(adapter.fetch()) == []
        mock_browser.capture_debug_artifacts.assert_called_once()

    def test_evaluate_fetch_exception_stops_and_captures_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _make_session(captured_response=None)
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.side_effect = RuntimeError("CORS error")
        assert list(adapter.fetch()) == []
        mock_browser.capture_debug_artifacts.assert_called_once()

    def test_post_pagination_uses_set_nested_and_preserves_other_keys(self):
        """POST: page 2 updates pagination path via _set_nested; other keys unchanged."""
        from src.adapters.phenom_people import _set_nested
        original_body_dict = _set_nested({_PAGE_PATH[-1]: 0, "size": _PAGE_SIZE, "keyword": "intern"}, [], 0)
        page1 = _one_page(0, total=_PAGE_SIZE * 2, size=_PAGE_SIZE)
        session = _make_session(
            method="POST",
            captured_body=json.dumps(original_body_dict),
            captured_response=json.dumps(page1),
        )
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {_JOBS_KEY: [], _TOTAL_KEY: _PAGE_SIZE * 2}
        list(adapter.fetch())
        mock_browser.evaluate_fetch.assert_called_once()
        sent_body = mock_browser.evaluate_fetch.call_args.kwargs.get("body") \
                    or mock_browser.evaluate_fetch.call_args[1].get("body")
        assert sent_body is not None
        # Navigate _PAGE_PATH to confirm offset updated
        node = sent_body
        for key in _PAGE_PATH[:-1]:
            node = node[key]
        assert node[_PAGE_PATH[-1]] == _PAGE_SIZE
        assert sent_body.get("keyword") == "intern"  # other keys preserved

    def test_get_pagination_sends_updated_params(self):
        page1 = _one_page(0, total=_PAGE_SIZE * 2, size=_PAGE_SIZE)
        session = _make_session(
            method="GET",
            captured_body=None,
            captured_response=json.dumps(page1),
        )
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {_JOBS_KEY: [], _TOTAL_KEY: _PAGE_SIZE * 2}
        list(adapter.fetch())
        mock_browser.evaluate_fetch.assert_called_once()
        sent_params = mock_browser.evaluate_fetch.call_args[0][1]
        assert str(sent_params.get(_PAGE_PATH[-1], "")) == str(_PAGE_SIZE)
```

- [ ] **Step 2: Run to verify fails**

```
pytest tests/test_phenom_people_adapter.py::TestPhenomPeopleAdapter tests/test_phenom_people_adapter.py::TestSetNested -v
```

Expected: `TestSetNested` — FAIL (`_set_nested` not imported). `TestPhenomPeopleAdapter` — FAIL (stub yields nothing).

- [ ] **Step 3: Implement PhenomPeopleAdapter.fetch()**

Replace the `PhenomPeopleAdapter` class in `src/adapters/phenom_people.py`:

```python
class PhenomPeopleAdapter(BaseAdapter):
    source_platform = "phenom_people"

    def fetch(self) -> Iterator[Job]:
        if self.browser is None or not self.browser.available:
            logger.warning(
                "PhenomPeopleAdapter[%s]: no BrowserClient available — skipping",
                self.company,
            )
            return

        tenant = self.config["tenant"]
        base_url = self.config["base_url"].rstrip("/")
        search_url = self.config.get("search_url", base_url)
        timeout_seconds = int(self.config.get("browser_timeout_seconds", 30))
        wait_for_url = self.config.get(
            "wait_for_response_url",
            f"**/api/{tenant}/searchJobs**",
        )

        try:
            session = self.browser.bootstrap_session(
                search_url,
                company=self.company,
                wait_for_response_url=wait_for_url,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            logger.warning(
                "PhenomPeopleAdapter[%s]: browser bootstrap failed: %s",
                self.company, exc,
            )
            self.browser.capture_debug_artifacts(self.company, exc)
            return

        # Prefer captured URL (strip query string) — avoids config mismatch.
        # Fall back to api_base_url + api_path.format(tenant=...) from config.
        if session.captured_request_url:
            parsed = urlparse(session.captured_request_url)
            api_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        else:
            api_base = self.config.get(
                "api_base_url", "https://content-us.phenompeople.com"
            ).rstrip("/")
            api_path = self.config.get(
                "api_path", "/api/{tenant}/searchJobs"
            ).format(tenant=tenant)
            api_url = f"{api_base}{api_path}"

        logger.info(
            "PhenomPeopleAdapter[%s]: boot complete — api_url=%s method=%s has_response=%s",
            self.company,
            api_url,
            session.captured_request_method,
            session.captured_first_response is not None,
        )

        detected_at = datetime.now(tz=timezone.utc)
        request_method = session.captured_request_method
        body_template: dict | None = None
        if session.captured_request_body:
            try:
                body_template = json.loads(session.captured_request_body)
            except (ValueError, TypeError):
                pass

        offset = 0
        total: int | None = None
        use_intercept = bool(session.captured_first_response)

        while True:
            if use_intercept:
                use_intercept = False
                try:
                    payload = json.loads(session.captured_first_response)  # type: ignore[arg-type]
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "PhenomPeopleAdapter[%s]: bad captured response, falling to evaluate_fetch: %s",
                        self.company, exc,
                    )
                    continue
                if _is_auth_failure(payload):
                    logger.warning(
                        "PhenomPeopleAdapter[%s]: captured response is auth failure, falling to evaluate_fetch",
                        self.company,
                    )
                    continue
            else:
                if request_method == "POST" and body_template is not None:
                    body: dict | None = _set_nested(body_template, _PAGE_PATH, offset)
                    params: dict = {}
                else:
                    body = None
                    params = {_PAGE_PATH[-1]: offset, "size": _PAGE_SIZE}

                try:
                    payload = self.browser.evaluate_fetch(
                        api_url,
                        params,
                        method=request_method,
                        body=body,
                    )
                except Exception as exc:
                    logger.error(
                        "PhenomPeopleAdapter[%s]: evaluate_fetch failed at offset=%d: %s",
                        self.company, offset, exc,
                    )
                    self.browser.capture_debug_artifacts(self.company, exc)
                    return

                if _is_auth_failure(payload):
                    logger.error(
                        "PhenomPeopleAdapter[%s]: evaluate_fetch auth failure at offset=%d",
                        self.company, offset,
                    )
                    self.browser.capture_debug_artifacts(
                        self.company,
                        RuntimeError(f"evaluate_fetch auth failure: {payload}"),
                    )
                    return

            jobs_list = _extract_jobs_list(payload)
            count = _extract_total(payload)
            if total is None and count is not None:
                total = count

            if not jobs_list:
                break

            for record in jobs_list:
                try:
                    job = _parse_phenom_job(
                        record, self.company, self.source_platform, detected_at
                    )
                    if job is not None:
                        yield job
                except Exception as exc:
                    logger.warning(
                        "PhenomPeopleAdapter[%s]: skipping record %s: %s",
                        self.company, record.get(_ID_KEY, "?"), exc,
                    )

            offset += len(jobs_list)
            if total is not None and offset >= total:
                break
```

- [ ] **Step 4: Run adapter and _set_nested tests**

```
pytest tests/test_phenom_people_adapter.py::TestPhenomPeopleAdapter tests/test_phenom_people_adapter.py::TestSetNested -v
```

Expected: PASS all.

- [ ] **Step 5: Run full test file**

```
pytest tests/test_phenom_people_adapter.py -v
```

Expected: PASS all.

- [ ] **Step 6: Commit**

```bash
git add src/adapters/phenom_people.py tests/test_phenom_people_adapter.py
git commit -m "feat: implement PhenomPeopleAdapter.fetch() with nested pagination and captured URL preference"
```

---

### Task 5: Wire-up and smoke test

**Files:**
- Modify: `src/adapters/__init__.py`
- Modify: `companies.yaml`

---

- [ ] **Step 1: Register the adapter**

In `src/adapters/__init__.py`, append after the last `ADAPTER_REGISTRY` entry:

```python
from src.adapters.phenom_people import PhenomPeopleAdapter  # noqa: E402

ADAPTER_REGISTRY["phenom_people"] = PhenomPeopleAdapter
```

- [ ] **Step 2: Run full test suite — verify no regressions**

```
pytest -v
```

Expected: all existing tests green + all new tests green. Zero regressions.

- [ ] **Step 3: Update companies.yaml Snowflake entry**

Replace the existing Snowflake block in `companies.yaml`:

```yaml
  - name: Snowflake
    adapter: phenom_people
    enabled: true
    config:
      tenant: SNCOUS
      base_url: https://careers.snowflake.com
      search_url: https://careers.snowflake.com/us/en/search
      api_base_url: https://content-us.phenompeople.com
      api_path: /api/{tenant}/searchJobs
      location_country: United States
      use_playwright: true
      browser_timeout_seconds: 30
```

- [ ] **Step 4: Smoke test (requires Playwright + Chromium)**

```
python main.py run --company Snowflake --dry-run --verbose
```

Expected: jobs printed to stdout, no errors, no auth failures.

**If zero jobs returned:**
1. Log shows `captured_request_url` empty → XHR pattern didn't match; adjust `wait_for_response_url` in config.
2. Log shows auth failure on evaluate_fetch → CORS issue confirmed in discovery script; investigate further.
3. Jobs have blank titles → update `_TITLE_KEY` in `phenom_people.py`.
4. Pagination returns same page repeatedly → `_PAGE_PATH` is wrong; inspect request body and correct.

- [ ] **Step 5: Commit and push**

```bash
git add src/adapters/__init__.py companies.yaml
git commit -m "feat: register phenom_people adapter and enable Snowflake"
git push
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `BrowserSessionContext` 3 new fields with defaults | Task 1 |
| `bootstrap_session` captures method / URL / post_data on first XHR match | Task 1 |
| `evaluate_fetch` GET (URLSearchParams) and POST (JSON.stringify) with `mode: "cors"` | Task 1 |
| Fixture discovery before normalizer is written | Task 2 |
| Fixture discovery validates evaluate_fetch CORS path | Task 2 |
| `_parse_phenom_job` — title guard, location extraction, posted_at, `make_job_id` | Task 3 |
| `_set_nested` for flat and nested pagination field paths | Task 4 |
| Prefer captured request URL (strip query string) over config-derived URL | Task 4 |
| Auth failure detection on captured response → fall to evaluate_fetch | Task 4 |
| Auth failure on evaluate_fetch → ERROR + `capture_debug_artifacts` + return | Task 4 |
| evaluate_fetch exception → ERROR + `capture_debug_artifacts` + return | Task 4 |
| POST pagination: `_set_nested(body_template, _PAGE_PATH, offset)`, original keys preserved | Task 4 |
| GET pagination: flat params with `_PAGE_PATH[-1]` key | Task 4 |
| `browser=None` or `available=False` → WARNING + return | Task 4 |
| `bootstrap_session` raises → WARNING + `capture_debug_artifacts` + return | Task 4 |
| Register in `__init__.py` | Task 5 |
| Snowflake switched to `phenom_people` in `companies.yaml` | Task 5 |
| Unit tests: `TestBrowserSessionContextPhenom` | Task 1 |
| Unit tests: `TestBootstrapSessionXHRInterception.test_captures_request_method_url_body` | Task 1 |
| Unit tests: `TestEvaluateFetchGetPost` (POST JS, GET params, cors+credentials) | Task 1 |
| Unit tests: `TestPhenomPeopleParser` (6 cases from fixture) | Task 3 |
| Unit tests: `TestSetNested` (flat, nested, no-mutation) | Task 4 |
| Unit tests: `TestPhenomPeopleAdapter` (10 cases) | Task 4 |

**Placeholder check:** `_JOBS_KEY`, `_TOTAL_KEY`, `_TITLE_KEY`, `_LOCATION_KEY`, `_DEPT_KEY`, `_URL_KEY`, `_POSTED_KEY`, `_PAGE_PATH`, `_PAGE_SIZE` are initialized with best-guess values and **must be updated in Task 3 after reviewing real fixture data.** `_PAGE_PATH` is the most critical — it must match the exact nesting in the captured request body.

**Python version:** 3.12 (matches CI workflow at `.github/workflows/*.yml:21`).

**`make_job_id` location:** `src/filtering.py:342` — confirmed. Imported as `from src.filtering import make_job_id`.

**Type consistency:** `_parse_phenom_job(record, company, source_platform, detected_at)` signature matches between Task 3 definition and Task 4 call. `evaluate_fetch(url, params, *, method, body)` added in Task 1 is called with matching kwargs in Task 4. `_set_nested(d, path, value)` defined in Task 3 is imported and used in Task 4 tests and the adapter.
