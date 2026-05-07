"""Tests for AppleJobsAdapter (HTML scraping mode)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from src.adapters.apple_jobs import AppleJobsAdapter
from src.http import HTTPClient


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _job_card_html(
    job_id: str,
    title: str,
    team: str = "Software and Services",
    location: str = "Cupertino, California, United States",
    posted: str = "May 07, 2026",
    team_code: str = "SOFTDV",
) -> str:
    loc_span = (
        f'<span class="table--advanced-search__location-sub">{location}</span>'
        if location else ""
    )
    return f"""
<div class="d-flex flex-row row large-12 job-title job-list-item" id="search-job-{job_id}">
  <div class="d-flex flex-column column large-6 small-12 text-align-start job-title-link">
    <h3><a class="link-inline" href="/en-us/details/{job_id}/slug?team={team_code}">{title}</a></h3>
    <a class="link-inline" href="/en-us/details/{job_id}/slug/locationPicker">Choose Location</a>
    <span class="team-name mt-0">{team}</span>
    <span class="job-posted-date">{posted}</span>
  </div>
  <div class="column large-4 small-12 text-align-start job-title-location">
    <span class="a11y">Location</span>
    {loc_span}
  </div>
</div>"""


def _page_html(*cards: str) -> str:
    return "<html><body>" + "".join(cards) + "</body></html>"


def _empty_page() -> str:
    return "<html><body></body></html>"


# ---------------------------------------------------------------------------
# Test fixtures / factories
# ---------------------------------------------------------------------------

def _make_http() -> MagicMock:
    http = MagicMock(spec=HTTPClient)
    http.polite_delay = MagicMock()
    return http


def _mock_get(text: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def _make_adapter(
    http: MagicMock,
    config: dict | None = None,
) -> AppleJobsAdapter:
    cfg = config or {
        "search_url": "https://jobs.apple.com/en-us/search",
        "locations": ["united-states-USA"],
        "max_pages": 10,
        "sources": [
            {"kind": "internships", "team": "internships-STDNT-INTRN", "require_early_career": False},
            {"kind": "general", "require_early_career": True},
        ],
    }
    return AppleJobsAdapter(company="Apple", config=cfg, http=http)


# ---------------------------------------------------------------------------
# Role type assignment
# ---------------------------------------------------------------------------

class TestRoleType:
    def test_internship_source_sets_internship_role_type(self):
        page = _page_html(_job_card_html("100", "Software Engineering Intern"))
        http = _make_http()
        # intern: page1, then empty; general: empty
        http.get.side_effect = [
            _mock_get(page),        # intern page 1
            _mock_get(_empty_page()),  # intern page 2 (stop)
            _mock_get(_empty_page()),  # general page 1
        ]
        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 1
        assert jobs[0].role_type == "internship"

    def test_general_source_sets_unknown_role_type(self):
        page = _page_html(_job_card_html("200", "Software Engineer"))
        http = _make_http()
        # intern: empty; general: page1, then empty
        http.get.side_effect = [
            _mock_get(_empty_page()),  # intern page 1
            _mock_get(page),           # general page 1
            _mock_get(_empty_page()),  # general page 2 (stop)
        ]
        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 1
        assert jobs[0].role_type == "unknown"

    def test_internship_only_config(self):
        page = _page_html(
            _job_card_html("101", "iOS Intern"),
            _job_card_html("102", "ML Intern"),
        )
        http = _make_http()
        http.get.side_effect = [_mock_get(page), _mock_get(_empty_page())]
        config = {
            "search_url": "https://jobs.apple.com/en-us/search",
            "locations": ["united-states-USA"],
            "max_pages": 5,
            "sources": [{"kind": "internships", "team": "internships-STDNT-INTRN"}],
        }
        adapter = AppleJobsAdapter(company="Apple", config=config, http=http)
        jobs = list(adapter.fetch())
        assert len(jobs) == 2
        assert all(j.role_type == "internship" for j in jobs)


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

class TestFieldMapping:
    def _single_job(self) -> list:
        page = _page_html(_job_card_html(
            job_id="200606296",
            title="Software Engineering Intern",
            team="Software and Services",
            location="Cupertino, California, United States",
            posted="May 07, 2026",
        ))
        http = _make_http()
        http.get.side_effect = [
            _mock_get(page),
            _mock_get(_empty_page()),
            _mock_get(_empty_page()),
        ]
        return list(_make_adapter(http).fetch())

    def test_source_platform(self):
        jobs = self._single_job()
        assert jobs[0].source_platform == "apple_jobs"

    def test_company(self):
        jobs = self._single_job()
        assert jobs[0].company == "Apple"

    def test_title(self):
        jobs = self._single_job()
        assert jobs[0].title == "Software Engineering Intern"

    def test_location(self):
        jobs = self._single_job()
        assert jobs[0].location == "Cupertino, California, United States"

    def test_department(self):
        jobs = self._single_job()
        assert jobs[0].department == "Software and Services"

    def test_url_contains_official_id(self):
        jobs = self._single_job()
        assert "200606296" in jobs[0].url
        assert "jobs.apple.com" in jobs[0].url

    def test_official_id_in_job_id(self):
        jobs = self._single_job()
        assert "200606296" in jobs[0].id

    def test_posted_at_parsed(self):
        jobs = self._single_job()
        assert jobs[0].posted_at is not None
        assert jobs[0].posted_at.year == 2026
        assert jobs[0].posted_at.month == 5
        assert jobs[0].posted_at.day == 7

    def test_raw_text_lowercase_contains_key_fields(self):
        jobs = self._single_job()
        j = jobs[0]
        assert j.raw_text == j.raw_text.lower()
        assert "software engineering intern" in j.raw_text
        assert "cupertino" in j.raw_text
        assert "software and services" in j.raw_text

    def test_category_is_none(self):
        jobs = self._single_job()
        assert jobs[0].category is None

    def test_empty_location_kept(self):
        page = _page_html(_job_card_html("300", "Remote Job", location=""))
        http = _make_http()
        http.get.side_effect = [
            _mock_get(page), _mock_get(_empty_page()), _mock_get(_empty_page()),
        ]
        jobs = list(_make_adapter(http).fetch())
        assert jobs[0].location == ""

    def test_job_without_title_skipped(self):
        # locationPicker link should not be matched; empty-title row skipped
        bad_html = """
