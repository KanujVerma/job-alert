"""Tests for AppleJobsAdapter."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from src.adapters.apple_jobs import AppleJobsAdapter
from src.http import HTTPClient
from src.models import Job

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_http() -> MagicMock:
    http = MagicMock(spec=HTTPClient)
    http.polite_delay = MagicMock()
    return http


def _make_adapter(http: MagicMock, config: dict | None = None) -> AppleJobsAdapter:
    cfg = config or {
        "api_url": "https://jobs.apple.com/api/role/search",
        "locations": ["united-states-USA"],
        "sources": [
            {
                "kind": "internships",
                "teams": ["internships-STDNT-INTRN"],
                "require_early_career": False,
            },
            {
                "kind": "general",
                "teams": [],
                "require_early_career": True,
            },
        ],
    }
    return AppleJobsAdapter(company="Apple", config=cfg, http=http)


def _mock_response(data: dict, status: int = 200, content_type: str = "application/json") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


def _make_empty_response() -> MagicMock:
    return _mock_response({"searchResults": [], "currentPage": 1, "totalRecords": 0, "pageSize": 20})


# ---------------------------------------------------------------------------
# Basic role_type assignment
# ---------------------------------------------------------------------------

class TestAppleRoleType:
    def test_internship_source_sets_internship_role_type(self):
        fixture = _load_fixture("apple_jobs_intern.json")
        http = _make_http()
        # intern pass → general pass (empty)
        http.post.side_effect = [
            _mock_response(fixture),
            _make_empty_response(),
        ]

        adapter = _make_adapter(http)
        jobs = list(adapter.fetch())

        intern_jobs = [j for j in jobs if j.role_type == "internship"]
        assert len(intern_jobs) == len(fixture["searchResults"])

    def test_general_source_sets_unknown_role_type(self):
        fixture = _load_fixture("apple_jobs_general.json")
        http = _make_http()
        # intern pass (empty) → general pass
        http.post.side_effect = [
            _make_empty_response(),
            _mock_response(fixture),
        ]

        adapter = _make_adapter(http)
        jobs = list(adapter.fetch())

        general_jobs = [j for j in jobs if j.role_type == "unknown"]
        assert len(general_jobs) == len(fixture["searchResults"])

    def test_all_intern_jobs_have_internship_role_type(self):
        fixture = _load_fixture("apple_jobs_intern.json")
        http = _make_http()
        http.post.side_effect = [_mock_response(fixture), _make_empty_response()]

        jobs = list(_make_adapter(http).fetch())
        for j in jobs:
            if j.title != "Software Engineer, New Grad":  # won't appear from intern fixture
                assert j.role_type == "internship"


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

class TestAppleFieldMapping:
    def test_source_platform(self):
        fixture = _load_fixture("apple_jobs_intern.json")
        http = _make_http()
        http.post.side_effect = [_mock_response(fixture), _make_empty_response()]

        jobs = list(_make_adapter(http).fetch())
        for j in jobs:
            assert j.source_platform == "apple_jobs"

    def test_field_mapping_first_intern_job(self):
        fixture = _load_fixture("apple_jobs_intern.json")
        http = _make_http()
        http.post.side_effect = [_mock_response(fixture), _make_empty_response()]

        jobs = list(_make_adapter(http).fetch())
        j = jobs[0]

        assert j.title == "Software Engineering Intern"
        assert j.location == "Cupertino, California, United States"
        assert j.department == "Software and Services"
        assert "200606296" in j.url
        assert j.category is None
        assert j.posted_at is None  # Apple API has no posted_at in search results

    def test_official_id_in_job_id(self):
        fixture = _load_fixture("apple_jobs_intern.json")
        http = _make_http()
        http.post.side_effect = [_mock_response(fixture), _make_empty_response()]

        jobs = list(_make_adapter(http).fetch())
        assert "200606296" in jobs[0].id

    def test_raw_text_lowercased_contains_title_location_team(self):
        fixture = _load_fixture("apple_jobs_intern.json")
        http = _make_http()
        http.post.side_effect = [_mock_response(fixture), _make_empty_response()]

        jobs = list(_make_adapter(http).fetch())
        j = jobs[0]
        assert j.raw_text == j.raw_text.lower()
        assert "software engineering intern" in j.raw_text
        assert "cupertino" in j.raw_text
        assert "software and services" in j.raw_text

    def test_url_constructed_when_missing(self):
        data = {
            "searchResults": [
                {
                    "id": "999888",
                    "postingTitle": "Test Role",
                    "location": "Cupertino, CA",
                    "teamName": "Engineering",
                    "jobNumber": "999888",
                    "homeOffice": False,
                    "jobUrl": "",  # empty
                }
            ],
            "currentPage": 1,
            "totalRecords": 1,
            "pageSize": 20,
        }
        http = _make_http()
        http.post.side_effect = [_mock_response(data), _make_empty_response()]

        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 1
        assert "999888" in jobs[0].url
        assert "jobs.apple.com" in jobs[0].url

    def test_job_without_title_skipped(self):
        data = {
            "searchResults": [
                {
                    "id": "111",
                    "postingTitle": "",
                    "location": "US",
                    "teamName": "Eng",
                    "jobNumber": "111",
                    "homeOffice": False,
                    "jobUrl": "https://example.com",
                },
                {
                    "id": "222",
                    "postingTitle": "Real Job",
                    "location": "Cupertino",
                    "teamName": "Eng",
                    "jobNumber": "222",
                    "homeOffice": False,
                    "jobUrl": "https://jobs.apple.com/222",
                },
            ],
            "currentPage": 1,
            "totalRecords": 2,
            "pageSize": 20,
        }
        http = _make_http()
        http.post.side_effect = [_mock_response(data), _make_empty_response()]

        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 1
        assert jobs[0].title == "Real Job"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestAppleDeduplication:
    def test_job_in_intern_and_general_yielded_once(self):
        """
        apple_jobs_general.json contains id 200606296 which is also in
        apple_jobs_intern.json. It should only be yielded once.
        """
        intern_fixture = _load_fixture("apple_jobs_intern.json")
        general_fixture = _load_fixture("apple_jobs_general.json")

        http = _make_http()
        http.post.side_effect = [
            _mock_response(intern_fixture),
            _mock_response(general_fixture),
        ]

        jobs = list(_make_adapter(http).fetch())

        # Count how many times 200606296 appears
        count_296 = sum(1 for j in jobs if "200606296" in j.id)
        assert count_296 == 1

    def test_total_unique_jobs_across_both_passes(self):
        """3 intern + 2 general (1 overlap) = 4 unique."""
        intern_fixture = _load_fixture("apple_jobs_intern.json")
        general_fixture = _load_fixture("apple_jobs_general.json")

        http = _make_http()
        http.post.side_effect = [
            _mock_response(intern_fixture),
            _mock_response(general_fixture),
        ]

        jobs = list(_make_adapter(http).fetch())
        # intern: 200606296, 200606297, 200606298
        # general: 200606299 (new), 200606296 (dup)
        assert len(jobs) == 4

    def test_role_type_preserved_from_first_pass(self):
        """Shared job yielded as internship (first pass), not unknown (second)."""
        intern_fixture = _load_fixture("apple_jobs_intern.json")
        general_fixture = _load_fixture("apple_jobs_general.json")

        http = _make_http()
        http.post.side_effect = [
            _mock_response(intern_fixture),
            _mock_response(general_fixture),
        ]

        jobs = list(_make_adapter(http).fetch())
        job_296 = next(j for j in jobs if "200606296" in j.id)
        assert job_296.role_type == "internship"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestApplePagination:
    def test_intern_pagination_fetches_all_pages(self):
        page1 = {
            "searchResults": [
                {"id": "1", "postingTitle": "Intern A", "location": "Cupertino, CA",
                 "teamName": "Eng", "jobNumber": "1", "homeOffice": False,
                 "jobUrl": "https://jobs.apple.com/1"},
            ],
            "currentPage": 1,
            "totalRecords": 2,
            "pageSize": 1,
        }
        page2 = {
            "searchResults": [
                {"id": "2", "postingTitle": "Intern B", "location": "Seattle, WA",
                 "teamName": "Eng", "jobNumber": "2", "homeOffice": False,
                 "jobUrl": "https://jobs.apple.com/2"},
            ],
            "currentPage": 2,
            "totalRecords": 2,
            "pageSize": 1,
        }
        http = _make_http()
        # intern: page1, page2 | general: empty
        http.post.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
            _make_empty_response(),
        ]

        config = {
            "api_url": "https://jobs.apple.com/api/role/search",
            "locations": ["united-states-USA"],
            "sources": [
                {"kind": "internships", "teams": ["internships-STDNT-INTRN"]},
                {"kind": "general", "teams": []},
            ],
        }
        adapter = AppleJobsAdapter(company="Apple", config=config, http=http)
        jobs = list(adapter.fetch())

        intern_jobs = [j for j in jobs if j.role_type == "internship"]
        assert len(intern_jobs) == 2

    def test_pagination_stops_at_total_records(self):
        """If currentPage*pageSize >= totalRecords, don't fetch next page."""
        page1 = {
            "searchResults": [
                {"id": "1", "postingTitle": "Job A", "location": "CA",
                 "teamName": "Eng", "jobNumber": "1", "homeOffice": False, "jobUrl": ""},
            ],
            "currentPage": 1,
            "totalRecords": 1,
            "pageSize": 20,
        }
        http = _make_http()
        # intern: page1 | general: empty
        http.post.side_effect = [_mock_response(page1), _make_empty_response()]

        jobs = list(_make_adapter(http).fetch())
        # Only 2 POST calls: intern (1 page) + general (1 page)
        assert http.post.call_count == 2


