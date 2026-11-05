"""Workday CXS adapter.

Supports any company hosted on Workday by configuring:
  base_url, tenant, site

Known companies:
  Micron, Salesforce, CrowdStrike, Intel, Applied Materials
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from src.adapters.base import BaseAdapter
from src.eligibility import _check_tech_role, _SENIOR_TITLE_PATTERN, _INTERN_TITLE_PATTERN
from src.filtering import make_job_id, _check_single_location
from src.models import Job

logger = logging.getLogger(__name__)

# Matches "Posting Date 01/06/2025"
_POSTING_DATE_RE = re.compile(r"Posting Date\s+(\d{2}/\d{2}/\d{4})")
# Matches "Posted Today"
_POSTED_TODAY_RE = re.compile(r"Posted\s+Today", re.IGNORECASE)
# Matches "Posted 3 Days Ago" or "Posted 30+ Days Ago"
_POSTED_DAYS_AGO_RE = re.compile(r"Posted\s+(\d+)\+?\s+Days?\s+Ago", re.IGNORECASE)
# Matches bullet field that looks like a req ID: starts with letters then digits
_REQ_ID_RE = re.compile(r"^[A-Z]{1,4}\d{4,}$")

_LIMIT = 20


def _parse_posted_on(raw: str, reference_dt: datetime | None = None) -> datetime | None:
    """Parse postedOn field to UTC datetime if possible.

    Handles absolute "Posting Date MM/DD/YYYY" and relative "Posted X Days Ago" / "Posted Today".
    For relative strings, reference_dt anchors the calculation (typically the fetch start time).
    """
    if not raw:
        return None

    # Absolute: "Posting Date 01/06/2025"
    m = _POSTING_DATE_RE.search(raw)
    if m:
        try:
            return datetime.strptime(m.group(1), "%m/%d/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    if reference_dt is not None:
        ref = reference_dt.replace(hour=0, minute=0, second=0, microsecond=0)

        # "Posted Today"
        if _POSTED_TODAY_RE.search(raw):
            return ref

        # "Posted X Days Ago" or "Posted 30+ Days Ago"
        m = _POSTED_DAYS_AGO_RE.search(raw)
        if m:
            return ref - timedelta(days=int(m.group(1)))

    return None


def _extract_official_id(bullet_fields: list) -> str | None:
    """Return first bullet field that looks like a requisition ID."""
    for field in bullet_fields or []:
        if isinstance(field, str) and _REQ_ID_RE.match(field):
            return field
    return None


def _parse_workday_location(locations_text: str, external_path: str) -> str:
    """Normalize location string from locationsText and externalPath."""
    loc = locations_text.strip() if locations_text else ""
    if not loc or re.search(r"^\d+\s+locations?$", loc, re.IGNORECASE):
        m = re.match(r"^/job/([^/]+)/", external_path or "")
        if m:
            slug = m.group(1)
            return slug.replace("---", ", ").replace("--", ", ").replace("-", " ")
    return loc


def _clean_workday_description(html_text: str) -> str:
    """Unescape HTML entities and strip markup into clean text."""
    if not html_text:
        return ""
    text = html.unescape(html_text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_workday_detail(
    http: Any,
    base_url: str,
    tenant: str,
    site: str,
    external_path: str,
) -> dict | None:
    """Retrieve full job detail from Workday CXS detail endpoint."""
    if not external_path:
        return None
    endpoint = f"{base_url}/wday/cxs/{tenant}/{site}{external_path}"
    try:
        resp = http.get(endpoint)
        if resp.status_code == 200:
            return resp.json().get("jobPostingInfo", {})
    except Exception as exc:
        logger.debug("Workday CXS detail fetch failed for %s: %s", external_path, exc)
    return None


class WorkdayAdapter(BaseAdapter):
    source_platform = "workday"

    def fetch(self) -> Iterator[Job]:
        base_url = self.config["base_url"].rstrip("/")
        tenant = self.config["tenant"]
        site = self.config["site"]
        endpoint = f"{base_url}/wday/cxs/{tenant}/{site}/jobs"

        offset = 0
        total: int | None = None
        detected_at = datetime.now(timezone.utc)

        while True:
            payload = {
                "appliedFacets": {},
                "limit": _LIMIT,
                "offset": offset,
                "searchText": "",
            }

            try:
                resp = self.http.post(endpoint, json=payload)
            except Exception as exc:
                logger.error(
                    "WorkdayAdapter[%s]: request failed at offset=%d: %s",
                    self.company, offset, exc,
                )
                return

            if resp.status_code != 200:
                logger.error(
                    "WorkdayAdapter[%s]: non-200 at offset=%d: %s",
                    self.company, offset, resp.status_code,
                )
                return

            try:
                data = resp.json()
                if total is None:
                    total = int(data.get("total", 0))
                postings = data.get("jobPostings", [])
            except Exception as exc:
                logger.error(
                    "WorkdayAdapter[%s]: JSON parse error at offset=%d: %s",
                    self.company, offset, exc,
                )
                return

            for posting in postings:
                title = posting.get("title") or ""
                external_path = posting.get("externalPath") or ""
                locations_text = posting.get("locationsText") or ""
                posted_on = posting.get("postedOn") or ""
                bullet_fields = posting.get("bulletFields") or []
                job_family_group = posting.get("jobFamilyGroup") or ""
                job_family = posting.get("jobFamily") or ""

                # Workday externalPath may or may not include the site segment.
                # Ensure it's always present: base_url/{site}/job/...
                if external_path:
                    site_prefix = f"/{site.strip('/')}/"
                    if not external_path.startswith(site_prefix):
                        url = f"{base_url.rstrip('/')}/{site.strip('/')}{external_path}"
                    else:
                        url = f"{base_url.rstrip('/')}{external_path}"
                else:
                    url = ""
                official_id = _extract_official_id(bullet_fields)
                posted_at = _parse_posted_on(posted_on, reference_dt=detected_at)
                department = job_family_group if job_family_group else None
                category = job_family if job_family else None
                location = _parse_workday_location(locations_text, external_path)

                raw_parts = [
                    title.lower(),
                    location.lower(),
                    job_family_group.lower(),
                    job_family.lower(),
                ]
                raw_text = " ".join(part for part in raw_parts if part)

                role_type = "unknown"

                # Cheap filter check: only fetch CXS detail for promising candidates
                is_tech, is_nontech, _ = _check_tech_role(title, department, category)
                is_senior = bool(_SENIOR_TITLE_PATTERN.search(title))
                is_intern = bool(_INTERN_TITLE_PATTERN.search(title))
                is_us, _ = _check_single_location(location)

                if (
                    is_tech
                    and not is_nontech
                    and not is_senior
                    and not is_intern
                    and is_us is not False
                    and self.config.get("fetch_details", True)
                    and external_path
                ):
                    detail = _fetch_workday_detail(self.http, base_url, tenant, site, external_path)
                    if detail:
                        clean_desc = _clean_workday_description(detail.get("jobDescription", ""))
                        time_type = detail.get("timeType")
                        if clean_desc:
                            raw_text = f"{clean_desc} {raw_text}"
                        if time_type:
                            raw_text = f"{raw_text} {str(time_type).lower()}"
                            if "intern" in str(time_type).lower():
                                role_type = "internship"
                        detail_loc = detail.get("location")
                        if detail_loc:
                            location = str(detail_loc)
                        add_locs = detail.get("additionalLocations") or []
                        if add_locs:
                            location = f"{location}; " + "; ".join(str(l) for l in add_locs)

                job_id = make_job_id(
                    company=self.company,
                    source_platform=self.source_platform,
                    title=title,
                    location=location,
                    official_id=official_id,
                )

                yield Job(
                    id=job_id,
                    company=self.company,
                    title=title,
                    location=location,
                    department=department,
                    category=category,
                    url=url,
                    source_platform=self.source_platform,
                    posted_at=posted_at,
                    detected_at=detected_at,
                    raw_text=raw_text,
                    role_type=role_type,
                    priority="normal",
                    matched_keywords=(),
                )

            offset += _LIMIT
            if total is not None and offset >= total:
                break
