# tests/test_smartrecruiters_adapter.py
"""Tests for SmartRecruitersAdapter."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
import requests

from src.adapters.smartrecruiters import SmartRecruitersAdapter
from src.http import HTTPClient
from src.models import Job

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "smartrecruiters_western_digital.json"


def _make_adapter(slug: str = "WesternDigital") -> SmartRecruitersAdapter:
    http = MagicMock(spec=HTTPClient)
    return SmartRecruitersAdapter(
        company="western_digital", config={"slug": slug}, http=http
    )


def _mock_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def test_fixture_file_exists():
    assert FIXTURE_PATH.exists(), f"Fixture missing: {FIXTURE_PATH}"


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def test_field_mapping():
    adapter = _make_adapter()
    fixture = json.loads(FIXTURE_PATH.read_text())
    # Fixture has totalFound=150 but only 2 items in content; make it self-contained.
    fixture_single_page = dict(fixture, totalFound=2)
    adapter.http.get.return_value = _mock_response(fixture_single_page)

    jobs = list(adapter.fetch())

    assert len(jobs) == 2
    first: Job = jobs[0]

    assert first.source_platform == "smartrecruiters"
    assert first.title == "Intern - Environmental Specialist"
    assert first.company == "western_digital"
    assert first.url == "https://jobs.smartrecruiters.com/WesternDigital/744000125027538"


def test_url_is_job_posting_not_api():
    """URL must point to the apply page, not the internal API endpoint."""
    adapter = _make_adapter()
    fixture = json.loads(FIXTURE_PATH.read_text())
    fixture_single_page = dict(fixture, totalFound=2)
    adapter.http.get.return_value = _mock_response(fixture_single_page)

    jobs = list(adapter.fetch())
    assert jobs[0].url == "https://jobs.smartrecruiters.com/WesternDigital/744000125027538"


def test_source_platform_is_smartrecruiters():
    adapter = _make_adapter()
    fixture = json.loads(FIXTURE_PATH.read_text())
    fixture_single_page = dict(fixture, totalFound=2)
    adapter.http.get.return_value = _mock_response(fixture_single_page)

    for job in adapter.fetch():
        assert job.source_platform == "smartrecruiters"


def test_official_id_in_job_id():
    adapter = _make_adapter()
    fixture = json.loads(FIXTURE_PATH.read_text())
    fixture_single_page = dict(fixture, totalFound=2)
    adapter.http.get.return_value = _mock_response(fixture_single_page)

    jobs = list(adapter.fetch())
    assert jobs[0].id == "western_digital::smartrecruiters::744000125027538"


# ---------------------------------------------------------------------------
# Location assembly
# ---------------------------------------------------------------------------

def test_location_assembled_from_city_region_country():
    adapter = _make_adapter()
    fixture = json.loads(FIXTURE_PATH.read_text())
    fixture_single_page = dict(fixture, totalFound=2)
    adapter.http.get.return_value = _mock_response(fixture_single_page)

    jobs = list(adapter.fetch())
    assert jobs[0].location == "San Jose, California, US"


def test_location_skips_none_parts():
    adapter = _make_adapter()
    item = {
        "id": "loc001",
        "name": "Test Job",
        "location": {"city": "Austin", "region": None, "country": "US"},
        "department": {"label": "Engineering"},
        "typeOfEmployment": {"label": "Intern"},
        "releasedDate": "2025-01-15T00:00:00Z",
        "ref": "https://example.com/job/loc001",
    }
    page = {"totalFound": 1, "offset": 0, "limit": 100, "content": [item]}
    adapter.http.get.return_value = _mock_response(page)

    jobs = list(adapter.fetch())
    assert jobs[0].location == "Austin, US"


def test_empty_department_returns_none():
    """department: {} (empty dict) should map to None."""
    adapter = _make_adapter()
    fixture = json.loads(FIXTURE_PATH.read_text())
    fixture_single_page = dict(fixture, totalFound=2)
    adapter.http.get.return_value = _mock_response(fixture_single_page)

    jobs = list(adapter.fetch())
    # Second item has department: {}
    assert jobs[1].department is None


# ---------------------------------------------------------------------------
# posted_at from releasedDate
# ---------------------------------------------------------------------------

def test_released_date_parsed():
    adapter = _make_adapter()
    fixture = json.loads(FIXTURE_PATH.read_text())
    fixture_single_page = dict(fixture, totalFound=2)
    adapter.http.get.return_value = _mock_response(fixture_single_page)

    jobs = list(adapter.fetch())
    expected = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert jobs[0].posted_at == expected


# ---------------------------------------------------------------------------
# raw_text lowercased
# ---------------------------------------------------------------------------

def test_raw_text_lowercased():
    adapter = _make_adapter()
    fixture = json.loads(FIXTURE_PATH.read_text())
    fixture_single_page = dict(fixture, totalFound=2)
    adapter.http.get.return_value = _mock_response(fixture_single_page)

    for job in adapter.fetch():
        assert job.raw_text == job.raw_text.lower()


# ---------------------------------------------------------------------------
# Pagination: totalFound=150 → 2 pages fetched, all jobs yielded
# ---------------------------------------------------------------------------

def _make_page(total: int, offset: int, count: int, start_id: int = 1) -> dict:
    """Build a synthetic page with `count` items."""
    content = [
        {
            "id": str(start_id + i),
            "name": f"Job {start_id + i}",
            "location": {"city": "San Jose", "region": "CA", "country": "US"},
            "department": {"label": "Engineering"},
            "typeOfEmployment": {"label": "Intern"},
            "releasedDate": "2025-06-01T00:00:00Z",
            "ref": f"https://example.com/job/{start_id + i}",
        }
        for i in range(count)
    ]
    return {"totalFound": total, "offset": offset, "limit": 100, "content": content}


def test_pagination_two_pages():
    """totalFound=150 → page1 (100 items) + page2 (50 items) = 150 jobs yielded."""
    adapter = _make_adapter()

    page1 = _make_page(total=150, offset=0, count=100, start_id=1)
    page2 = _make_page(total=150, offset=100, count=50, start_id=101)

    adapter.http.get.side_effect = [
        _mock_response(page1),
        _mock_response(page2),
    ]

    jobs = list(adapter.fetch())
    assert len(jobs) == 150
    assert adapter.http.get.call_count == 2


def test_pagination_page1_params():
    """Verify first GET is called with offset=0, limit=100."""
    adapter = _make_adapter()
    page1 = _make_page(total=50, offset=0, count=50, start_id=1)
    adapter.http.get.return_value = _mock_response(page1)

    list(adapter.fetch())

    adapter.http.get.assert_called_once_with(
        "https://api.smartrecruiters.com/v1/companies/WesternDigital/postings",
        params={"limit": 100, "offset": 0},
    )


# ---------------------------------------------------------------------------
# HTTP error on page 2 → yields first 100, stops cleanly
# ---------------------------------------------------------------------------

def test_http_error_page2_yields_first_page():
    adapter = _make_adapter()

    page1 = _make_page(total=150, offset=0, count=100, start_id=1)
    adapter.http.get.side_effect = [
        _mock_response(page1),
        requests.RequestException("timeout"),
    ]

    jobs = list(adapter.fetch())  # must not raise
    assert len(jobs) == 100


# ---------------------------------------------------------------------------
# HTTP error on page 1 → yields nothing
# ---------------------------------------------------------------------------

def test_http_error_page1_yields_nothing():
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.RequestException("dns failure")

    jobs = list(adapter.fetch())
    assert jobs == []
