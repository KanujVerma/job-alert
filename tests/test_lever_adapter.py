# tests/test_lever_adapter.py
"""Tests for LeverAdapter."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.adapters.lever import LeverAdapter
from src.http import HTTPClient
from src.models import Job

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lever_plaid.json"


def _make_adapter(slug: str = "plaid") -> LeverAdapter:
    http = MagicMock(spec=HTTPClient)
    return LeverAdapter(company="plaid", config={"slug": slug}, http=http)


def _mock_response(data: list | str) -> MagicMock:
    resp = MagicMock()
    if isinstance(data, str):
        resp.json.return_value = json.loads(data)
    else:
        resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

def test_fixture_file_exists():
    assert FIXTURE_PATH.exists(), f"Fixture missing: {FIXTURE_PATH}"


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def test_field_mapping():
    adapter = _make_adapter()
    postings = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(postings)

    jobs = list(adapter.fetch())

    assert len(jobs) == 2
    first: Job = jobs[0]

    assert first.source_platform == "lever"
    assert first.title == "Software Engineering Intern"
    assert first.location == "San Francisco, CA"
    assert first.department == "Engineering"
    assert first.category == "Backend"
    assert first.url == "https://jobs.lever.co/plaid/abc123def456"
    assert first.company == "plaid"


def test_official_id_used_in_job_id():
    adapter = _make_adapter()
    postings = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(postings)

    jobs = list(adapter.fetch())

    # id format: company::source_platform::official_id
    assert jobs[0].id == "plaid::lever::abc123def456"
    assert jobs[1].id == "plaid::lever::xyz789ghi012"


def test_source_platform_is_lever():
    adapter = _make_adapter()
    postings = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(postings)

    for job in adapter.fetch():
        assert job.source_platform == "lever"


# ---------------------------------------------------------------------------
# posted_at from createdAt milliseconds
# ---------------------------------------------------------------------------

def test_created_at_converted_to_datetime():
    adapter = _make_adapter()
    postings = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(postings)

    jobs = list(adapter.fetch())
    first = jobs[0]

    assert isinstance(first.posted_at, datetime)
    expected = datetime.fromtimestamp(1715000000000 / 1000, tz=timezone.utc)
    assert first.posted_at == expected


# ---------------------------------------------------------------------------
# HTML stripping in raw_text
# ---------------------------------------------------------------------------

def test_html_stripped_from_raw_text():
    adapter = _make_adapter()
    postings = [
        {
            "id": "test001",
            "text": "Intern",
            "categories": {
                "department": "Eng",
                "location": "SF",
                "team": "Backend",
            },
            "description": "<p>Hello <strong>World</strong> from <em>Plaid</em>.</p>",
            "hostedUrl": "https://jobs.lever.co/plaid/test001",
            "createdAt": 1715000000000,
        }
    ]
    adapter.http.get.return_value = _mock_response(postings)

    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    # HTML tags must not appear in raw_text
    assert "<p>" not in jobs[0].raw_text
    assert "<strong>" not in jobs[0].raw_text
    # Plain text content must be present (lowercased)
    assert "hello" in jobs[0].raw_text
    assert "world" in jobs[0].raw_text


def test_raw_text_is_lowercased():
    adapter = _make_adapter()
    postings = json.loads(FIXTURE_PATH.read_text())
    adapter.http.get.return_value = _mock_response(postings)

    for job in adapter.fetch():
        assert job.raw_text == job.raw_text.lower()


def test_raw_text_description_truncated_to_500():
    adapter = _make_adapter()
    long_text = "A" * 1000
    postings = [
        {
            "id": "trunc001",
            "text": "Intern",
            "categories": {"department": "Eng", "location": "SF", "team": "T"},
            "description": f"<p>{long_text}</p>",
            "hostedUrl": "https://jobs.lever.co/plaid/trunc001",
            "createdAt": 1715000000000,
        }
    ]
    adapter.http.get.return_value = _mock_response(postings)
    jobs = list(adapter.fetch())
    # description portion is capped at 500; full raw_text may be longer due to other fields
    # verify no more than 500 chars from the description "a"*500
    raw = jobs[0].raw_text
    assert len([c for c in raw if c == "a"]) <= 500


# ---------------------------------------------------------------------------
# HTTP error → yields nothing, no exception
# ---------------------------------------------------------------------------

def test_http_error_yields_nothing():
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.RequestException("connection refused")

    jobs = list(adapter.fetch())  # must not raise
    assert jobs == []


def test_http_404_yields_nothing():
    adapter = _make_adapter()
    resp = MagicMock()
    resp.json.side_effect = requests.HTTPError("404")
    adapter.http.get.side_effect = requests.HTTPError("404")

    jobs = list(adapter.fetch())
    assert jobs == []


# ---------------------------------------------------------------------------
# Empty response yields nothing
# ---------------------------------------------------------------------------

def test_empty_postings_list():
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response([])

    jobs = list(adapter.fetch())
    assert jobs == []
