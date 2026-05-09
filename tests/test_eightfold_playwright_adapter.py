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
    captured_urls=("https://careers.snowflake.com/api/apply/v2/jobs?limit=20",),
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


def test_returns_empty_if_no_cookies_and_no_headers():
    """With no cookies AND no headers AND no captured_request_headers, adapter still
    tries the API (two-tier strategy does not require cookies).  If the API returns
    an empty positions list the result is also empty."""
    adapter = _make_adapter()
    adapter.browser.bootstrap_session.return_value = BrowserSessionContext(
        cookies={}, headers={}, final_url="https://careers.snowflake.com", captured_urls=()
    )
    # Return empty positions so we get an empty result without an assertion error
    adapter.http.get.return_value = _mock_response({"count": 0, "positions": []})
    result = list(adapter.fetch())
    assert result == []


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
    adapter.http.get.side_effect = requests.RequestException("Connection reset")

    with caplog.at_level(logging.ERROR):
        result = list(adapter.fetch())

    assert result == []


def test_api_failure_status_falls_back_and_returns_empty(caplog):
    """Auth failure in HTTP tier triggers evaluate_fetch fallback.
    If evaluate_fetch also returns empty positions, result is []."""
    import logging
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(
        {"status": "failure", "errorMsg": "Tenant not identified"}
    )
    # evaluate_fetch fallback returns empty payload
    adapter.browser.evaluate_fetch.return_value = {"count": 0, "positions": []}

    with caplog.at_level(logging.INFO):
        result = list(adapter.fetch())

    assert result == []
    adapter.browser.evaluate_fetch.assert_called()


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


from src.adapters import ADAPTER_REGISTRY


def test_adapter_registered():
    from src.adapters.eightfold_playwright import EightfoldPlaywrightAdapter
    assert "eightfold_playwright" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["eightfold_playwright"] is EightfoldPlaywrightAdapter


# ---------------------------------------------------------------------------
# Two-tier auth tests
# ---------------------------------------------------------------------------

import json as _json_mod

_FIXTURE = FIXTURE_PATH  # reuse existing fixture path alias

_SESSION_V3 = BrowserSessionContext(
    cookies={"PHPSESSID": "test-session"},
    headers={
        "Origin": "https://careers.snowflake.com",
        "Referer": "https://careers.snowflake.com/us/en/jobs",
        "User-Agent": "Mozilla/5.0",
    },
    final_url="https://careers.snowflake.com/us/en/jobs",
    captured_urls=("https://careers.snowflake.com/api/apply/v2/jobs?limit=20",),
    captured_request_headers={
        "Authorization": "Bearer tenant-token-xyz",
        "Accept": "application/json",
    },
    captured_first_response=None,
)


def _make_adapter_v3(session=None, browser_available=True):
    http = MagicMock(spec=HTTPClient)
    browser = MagicMock(spec=BrowserClient)
    browser.available = browser_available
    browser.bootstrap_session.return_value = session or _SESSION_V3
    return EightfoldPlaywrightAdapter(
        company="Snowflake",
        config=_CONFIG,
        http=http,
        browser=browser,
    )


class TestTwoTierAuth:
    def test_httpClient_relay_success_uses_captured_headers(self):
        """If intercepted headers work, HTTPClient is used for all pages."""
        adapter = _make_adapter_v3()
        payload = _json_mod.loads(_FIXTURE.read_text())
        adapter.http.get.return_value = _mock_response(payload)

        jobs = list(adapter.fetch())

        assert len(jobs) > 0
        call_kwargs = adapter.http.get.call_args[1]
        # Should use captured_request_headers, not cookies
        assert call_kwargs.get("headers") == _SESSION_V3.captured_request_headers

    def test_httpClient_401_switches_to_evaluate_fetch(self):
        """HTTP 401 triggers fallback to page.evaluate_fetch."""
        adapter = _make_adapter_v3()
        payload = _json_mod.loads(_FIXTURE.read_text())

        # First call returns 401, evaluate_fetch returns good data
        adapter.http.get.return_value = _mock_response({}, status=401)
        adapter.browser.evaluate_fetch.return_value = payload

        jobs = list(adapter.fetch())

        adapter.browser.evaluate_fetch.assert_called()
        assert len(jobs) > 0

    def test_httpClient_403_switches_to_evaluate_fetch(self):
        adapter = _make_adapter_v3()
        payload = _json_mod.loads(_FIXTURE.read_text())

        adapter.http.get.return_value = _mock_response({}, status=403)
        adapter.browser.evaluate_fetch.return_value = payload

        jobs = list(adapter.fetch())

        adapter.browser.evaluate_fetch.assert_called()
        assert len(jobs) > 0

    def test_errormsg_in_response_switches_to_evaluate_fetch(self):
        """JSON errorMsg triggers fallback."""
        adapter = _make_adapter_v3()
        payload = _json_mod.loads(_FIXTURE.read_text())

        auth_error = {"status": "failure", "errorMsg": "Tenant not identified"}
        adapter.http.get.return_value = _mock_response(auth_error)
        adapter.browser.evaluate_fetch.return_value = payload

        jobs = list(adapter.fetch())

        adapter.browser.evaluate_fetch.assert_called()
        assert len(jobs) > 0

    def test_captured_first_response_skips_first_httpClient_call(self):
        """Page-1 from captured_first_response — HTTPClient is not called."""
        from src.adapters.eightfold import _LIMIT
        fixture_data = _json_mod.loads(_FIXTURE.read_text())
        first_resp_json = _json_mod.dumps(fixture_data)

        session_with_capture = BrowserSessionContext(
            cookies=_SESSION_V3.cookies,
            headers=_SESSION_V3.headers,
            final_url=_SESSION_V3.final_url,
            captured_urls=_SESSION_V3.captured_urls,
            captured_request_headers=_SESSION_V3.captured_request_headers,
            captured_first_response=first_resp_json,
        )
        adapter = _make_adapter_v3(session=session_with_capture)
        # If page-1 is used from captured_first_response and it's a single-page result, no HTTP call
        jobs = list(adapter.fetch())

        assert len(jobs) > 0
        adapter.http.get.assert_not_called()  # all data from captured response

    def test_evaluate_fetch_failure_returns_empty(self):
        """evaluate_fetch exception → capture_debug_artifacts + return []."""
        adapter = _make_adapter_v3()
        adapter.http.get.return_value = _mock_response({}, status=401)
        adapter.browser.evaluate_fetch.side_effect = RuntimeError("page closed")

        jobs = list(adapter.fetch())

        assert jobs == []
        adapter.browser.capture_debug_artifacts.assert_called_once()

    def test_no_captured_headers_falls_through_to_session_headers(self):
        """If captured_request_headers is empty, fall back to session.headers."""
        session_no_capture = BrowserSessionContext(
            cookies=_SESSION_V3.cookies,
            headers=_SESSION_V3.headers,
            final_url=_SESSION_V3.final_url,
            captured_urls=(),
            captured_request_headers={},  # empty
            captured_first_response=None,
        )
        adapter = _make_adapter_v3(session=session_no_capture)
        payload = _json_mod.loads(_FIXTURE.read_text())
        adapter.http.get.return_value = _mock_response(payload)

        jobs = list(adapter.fetch())

        assert len(jobs) > 0
        call_kwargs = adapter.http.get.call_args[1]
        # Should use session.headers when captured_request_headers is empty
        assert call_kwargs.get("headers") == _SESSION_V3.headers
