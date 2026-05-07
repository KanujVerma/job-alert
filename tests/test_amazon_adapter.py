"""Tests for AmazonJobsAdapter."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from src.adapters.amazon_jobs import AmazonJobsAdapter, _parse_amazon_date
from src.http import HTTPClient
from src.models import Job

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_http() -> MagicMock:
    http = MagicMock(spec=HTTPClient)
    http.polite_delay = MagicMock()
    return http


def _make_adapter(http: MagicMock, config: dict | None = None) -> AmazonJobsAdapter:
    cfg = config or {
        "base_url": "https://www.amazon.jobs",
        "search_path": "/en/search.json",
        "result_limit": 25,
        "include_internship_search": True,
        "base_categories": ["Software Development"],
        "gated_categories": [],
        "country_codes": ["USA"],
    }
    return AmazonJobsAdapter(company="Amazon", config=cfg, http=http)


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------

class TestAmazonDateParsing:
    def test_standard_format(self):
        dt = _parse_amazon_date("January 6, 2025")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 6

    def test_double_space_format(self):
        dt = _parse_amazon_date("May  6, 2026")
        assert dt is not None
        assert dt.month == 5
        assert dt.day == 6

    def test_none_input(self):
        assert _parse_amazon_date(None) is None

    def test_empty_string(self):
        assert _parse_amazon_date("") is None

    def test_invalid_format(self):
        assert _parse_amazon_date("not a date") is None


# ---------------------------------------------------------------------------
# Fixture-based tests (live-ish data)
# ---------------------------------------------------------------------------

class TestAmazonFixtures:
    def test_intern_fixture_yields_jobs(self):
        fixture = _load_fixture("amazon_jobs_intern.json")
        # Intern pass only, no categories
        config = {
            "base_url": "https://www.amazon.jobs",
            "search_path": "/en/search.json",
            "result_limit": 25,
            "include_internship_search": True,
            "base_categories": [],
            "gated_categories": [],
            "country_codes": ["USA"],
        }
        http = _make_http()
        # Single page: hits <= result_limit
        fixture_patched = dict(fixture)
        fixture_patched["hits"] = len(fixture["jobs"])
        http.get.return_value = _mock_response(fixture_patched)

        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())

        assert len(jobs) == len(fixture["jobs"])

    def test_software_fixture_yields_jobs(self):
        fixture = _load_fixture("amazon_jobs_software.json")
        config = {
            "base_url": "https://www.amazon.jobs",
            "search_path": "/en/search.json",
            "result_limit": 25,
            "include_internship_search": False,
            "base_categories": ["Software Development"],
            "gated_categories": [],
            "country_codes": ["USA"],
        }
        http = _make_http()
        fixture_patched = dict(fixture)
        fixture_patched["hits"] = len(fixture["jobs"])
        http.get.return_value = _mock_response(fixture_patched)

        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())

        assert len(jobs) == len(fixture["jobs"])
        for job in jobs:
            assert job.source_platform == "amazon_jobs"


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

class TestAmazonFieldMapping:
    def _one_job_response(self, overrides: dict | None = None) -> dict:
        job = {
            "id_icims": "9876543",
            "title": "Software Development Engineer Intern",
            "location": "US, WA, Seattle",
            "normalized_location": "Seattle, Washington, USA",
            "job_category": "Software Development",
            "posted_date": "January 6, 2025",
            "business_category": "Amazon Web Services",
            "job_path": "/en/jobs/9876543/software-development-engineer-intern",
            "description_short": "Build distributed systems at scale.",
        }
        if overrides:
            job.update(overrides)
        return {"jobs": [job], "hits": 1}

    def test_source_platform(self):
        http = _make_http()
        http.get.return_value = _mock_response(self._one_job_response())
        jobs = list(_make_adapter(http, config={
            "include_internship_search": True,
            "base_categories": [],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 25,
        }).fetch())
        assert jobs[0].source_platform == "amazon_jobs"

    def test_field_mapping(self):
        http = _make_http()
        http.get.return_value = _mock_response(self._one_job_response())
        config = {
            "include_internship_search": True,
            "base_categories": [],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 25,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())

        j = jobs[0]
        assert j.title == "Software Development Engineer Intern"
        assert j.location == "Seattle, Washington, USA"  # normalized_location preferred
        assert j.department == "Amazon Web Services"
        assert j.category == "Software Development"
        assert j.url == "https://www.amazon.jobs/en/jobs/9876543/software-development-engineer-intern"
        assert j.posted_at is not None
        assert j.posted_at.year == 2025

    def test_official_id_in_job_id(self):
        http = _make_http()
        http.get.return_value = _mock_response(self._one_job_response())
        config = {
            "include_internship_search": True,
            "base_categories": [],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 25,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())
        assert "9876543" in jobs[0].id

    def test_raw_text_lowercased(self):
        http = _make_http()
        http.get.return_value = _mock_response(self._one_job_response())
        config = {
            "include_internship_search": True,
            "base_categories": [],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 25,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())
        j = jobs[0]
        assert j.raw_text == j.raw_text.lower()
        assert "software development engineer intern" in j.raw_text
        assert "distributed systems" in j.raw_text


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestAmazonDeduplication:
    def test_job_appearing_in_both_intern_and_category_yielded_once(self):
        """Same id_icims in intern pass and category pass → yielded only once."""
        shared_job = {
            "id_icims": "SHARED123",
            "title": "SDE Intern",
            "location": "US, WA, Seattle",
            "normalized_location": "Seattle, Washington, USA",
            "job_category": "Software Development",
            "posted_date": "May  6, 2026",
            "business_category": "AWS",
            "job_path": "/en/jobs/SHARED123/sde-intern",
            "description_short": "Intern role.",
        }
        different_job = {
            "id_icims": "DIFF456",
            "title": "SDE",
            "location": "US, WA, Seattle",
            "normalized_location": "Seattle, Washington, USA",
            "job_category": "Software Development",
            "posted_date": "May  5, 2026",
            "business_category": "AWS",
            "job_path": "/en/jobs/DIFF456/sde",
            "description_short": "Full-time role.",
        }

        intern_resp = {"jobs": [shared_job], "hits": 1}
        cat_resp = {"jobs": [shared_job, different_job], "hits": 2}

        http = _make_http()
        http.get.side_effect = [_mock_response(intern_resp), _mock_response(cat_resp)]

        config = {
            "include_internship_search": True,
            "base_categories": ["Software Development"],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 25,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())

        ids = [j.id for j in jobs]
        assert len(jobs) == 2  # SHARED123 only once + DIFF456
        # SHARED123 job id appears exactly once
        shared_count = sum(1 for j in jobs if "SHARED123" in j.id)
        assert shared_count == 1

    def test_no_duplicates_within_single_pass(self):
        """If API somehow returns duplicate ids, deduplicate within pass."""
        job = {
            "id_icims": "DUP789",
            "title": "Backend Intern",
            "location": "US, CA",
            "normalized_location": "California, USA",
            "job_category": "Software Development",
            "posted_date": "January 1, 2025",
            "business_category": "Alexa",
            "job_path": "/en/jobs/DUP789/backend-intern",
            "description_short": "",
        }
        # Simulate two pages, same job appears on both
        page1 = {"jobs": [job], "hits": 2}
        page2 = {"jobs": [job], "hits": 2}

        http = _make_http()
        http.get.side_effect = [_mock_response(page1), _mock_response(page2)]

        config = {
            "include_internship_search": True,
            "base_categories": [],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 1,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())

        assert len(jobs) == 1


# ---------------------------------------------------------------------------
# Multi-pass and error handling
# ---------------------------------------------------------------------------

class TestAmazonMultiPass:
    def test_intern_and_category_both_fetched(self):
        """Two passes → two HTTP calls."""
        resp = {"jobs": [], "hits": 0}
        http = _make_http()
        http.get.return_value = _mock_response(resp)

        config = {
            "include_internship_search": True,
            "base_categories": ["Software Development"],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 25,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        list(adapter.fetch())

        assert http.get.call_count == 2  # intern pass + category pass

    def test_gated_categories_fetched(self):
        """Gated categories trigger an additional pass."""
        resp = {"jobs": [], "hits": 0}
        http = _make_http()
        http.get.return_value = _mock_response(resp)

        config = {
            "include_internship_search": False,
            "base_categories": [],
            "gated_categories": ["Research Science"],
            "country_codes": ["USA"],
            "result_limit": 25,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        list(adapter.fetch())

        assert http.get.call_count == 1

    def test_failed_category_continues_to_next(self):
        """If one category pass fails (HTTP error), adapter continues to next."""
        good_job = {
            "id_icims": "GOOD1",
            "title": "Good Job",
            "location": "US, WA, Seattle",
            "normalized_location": "Seattle, Washington, USA",
            "job_category": "Software Development",
            "posted_date": "January 1, 2025",
            "business_category": "AWS",
            "job_path": "/en/jobs/GOOD1/good-job",
            "description_short": "",
        }
        good_resp = {"jobs": [good_job], "hits": 1}

        http = _make_http()
        http.get.side_effect = [
            requests.HTTPError("500"),        # intern pass fails
            _mock_response(good_resp),        # category pass succeeds
        ]

        config = {
            "include_internship_search": True,
            "base_categories": ["Software Development"],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 25,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())

        assert len(jobs) == 1
        assert jobs[0].title == "Good Job"

    def test_all_passes_fail_yields_nothing(self):
        http = _make_http()
        http.get.side_effect = requests.ConnectionError("network down")

        jobs = list(_make_adapter(http).fetch())
        assert jobs == []


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestAmazonPagination:
    def test_two_page_pagination(self):
        job_a = {
            "id_icims": "A1",
            "title": "Job A",
            "location": "US, WA",
            "normalized_location": "Washington, USA",
            "job_category": "Software Development",
            "posted_date": "January 1, 2025",
            "business_category": "AWS",
            "job_path": "/en/jobs/A1/job-a",
            "description_short": "",
        }
        job_b = {
            "id_icims": "B2",
            "title": "Job B",
            "location": "US, CA",
            "normalized_location": "California, USA",
            "job_category": "Software Development",
            "posted_date": "January 2, 2025",
            "business_category": "Amazon",
            "job_path": "/en/jobs/B2/job-b",
            "description_short": "",
        }
        page1 = {"jobs": [job_a], "hits": 2}
        page2 = {"jobs": [job_b], "hits": 2}

        http = _make_http()
        http.get.side_effect = [_mock_response(page1), _mock_response(page2)]

        config = {
            "include_internship_search": True,
            "base_categories": [],
            "gated_categories": [],
            "country_codes": ["USA"],
            "result_limit": 1,
        }
        adapter = AmazonJobsAdapter(company="Amazon", config=config, http=http)
        jobs = list(adapter.fetch())

        assert len(jobs) == 2
        assert http.get.call_count == 2
