"""Tests for EightfoldAdapter (Snowflake).

Live endpoint notes (tested 2026-05-07):
  https://careers.snowflake.com/api/apply/v2/jobs returns
  {"status":"failure","errorMsg":"Tenant not identified"} for all tested
  domain/tenant params without browser-session cookies. The careers site
  uses Phenom People (phenompeople.com) as the SPA layer on top of Eightfold.
  The adapter handles this gracefully by returning [] with a log warning.

Tests use the fixture at tests/fixtures/eightfold_snowflake.json which
represents the expected success response shape.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.adapters.eightfold import EightfoldAdapter
from src.http import HTTPClient
from src.models import Job

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "eightfold_snowflake.json"

_CONFIG = {
    "base_url": "https://careers.snowflake.com",
    "api_path": "/api/apply/v2/jobs",
    "location_country": "United States",
}


def _make_adapter(config: dict | None = None) -> EightfoldAdapter:
    http = MagicMock(spec=HTTPClient)
    return EightfoldAdapter(
        company="snowflake",
        config=config or _CONFIG,
        http=http,
    )


def _mock_response(data: dict | str | None = None, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = (status < 400)
    resp.status_code = status
    if data is not None:
        if isinstance(data, str):
            resp.json.return_value = json.loads(data)
        else:
            resp.json.return_value = data
    else:
        resp.json.side_effect = ValueError("no content")
    return resp


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def test_field_mapping():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert len(jobs) == 2
    first: Job = jobs[0]

    assert first.source_platform == "eightfold"
    assert first.company == "snowflake"
    assert first.title == "Software Engineer Intern"
    assert first.location == "San Mateo, California"
    assert first.department == "Engineering"
    assert "careers.snowflake.com" in first.url


def test_official_id_in_job_id():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert jobs[0].id == "snowflake::eightfold::12345"
    assert jobs[1].id == "snowflake::eightfold::67890"


def test_posted_at_parsed_from_t_create():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert isinstance(jobs[0].posted_at, datetime)
    assert jobs[0].posted_at == datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)


def test_raw_text_lowercased_contains_fields():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())
    raw = jobs[0].raw_text

    assert "software engineer intern" in raw
    assert "san mateo" in raw
    assert "engineering" in raw


def test_description_html_stripped():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    # raw_text should not contain HTML tags
    assert "<p>" not in jobs[0].raw_text
    assert "<br" not in jobs[0].raw_text


def test_role_type_defaults_to_unknown():
    adapter = _make_adapter()
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(payload)

    for job in adapter.fetch():
        assert job.role_type == "unknown"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_pagination_stops_when_total_reached():
    """Adapter stops fetching pages when offset >= total."""
    adapter = _make_adapter()

    # First call returns 2 jobs with count=2 (no next page)
    payload = json.loads(FIXTURE_PATH.read_text())
    # count=2, limit=20 → offset 20 >= 2, so only one request
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())
    assert len(jobs) == 2
    assert adapter.http.get.call_count == 1


def test_pagination_multiple_pages():
    """When count > limit, adapter fetches additional pages."""
    adapter = _make_adapter()

    # First page: 1 job, count=21 (signals more pages exist)
    page1 = {
        "status": "success",
        "data": {
            "count": 21,
            "positions": [
                {
                    "id": "111",
                    "name": "Backend Engineer Intern",
                    "location": "San Mateo, CA",
                    "department": "Engineering",
                    "canonicalPositionUrl": "https://careers.snowflake.com/job/111",
                    "t_create": "2025-01-01T00:00:00Z",
                    "description": "Work on backend systems.",
                }
            ] * 20,  # 20 positions on first page
        }
    }
    page2 = {
        "status": "success",
        "data": {
            "count": 21,
            "positions": [
                {
                    "id": "222",
                    "name": "Frontend Engineer Intern",
                    "location": "Bellevue, WA",
                    "department": "Engineering",
                    "canonicalPositionUrl": "https://careers.snowflake.com/job/222",
                    "t_create": "2025-01-02T00:00:00Z",
                    "description": "Work on frontend.",
                }
            ],
        }
    }
    adapter.http.get.side_effect = [
        _mock_response(page1),
        _mock_response(page2),
    ]

    jobs = list(adapter.fetch())
    assert adapter.http.get.call_count == 2
    assert len(jobs) == 21


def test_empty_positions_stops_pagination():
    """Empty positions list stops the loop without error."""
    adapter = _make_adapter()
    payload = {"status": "success", "data": {"count": 0, "positions": []}}
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())
    assert jobs == []
    assert adapter.http.get.call_count == 1


# ---------------------------------------------------------------------------
# Top-level response shape (positions at root, no "data" wrapper)
# ---------------------------------------------------------------------------

def test_top_level_positions_shape():
    """Adapter handles positions directly at root (no 'data' wrapper)."""
    adapter = _make_adapter()
    payload = {
        "count": 1,
        "positions": [
            {
                "id": "999",
                "name": "ML Engineer Intern",
                "location": "Bellevue, WA",
                "department": "AI",
                "canonicalPositionUrl": "https://careers.snowflake.com/job/999",
                "t_create": None,
                "description": "Work on ML.",
            }
        ]
    }
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    assert jobs[0].title == "ML Engineer Intern"


# ---------------------------------------------------------------------------
# Error handling — never raises, always returns []
# ---------------------------------------------------------------------------

def test_http_error_returns_empty():
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.RequestException("connection error")

    jobs = list(adapter.fetch())
    assert jobs == []


def test_non_ok_status_returns_empty():
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(status=500)

    jobs = list(adapter.fetch())
    assert jobs == []


def test_eightfold_failure_status_returns_empty():
    """API failure (tenant not identified) returns [] with no exception."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response({
        "status": "failure",
        "errorCode": None,
        "errorMsg": "Tenant not identified",
        "data": None,
    })

    jobs = list(adapter.fetch())
    assert jobs == []


def test_json_parse_error_returns_empty():
    adapter = _make_adapter()
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.side_effect = ValueError("bad json")
    adapter.http.get.return_value = resp

    jobs = list(adapter.fetch())
    assert jobs == []


def test_missing_title_skips_position():
    """Positions without a name/title are skipped."""
    adapter = _make_adapter()
    payload = {
        "status": "success",
        "data": {
            "count": 2,
            "positions": [
                {"id": "1", "name": "", "location": "CA", "department": "Eng", "canonicalPositionUrl": "https://x.com/1", "t_create": None, "description": ""},
                {"id": "2", "name": "Valid Role", "location": "CA", "department": "Eng", "canonicalPositionUrl": "https://x.com/2", "t_create": None, "description": ""},
            ]
        }
    }
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    assert jobs[0].title == "Valid Role"


# ---------------------------------------------------------------------------
# source_platform constant
# ---------------------------------------------------------------------------

def test_source_platform_constant():
    assert EightfoldAdapter.source_platform == "eightfold"
