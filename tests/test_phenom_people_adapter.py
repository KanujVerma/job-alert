from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load fixtures (written by Task 2)
# ---------------------------------------------------------------------------
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_RAW_RESPONSE = json.loads((_FIXTURE_DIR / "phenom_snowflake_response.json").read_text())
_RAW_REQUEST = json.loads((_FIXTURE_DIR / "phenom_snowflake_request.json").read_text())


def _find_jobs_in_fixture(data: dict) -> list:
    for key in ("jobs", "positions", "results"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    sub = data.get("data") or {}
    if isinstance(sub, dict):
        for key in ("jobs", "positions", "results"):
            val = sub.get(key)
            if isinstance(val, list):
                return val
    # Handle Phenom People's actual nested structure: searchJobs.data.jobs
    search = data.get("searchJobs") or {}
    if isinstance(search, dict):
        inner = search.get("data") or {}
        if isinstance(inner, dict):
            for key in ("jobs", "positions", "results"):
                val = inner.get(key)
                if isinstance(val, list):
                    return val
    return []


_FIXTURE_JOBS = _find_jobs_in_fixture(_RAW_RESPONSE)
_SAMPLE_JOB = _FIXTURE_JOBS[0] if _FIXTURE_JOBS else {}


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------
class TestPhenomPeopleParser:
    _DETECTED = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_valid_job(self):
        if not _SAMPLE_JOB:
            pytest.skip("No job records in fixture")
        from src.adapters.phenom_people import _parse_phenom_job
        job = _parse_phenom_job(_SAMPLE_JOB, "Snowflake", "phenom_people", self._DETECTED)
        assert job is not None
        assert job.company == "Snowflake"
        assert job.source_platform == "phenom_people"
        assert job.title
        assert job.detected_at == self._DETECTED

    def test_parse_missing_title_returns_none(self):
        from src.adapters.phenom_people import _parse_phenom_job, _TITLE_KEY
        record = dict(_SAMPLE_JOB) if _SAMPLE_JOB else {"id": "x"}
        record.pop(_TITLE_KEY, None)
        for alt in ("name", "jobTitle", "job_title"):
            record.pop(alt, None)
        assert _parse_phenom_job(record, "Snowflake", "phenom_people", self._DETECTED) is None

    def test_parse_location_is_non_empty_string(self):
        if not _SAMPLE_JOB:
            pytest.skip("No job records in fixture")
        from src.adapters.phenom_people import _parse_phenom_job
        job = _parse_phenom_job(_SAMPLE_JOB, "Snowflake", "phenom_people", self._DETECTED)
        assert job is not None
        assert isinstance(job.location, str) and job.location

    def test_parse_posted_at_is_datetime_or_none(self):
        if not _SAMPLE_JOB:
            pytest.skip("No job records in fixture")
        from src.adapters.phenom_people import _parse_phenom_job
        job = _parse_phenom_job(_SAMPLE_JOB, "Snowflake", "phenom_people", self._DETECTED)
        assert job is not None
        assert job.posted_at is None or isinstance(job.posted_at, datetime)

    def test_parse_url_present(self):
        if not _SAMPLE_JOB:
            pytest.skip("No job records in fixture")
        from src.adapters.phenom_people import _parse_phenom_job
        job = _parse_phenom_job(_SAMPLE_JOB, "Snowflake", "phenom_people", self._DETECTED)
        assert job is not None
        assert job.url

    def test_parse_missing_location_falls_back_to_not_specified(self):
        from src.adapters.phenom_people import _parse_phenom_job, _LOCATION_KEY
        record = {"id": "99", **{k: v for k, v in (_SAMPLE_JOB or {}).items()}}
        record.pop(_LOCATION_KEY, None)
        for alt in ("city", "locationName", "location_name"):
            record.pop(alt, None)
        if not record.get("title") and not record.get("name"):
            record["title"] = "Test Job"
        job = _parse_phenom_job(record, "Snowflake", "phenom_people", self._DETECTED)
        if job is not None:
            assert job.location == "Not specified"


# ---------------------------------------------------------------------------
# _set_nested tests
# ---------------------------------------------------------------------------
class TestSetNested:
    def test_flat_path(self):
        from src.adapters.phenom_people import _set_nested
        result = _set_nested({"from": 0, "size": 20, "keyword": "intern"}, ["from"], 20)
        assert result["from"] == 20
        assert result["keyword"] == "intern"  # other keys preserved

    def test_nested_path(self):
        from src.adapters.phenom_people import _set_nested
        original = {"pagination": {"from": 0, "size": 20}, "keyword": "intern"}
        result = _set_nested(original, ["pagination", "from"], 20)
        assert result["pagination"]["from"] == 20
        assert result["pagination"]["size"] == 20  # sibling preserved
        assert result["keyword"] == "intern"

    def test_no_mutation_of_original(self):
        from src.adapters.phenom_people import _set_nested
        original = {"from": 0}
        _set_nested(original, ["from"], 99)
        assert original["from"] == 0  # original untouched


# ---------------------------------------------------------------------------
# Adapter tests (all BrowserClient calls mocked — no Chromium needed)
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock
from src.browser import BrowserClient, BrowserSessionContext
from src.adapters.phenom_people import (
    PhenomPeopleAdapter,
    _JOBS_KEY, _TOTAL_KEY, _ID_KEY, _TITLE_KEY, _LOCATION_KEY, _URL_KEY,
    _PAGE_PATH, _PAGE_SIZE,
)
from src.http import HTTPClient

_SNOWFLAKE_CONFIG = {
    "tenant": "SNCOUS",
    "base_url": "https://careers.snowflake.com",
    "search_url": "https://careers.snowflake.com/us/en/search",
    "api_base_url": "https://content-us.phenompeople.com",
    "api_path": "/api/{tenant}/searchJobs",
    "use_playwright": True,
    "browser_timeout_seconds": 30,
}

_CAPTURED_URL = "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
_SENTINEL = object()  # used to distinguish "not passed" from explicit None


def _make_session(
    *,
    method: str = "GET",
    captured_body: str | None = None,
    captured_response: object = _SENTINEL,
    captured_url: str = _CAPTURED_URL,
) -> BrowserSessionContext:
    if captured_response is _SENTINEL:
        captured_response = json.dumps(_one_page(0, total=1))
    return BrowserSessionContext(
        cookies={"sid": "abc"},
        headers={"Origin": "https://careers.snowflake.com"},
        final_url="https://careers.snowflake.com/us/en/search",
        captured_urls=(captured_url,),
        captured_request_headers={},
        captured_first_response=captured_response,
        captured_request_method=method,
        captured_request_url=captured_url,
        captured_request_body=captured_body,
    )


def _one_page(offset: int, *, total: int, size: int = 1) -> dict:
    jobs = [
        {
            _ID_KEY: str(offset + i),
            _TITLE_KEY: f"Software Engineering Intern {offset + i}",
            _LOCATION_KEY: "San Mateo, CA",
            _URL_KEY: f"https://careers.snowflake.com/job/{offset + i}",
        }
        for i in range(size)
    ]
    # Use the real Phenom nested structure
    return {"searchJobs": {"status": "success", "data": {_JOBS_KEY: jobs, _TOTAL_KEY: total}}}


def _make_adapter(session: BrowserSessionContext) -> tuple[PhenomPeopleAdapter, MagicMock]:
    mock_browser = MagicMock(spec=BrowserClient)
    mock_browser.available = True
    mock_browser.bootstrap_session.return_value = session
    adapter = PhenomPeopleAdapter(
        company="Snowflake",
        config=_SNOWFLAKE_CONFIG,
        http=MagicMock(spec=HTTPClient),
        browser=mock_browser,
    )
    return adapter, mock_browser


class TestPhenomPeopleAdapter:
    def test_browser_none_yields_nothing(self):
        adapter = PhenomPeopleAdapter(
            company="Snowflake",
            config=_SNOWFLAKE_CONFIG,
            http=MagicMock(spec=HTTPClient),
            browser=None,
        )
        assert list(adapter.fetch()) == []

    def test_browser_unavailable_yields_nothing(self):
        mock_browser = MagicMock(spec=BrowserClient)
        mock_browser.available = False
        adapter = PhenomPeopleAdapter(
            company="Snowflake",
            config=_SNOWFLAKE_CONFIG,
            http=MagicMock(spec=HTTPClient),
            browser=mock_browser,
        )
        assert list(adapter.fetch()) == []
        mock_browser.bootstrap_session.assert_not_called()

    def test_bootstrap_failure_yields_nothing_and_captures_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        adapter, mock_browser = _make_adapter(_make_session())
        mock_browser.bootstrap_session.side_effect = RuntimeError("timeout")
        assert list(adapter.fetch()) == []
        mock_browser.capture_debug_artifacts.assert_called_once()

    def test_happy_path_single_page(self):
        session = _make_session(captured_response=json.dumps(_one_page(0, total=1)))
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {"searchJobs": {"status": "success", "data": {_JOBS_KEY: [], _TOTAL_KEY: 1}}}
        jobs = list(adapter.fetch())
        assert len(jobs) == 1
        assert jobs[0].title == "Software Engineering Intern 0"
        assert jobs[0].company == "Snowflake"
        assert jobs[0].source_platform == "phenom_people"

    def test_adapter_prefers_captured_url_strips_query(self):
        """API URL comes from captured_request_url, query string stripped."""
        custom_url = "https://content-us.phenompeople.com/api/SNCOUS/searchJobs?extra=1"
        page1 = _one_page(0, total=_PAGE_SIZE * 2, size=_PAGE_SIZE)
        session = _make_session(captured_url=custom_url, captured_response=json.dumps(page1))
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {"searchJobs": {"status": "success", "data": {_JOBS_KEY: [], _TOTAL_KEY: _PAGE_SIZE * 2}}}
        list(adapter.fetch())
        called_url = mock_browser.evaluate_fetch.call_args[0][0]
        assert called_url == "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
        assert "?" not in called_url

    def test_no_xhr_captured_falls_to_evaluate_fetch(self):
        session = _make_session(captured_response=None)
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = _one_page(0, total=1)
        jobs = list(adapter.fetch())
        assert len(jobs) == 1
        mock_browser.evaluate_fetch.assert_called()

    def test_auth_failure_on_captured_response_falls_to_evaluate_fetch(self):
        session = _make_session(captured_response='{"searchJobs":{"status":"failure"}}')
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = _one_page(0, total=1)
        assert len(list(adapter.fetch())) == 1

    def test_auth_failure_on_evaluate_fetch_stops_and_captures_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _make_session(captured_response=None)
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {"searchJobs": {"status": "failure"}}
        assert list(adapter.fetch()) == []
        mock_browser.capture_debug_artifacts.assert_called_once()

    def test_evaluate_fetch_exception_stops_and_captures_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _make_session(captured_response=None)
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.side_effect = RuntimeError("CORS error")
        assert list(adapter.fetch()) == []
        mock_browser.capture_debug_artifacts.assert_called_once()

    def test_get_pagination_sends_updated_params(self):
        page1 = _one_page(0, total=_PAGE_SIZE * 2, size=_PAGE_SIZE)
        session = _make_session(
            method="GET",
            captured_body=None,
            captured_response=json.dumps(page1),
        )
        adapter, mock_browser = _make_adapter(session)
        mock_browser.evaluate_fetch.return_value = {"searchJobs": {"status": "success", "data": {_JOBS_KEY: [], _TOTAL_KEY: _PAGE_SIZE * 2}}}
        list(adapter.fetch())
        mock_browser.evaluate_fetch.assert_called_once()
        sent_params = mock_browser.evaluate_fetch.call_args[0][1]
        assert str(sent_params.get(_PAGE_PATH[-1], "")) == str(_PAGE_SIZE)
