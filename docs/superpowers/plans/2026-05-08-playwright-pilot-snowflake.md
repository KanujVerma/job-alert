# Playwright Pilot — Snowflake/Eightfold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add headless-browser infrastructure (`BrowserClient`) and a new `eightfold_playwright` adapter so that Snowflake's JS-rendered careers site actually produces jobs in Discord alerts.

**Architecture:** Hybrid approach — Playwright boots the Snowflake SPA once to capture session cookies and safe headers, then hands them to the existing `HTTPClient` for all JSON pagination. The new `eightfold_playwright` adapter uses these cookies alongside the existing Eightfold JSON parser helpers; `eightfold.py` is untouched. The browser is lazy-started only when at least one enabled company in `companies.yaml` has `use_playwright: true`.

**Tech Stack:** Python 3.12, `playwright>=1.45` (sync API, chromium), `requests` (unchanged), `pytest` + `unittest.mock`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/browser.py` | **Create** | `BrowserSessionContext` dataclass, `BrowserClient` class |
| `src/adapters/eightfold_playwright.py` | **Create** | `EightfoldPlaywrightAdapter` — Snowflake pilot adapter |
| `tests/test_browser.py` | **Create** | Unit tests for `BrowserClient` (mocked playwright) |
| `tests/test_eightfold_playwright_adapter.py` | **Create** | Unit tests for the pilot adapter |
| `src/adapters/base.py` | **Modify** | Add `browser: BrowserClient | None = None` kwarg |
| `src/adapters/__init__.py` | **Modify** | Register `eightfold_playwright` key |
| `main.py` | **Modify** | Lazy browser instantiation + `try/finally` teardown |
| `companies.yaml` | **Modify** | Snowflake switches to `eightfold_playwright` adapter |
| `requirements.txt` | **Modify** | Add `playwright>=1.45` |
| `.github/workflows/job-alerts.yml` | **Modify** | Cache + install chromium |
| `.gitignore` | **Modify** | Add `debug_artifacts/` |
| `README.md` | **Modify** | Add v2 Playwright section |

---

## Task 1: Create `src/browser.py` — `BrowserSessionContext` + `BrowserClient`

**Files:**
- Create: `src/browser.py`
- Test: `tests/test_browser.py`

### Background

`BrowserClient` wraps the Playwright sync API. Only `src/browser.py` and `src/adapters/eightfold_playwright.py` import Playwright — no other file touches it. The module-level `_sync_playwright` reference makes it easy to mock in tests. `close()` runs in `do_run()`'s `finally` block regardless of adapter failures.

- [ ] **Step 1.1: Write failing tests for `BrowserSessionContext`**

```python
# tests/test_browser.py
from __future__ import annotations
from src.browser import BrowserSessionContext


def test_session_context_is_frozen():
    ctx = BrowserSessionContext(
        cookies={"sid": "abc"},
        headers={"Origin": "https://careers.snowflake.com"},
        final_url="https://careers.snowflake.com/us/en/jobs",
        captured_urls=["https://careers.snowflake.com/api/apply/v2/jobs?limit=20"],
    )
    assert ctx.cookies == {"sid": "abc"}
    assert ctx.final_url == "https://careers.snowflake.com/us/en/jobs"
    assert len(ctx.captured_urls) == 1


def test_session_context_frozen_raises_on_mutate():
    import pytest
    ctx = BrowserSessionContext(cookies={}, headers={}, final_url="", captured_urls=[])
    with pytest.raises((AttributeError, TypeError)):
        ctx.cookies = {}  # type: ignore
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```
pytest tests/test_browser.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.browser'`

- [ ] **Step 1.3: Create `src/browser.py` with `BrowserSessionContext` + full `BrowserClient`**

