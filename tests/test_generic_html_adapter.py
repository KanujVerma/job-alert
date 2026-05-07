"""Tests for GenericHTMLAdapter (Applied Digital and generic static pages).

Live site notes (tested 2026-05-07):
  https://www.applieddigital.com/careers is a Webflow-hosted SPA.
  The static HTML (27KB) contains no job listings — content is JS-rendered.
  No embedded job board links (Lever, Greenhouse, Ashby, Workday) were found.
  Auto-detection finds no job card elements and returns [] with a log warning.

Tests use the fixture at tests/fixtures/applied_digital.html which represents
a simplified static page with discoverable job elements for testing.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from src.adapters.generic_html import GenericHTMLAdapter
from src.http import HTTPClient
from src.models import Job

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "applied_digital.html"

_BASE_CONFIG = {
    "url": "https://www.applieddigital.com/careers",
    "job_card_selector": "",
    "title_selector": "",
    "location_selector": "",
    "url_selector": "",
}


def _make_adapter(config: dict | None = None) -> GenericHTMLAdapter:
    http = MagicMock(spec=HTTPClient)
    return GenericHTMLAdapter(
        company="applied digital",
        config=_BASE_CONFIG if config is None else config,
        http=http,
    )


def _mock_response(text: str = "", status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = (status < 400)
    resp.status_code = status
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# With explicit CSS selectors → yields Jobs
# ---------------------------------------------------------------------------

def test_explicit_selectors_yield_jobs():
    """With matching CSS selectors, jobs are extracted correctly."""
    adapter = _make_adapter({
        "url": "https://www.applieddigital.com/careers",
        "job_card_selector": ".job-card",
        "title_selector": ".job-title",
        "location_selector": ".job-location",
        "url_selector": "a.job-link",
    })
    html = FIXTURE_PATH.read_text()
    adapter.http.get.return_value = _mock_response(html)

    jobs = list(adapter.fetch())

    assert len(jobs) == 3
    titles = [j.title for j in jobs]
    assert "Software Engineer" in titles
    assert "Data Center Technician" in titles
    assert "Cloud Infrastructure Engineer" in titles


def test_explicit_selectors_field_mapping():
    """Fields are mapped correctly from CSS selectors."""
    adapter = _make_adapter({
        "url": "https://www.applieddigital.com/careers",
        "job_card_selector": ".job-card",
        "title_selector": ".job-title",
        "location_selector": ".job-location",
        "url_selector": "a.job-link",
    })
    html = FIXTURE_PATH.read_text()
    adapter.http.get.return_value = _mock_response(html)

    jobs = list(adapter.fetch())

    first = jobs[0]
    assert first.company == "applied digital"
    assert first.source_platform == "generic_html"
    assert first.location == "Dallas, TX"
    assert "applieddigital.com" in first.url
    assert first.role_type == "unknown"
    assert first.department is None
    assert first.category is None


def test_url_made_absolute():
    """Relative href values are made absolute using the base URL."""
    adapter = _make_adapter({
        "url": "https://www.applieddigital.com/careers",
        "job_card_selector": ".job-card",
        "title_selector": ".job-title",
        "location_selector": ".job-location",
        "url_selector": "a.job-link",
    })
    html = FIXTURE_PATH.read_text()
    adapter.http.get.return_value = _mock_response(html)

    jobs = list(adapter.fetch())

    for job in jobs:
        assert job.url.startswith("https://www.applieddigital.com/")


def test_raw_text_lowercased():
    adapter = _make_adapter({
        "url": "https://www.applieddigital.com/careers",
        "job_card_selector": ".job-card",
        "title_selector": ".job-title",
        "location_selector": ".job-location",
        "url_selector": "a.job-link",
    })
    html = FIXTURE_PATH.read_text()
    adapter.http.get.return_value = _mock_response(html)

    jobs = list(adapter.fetch())

    for job in jobs:
        assert job.raw_text == job.raw_text.lower()


def test_source_platform_constant():
    assert GenericHTMLAdapter.source_platform == "generic_html"


# ---------------------------------------------------------------------------
# Auto-detection with matching HTML
# ---------------------------------------------------------------------------

def test_auto_detection_finds_job_cards():
    """Auto-detection works when HTML has elements with 'job-card' in class."""
    adapter = _make_adapter({
        "url": "https://www.applieddigital.com/careers",
        "job_card_selector": "",
        "title_selector": "",
        "location_selector": "",
        "url_selector": "",
    })
    html = FIXTURE_PATH.read_text()
    adapter.http.get.return_value = _mock_response(html)

    jobs = list(adapter.fetch())

    # Fixture has .job-card elements which auto-detection should find
    assert len(jobs) >= 1


# ---------------------------------------------------------------------------
# With no matching selectors → returns []
# ---------------------------------------------------------------------------

def test_non_matching_selectors_return_empty():
    """CSS selector that matches nothing returns [] without exception."""
    adapter = _make_adapter({
        "url": "https://www.applieddigital.com/careers",
        "job_card_selector": ".this-selector-will-never-match-anything",
        "title_selector": "",
        "location_selector": "",
        "url_selector": "",
    })
    html = FIXTURE_PATH.read_text()
    adapter.http.get.return_value = _mock_response(html)

    jobs = list(adapter.fetch())
    assert jobs == []


def test_no_jobs_on_empty_page():
    """Page with no job elements returns []."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(
        "<html><body><h1>Careers</h1><p>Check back soon.</p></body></html>"
    )

    jobs = list(adapter.fetch())
    assert jobs == []