# ---------------------------------------------------------------------------
# Error handling and fallback
# ---------------------------------------------------------------------------

class TestAppleErrorHandling:
    def test_http_error_intern_yields_nothing_from_intern_pass(self):
        http = _make_http()
        http.post.side_effect = [
            requests.HTTPError("404"),      # intern fails
            _make_empty_response(),         # general empty
        ]

        jobs = list(_make_adapter(http).fetch())
        assert all(j.role_type == "unknown" or True for j in jobs)
        assert len(jobs) == 0  # both empty

    def test_general_http_error_triggers_no_crash(self):
        """General pass HTTP error is caught; adapter still yields intern jobs."""
        intern_fixture = _load_fixture("apple_jobs_intern.json")
        http = _make_http()
        http.post.side_effect = [
            _mock_response(intern_fixture),  # intern succeeds
            requests.HTTPError("503"),        # general fails
        ]

        # Need to mock the fallback GET too
        fallback_resp = MagicMock()
        fallback_resp.status_code = 200
        fallback_resp.text = "<html><body>no jobs here</body></html>"
        fallback_resp.raise_for_status = MagicMock()
        http.get.return_value = fallback_resp

        jobs = list(_make_adapter(http).fetch())
        # Intern jobs should still be present
        intern_jobs = [j for j in jobs if j.role_type == "internship"]
        assert len(intern_jobs) == len(intern_fixture["searchResults"])

    def test_non_json_content_type_handled_gracefully(self):
        """Non-JSON response is handled without crash."""
        http = _make_http()
        html_resp = _mock_response({}, content_type="text/html")
        http.post.side_effect = [
            html_resp,               # intern gets HTML (treated as error)
            _make_empty_response(),  # general empty
        ]
        # Fallback GET
        fallback = MagicMock()
        fallback.status_code = 200
        fallback.text = "<html></html>"
        fallback.raise_for_status = MagicMock()
        http.get.return_value = fallback

        jobs = list(_make_adapter(http).fetch())
        # No crash, may yield 0 or more jobs
        assert isinstance(jobs, list)

    def test_internship_only_config_works(self):
        """Config with only internship source works."""
        fixture = _load_fixture("apple_jobs_intern.json")
        http = _make_http()
        http.post.return_value = _mock_response(fixture)

        config = {
            "api_url": "https://jobs.apple.com/api/role/search",
            "locations": ["united-states-USA"],
            "sources": [
                {"kind": "internships", "teams": ["internships-STDNT-INTRN"]},
            ],
        }
        adapter = AppleJobsAdapter(company="Apple", config=config, http=http)
        jobs = list(adapter.fetch())

        assert len(jobs) == len(fixture["searchResults"])
        assert all(j.role_type == "internship" for j in jobs)
