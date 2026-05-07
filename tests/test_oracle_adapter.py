"""Tests for OracleAdapter."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.adapters.oracle_careers import OracleAdapter
from src.http import HTTPClient
from src.models import Job

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_http() -> MagicMock:
    http = MagicMock(spec=HTTPClient)
    http.polite_delay = MagicMock()
    return http


def _make_adapter(http: MagicMock, config: dict | None = None) -> OracleAdapter:
    cfg = config or {
        "base_url": "https://eeho.fa.us2.oraclecloud.com",
        "api_path": "/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
    }
    return OracleAdapter(company="Oracle", config=cfg, http=http)


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Basic field mapping
# ---------------------------------------------------------------------------

class TestOracleFieldMapping:
    def test_yields_jobs_from_fixture(self):
        fixture = _load_fixture("oracle_hcm.json")
        http = _make_http()
        http.get.return_value = _mock_response(fixture)

        adapter = _make_adapter(http)
        jobs = list(adapter.fetch())

        assert len(jobs) == 3

    def test_source_platform(self):
        fixture = _load_fixture("oracle_hcm.json")
        http = _make_http()
        http.get.return_value = _mock_response(fixture)

        jobs = list(_make_adapter(http).fetch())
        for job in jobs:
            assert job.source_platform == "oracle_careers"

    def test_field_mapping_first_job(self):
        fixture = _load_fixture("oracle_hcm.json")
        http = _make_http()
        http.get.return_value = _mock_response(fixture)

        jobs = list(_make_adapter(http).fetch())
        j = jobs[0]

        assert j.title == "Software Engineering Intern"
        assert j.location == "US-CA-Santa Clara"
        assert j.department == "Information Technology"
        assert "careers.oracle.com" in j.url
        assert j.posted_at is not None
        assert j.posted_at.year == 2025

    def test_url_constructed_when_empty(self):
        """Job with empty ExternalURL gets constructed URL from Id."""
        fixture = _load_fixture("oracle_hcm.json")
        http = _make_http()
        http.get.return_value = _mock_response(fixture)

        jobs = list(_make_adapter(http).fetch())
        # Third job has empty ExternalURL
        j = jobs[2]
        assert j.url == "https://careers.oracle.com/jobs/240614"

    def test_official_id_in_job_id(self):
        fixture = _load_fixture("oracle_hcm.json")
        http = _make_http()
        http.get.return_value = _mock_response(fixture)

        jobs = list(_make_adapter(http).fetch())
        # Id-based job IDs include the official_id
        assert "240612" in jobs[0].id

    def test_raw_text_lowercased_contains_title(self):
        fixture = _load_fixture("oracle_hcm.json")
        http = _make_http()
        http.get.return_value = _mock_response(fixture)

        jobs = list(_make_adapter(http).fetch())
        j = jobs[0]
        assert "software engineering intern" in j.raw_text
        assert j.raw_text == j.raw_text.lower()

    def test_short_description_in_raw_text(self):
        fixture = _load_fixture("oracle_hcm.json")
        http = _make_http()
        http.get.return_value = _mock_response(fixture)

        jobs = list(_make_adapter(http).fetch())
        j = jobs[0]
        assert "oracle" in j.raw_text  # from ShortDescription

    def test_posted_at_none_when_missing(self):
        data = {
            "count": 1,
            "hasMore": False,
            "items": [
                {
                    "requisitionList": [
                        {
                            "Id": "999",
                            "Title": "Test Job",
                            "PrimaryLocation": "US-CA",
                            "JobFunction": "IT",
                            "PostedDate": None,
                            "ExternalURL": "https://example.com",
                            "ShortDescription": "",
                        }
                    ]
                }
            ],
        }
        http = _make_http()
        http.get.return_value = _mock_response(data)

        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 1
        assert jobs[0].posted_at is None

    def test_job_is_frozen_dataclass(self):
        fixture = _load_fixture("oracle_hcm.json")
        http = _make_http()
        http.get.return_value = _mock_response(fixture)

        jobs = list(_make_adapter(http).fetch())
        assert isinstance(jobs[0], Job)
        with pytest.raises((AttributeError, TypeError)):
            jobs[0].title = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestOraclePagination:
    def test_two_page_pagination(self):
        """Adapter fetches second page when hasMore=True on first page."""
        page1 = {
            "count": 2,
            "hasMore": True,
            "totalResults": 4,
            "items": [
                {"requisitionList": [{"Id": "1", "Title": "Job A", "PrimaryLocation": "US-CA",
                                       "JobFunction": "IT", "PostedDate": None,
                                       "ExternalURL": "https://example.com/1", "ShortDescription": ""}]},
                {"requisitionList": [{"Id": "2", "Title": "Job B", "PrimaryLocation": "US-TX",
                                       "JobFunction": "IT", "PostedDate": None,
                                       "ExternalURL": "https://example.com/2", "ShortDescription": ""}]},
            ],
        }
        page2 = {
            "count": 2,
            "hasMore": False,
            "totalResults": 4,
            "items": [
                {"requisitionList": [{"Id": "3", "Title": "Job C", "PrimaryLocation": "US-WA",
                                       "JobFunction": "IT", "PostedDate": None,
                                       "ExternalURL": "https://example.com/3", "ShortDescription": ""}]},
                {"requisitionList": [{"Id": "4", "Title": "Job D", "PrimaryLocation": "US-NY",
                                       "JobFunction": "IT", "PostedDate": None,
                                       "ExternalURL": "https://example.com/4", "ShortDescription": ""}]},
            ],
        }

        http = _make_http()
        http.get.side_effect = [_mock_response(page1), _mock_response(page2)]

        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 4
        assert http.get.call_count == 2

    def test_stops_when_no_items(self):
        """Empty items list stops pagination immediately."""
        data = {"count": 0, "hasMore": False, "items": []}
        http = _make_http()
        http.get.return_value = _mock_response(data)

        jobs = list(_make_adapter(http).fetch())
        assert jobs == []
        assert http.get.call_count == 1

    def test_pagination_uses_offset(self):
        """Second page call uses correct offset parameter."""
        page1 = {
            "count": 2,
            "hasMore": True,
            "totalResults": 4,
            "items": [
                {"requisitionList": [{"Id": "1", "Title": "Job A", "PrimaryLocation": "US-CA",
                                       "JobFunction": "IT", "PostedDate": None,
                                       "ExternalURL": "https://example.com/1", "ShortDescription": ""}]},
                {"requisitionList": [{"Id": "2", "Title": "Job B", "PrimaryLocation": "US-TX",
                                       "JobFunction": "IT", "PostedDate": None,
                                       "ExternalURL": "https://example.com/2", "ShortDescription": ""}]},
            ],
        }
        page2 = {"count": 0, "hasMore": False, "items": []}

        http = _make_http()
        http.get.side_effect = [_mock_response(page1), _mock_response(page2)]

        list(_make_adapter(http).fetch())

        # Second call should have offset=2
        _, kwargs = http.get.call_args_list[1]
        params = kwargs.get("params", {})
        assert params.get("offset") == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestOracleErrorHandling:
    def test_http_error_yields_nothing(self):
        http = _make_http()
        http.get.side_effect = requests.HTTPError("403 Forbidden")

        jobs = list(_make_adapter(http).fetch())
        assert jobs == []

    def test_connection_error_yields_nothing(self):
        http = _make_http()
        http.get.side_effect = requests.ConnectionError("network down")

        jobs = list(_make_adapter(http).fetch())
        assert jobs == []

    def test_invalid_json_yields_nothing(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = ValueError("bad json")

        http = _make_http()
        http.get.return_value = resp

        jobs = list(_make_adapter(http).fetch())
        assert jobs == []

    def test_missing_title_job_skipped(self):
        data = {
            "count": 2,
            "hasMore": False,
            "items": [
                {"requisitionList": [{"Id": "1", "Title": "", "PrimaryLocation": "US-CA",
                                       "JobFunction": "IT", "PostedDate": None,
                                       "ExternalURL": "https://example.com", "ShortDescription": ""}]},
                {"requisitionList": [{"Id": "2", "Title": "Real Job", "PrimaryLocation": "US-TX",
                                       "JobFunction": "IT", "PostedDate": None,
                                       "ExternalURL": "https://example.com/2", "ShortDescription": ""}]},
            ],
        }
        http = _make_http()
        http.get.return_value = _mock_response(data)

        jobs = list(_make_adapter(http).fetch())
        assert len(jobs) == 1
        assert jobs[0].title == "Real Job"
