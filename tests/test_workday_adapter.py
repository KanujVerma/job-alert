"""Tests for WorkdayAdapter."""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest
import responses as resp_lib
from responses import matchers

from datetime import timedelta

from src.adapters.workday import WorkdayAdapter, _parse_posted_on
from src.http import HTTPClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "workday_micron.json"

_BASE_URL = "https://micron.wd1.myworkdayjobs.com"
_ENDPOINT = f"{_BASE_URL}/wday/cxs/micron/External/jobs"
_HTTP = HTTPClient(user_agent="job-alert-bot/0.1", timeout=15, max_retries=0)


def _make_adapter(base_url: str = _BASE_URL) -> WorkdayAdapter:
    config = {
        "base_url": base_url,
        "tenant": "micron",
        "site": "External",
    }
    return WorkdayAdapter(company="Micron", config=config, http=_HTTP)


def _make_posting(i: int) -> dict:
    return {
        "title": f"Software Engineer {i}",
        "externalPath": f"/job/Boise-ID/Software-Engineer_{i}_JR{10000 + i}",
        "timeType": "Full time",
        "locationsText": "Boise, ID",
        "postedOn": "Posted Today",
        "bulletFields": [f"JR{10000 + i}"],
    }


def _page(postings: list[dict], total: int) -> dict:
    return {"total": total, "jobPostings": postings}


# ---------------------------------------------------------------------------
# Test: yields at least one Job from live fixture
# ---------------------------------------------------------------------------

@resp_lib.activate
def test_yields_at_least_one_job_from_fixture():
    """Adapter yields ≥1 Job when given the real Micron fixture (single page)."""
    data = json.loads(FIXTURE_PATH.read_text())
    # Return only first page; cap total to 20 so pagination stops after page 1
    page_data = {"total": len(data["jobPostings"]), "jobPostings": data["jobPostings"]}

    resp_lib.add(
        resp_lib.POST,
        _ENDPOINT,
        json=page_data,
        status=200,
    )

    adapter = _make_adapter()
    jobs = list(adapter.fetch())
    assert len(jobs) >= 1


# ---------------------------------------------------------------------------
# Test: field mapping is correct
# ---------------------------------------------------------------------------

