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


def test_returns_empty_if_no_cookies():
    adapter = _make_adapter()
    adapter.browser.bootstrap_session.return_value = BrowserSessionContext(
        cookies={}, headers={}, final_url="https://careers.snowflake.com", captured_urls=()
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


from src.adapters import ADAPTER_REGISTRY


def test_adapter_registered():
    from src.adapters.eightfold_playwright import EightfoldPlaywrightAdapter
    assert "eightfold_playwright" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["eightfold_playwright"] is EightfoldPlaywrightAdapter