```python
# src/browser.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError:
    _sync_playwright = None  # type: ignore[assignment]

_DEBUG_HTML_MAX = 1_048_576  # 1 MB cap on saved HTML


@dataclass(frozen=True)
class BrowserSessionContext:
    cookies: dict[str, str]
    headers: dict[str, str]
    final_url: str
    captured_urls: list[str]


class BrowserClient:
    """Shared headless-browser for JS-rendered career sites.

    Lazy-starts chromium on first bootstrap_session call. Must be used as
    a context manager (or close() called explicitly) so chromium shuts down.

    Only src/browser.py and src/adapters/eightfold_playwright.py import Playwright.
    """

    def __init__(self) -> None:
        self.available: bool = True
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "BrowserClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def _ensure_started(self) -> None:
        if self._pw is not None:
            return
        if _sync_playwright is None:
            self.available = False
            raise RuntimeError(
                "playwright package not installed. "
                "Run: pip install playwright && python -m playwright install chromium"
            )
        try:
            self._pw = _sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._context = self._browser.new_context()
        except Exception as exc:
            logger.error("BrowserClient: failed to start chromium: %s", exc)
            self.available = False
            self.close()
            raise

    def bootstrap_session(
        self,
        url: str,
        *,
        company: str = "unknown",
        wait_for_selector: str | None = None,
        wait_for_response_url: str | None = None,
        timeout_seconds: int = 30,
    ) -> BrowserSessionContext:
        """Navigate to url, wait for SPA to settle, return cookies + safe headers.

        Primary wait: wait_for_selector if provided, else networkidle.
        Secondary: if wait_for_response_url is set, record matching XHR URLs
        in the returned captured_urls (non-blocking — does not fail if absent).

        On any exception: saves debug artifacts to debug_artifacts/{company}/{ts}/
        then re-raises so the adapter can log and return [].
        """
        self._ensure_started()
        timeout_ms = timeout_seconds * 1000
        captured_urls: list[str] = []

        page = self._context.new_page()
        try:
            if wait_for_response_url:
                needle = wait_for_response_url.replace("**", "")
                page.on(
                    "response",
                    lambda resp: captured_urls.append(resp.url)
                    if needle in resp.url
                    else None,
                )

            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            if wait_for_selector:
                try:
                    page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
                except Exception:
                    # Selector not found — fall back to networkidle
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
            else:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)

            final_url = page.url
            raw_cookies = self._context.cookies()
            cookies = {c["name"]: c["value"] for c in raw_cookies}

            # Build headers: derive from URL (safe subset only, no browser internals)
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            headers: dict[str, str] = {
                "Origin": origin,
                "Referer": final_url,
            }
            try:
                ua = page.evaluate("navigator.userAgent")
                if ua:
                    headers["User-Agent"] = str(ua)
            except Exception:
                pass

            return BrowserSessionContext(
                cookies=cookies,
                headers=headers,
                final_url=final_url,
                captured_urls=captured_urls,
            )

        except Exception as exc:
            # Save debug artifacts while the page is still open, then re-raise
            self._save_artifacts(page, company, exc)
            raise

        finally:
            page.close()

    def capture_debug_artifacts(self, company: str, error: Exception) -> None:
        """Save error.txt for post-bootstrap failures (no page available)."""
        self._save_artifacts(None, company, error)

    def close(self) -> None:
        """Idempotent teardown. Call in do_run() finally block."""
        for attr, method in [("_context", "close"), ("_browser", "close"), ("_pw", "stop")]:
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
                setattr(self, attr, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_artifacts(self, page, company: str, error: Exception) -> None:
        sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", company)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact_dir = Path("debug_artifacts") / sanitized / ts
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("BrowserClient: cannot create artifact dir: %s", e)
            return

        if page is not None:
            try:
                page.screenshot(path=str(artifact_dir / "screenshot.png"))
            except Exception as e:
                logger.debug("BrowserClient: screenshot failed: %s", e)

            try:
                html = page.content()
                if len(html) > _DEBUG_HTML_MAX:
                    html = html[:_DEBUG_HTML_MAX] + "\n<!-- TRUNCATED -->"
                (artifact_dir / "page.html").write_text(html, encoding="utf-8")
            except Exception as e:
                logger.debug("BrowserClient: html dump failed: %s", e)

        (artifact_dir / "error.txt").write_text(
            f"{type(error).__name__}: {error}", encoding="utf-8"
        )
        logger.info("BrowserClient: debug artifacts saved to %s", artifact_dir)
```

- [ ] **Step 1.4: Run `BrowserSessionContext` tests**

```
pytest tests/test_browser.py -v
```
Expected: both `test_session_context_*` tests PASS.

- [ ] **Step 1.5: Write `BrowserClient` unit tests**

```python
# append to tests/test_browser.py
from unittest.mock import MagicMock, patch, call
import pytest
from src.browser import BrowserClient, BrowserSessionContext


def _make_mock_pw():
    """Build a minimal sync_playwright mock tree."""
    mock_cookie = {"name": "PHPSESSID", "value": "abc123"}
    mock_page = MagicMock()
    mock_page.url = "https://careers.snowflake.com/us/en/jobs"
    mock_page.evaluate.return_value = "Mozilla/5.0 Chrome/120"
    mock_context = MagicMock()
    mock_context.cookies.return_value = [mock_cookie]
    mock_context.new_page.return_value = mock_page
    mock_context.pages = [mock_page]
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_chromium = MagicMock()
    mock_chromium.launch.return_value = mock_browser
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium = mock_chromium
    mock_pw_manager = MagicMock()
    mock_pw_manager.start.return_value = mock_pw_instance
    return mock_pw_manager, mock_pw_instance, mock_browser, mock_context, mock_page


def test_bootstrap_session_returns_context():
    mock_pw_manager, _, _, mock_context, mock_page = _make_mock_pw()
    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        client = BrowserClient()
        ctx = client.bootstrap_session(
            "https://careers.snowflake.com",
            company="Snowflake",
        )

    assert isinstance(ctx, BrowserSessionContext)
    assert ctx.cookies == {"PHPSESSID": "abc123"}
    assert ctx.headers["Origin"] == "https://careers.snowflake.com"
    assert "careers.snowflake.com" in ctx.headers["Referer"]
    assert ctx.headers["User-Agent"] == "Mozilla/5.0 Chrome/120"
    mock_page.close.assert_called_once()


def test_bootstrap_session_captures_xhr_urls():
    mock_pw_manager, _, _, mock_context, mock_page = _make_mock_pw()

    def setup_response_listener(event, callback):
        # Simulate a matching XHR response being observed
        mock_resp = MagicMock()
        mock_resp.url = "https://careers.snowflake.com/api/apply/v2/jobs?limit=20"
        callback(mock_resp)

    mock_page.on.side_effect = setup_response_listener

    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        client = BrowserClient()
        ctx = client.bootstrap_session(
            "https://careers.snowflake.com",
            company="Snowflake",
            wait_for_response_url="**/api/apply/v2/jobs**",
        )

    assert any("api/apply/v2/jobs" in u for u in ctx.captured_urls)


def test_bootstrap_session_playwright_not_installed():
    with patch("src.browser._sync_playwright", None):
        client = BrowserClient()
        with pytest.raises(RuntimeError, match="playwright package not installed"):
            client.bootstrap_session("https://example.com")
    assert client.available is False


def test_bootstrap_session_saves_artifacts_on_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_pw_manager, _, _, mock_context, mock_page = _make_mock_pw()
    mock_page.goto.side_effect = Exception("Navigation timeout")

    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        client = BrowserClient()
        with pytest.raises(Exception, match="Navigation timeout"):
            client.bootstrap_session(
                "https://careers.snowflake.com",
                company="Snowflake",
            )

    artifact_dirs = list((tmp_path / "debug_artifacts" / "Snowflake").iterdir())
    assert len(artifact_dirs) == 1
    assert (artifact_dirs[0] / "error.txt").read_text() == "Exception: Navigation timeout"


def test_close_is_idempotent():
    mock_pw_manager, _, _, _, _ = _make_mock_pw()
    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        client = BrowserClient()
        client._ensure_started()
        client.close()
        client.close()  # second call must not raise
    assert client._pw is None
    assert client._browser is None
    assert client._context is None


def test_context_manager_closes_on_exit():
    mock_pw_manager, mock_pw_instance, mock_browser, mock_context, _ = _make_mock_pw()
    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        with BrowserClient() as client:
            client._ensure_started()
    mock_context.close.assert_called_once()
    mock_browser.close.assert_called_once()
    mock_pw_instance.stop.assert_called_once()
```

