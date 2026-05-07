"""Tests for WorkdayAdapter."""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest
import responses as resp_lib
from responses import matchers

from src.adapters.workday import WorkdayAdapter
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
    assert job.url == f"{_BASE_URL}/job/Boise-ID/Software-Engineering-Intern_JR12345"
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