<html><body>
<div class="job-list-item">
  <div class="job-title-link">
    <h3><a href="/en-us/details/111/slug/locationPicker">Choose</a></h3>
    <span class="team-name">Eng</span>
  </div>
</div>
<div class="job-list-item">
  <div class="job-title-link">
    <h3><a href="/en-us/details/222/real-job?team=ENG">Real Job</a></h3>
    <span class="team-name">Eng</span>
  </div>
</div>
</body></html>"""
        http = _make_http()
        http.get.side_effect = [
            _mock_get(bad_html), _mock_get(_empty_page()), _mock_get(_empty_page()),
        ]
        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 1
        assert jobs[0].title == "Real Job"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_job_appearing_in_both_passes_yielded_once(self):
        shared_card = _job_card_html("200606296", "Software Engineering Intern")
        intern_page = _page_html(shared_card)
        general_page = _page_html(
            shared_card,
            _job_card_html("200606299", "New Grad Software Engineer"),
        )
        http = _make_http()
        http.get.side_effect = [
            _mock_get(intern_page),    # intern page 1
            _mock_get(_empty_page()),  # intern page 2
            _mock_get(general_page),   # general page 1
            _mock_get(_empty_page()),  # general page 2
        ]
        jobs = list(_make_adapter(http).fetch())

        ids_with_296 = [j for j in jobs if "200606296" in j.id]
        assert len(ids_with_296) == 1

    def test_role_type_from_first_pass_wins(self):
        shared_card = _job_card_html("200606296", "Software Engineering Intern")
        http = _make_http()
        http.get.side_effect = [
            _mock_get(_page_html(shared_card)),   # intern page 1
            _mock_get(_empty_page()),              # intern page 2
            _mock_get(_page_html(shared_card)),   # general page 1 (dup)
            _mock_get(_empty_page()),              # general page 2
        ]
        jobs = list(_make_adapter(http).fetch())
        job = next(j for j in jobs if "200606296" in j.id)
        assert job.role_type == "internship"

    def test_total_unique_across_both_passes(self):
        """3 intern + 2 general (1 overlap) = 4 unique."""
        intern_page = _page_html(
            _job_card_html("101", "Intern A"),
            _job_card_html("102", "Intern B"),
            _job_card_html("103", "Intern C"),
        )
        general_page = _page_html(
            _job_card_html("103", "Intern C"),   # dup
            _job_card_html("200", "New Grad Dev"),
        )
        http = _make_http()
        http.get.side_effect = [
            _mock_get(intern_page), _mock_get(_empty_page()),
            _mock_get(general_page), _mock_get(_empty_page()),
        ]
        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 4


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    def test_fetches_multiple_pages_until_empty(self):
        page1 = _page_html(_job_card_html("1", "Job One"))
        page2 = _page_html(_job_card_html("2", "Job Two"))
        http = _make_http()
        http.get.side_effect = [
            _mock_get(page1),           # intern page 1
            _mock_get(page2),           # intern page 2
            _mock_get(_empty_page()),   # intern page 3 (stop)
            _mock_get(_empty_page()),   # general page 1
        ]
        config = {
            "search_url": "https://jobs.apple.com/en-us/search",
            "locations": ["united-states-USA"],
            "max_pages": 10,
            "sources": [
                {"kind": "internships", "team": "internships-STDNT-INTRN"},
                {"kind": "general"},
            ],
        }
        jobs = list(AppleJobsAdapter(company="Apple", config=config, http=http).fetch())
        assert len([j for j in jobs if j.role_type == "internship"]) == 2

    def test_max_pages_cap_respected(self):
        always_full = _page_html(_job_card_html("999", "Infinite Job"))
        # Each call returns a page with the same job ID → after page 1 all are dups → stops
        # To test max_pages cap, we need unique IDs each page
        pages = [_mock_get(_page_html(_job_card_html(str(i), f"Job {i}"))) for i in range(20)]
        http = _make_http()
        http.get.side_effect = pages  # never returns empty — should stop at max_pages

        config = {
            "search_url": "https://jobs.apple.com/en-us/search",
            "locations": ["united-states-USA"],
            "max_pages": 3,
            "sources": [{"kind": "general"}],
        }
        jobs = list(AppleJobsAdapter(company="Apple", config=config, http=http).fetch())
        assert len(jobs) == 3  # max_pages=3 → 3 jobs max

    def test_stops_when_all_on_page_are_already_seen(self):
        """If every job on a page was seen in pass 1, stop paginating."""
        shared_card = _job_card_html("shared", "Shared Job")
        http = _make_http()
        http.get.side_effect = [
            _mock_get(_page_html(shared_card)),   # intern page 1
            _mock_get(_empty_page()),              # intern page 2
            _mock_get(_page_html(shared_card)),   # general page 1 (all dups → stop)
        ]
        jobs = list(_make_adapter(http).fetch())
        # Only called 3 times (no general page 2 fetch)
        assert http.get.call_count == 3

    def test_team_param_sent_for_internship_pass(self):
        http = _make_http()
        http.get.return_value = _mock_get(_empty_page())
        list(_make_adapter(http).fetch())
        # First call (intern page 1) should include team param
        first_call_kwargs = http.get.call_args_list[0]
        params = first_call_kwargs[1].get("params") or first_call_kwargs[0][1]
        assert params.get("team") == "internships-STDNT-INTRN"

    def test_no_team_param_for_general_pass(self):
        http = _make_http()
        http.get.return_value = _mock_get(_empty_page())
        list(_make_adapter(http).fetch())
        # Second call (general page 1) should NOT include team param
        second_call_kwargs = http.get.call_args_list[1]
        params = second_call_kwargs[1].get("params") or second_call_kwargs[0][1]
        assert "team" not in params or not params.get("team")

    def test_polite_delay_called_between_pages(self):
        page1 = _page_html(_job_card_html("1", "Job One"))
        page2 = _page_html(_job_card_html("2", "Job Two"))
        http = _make_http()
        http.get.side_effect = [
            _mock_get(page1), _mock_get(page2), _mock_get(_empty_page()),
            _mock_get(_empty_page()),
        ]
        list(_make_adapter(http).fetch())
        assert http.polite_delay.call_count >= 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_request_exception_stops_source_gracefully(self):
        http = _make_http()
        http.get.side_effect = [
            requests.RequestException("timeout"),   # intern fails
            _mock_get(_empty_page()),               # general page 1
        ]
        jobs = list(_make_adapter(http).fetch())
        assert isinstance(jobs, list)
        assert len(jobs) == 0

    def test_second_source_still_runs_after_first_source_error(self):
        page = _page_html(_job_card_html("300", "Software Engineer"))
        http = _make_http()
        http.get.side_effect = [
            requests.RequestException("timeout"),   # intern fails
            _mock_get(page),                        # general page 1
            _mock_get(_empty_page()),               # general page 2
        ]
        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 1
        assert jobs[0].role_type == "unknown"