- [ ] **Step 1.6: Run all `BrowserClient` tests**

```
pytest tests/test_browser.py -v
```
Expected: all 8 tests PASS.

- [ ] **Step 1.7: Commit**

```bash
git add src/browser.py tests/test_browser.py
git commit -m "feat: add BrowserClient and BrowserSessionContext for Playwright support"
```

---

## Task 2: Extend `BaseAdapter` with optional `browser` kwarg

**Files:**
- Modify: `src/adapters/base.py`

- [ ] **Step 2.1: Write failing test for extended constructor**

Add this to any existing test file, e.g., create `tests/test_base_adapter.py`:

```python
# tests/test_base_adapter.py
from unittest.mock import MagicMock
from src.adapters.base import BaseAdapter
from src.http import HTTPClient
from src.browser import BrowserClient


class _ConcreteAdapter(BaseAdapter):
    source_platform = "test"

    def fetch(self):
        return iter([])


def test_base_adapter_accepts_browser_kwarg():
    http = MagicMock(spec=HTTPClient)
    browser = MagicMock(spec=BrowserClient)
    adapter = _ConcreteAdapter("TestCo", {}, http, browser=browser)
    assert adapter.browser is browser


def test_base_adapter_browser_defaults_to_none():
    http = MagicMock(spec=HTTPClient)
    adapter = _ConcreteAdapter("TestCo", {}, http)
    assert adapter.browser is None
```

- [ ] **Step 2.2: Run to confirm failure**

```
pytest tests/test_base_adapter.py -v
```
Expected: `TypeError: __init__() got an unexpected keyword argument 'browser'`

- [ ] **Step 2.3: Update `src/adapters/base.py`**

```python
# src/adapters/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING

from src.models import Job
from src.http import HTTPClient

if TYPE_CHECKING:
    from src.browser import BrowserClient


class BaseAdapter(ABC):
    source_platform: str  # class-level constant, e.g. "workday"

    def __init__(self, company: str, config: dict, http: HTTPClient, browser: "BrowserClient | None" = None):
        self.company = company
        self.config = config
        self.http = http
        self.browser = browser

    @abstractmethod
    def fetch(self) -> Iterator[Job]:
        """
        Yield normalized Job objects.
        - Set role_type hint if this is a known intern-only source.
        - Include official job ID if source provides one.
        - Populate raw_text from available list-response fields only (no extra HTTP).
        - Never raise — log errors and yield nothing on failure.
        """
```

- [ ] **Step 2.4: Run tests**

```
pytest tests/test_base_adapter.py -v
```
Expected: both PASS.

- [ ] **Step 2.5: Confirm existing adapter tests still pass**

```
pytest tests/ -v --ignore=tests/test_browser.py --ignore=tests/test_base_adapter.py
```
Expected: all existing tests PASS (existing adapters pass `browser=None` implicitly via default).

- [ ] **Step 2.6: Commit**

```bash
git add src/adapters/base.py tests/test_base_adapter.py
git commit -m "feat: extend BaseAdapter with optional browser kwarg"
```

---

## Task 3: Create `src/adapters/eightfold_playwright.py`

**Files:**
- Create: `src/adapters/eightfold_playwright.py`
- Test: `tests/test_eightfold_playwright_adapter.py`

### Background

This adapter reuses `_strip_html`, `_parse_iso`, `_DESCRIPTION_MAX`, and `_LIMIT` from `eightfold.py` (module-level symbols) plus `make_job_id` from `src.filtering`. It does NOT subclass `EightfoldAdapter` — the `_parse` method logic is reproduced locally as `_parse_position()`. The `fetch()` method:

