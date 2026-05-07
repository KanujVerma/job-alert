"""Tests for MicrosoftResearchAdapter.

Strategy used (tested 2026-05-07):
  1. Attempt Eightfold API at apply.careers.microsoft.com with domain=microsoft.com.
     Live result: HTTP 403 {"message": "Not authorized for PCSX"} — requires SPA auth.
  2. Fallback: HTML scrape of jobs.careers.microsoft.com/global/en/search with
     __NEXT_DATA__ JSON extraction. Live result: page is JS-rendered SPA (Eightfold),
     no __NEXT_DATA__ in static HTML, no job data accessible.

  The adapter returns [] with a log warning when both strategies fail. It NEVER raises.
  Tests verify:
    - Correct field mapping when API returns valid data (using fixture JSON)
    - Empty list returned on HTTP error without exception
    - Empty list returned on Eightfold failure status
    - Fallback to HTML scrape when Eightfold API fails
    - __NEXT_DATA__ parsing when present
    - No exception on any failure path
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
import requests

from src.adapters.microsoft_research import MicrosoftResearchAdapter
from src.http import HTTPClient
from src.models import Job

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "microsoft_research.json"

_CONFIG = {
    "base_url": "https://www.microsoft.com/en-us/research/careers/open-positions/",
}


def _make_adapter(config: dict | None = None) -> MicrosoftResearchAdapter:
    http = MagicMock(spec=HTTPClient)
    return MicrosoftResearchAdapter(
        company="microsoft research",
        config=config or _CONFIG,
        http=http,
    )


def _mock_response(data=None, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = (status < 400)
    resp.status_code = status
    if data is not None:
        if isinstance(data, str):
            resp.text = data
            try:
                resp.json.return_value = json.loads(data)
            except ValueError:
                resp.json.side_effect = ValueError("not json")
        elif isinstance(data, dict):
            resp.json.return_value = data
            resp.text = json.dumps(data)
        else:
            resp.json.return_value = data
            resp.text = str(data)
    else:
        resp.json.side_effect = ValueError("no content")
        resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# Successful Eightfold API response
# ---------------------------------------------------------------------------

def test_field_mapping_with_fixture():
    """When Eightfold API returns valid data, jobs are yielded with correct fields."""
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    # First call: Eightfold API succeeds
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert len(jobs) == 2
    first: Job = jobs[0]
    assert first.source_platform == "microsoft_research"
    assert first.company == "microsoft research"
    assert first.title == "Research Intern - Machine Learning"
    assert "Redmond" in first.location
    assert first.department == "Microsoft Research"
    assert "careers.microsoft.com" in first.url


def test_official_id_in_job_id():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert jobs[0].id == "microsoft research::microsoft_research::MSR-001"
    assert jobs[1].id == "microsoft research::microsoft_research::MSR-002"


def test_posted_at_parsed():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert isinstance(jobs[0].posted_at, datetime)
    assert jobs[0].posted_at == datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_source_platform_constant():
    assert MicrosoftResearchAdapter.source_platform == "microsoft_research"


def test_role_type_defaults_to_unknown():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    for job in adapter.fetch():
        assert job.role_type == "unknown"


# ---------------------------------------------------------------------------
# HTTP error — yields nothing, no exception
# ---------------------------------------------------------------------------

def test_http_error_returns_empty():
    """RequestException on Eightfold call → fallback to HTML → also fails → []."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.RequestException("timeout")

    jobs = list(adapter.fetch())
    assert jobs == []


def test_non_ok_status_returns_empty():
    """HTTP 403 on Eightfold → fallback to HTML → 403 → []."""
    adapter = _make_adapter()
    # Both Eightfold and HTML scrape return 403
    adapter.http.get.return_value = _mock_response(
        {"message": "Not authorized for PCSX"}, status=403
    )

    jobs = list(adapter.fetch())
    assert jobs == []


# ---------------------------------------------------------------------------
# Eightfold failure status → fallback to HTML scrape
# ---------------------------------------------------------------------------

def test_eightfold_failure_triggers_html_fallback():
    """Eightfold 'failure' status → attempts HTML scrape as fallback."""
    adapter = _make_adapter()

    eightfold_fail = _mock_response({
        "status": "failure",
        "errorCode": None,
        "errorMsg": "Tenant not identified",
        "data": None,
    })
    # HTML fallback also fails (no jobs)
    html_no_data = _mock_response("<html><body>No jobs here</body></html>")

    adapter.http.get.side_effect = [eightfold_fail, html_no_data]

    jobs = list(adapter.fetch())
    assert jobs == []
    # Two calls: Eightfold + HTML scrape
    assert adapter.http.get.call_count == 2


def test_eightfold_not_authorized_triggers_html_fallback():
    """Eightfold 403 + auth message → falls back to HTML."""
    adapter = _make_adapter()

    eightfold_fail = _mock_response({"message": "Not authorized for PCSX"}, status=403)
    html_no_data = _mock_response("<html><body>SPA content</body></html>")

    adapter.http.get.side_effect = [eightfold_fail, html_no_data]

    jobs = list(adapter.fetch())
    assert jobs == []


# ---------------------------------------------------------------------------
# HTML scrape with __NEXT_DATA__
# ---------------------------------------------------------------------------

def test_next_data_json_parsed_when_present():
    """When __NEXT_DATA__ is present in HTML, jobs are extracted."""
    adapter = _make_adapter()

    # Eightfold fails first
    eightfold_fail = _mock_response({
        "status": "failure",
        "errorMsg": "Tenant not identified",
        "data": None,
    })

    # HTML page with embedded __NEXT_DATA__
    next_data = {
        "props": {
            "pageProps": {
                "jobs": [
                    {
                        "jobId": "R1234567",
                        "title": "Research Intern - NLP",
                        "location": "Redmond, WA",
                        "department": "Microsoft Research",
                        "url": "https://jobs.careers.microsoft.com/job/R1234567",
                    }
                ]
            }
        }
    }
    html_content = f"""
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>
    </body></html>
    """
    html_resp = _mock_response(html_content)

    adapter.http.get.side_effect = [eightfold_fail, html_resp]

    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    assert jobs[0].title == "Research Intern - NLP"
    assert jobs[0].source_platform == "microsoft_research"


def test_next_data_searchresults_fallback():
    """When jobs not at pageProps.jobs, tries pageProps.searchResults."""
    adapter = _make_adapter()

    eightfold_fail = _mock_response({
        "status": "failure",
        "errorMsg": "Tenant not identified",
        "data": None,
    })

    next_data = {
        "props": {
            "pageProps": {
                "searchResults": [
                    {
                        "id": "R9999999",
                        "title": "Research Intern - CV",
                        "location": "Redmond, WA",
                        "department": "Microsoft Research",
                        "url": "https://jobs.careers.microsoft.com/job/R9999999",
                    }
                ]
            }
        }
    }
    html_content = f"""
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>
    </body></html>
    """
    html_resp = _mock_response(html_content)
    adapter.http.get.side_effect = [eightfold_fail, html_resp]

    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    assert jobs[0].title == "Research Intern - CV"


# ---------------------------------------------------------------------------
# No exception on any failure path
# ---------------------------------------------------------------------------

def test_no_exception_on_json_error():
    adapter = _make_adapter()
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.side_effect = ValueError("malformed json")
    resp.text = "<html>some html</html>"
    adapter.http.get.side_effect = [resp, _mock_response("<html></html>")]

    jobs = list(adapter.fetch())
    assert jobs == []


def test_no_exception_on_network_error():
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.ConnectionError("DNS failure")

    jobs = list(adapter.fetch())
    assert jobs == []