def test_js_rendered_page_returns_empty():
    """JS-rendered SPA page (no static job content) returns []."""
    adapter = _make_adapter()
    # Simulate what the live Applied Digital page returns
    js_heavy = """
    <!DOCTYPE html><html><head><script>window.__app = {};</script></head>
    <body><div id="root"></div><script src="/main.js"></script></body></html>
    """
    adapter.http.get.return_value = _mock_response(js_heavy)

    jobs = list(adapter.fetch())
    assert jobs == []


# ---------------------------------------------------------------------------
# HTTP error → returns []
# ---------------------------------------------------------------------------

def test_http_error_returns_empty():
    """RequestException returns [] without raising."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.RequestException("connection reset")

    jobs = list(adapter.fetch())
    assert jobs == []


def test_non_ok_status_returns_empty():
    """HTTP 404 returns [] without raising."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response("<html>Not Found</html>", status=404)

    jobs = list(adapter.fetch())
    assert jobs == []


def test_http_500_returns_empty():
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response("<html>Error</html>", status=500)

    jobs = list(adapter.fetch())
    assert jobs == []


# ---------------------------------------------------------------------------
# Missing URL config
# ---------------------------------------------------------------------------

def test_missing_url_config_returns_empty():
    """Adapter with no 'url' in config returns [] immediately."""
    adapter = _make_adapter(config={})

    jobs = list(adapter.fetch())
    assert jobs == []
    # Should not even attempt HTTP
    adapter.http.get.assert_not_called()


# ---------------------------------------------------------------------------
# Location fallback
# ---------------------------------------------------------------------------

def test_location_defaults_to_not_specified_when_absent():
    """When no location element found, defaults to 'Not specified'."""
    adapter = _make_adapter({
        "url": "https://example.com/careers",
        "job_card_selector": ".job",
        "title_selector": "h3",
        "location_selector": ".nonexistent-loc",
        "url_selector": "a",
    })
    html = """
    <html><body>
    <div class="job"><h3>DevOps Engineer</h3><a href="/jobs/devops">Apply</a></div>
    </body></html>
    """
    adapter.http.get.return_value = _mock_response(html)

    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    assert jobs[0].location == "Not specified"