1. Guards: returns early if `self.browser` is `None` or `self.browser.available is False`.
2. Calls `bootstrap_session` with `networkidle` wait (no hard selector — Snowflake's Phenom SPA uses dynamic class names).
3. Guards: if `not session.cookies`, logs and returns.
4. Paginates the Eightfold JSON API via `self.http.get(...)` with the captured cookies/headers.
5. Reuses the same JSON parsing logic as `EightfoldAdapter`.

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_eightfold_playwright_adapter.py
"""Tests for EightfoldPlaywrightAdapter.

Playwright is always mocked — no live chromium required.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.adapters.eightfold_playwright import EightfoldPlaywrightAdapter
from src.browser import BrowserClient, BrowserSessionContext
from src.http import HTTPClient
from src.models import Job

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "eightfold_snowflake.json"

_CONFIG = {
    "base_url": "https://careers.snowflake.com",
    "api_path": "/api/apply/v2/jobs",
    "location_country": "United States",
    "use_playwright": True,
    "browser_timeout_seconds": 30,
}

_SESSION = BrowserSessionContext(
    cookies={"PHPSESSID": "test-session-cookie"},
    headers={
        "Origin": "https://careers.snowflake.com",
        "Referer": "https://careers.snowflake.com/us/en/jobs",
        "User-Agent": "Mozilla/5.0",
    },
    final_url="https://careers.snowflake.com/us/en/jobs",
    captured_urls=["https://careers.snowflake.com/api/apply/v2/jobs?limit=20"],
)


def _make_adapter(config=None, browser_available=True):
    http = MagicMock(spec=HTTPClient)
    browser = MagicMock(spec=BrowserClient)
    browser.available = browser_available
    browser.bootstrap_session.return_value = _SESSION
    return EightfoldPlaywrightAdapter(
        company="Snowflake",
        config=config or _CONFIG,
        http=http,
        browser=browser,
    )


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = status < 400
    resp.status_code = status
    resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_yields_jobs():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert len(jobs) == 2
    job: Job = jobs[0]
    assert job.company == "Snowflake"
    assert job.source_platform == "eightfold_playwright"
    assert job.title == "Software Engineer Intern"
    assert job.location == "San Mateo, California"
    assert "careers.snowflake.com" in job.url
    assert job.role_type == "unknown"


def test_cookies_forwarded_to_http():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    list(adapter.fetch())

    call_kwargs = adapter.http.get.call_args
    assert call_kwargs.kwargs.get("cookies") == _SESSION.cookies or \
           (call_kwargs.args and "cookies" not in call_kwargs.kwargs)


def test_bootstrap_called_with_correct_url_and_company():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    list(adapter.fetch())

    adapter.browser.bootstrap_session.assert_called_once()
    call_kwargs = adapter.browser.bootstrap_session.call_args
    assert "careers.snowflake.com" in call_kwargs.args[0]
    assert call_kwargs.kwargs.get("company") == "Snowflake"


def test_uses_browser_timeout_from_config():
    config = {**_CONFIG, "browser_timeout_seconds": 45}
    adapter = _make_adapter(config=config)
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    list(adapter.fetch())

    call_kwargs = adapter.browser.bootstrap_session.call_args
    assert call_kwargs.kwargs.get("timeout_seconds") == 45


# ---------------------------------------------------------------------------
# Guard conditions
# ---------------------------------------------------------------------------

def test_returns_empty_if_browser_is_none():
    http = MagicMock(spec=HTTPClient)
    adapter = EightfoldPlaywrightAdapter("Snowflake", _CONFIG, http, browser=None)
    assert list(adapter.fetch()) == []
    http.get.assert_not_called()


def test_returns_empty_if_browser_unavailable():
    adapter = _make_adapter(browser_available=False)
    assert list(adapter.fetch()) == []
    adapter.browser.bootstrap_session.assert_not_called()


def test_returns_empty_if_no_cookies():
    adapter = _make_adapter()
    adapter.browser.bootstrap_session.return_value = BrowserSessionContext(
        cookies={}, headers={}, final_url="https://careers.snowflake.com", captured_urls=[]
    )
    assert list(adapter.fetch()) == []
    adapter.http.get.assert_not_called()


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

def test_bootstrap_exception_returns_empty(caplog):
    import logging
    adapter = _make_adapter()
    adapter.browser.bootstrap_session.side_effect = Exception("Navigation timeout")

    with caplog.at_level(logging.WARNING):
        result = list(adapter.fetch())

    assert result == []
    assert "Snowflake" in caplog.text


def test_http_error_after_bootstrap_returns_empty(caplog):
    import logging
    import requests
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.side_effect = requests.RequestException("Connection reset")

    with caplog.at_level(logging.ERROR):
        result = list(adapter.fetch())

    assert result == []


def test_api_failure_status_returns_empty(caplog):
    import logging
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(
        {"status": "failure", "errorMsg": "Tenant not identified"}
    )

    with caplog.at_level(logging.WARNING):
        result = list(adapter.fetch())

    assert result == []


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_pagination_fetches_all_pages():
    adapter = _make_adapter()

    page1 = {
        "status": "success",
        "data": {
            "count": 3,
            "positions": [
                {
                    "id": "1",
                    "name": "SWE Intern",
                    "location": "San Mateo, CA",
                    "department": "Eng",
                    "canonicalPositionUrl": "https://careers.snowflake.com/job/1",
                    "t_create": "2025-01-01T00:00:00Z",
                    "description": "<p>desc1</p>",
                },
                {
                    "id": "2",
                    "name": "PM Intern",
                    "location": "Seattle, WA",
                    "department": "PM",
                    "canonicalPositionUrl": "https://careers.snowflake.com/job/2",
                    "t_create": "2025-01-02T00:00:00Z",
                    "description": "<p>desc2</p>",
                },
            ],
        },
    }
    page2 = {
        "status": "success",
        "data": {
            "count": 3,
            "positions": [
                {
                    "id": "3",
                    "name": "Data Intern",
                    "location": "New York, NY",
                    "department": "Data",
                    "canonicalPositionUrl": "https://careers.snowflake.com/job/3",
                    "t_create": "2025-01-03T00:00:00Z",
                    "description": "<p>desc3</p>",
                }
            ],
        },
    }
    adapter.http.get.side_effect = [_mock_response(page1), _mock_response(page2)]

    jobs = list(adapter.fetch())
    assert len(jobs) == 3
    assert adapter.http.get.call_count == 2
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```
pytest tests/test_eightfold_playwright_adapter.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.adapters.eightfold_playwright'`

- [ ] **Step 3.3: Create `src/adapters/eightfold_playwright.py`**

```python
# src/adapters/eightfold_playwright.py
"""Eightfold adapter with Playwright browser bootstrap for JS-rendered SPA auth.

Pilot adapter for Snowflake (careers.snowflake.com). Boots the SPA via
BrowserClient to capture session cookies, then uses the existing HTTPClient
for JSON pagination. Parser logic mirrors EightfoldAdapter._parse but is
implemented locally to avoid inheritance coupling.

Config keys (same as eightfold adapter, plus):
  use_playwright: true
  browser_timeout_seconds: 30    (optional, default 30)
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

import requests

from src.adapters.base import BaseAdapter
from src.adapters.eightfold import _strip_html, _parse_iso, _DESCRIPTION_MAX, _LIMIT
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)


