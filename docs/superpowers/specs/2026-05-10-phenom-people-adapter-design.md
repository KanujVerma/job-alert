# Phenom People Adapter Design

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this spec task-by-task.

**Goal:** Build a generic `phenom_people` adapter that scrapes job listings from Phenom People ATS sites via Playwright, piloted with Snowflake (tenant `SNCOUS`).

**Background:** `careers.snowflake.com` is a Phenom People SPA, not Eightfold. Diagnostic runs confirmed the site calls `content-us.phenompeople.com/api/SNCOUS/searchJobs`. The Eightfold adapter was the wrong tool entirely.

---

## Architecture

Three-phase fetch per run:

1. **SPA boot + XHR intercept** — Navigate to `search_url`, intercept the SPA's native job-search XHR. Capture: response body (page 1), request method, exact URL, query params or POST body, allowlisted headers.
2. **Page 1 from intercept** — If `captured_first_response` is valid (non-failure), parse as page 1. If missing or auth-failure-shaped, fall through to evaluate_fetch at `from=0`.
3. **Pages 2+ via evaluate_fetch** — Call the Phenom search API from inside the live browser page (`mode: "cors", credentials: "include"`). Clone the original SPA request payload; update only the pagination field.

All three phases route through the same `_parse_phenom_job()` normalizer.

---

## Config Schema (Snowflake)

```yaml
- name: Snowflake
  adapter: phenom_people
  enabled: true
  config:
    tenant: SNCOUS
    base_url: https://careers.snowflake.com          # used for Origin/Referer headers
    search_url: https://careers.snowflake.com/us/en/search  # SPA page to navigate to
    api_base_url: https://content-us.phenompeople.com
    api_path: /api/{tenant}/searchJobs               # {tenant} substituted at runtime
    location_country: United States                  # optional; passed in search payload if present
    use_playwright: true
    browser_timeout_seconds: 30
```

The `wait_for_response_url` pattern is auto-derived as `**/api/{tenant}/searchJobs**` unless overridden with an explicit `wait_for_response_url` key in config.

The `api_path` value may include `{tenant}` as a literal placeholder; the adapter substitutes it at runtime: `api_path.format(tenant=tenant)`.

---

## Files

| Action | Path |
|--------|------|
| Create | `src/adapters/phenom_people.py` |
| Modify | `src/adapters/__init__.py` — register `"phenom_people": PhenomPeopleAdapter` |
| Modify | `companies.yaml` — switch Snowflake to `adapter: phenom_people, enabled: true` |
| Modify | `src/browser.py` — extend `BrowserSessionContext` with 3 new fields; extend `bootstrap_session` capture; extend `evaluate_fetch` to support POST |
| Create | `tests/fixtures/phenom_snowflake_request.json` — captured real SPA request |
| Create | `tests/fixtures/phenom_snowflake_response.json` — captured real SPA response |
| Create | `tests/test_phenom_people_adapter.py` |

---

## Infrastructure Changes (browser.py)

### BrowserSessionContext — three new fields

```python
captured_request_method: str = "GET"
captured_request_url: str = ""
captured_request_body: str | None = None
```

These join the existing `captured_request_headers` and `captured_first_response` fields. All have defaults so existing callers are unaffected.

### bootstrap_session — extended capture

Inside `handle_response`, when the needle matches, additionally capture:

```python
captured_request_method = resp.request.method            # "GET" or "POST"
captured_request_url = resp.url                          # exact URL with query string
captured_request_body = resp.request.post_data           # None for GET; JSON string for POST
```

Only captured on the first match (same guard as `captured_request_headers`).

### evaluate_fetch — GET and POST support

```python
def evaluate_fetch(
    self,
    url: str,
    params: dict,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> dict:
```

JS updated to branch on method:

```js
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
```

`mode: "cors"` is safe for same-origin requests (does not break `eightfold_playwright`).

---

## Fixture Discovery (First Implementation Step)

Before writing the normalizer, capture real Phenom People responses. This must happen before the `_parse_phenom_job` implementation is locked in.

Run a one-off diagnostic (local, with Playwright installed):

```bash
python main.py run --company Snowflake --dry-run --verbose
```

With temporary extra logging in the adapter, capture and commit to `tests/fixtures/`:

- `phenom_snowflake_request.json` — `{method, url, headers, body_or_params}`
- `phenom_snowflake_response.json` — raw response body (one page)

Inspect both fixtures to determine:
- Job ID field name
- Title field name
- Location field name (may be nested)
- Department / category field names
- Job detail URL format or field
- Pagination shape: total count field name, page cursor field name (`from`, `start`, `page`, etc.)
- Posted date field name and format if present

