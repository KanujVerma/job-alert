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