class EightfoldPlaywrightAdapter(BaseAdapter):
    """Eightfold adapter that bootstraps the SPA via Playwright to obtain auth cookies."""

    source_platform = "eightfold_playwright"

    def fetch(self) -> Iterator[Job]:
        if self.browser is None or not self.browser.available:
            logger.warning(
                "EightfoldPlaywrightAdapter[%s]: no BrowserClient available — skipping",
                self.company,
            )
            return

        base_url = self.config["base_url"].rstrip("/")
        api_path = self.config.get("api_path", "/api/apply/v2/jobs")
        location_country = self.config.get("location_country", "United States")
        domain = self.config.get("domain") or base_url.split("//", 1)[-1].split("/")[0]
        timeout_seconds = int(self.config.get("browser_timeout_seconds", 30))

        # Step 1: Boot SPA, capture cookies + headers
        try:
            session = self.browser.bootstrap_session(
                base_url,
                company=self.company,
                wait_for_response_url="**/api/apply/v2/jobs**",
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            logger.warning(
                "EightfoldPlaywrightAdapter[%s]: browser bootstrap failed: %s",
                self.company, exc,
            )
            return

        if not session.cookies:
            logger.warning(
                "EightfoldPlaywrightAdapter[%s]: bootstrap returned no cookies — cannot auth",
                self.company,
            )
            return

        # Step 2: Paginate the JSON API with captured cookies + headers
        api_url = f"{base_url}{api_path}"
        offset = 0
        total: int | None = None
        detected_at = datetime.now(tz=timezone.utc)

        while True:
            params: dict = {
                "domain": domain,
                "limit": _LIMIT,
                "offset": offset,
                "json": "true",
            }
            if location_country:
                params["location_country"] = location_country

            try:
                resp = self.http.get(
                    api_url,
                    params=params,
                    cookies=session.cookies,
                    headers=session.headers,
                )
            except requests.RequestException as exc:
                logger.error(
                    "EightfoldPlaywrightAdapter[%s]: request failed at offset=%d: %s",
                    self.company, offset, exc,
                )
                return

            if not resp.ok:
                logger.error(
                    "EightfoldPlaywrightAdapter[%s]: HTTP %d at offset=%d",
                    self.company, resp.status_code, offset,
                )
                return

            try:
                payload = resp.json()
            except ValueError as exc:
                logger.error(
                    "EightfoldPlaywrightAdapter[%s]: JSON parse error at offset=%d: %s",
                    self.company, offset, exc,
                )
                return

            status = payload.get("status")
            if status == "failure":
                logger.warning(
                    "EightfoldPlaywrightAdapter[%s]: API returned failure: %s",
                    self.company, payload.get("errorMsg", "unknown"),
                )
                return

            data = payload.get("data") or payload
            positions = data.get("positions", [])
            count = data.get("count", len(positions))

            if total is None:
                total = count

            if not positions:
                break

            for pos in positions:
                try:
                    job = _parse_position(pos, self.company, self.source_platform, detected_at)
                    if job is not None:
                        yield job
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "EightfoldPlaywrightAdapter[%s]: skipping position %s: %s",
                        self.company, pos.get("id"), exc,
                    )

            offset += _LIMIT
            if total is not None and offset >= total:
                break

            self.http.polite_delay(1.0, 2.0)


def _parse_position(
    pos: dict,
    company: str,
    source_platform: str,
    detected_at: datetime,
) -> Job | None:
    """Parse one Eightfold position dict into a Job. Returns None if title is missing."""
    official_id = str(pos.get("id") or "").strip()
    title = (pos.get("name") or "").strip()
    if not title:
        return None

    location = (pos.get("location") or "Not specified").strip()
    department = (pos.get("department") or "").strip() or None
    job_url = (pos.get("canonicalPositionUrl") or "").strip()
    posted_at = _parse_iso(pos.get("t_create"))
    raw_desc = _strip_html(pos.get("description") or "")[:_DESCRIPTION_MAX]
    raw_text = " ".join(filter(None, [title, location, department, raw_desc])).lower()

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
        url=job_url,
        source_platform=source_platform,
        posted_at=posted_at,
        detected_at=detected_at,
        raw_text=raw_text,
        role_type="unknown",
        priority="normal",
        matched_keywords=(),
    )