The normalizer is implemented against these confirmed field names. Do not assume Eightfold-style fields.

---

## Adapter Implementation

### Pagination logic

For GET:
- Pagination field in query params (e.g., `from=0`, `from=20`, …)
- Stop when `from >= total_count` or when returned jobs count is 0

For POST:
- Original request body is parsed once as a JSON template
- Each subsequent page: clone template dict, update only the pagination field to the new offset
- Stop condition: same as GET

The pagination field name and increment size come from the fixture discovery step.

### Auth failure detection

Reuse `_is_auth_failure(payload)` from `eightfold_playwright.py` or define an equivalent:

```python
def _is_auth_failure(payload: dict) -> bool:
    return payload.get("status") == "failure" or bool(payload.get("errorMsg"))
```

Applied to both the `captured_first_response` (page-1 optimization) and each `evaluate_fetch` result.

### _parse_phenom_job

Signature and return type match the existing pattern:

```python
def _parse_phenom_job(
    record: dict,
    company: str,
    source_platform: str,
    detected_at: datetime,
) -> Job | None:
```

Returns `None` if title is missing. Field names determined from fixture. Uses `make_job_id` from `src.filtering`.

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| `bootstrap_session` raises (page existed at crash) | Log WARNING + `capture_debug_artifacts` + return |
| `bootstrap_session` raises (no page before crash) | Log WARNING only + return |
| No XHR captured (`captured_first_response=None`) | Log INFO, fall to `evaluate_fetch` at from=0 |
| `captured_first_response` is auth-failure JSON | Log WARNING, fall to `evaluate_fetch` at from=0 |
| `evaluate_fetch` raises (CORS, network, JS error) | Log ERROR + `capture_debug_artifacts` + return |
| `evaluate_fetch` returns auth-failure JSON | Log ERROR + `capture_debug_artifacts` + return |
| `evaluate_fetch` returns empty jobs list | Break pagination loop cleanly |
| Individual job parse fails | Log WARNING + skip job + continue |
| `browser` is None or unavailable | Log WARNING + return immediately |

---

## Testing

### Fixture-based unit tests (`tests/test_phenom_people_adapter.py`)

No live Chromium required. `BrowserClient` fully mocked.

**Parser tests (`TestPhenomPeopleParser`):**
- `test_parse_valid_job` — field-by-field assertion from fixture data
- `test_parse_missing_title_returns_none` — title absent → `None`
- `test_parse_location_normalized` — location field correctly extracted (may be nested)
- `test_parse_posted_at` — date field parsed correctly; `None` if absent

**Adapter tests (`TestPhenomPeopleAdapter`):**
- `test_happy_path_intercept_plus_pagination` — page 1 from captured response, page 2 from evaluate_fetch → N total jobs yielded
- `test_no_xhr_captured_falls_to_evaluate_fetch` — `captured_first_response=None` → evaluate_fetch called at from=0
- `test_auth_failure_on_captured_response_falls_to_evaluate_fetch` — failure JSON in captured → evaluate_fetch path
- `test_auth_failure_on_evaluate_fetch` — evaluate_fetch returns failure → ERROR logged + `capture_debug_artifacts` called + 0 jobs
- `test_browser_unavailable` — `browser.available=False` → 0 jobs, WARNING logged
- `test_bootstrap_failure` — `bootstrap_session` raises → WARNING + debug artifact if page exists + 0 jobs
- `test_post_body_pagination` — captured method is POST → evaluate_fetch called with correct updated body, original fields preserved
- `test_get_param_pagination` — captured method is GET → evaluate_fetch called with updated params

**BrowserSessionContext tests:**
- `test_new_fields_have_defaults` — `captured_request_method="GET"`, `captured_request_url=""`, `captured_request_body=None`

**evaluate_fetch tests:**
- `test_evaluate_fetch_post_calls_correct_js` — POST path: JS contains `method:"POST"` and `JSON.stringify`
- `test_evaluate_fetch_get_uses_query_params` — GET path: JS constructs URLSearchParams

### Manual smoke test

After enabling Snowflake in `companies.yaml`:
```bash
python main.py run --company Snowflake --dry-run --verbose
```

Expected: jobs printed to stdout (not sent to Discord), no errors.

---

## Scope

**In scope:**
- `phenom_people` adapter, generic by tenant/URL config
- Snowflake as the only enabled pilot company
- Changes to `browser.py` (new BrowserSessionContext fields, evaluate_fetch POST support)

**Out of scope:**
- Microsoft Research, Oracle, Applied Digital
- Any other Phenom People company
- Anti-bot stealth, persistent cookie cache, async/httpx migration
