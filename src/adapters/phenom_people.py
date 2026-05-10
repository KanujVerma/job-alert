# src/adapters/phenom_people.py
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

_JOBS_KEY = "jobs"
_TOTAL_KEY = "totalHits"
_ID_KEY = "jobSeqNo"
_TITLE_KEY = "title"
_LOCATION_KEY = "location"
_DEPT_KEY = "category"
_URL_KEY = "detailUrl"
_POSTED_KEY = "postedDate"

_PAGE_PATH: list[str] = ["from"]
_PAGE_SIZE = 10


def _is_auth_failure(payload: dict) -> bool:
    search = payload.get("searchJobs")
    if isinstance(search, dict):
        if search.get("status") == "failure":
            return True
        if bool(search.get("errorMsg")):
            return True
    return payload.get("status") == "failure" or bool(payload.get("errorMsg"))


def _set_nested(d: dict, path: list[str], value: object) -> dict:
    """Return a shallow-copy of d with path set to value (no mutation)."""
    if not path:
        return d
    result = dict(d)
    if len(path) == 1:
        result[path[0]] = value
    else:
        result[path[0]] = _set_nested(dict(d.get(path[0]) or {}), path[1:], value)
    return result


def _extract_location(record: dict) -> str:
    loc = record.get(_LOCATION_KEY)
    if isinstance(loc, str):
        return loc.strip() or "Not specified"
    if isinstance(loc, dict):
        city = loc.get("city") or loc.get("name") or ""
        state = loc.get("state") or loc.get("stateCode") or ""
        parts = [p for p in (city, state) if p]
        return ", ".join(parts) or "Not specified"
    return "Not specified"


def _parse_posted_at(record: dict) -> datetime | None:
    raw = record.get(_POSTED_KEY)
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def _extract_jobs_list(payload: dict) -> list:
    # Real Phenom structure: payload["searchJobs"]["data"]["jobs"]
    search = payload.get("searchJobs")
    if isinstance(search, dict):
        data = search.get("data")
        if isinstance(data, dict):
            val = data.get(_JOBS_KEY)
            if isinstance(val, list):
                return val
    # Fallback for flat or alternative structures
    val = payload.get(_JOBS_KEY)
    if isinstance(val, list):
        return val
    data = payload.get("data")
    if isinstance(data, dict):
        for key in (_JOBS_KEY, "positions", "jobs"):
            sub = data.get(key)
            if isinstance(sub, list):
                return sub
    return []


def _extract_total(payload: dict) -> int | None:
    # Real Phenom structure: payload["searchJobs"]["data"]["totalHits"]
    search = payload.get("searchJobs")
    if isinstance(search, dict):
        data = search.get("data")
        if isinstance(data, dict):
            for key in (_TOTAL_KEY, "total", "count", "totalCount"):
                val = data.get(key)
                if isinstance(val, int):
                    return val
    # Fallback
    val = payload.get(_TOTAL_KEY)
    if isinstance(val, int):
        return val
    data = payload.get("data")
    if isinstance(data, dict):
        for key in (_TOTAL_KEY, "total", "count", "totalCount"):
            sub = data.get(key)
            if isinstance(sub, int):
                return sub
    return None


def _parse_phenom_job(
    record: dict,
    company: str,
    source_platform: str,
    detected_at: datetime,
) -> Job | None:
    """Parse one Phenom People job record into a Job. Returns None if title missing."""
    official_id = str(record.get(_ID_KEY) or "").strip()
    title = (record.get(_TITLE_KEY) or "").strip()
    if not title:
        return None

    location = _extract_location(record)
    department = (record.get(_DEPT_KEY) or "").strip() or None
    url = (record.get(_URL_KEY) or "").strip()
    posted_at = _parse_posted_at(record)
    raw_text = " ".join(filter(None, [title, location, department])).lower()

    job_id = make_job_id(
        company=company,
        source_platform=source_platform,
        title=title,
        location=location,
        official_id=official_id if official_id else None,
    )

    return Job(
        id=job_id,
        company=company,
        title=title,
        location=location,
        department=department,
        category=None,
        url=url,
        source_platform=source_platform,
        posted_at=posted_at,
        detected_at=detected_at,
        raw_text=raw_text,
        role_type="unknown",
        priority="normal",
        matched_keywords=(),
    )


class PhenomPeopleAdapter(BaseAdapter):
    source_platform = "phenom_people"

    def fetch(self) -> Iterator[Job]:
        yield from ()  # stub — implemented in Task 4