```

- [ ] **Step 3.4: Run the new adapter tests**

```
pytest tests/test_eightfold_playwright_adapter.py -v
```
Expected: all tests PASS (no live chromium needed — browser is mocked).

- [ ] **Step 3.5: Run full test suite to confirm no regressions**

```
pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 3.6: Commit**

```bash
git add src/adapters/eightfold_playwright.py tests/test_eightfold_playwright_adapter.py
git commit -m "feat: add EightfoldPlaywrightAdapter for Snowflake SPA bootstrap"
```

---

## Task 4: Register `eightfold_playwright` in the adapter registry

**Files:**
- Modify: `src/adapters/__init__.py`

- [ ] **Step 4.1: Write failing test**

```python
# append to tests/test_eightfold_playwright_adapter.py

from src.adapters import ADAPTER_REGISTRY


def test_adapter_registered():
    from src.adapters.eightfold_playwright import EightfoldPlaywrightAdapter
    assert "eightfold_playwright" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["eightfold_playwright"] is EightfoldPlaywrightAdapter
```

- [ ] **Step 4.2: Run to confirm it fails**

```
pytest tests/test_eightfold_playwright_adapter.py::test_adapter_registered -v
```
Expected: `AssertionError: assert 'eightfold_playwright' in {...}`

- [ ] **Step 4.3: Add registration to `src/adapters/__init__.py`**

Append these two lines at the end of `src/adapters/__init__.py`:

```python
from src.adapters.eightfold_playwright import EightfoldPlaywrightAdapter  # noqa: E402

ADAPTER_REGISTRY["eightfold_playwright"] = EightfoldPlaywrightAdapter
```

- [ ] **Step 4.4: Run tests**

```
pytest tests/test_eightfold_playwright_adapter.py::test_adapter_registered -v
```
Expected: PASS.

- [ ] **Step 4.5: Run full suite**

```
pytest tests/ -v
```
Expected: all PASS.

- [ ] **Step 4.6: Commit**

```bash
git add src/adapters/__init__.py
git commit -m "feat: register eightfold_playwright in ADAPTER_REGISTRY"
```

---

## Task 5: Wire `BrowserClient` lifecycle into `main.py`

**Files:**
- Modify: `main.py`

### What changes

In `do_run()`:
1. After loading companies (line 114), scan for any enabled company with `config.get("use_playwright", False)`.
2. If any found, create a `BrowserClient()`.
3. Wrap the company loop in `try / finally: browser.close()`.
4. Pass `browser=browser` to every adapter instantiation.

Existing line 134:
```python
adapter = adapter_cls(cname, company_cfg.get("config", {}), http)
```
Becomes:
```python
adapter = adapter_cls(cname, company_cfg.get("config", {}), http, browser=browser)
```

- [ ] **Step 5.1: Add the import and modify `do_run()` in `main.py`**

Add the import near the top (after `from src.http import HTTPClient`):

```python
from src.browser import BrowserClient
```

Replace the block from line 113 to line 135 (companies setup through adapter instantiation):

```python
    # Determine which companies to process
    companies = config.companies
    if getattr(args, "company", None):
        companies = [c for c in companies if c.get("name") == args.company]

    delay_range = config.defaults.get("request_delay_seconds", [2, 4])
    min_delay = float(delay_range[0]) if isinstance(delay_range, list) else 2.0
    max_delay = float(delay_range[1]) if isinstance(delay_range, (list, tuple)) and len(delay_range) > 1 else 4.0

    # Lazy-start a BrowserClient only if at least one enabled company needs it
    needs_browser = any(
        c.get("enabled", True) and c.get("config", {}).get("use_playwright", False)
        for c in companies
    )
    browser = BrowserClient() if needs_browser else None

    try:
        for company_cfg in companies:
            if not company_cfg.get("enabled", True):
                continue

            cname = company_cfg["name"]
            adapter_key = company_cfg.get("adapter")

            if adapter_key not in ADAPTER_REGISTRY:
                logger.debug(f"Skipping {cname}: adapter '{adapter_key}' not registered")
                continue

            adapter_cls = ADAPTER_REGISTRY[adapter_key]
            adapter = adapter_cls(cname, company_cfg.get("config", {}), http, browser=browser)
```

Then close the `try` block after the existing company loop body, and add the `finally` before the post-loop state save section. The full replacement section (lines 113–185 in the original, ending with `http.polite_delay(...)`) should become:

