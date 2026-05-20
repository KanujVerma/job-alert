# src/adapters/smartrecruiters.py
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

import requests
from dateutil.parser import parse as parse_iso

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

_LIMIT = 100


def _build_location(loc: dict) -> str:
    """Combine city, region, country — skip None/empty parts."""
    parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    return ", ".join(p for p in parts if p)


class SmartRecruitersAdapter(BaseAdapter):
    source_platform = "smartrecruiters"

    def fetch(self) -> Iterator[Job]:
        slug = self.config["slug"]
        base_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        detected_at = datetime.now(tz=timezone.utc)

        offset = 0
        total_found: int | None = None

        while True:
            try:
                resp = self.http.get(base_url, params={"limit": _LIMIT, "offset": offset})
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                logger.error(
                    "SmartRecruitersAdapter [%s] fetch failed at offset %d: %s",
                    slug,
                    offset,
                    exc,
                )
                return

            if total_found is None:
                total_found = data.get("totalFound", 0)

            content = data.get("content", [])
            for item in content:
                try:
                    yield self._parse(item, detected_at)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "SmartRecruitersAdapter [%s] skipping posting %s: %s",
                        slug,
                        item.get("id"),
                        exc,
                    )

            offset += len(content)
            if offset >= total_found or not content:
                break

    def _parse(self, item: dict, detected_at: datetime) -> Job:
        official_id = item.get("id", "")
        title = item.get("name", "")

        loc_dict = item.get("location") or {}
        location = _build_location(loc_dict)

        dept_dict = item.get("department") or {}
        department = dept_dict.get("label") or None

        emp_dict = item.get("typeOfEmployment") or {}
        category = emp_dict.get("label") or None

        slug = self.config["slug"]
        url = (
            f"https://jobs.smartrecruiters.com/{slug}/{official_id}"
            if official_id
            else item.get("ref", "")
        )

        released = item.get("releasedDate")
        posted_at: datetime | None = None
        if released:
            posted_at = parse_iso(released)
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)

        raw_text = " ".join(
            filter(None, [title, location, department, category])
        ).lower()

        job_id = make_job_id(
            company=self.company,
            source_platform=self.source_platform,
            title=title,
            location=location,
            official_id=official_id,
        )

        return Job(
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
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