@resp_lib.activate
def test_field_mapping():
    """Job fields are correctly mapped from posting JSON."""
    posting = {
        "title": "Software Engineering Intern",
        "externalPath": "/job/Boise-ID/Software-Engineering-Intern_JR12345",
        "timeType": "Full time",
        "locationsText": "Boise, ID",
        "postedOn": "Posting Date 01/06/2025",
        "bulletFields": ["JR12345"],
        "jobFamilyGroup": "Engineering",
        "jobFamily": "Software Engineering",
    }
    resp_lib.add(resp_lib.POST, _ENDPOINT, json={"total": 1, "jobPostings": [posting]}, status=200)

    adapter = _make_adapter()
    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    job = jobs[0]

    assert job.title == "Software Engineering Intern"
    assert job.url == f"{_BASE_URL}/External/job/Boise-ID/Software-Engineering-Intern_JR12345"
    assert job.location == "Boise, ID"
    assert job.department == "Engineering"
    assert job.category == "Software Engineering"
    assert job.source_platform == "workday"
    assert job.company == "Micron"
    assert job.posted_at == datetime(2025, 1, 6, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test: make_job_id is called — id is non-empty string
# ---------------------------------------------------------------------------

@resp_lib.activate
def test_job_id_is_non_empty():
    """Each yielded job has a non-empty string id."""
    posting = _make_posting(1)
    resp_lib.add(resp_lib.POST, _ENDPOINT, json=_page([posting], 1), status=200)

    adapter = _make_adapter()
    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    assert isinstance(jobs[0].id, str)
    assert len(jobs[0].id) > 0


# ---------------------------------------------------------------------------
# Test: all jobs have source_platform="workday"
# ---------------------------------------------------------------------------

@resp_lib.activate
def test_all_jobs_source_platform_workday():
    """Every yielded job has source_platform='workday'."""
    data = json.loads(FIXTURE_PATH.read_text())
    page_data = {"total": len(data["jobPostings"]), "jobPostings": data["jobPostings"]}

    resp_lib.add(resp_lib.POST, _ENDPOINT, json=page_data, status=200)

    adapter = _make_adapter()
    jobs = list(adapter.fetch())
    assert len(jobs) > 0
    assert all(j.source_platform == "workday" for j in jobs)


# ---------------------------------------------------------------------------
# Test: pagination — total=25, two pages (20+5)
# ---------------------------------------------------------------------------

@resp_lib.activate
def test_pagination_yields_all_25():
    """With total=25, adapter fetches two pages and yields all 25 jobs."""
    page1_postings = [_make_posting(i) for i in range(20)]
    page2_postings = [_make_posting(i) for i in range(20, 25)]

    # responses library matches calls in order
    resp_lib.add(resp_lib.POST, _ENDPOINT, json=_page(page1_postings, 25), status=200)
    resp_lib.add(resp_lib.POST, _ENDPOINT, json=_page(page2_postings, 25), status=200)

    adapter = _make_adapter()
    jobs = list(adapter.fetch())
    assert len(jobs) == 25


# ---------------------------------------------------------------------------
# Test: HTTP error on first page → yields nothing, no exception
# ---------------------------------------------------------------------------

@resp_lib.activate
def test_http_error_first_page_yields_nothing():
    """If first page returns 500, fetch() yields nothing and does not raise."""
    resp_lib.add(resp_lib.POST, _ENDPOINT, status=500)

    adapter = _make_adapter()
    jobs = list(adapter.fetch())
    assert jobs == []


# ---------------------------------------------------------------------------
# Test: HTTP error on second page → yields first 20, then stops
# ---------------------------------------------------------------------------

@resp_lib.activate
def test_http_error_second_page_yields_first_20():
    """If second page returns 500, adapter yields first 20 jobs and stops cleanly."""
    page1_postings = [_make_posting(i) for i in range(20)]

    resp_lib.add(resp_lib.POST, _ENDPOINT, json=_page(page1_postings, 25), status=200)
    resp_lib.add(resp_lib.POST, _ENDPOINT, status=500)

    adapter = _make_adapter()
    jobs = list(adapter.fetch())
    assert len(jobs) == 20


# ---------------------------------------------------------------------------
# _parse_posted_on — relative date parsing
# ---------------------------------------------------------------------------

_REF = datetime(2026, 5, 20, 14, 30, 0, tzinfo=timezone.utc)
_TODAY = _REF.replace(hour=0, minute=0, second=0, microsecond=0)


def test_parse_posted_on_absolute_date():
    """Absolute 'Posting Date MM/DD/YYYY' still works."""
    result = _parse_posted_on("Posting Date 01/06/2025")
    assert result == datetime(2025, 1, 6, tzinfo=timezone.utc)


def test_parse_posted_on_posted_today():
    result = _parse_posted_on("Posted Today", reference_dt=_REF)
    assert result == _TODAY


def test_parse_posted_on_posted_1_day_ago():
    result = _parse_posted_on("Posted 1 Day Ago", reference_dt=_REF)
    assert result == _TODAY - timedelta(days=1)


def test_parse_posted_on_posted_3_days_ago():
    result = _parse_posted_on("Posted 3 Days Ago", reference_dt=_REF)
    assert result == _TODAY - timedelta(days=3)


def test_parse_posted_on_posted_30_plus_days_ago():
    """'Posted 30+ Days Ago' — the + is stripped, treated as exactly 30 days."""
    result = _parse_posted_on("Posted 30+ Days Ago", reference_dt=_REF)
    assert result == _TODAY - timedelta(days=30)


def test_parse_posted_on_no_reference_returns_none_for_relative():
    """Without reference_dt, relative strings return None."""
    assert _parse_posted_on("Posted Today") is None
    assert _parse_posted_on("Posted 3 Days Ago") is None


def test_parse_posted_on_empty_returns_none():
    assert _parse_posted_on("") is None
    assert _parse_posted_on(None) is None


def test_adapter_posted_today_sets_posted_at():
    """Adapter: 'Posted Today' in fixture → posted_at is set to start of today."""
    adapter = _make_adapter()
    posting = {
        "title": "Software Engineer Intern",
        "externalPath": "/job/Boise-ID/Software-Engineer-Intern_JR99999",
        "locationsText": "Boise, ID",
        "postedOn": "Posted Today",
        "bulletFields": ["JR99999"],
    }
    resp_lib.add(resp_lib.POST, _ENDPOINT, json=_page([posting], 1), status=200)

    # decorate manually since not using decorator
    with resp_lib.RequestsMock() as rsps:
        rsps.add(resp_lib.POST, _ENDPOINT, json=_page([posting], 1), status=200)
        jobs = list(adapter.fetch())

    assert len(jobs) == 1
    assert jobs[0].posted_at is not None
    # posted_at should be today (start of day UTC)
    today_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert jobs[0].posted_at == today_utc


def test_adapter_posted_days_ago_sets_posted_at():
    """Adapter: 'Posted 2 Days Ago' → posted_at is 2 days before fetch start."""
    adapter = _make_adapter()
    posting = {
        "title": "Software Engineer Intern",
        "externalPath": "/job/Boise-ID/Software-Engineer-Intern_JR88888",
        "locationsText": "Boise, ID",
        "postedOn": "Posted 2 Days Ago",
        "bulletFields": ["JR88888"],
    }
    with resp_lib.RequestsMock() as rsps:
        rsps.add(resp_lib.POST, _ENDPOINT, json=_page([posting], 1), status=200)
        before = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        jobs = list(adapter.fetch())

    assert len(jobs) == 1
    assert jobs[0].posted_at is not None
    expected = before - timedelta(days=2)
    assert jobs[0].posted_at == expected