```python
    # Determine which companies to process
    companies = config.companies
    if getattr(args, "company", None):
        companies = [c for c in companies if c.get("name") == args.company]

    delay_range = config.defaults.get("request_delay_seconds", [2, 4])
    min_delay = float(delay_range[0]) if isinstance(delay_range, list) else 2.0
    max_delay = float(delay_range[1]) if isinstance(delay_range, (list, tuple)) and len(delay_range) > 1 else 4.0

    needs_browser = any(
        c.get("enabled", True) and c.get("config", {}).get("use_playwright", False)
        for c in companies
    )
    browser = BrowserClient() if needs_browser else None

    try:
        for company_cfg in companies:
            if not company_cfg.get("enabled", True):
                continue

            cname = company_cfg["name"]
            adapter_key = company_cfg.get("adapter")

            if adapter_key not in ADAPTER_REGISTRY:
                logger.debug(f"Skipping {cname}: adapter '{adapter_key}' not registered")
                continue

            adapter_cls = ADAPTER_REGISTRY[adapter_key]
            adapter = adapter_cls(cname, company_cfg.get("config", {}), http, browser=browser)

            fetched = []
            try:
                fetched = list(adapter.fetch())
                any_company_succeeded = True
            except Exception as e:
                logger.error(f"{cname}: fetch failed: {e}", exc_info=True)

            # Apply filter pipeline
            source_config = company_cfg.get("config", {})
            matched = []
            filter_reasons = {}
            for job in fetched:
                filtered_job, reasons = apply_filter_pipeline(job, config.filters, source_config)
                if filtered_job is not None:
                    matched.append(filtered_job)
                filter_reasons[job.id] = reasons

            # Diff against state
            new_jobs = get_new_jobs(matched, cname, state)

            alerted = 0
            for job in new_jobs:
                if notify and not getattr(args, "dry_run", False):
                    if not cap_hit:
                        if alert_count >= max_alerts:
                            cap_hit = True
                            if notifier:
                                notifier.send_summary(
                                    title="⚠️ Alert Cap Reached",
                                    description=f"Max alerts per run ({max_alerts}) reached. Remaining jobs silenced.",
                                )
                        else:
                            if notifier:
                                notifier.send_job_alert(job)
                            alert_count += 1
                            alerted += 1
                elif summary_mode:
                    summary_jobs.append(job)

            # Mark seen (even in dry-run)
            mark_seen(new_jobs, cname, state)

            if getattr(args, "verbose", False):
                print(
                    f"{cname}: fetched={len(fetched)} matched={len(matched)} "
                    f"new={len(new_jobs)} alerted={alerted}"
                )

            # Polite delay between companies
            http.polite_delay(min_delay, max_delay)

    finally:
        if browser is not None:
            browser.close()
```

- [ ] **Step 5.2: Run full test suite to verify no regressions**

```
pytest tests/ -v
```
Expected: all PASS.

- [ ] **Step 5.3: Commit**

```bash
git add main.py
git commit -m "feat: wire BrowserClient lifecycle into do_run() with lazy start and guaranteed teardown"
```

---

## Task 6: Update `companies.yaml` — Snowflake switches to `eightfold_playwright`

**Files:**
- Modify: `companies.yaml` (lines 206–212)

- [ ] **Step 6.1: Replace the Snowflake entry**

Find (lines 206–212):
```yaml
  - name: Snowflake
    adapter: eightfold
    enabled: true
    config:
      base_url: https://careers.snowflake.com
      api_path: /api/apply/v2/jobs
      location_country: United States
```

Replace with:
```yaml
  - name: Snowflake
    adapter: eightfold_playwright
    enabled: true
    config:
      base_url: https://careers.snowflake.com
      api_path: /api/apply/v2/jobs
      location_country: United States
      use_playwright: true
      browser_timeout_seconds: 30
```

- [ ] **Step 6.2: Validate config**

```
python main.py validate-config
```
Expected: `Config is valid.`

- [ ] **Step 6.3: Commit**

```bash
git add companies.yaml
git commit -m "config: switch Snowflake to eightfold_playwright adapter"
```

---

## Task 7: Add `playwright` to `requirements.txt` and update CI

**Files:**
- Modify: `requirements.txt`
- Modify: `.github/workflows/job-alerts.yml`
- Modify: `.gitignore`

- [ ] **Step 7.1: Add playwright to `requirements.txt`**

Append after `responses>=0.25`:
```
playwright>=1.45
```

- [ ] **Step 7.2: Add cache + chromium install steps to `.github/workflows/job-alerts.yml`**

After the `Install dependencies` step, add two new steps:

```yaml
      - name: Cache Playwright browsers
        uses: actions/cache@v4
        with:
          path: ~/.cache/ms-playwright
          key: playwright-${{ runner.os }}-${{ hashFiles('requirements.txt') }}
      - name: Install Chromium
        run: python -m playwright install --with-deps chromium
```

The full `steps:` section should look like:

```yaml
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Cache Playwright browsers
        uses: actions/cache@v4
        with:
          path: ~/.cache/ms-playwright
          key: playwright-${{ runner.os }}-${{ hashFiles('requirements.txt') }}
      - name: Install Chromium
        run: python -m playwright install --with-deps chromium
      - name: Run job alerts
        run: python main.py run
        env:
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
      - name: Commit state
        run: |
          git config user.name  "job-alerts-bot"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state/seen_jobs.json
          git diff --cached --quiet || (git commit -m "state: $(date -u +%FT%TZ)" && git pull --rebase origin main && git push)
```

Note: if the `hashFiles('requirements.txt')` key causes unwanted cache misses in practice, remove the cache step and let chromium install every run (~2 min overhead, acceptable at 15-min cadence).

- [ ] **Step 7.3: Add `debug_artifacts/` to `.gitignore`**

Append to `.gitignore`:
```
debug_artifacts/
```

- [ ] **Step 7.4: Verify config still validates**

```
python main.py validate-config --dry-run
```
Expected: `Config is valid.`

- [ ] **Step 7.5: Commit**

```bash
git add requirements.txt .github/workflows/job-alerts.yml .gitignore
git commit -m "chore: add playwright dep, chromium CI install, gitignore debug_artifacts"
```

---

## Task 8: Update `README.md` with v2 Playwright section

**Files:**
- Modify: `README.md`

- [ ] **Step 8.1: Replace the stub in section 11 (lines 153–163) with the full v2 section**

Replace the existing `## 11. Adding Playwright (future)` section with:

