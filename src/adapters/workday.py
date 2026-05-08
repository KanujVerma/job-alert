"""Workday CXS adapter.

Supports any company hosted on Workday by configuring:
  base_url, tenant, site

Known companies:
  Micron, Salesforce, CrowdStrike, Intel, Applied Materials
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import datetime, timezone

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

# Matches "Posting Date 01/06/2025"
_POSTING_DATE_RE = re.compile(r"Posting Date\s+(\d{2}/\d{2}/\d{4})")
# Matches bullet field that looks like a req ID: starts with letters then digits
_REQ_ID_RE = re.compile(r"^[A-Z]{1,4}\d{4,}$")

_LIMIT = 20


def _parse_posted_on(raw: str) -> datetime | None:
    """Parse postedOn field to UTC datetime if possible."""
    if not raw:
        return None

    # Format: "Posting Date 01/06/2025"
    m = _POSTING_DATE_RE.search(raw)
    if m:
        try:
            return datetime.strptime(m.group(1), "%m/%d/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # "Posted Today" / "Posted X Days Ago" — relative, skip
    return None


def _extract_official_id(bullet_fields: list) -> str | None:
    """Return first bullet field that looks like a requisition ID."""
    for field in bullet_fields or []:
        if isinstance(field, str) and _REQ_ID_RE.match(field):
            return field
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
                posted_at = _parse_posted_on(posted_on)
                department = job_family_group if job_family_group else None
                category = job_family if job_family else None

                raw_text = " ".join(
                    part for part in [
                        title.lower(),
                        locations_text.lower(),
                        job_family_group.lower(),
                        job_family.lower(),
                    ]
                    if part
                )

                job_id = make_job_id(
                    company=self.company,
                    source_platform=self.source_platform,
                    title=title,
                    location=locations_text,
                    official_id=official_id,
                )

                yield Job(
                    id=job_id,
                    company=self.company,
                    title=title,
                    location=locations_text,
                    department=department,
                    category=category,
                    url=url,
                    source_platform=self.source_platform,
                    posted_at=posted_at,
                    detected_at=detected_at,
                    raw_text=raw_text,
                    role_type="unknown",
                    priority="normal",
                    matched_keywords=(),
                )

            offset += _LIMIT
            if total is not None and offset >= total:
                break