```markdown
## 11. Playwright — JavaScript-Rendered Career Sites (v2)

Some career sites are JavaScript-rendered SPAs that the plain `requests`-based
pipeline cannot authenticate. The **hybrid approach** boots the SPA once with
a headless Chromium browser to capture session cookies, then uses the normal
HTTP client for all subsequent JSON pagination.

**Currently enabled:** Snowflake only (`adapter: eightfold_playwright`).
Microsoft Research, Applied Digital, and Oracle are disabled pending separate plans.

### Local setup

```bash
# Step 1: Python package (already in requirements.txt)
pip install -r requirements.txt

# Step 2: Chromium binary (only needed to run browser-enabled adapters)
python -m playwright install chromium
```

The Python package is always installed. The Chromium binary is only needed
in environments where a browser-enabled adapter is active. If Snowflake is
disabled (`enabled: false` in `companies.yaml`), no browser is ever started.

### Running Snowflake locally

```bash
# Single-company dry run with verbose output
python main.py run --company Snowflake --dry-run --verbose
```

On success you will see output like:
```
Snowflake: fetched=40 matched=12 new=12 alerted=0
```

### Debug artifacts

If the browser bootstrap fails (timeout, anti-bot block, network error),
artifacts are saved to:

```
debug_artifacts/Snowflake/<timestamp>/
├── screenshot.png     # page state at failure
├── page.html          # DOM dump (capped at 1 MB)
└── error.txt          # exception type + message
```

The `debug_artifacts/` directory is gitignored and never committed.

### Disabling Snowflake

Set `enabled: false` in `companies.yaml`:

```yaml
- name: Snowflake
  adapter: eightfold_playwright
  enabled: false          # ← disable here; Chromium will not start
  config:
    ...
```

### Adding more Playwright adapters (future)

1. Set `use_playwright: true` in the company's `config` block.
2. Create `src/adapters/<name>_playwright.py`, extending `BaseAdapter` with
   `self.browser` for the bootstrap session and `self.http` for API calls.
3. Register in `src/adapters/__init__.py`.
4. See `src/adapters/eightfold_playwright.py` as the reference implementation.
```

- [ ] **Step 8.2: Commit**

```bash
git add README.md
git commit -m "docs: add v2 Playwright section to README"
```

---

## Task 9: End-to-end verification

- [ ] **Step 9.1: Install playwright locally if not already done**

```bash
python -m playwright install chromium
```

Expected: downloads or confirms chromium is installed.

- [ ] **Step 9.2: Run the full test suite (no live browser)**

```
pytest tests/ -v
```
Expected: all tests PASS. The Playwright tests use `MagicMock` — no chromium started.

- [ ] **Step 9.3: Local dry-run — Snowflake only**

```bash
python main.py run --company Snowflake --dry-run --verbose
```
Expected output (approximately):
```
Snowflake: fetched=<N> matched=<M> new=<K> alerted=0
```
`fetched` should be > 0. If 0, check the browser bootstrap: try `DEBUG=True` or inspect `debug_artifacts/` if a failure occurred.

- [ ] **Step 9.4: Verify no-browser run when Snowflake disabled**

In `companies.yaml`, temporarily set `enabled: false` for Snowflake, then:

```bash
python main.py run --dry-run --verbose 2>&1 | grep -i playwright
```
Expected: zero Playwright-related log lines (chromium never starts).

Restore `enabled: true` before committing.

- [ ] **Step 9.5: Verify debug artifacts on forced failure**

In `companies.yaml`, temporarily change Snowflake `base_url` to `https://httpstat.us/404`, then:

```bash
python main.py run --company Snowflake --dry-run --verbose
```
Expected: `debug_artifacts/Snowflake/<timestamp>/error.txt` exists. Restore `base_url` before committing.

- [ ] **Step 9.6: Push to GitHub and confirm CI**

```bash
git push origin main
```

Go to the GitHub Actions tab → Job Alerts workflow → trigger `workflow_dispatch`.

- First run: chromium will download (~150 MB, expect 1–2 min extra). Confirm the run completes without error.
- Second run (15 min later or another dispatch): cache hits, setup is < 10 s.
- Confirm Snowflake jobs appear in the run log (`Snowflake: fetched=N matched=M new=K`).

---

## Self-Review Checklist

- [x] `BrowserSessionContext` frozen dataclass matches usage in tests and adapter
- [x] `bootstrap_session` signature `(url, *, company, wait_for_selector, wait_for_response_url, timeout_seconds)` matches all call sites in `eightfold_playwright.py`
- [x] `_parse_position(pos, company, source_platform, detected_at)` signature matches the call in `EightfoldPlaywrightAdapter.fetch()`
- [x] `BrowserClient.close()` loop uses correct method names: `context.close()`, `browser.close()`, `pw.stop()`
- [x] `main.py` `needs_browser` scan reads `c.get("config", {}).get("use_playwright", False)` — matches `companies.yaml` nesting
- [x] `browser=browser` kwarg passed at `adapter_cls(...)` call — matches `BaseAdapter.__init__` new signature
- [x] `TYPE_CHECKING` guard in `base.py` prevents circular import at runtime
- [x] `debug_artifacts/` in `.gitignore`
- [x] `--company`, `--dry-run`, `--verbose` flags confirmed at `main.py:252-254`
- [x] No `--only` flag invented — `--company` is the correct flag
- [x] Only `src/browser.py` and `src/adapters/eightfold_playwright.py` import `playwright.*`
- [x] `eightfold.py` not modified anywhere in this plan
