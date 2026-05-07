# oracle_careers.py
"""
Oracle Careers adapter — HCM Recruiting REST API.

Primary endpoint:
    GET https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&limit=25&offset=0&expand=requisitionList

The public careers.oracle.com URL redirects to a 404 for this endpoint,
so we use the underlying Oracle Cloud HCM tenant URL directly.

Response shape:
    {
        "count": 25,
        "hasMore": true,
        "items": [
            {
                "requisitionList": [
                    {
                        "Id": "240612",
                        "Title": "Software Engineering Intern",
                        "PrimaryLocation": "US-CA-Santa Clara",
                        "JobFunction": "Information Technology",
                        "PostedDate": "2025-01-15T00:00:00+00:00",
                        "ExternalURL": "https://careers.oracle.com/...",
                        "ShortDescription": "..."
                    }
                ]
            }
        ]
    }

If the HCM endpoint returns a non-200 response (e.g. the tenant URL changes or
access is revoked), the adapter logs the error and yields nothing — it does NOT
fall back to web scraping, because the Oracle careers page is a heavy React SPA
that requires JavaScript rendering and does not expose stable HTML job listings.

Config keys:
    base_url  (str): Oracle HCM tenant base URL, e.g.
                     "https://eeho.fa.us2.oraclecloud.com"
    api_path  (str): Path to the requisitions endpoint, e.g.
                     "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    limit     (int, optional): Page size. Default 25.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

import requests

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 25


class OracleAdapter(BaseAdapter):
    source_platform = "oracle_careers"

    def fetch(self) -> Iterator[Job]:
        base_url = self.config.get("base_url", "https://eeho.fa.us2.oraclecloud.com")
        api_path = self.config.get(
            "api_path",
            "/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
        )
        limit = int(self.config.get("limit", _DEFAULT_LIMIT))
        url = base_url.rstrip("/") + api_path

        offset = 0
        total = None

        while True:
            params = {
                "onlyData": "true",
                "limit": limit,
                "offset": offset,
                "expand": "requisitionList",
            }

            try:
                resp = self.http.get(url, params=params)
            except requests.HTTPError as exc:
                logger.error(
                    "Oracle HCM API HTTP error at offset %d: %s", offset, exc
                )
                return
            except requests.RequestException as exc:
                logger.error(
                    "Oracle HCM API request failed at offset %d: %s", offset, exc
                )
                return

            try:
                data = resp.json()
            except ValueError as exc:
                logger.error("Oracle HCM API returned invalid JSON: %s", exc)
                return

            count = data.get("count", 0)
            has_more = data.get("hasMore", False)

            # totalResults may be present (spec says so) but some tenant versions
            # omit it — fall back to has_more flag.
            if total is None:
                total = data.get("totalResults")

            items = data.get("items", [])
            if not items:
                break

            for item in items:
                req_list = item.get("requisitionList", [])
                for req in req_list:
                    job = self._parse_requisition(req)
                    if job is not None:
                        yield job

            # Advance pagination
            offset += count if count > 0 else limit

            # Stop conditions
            if not has_more:
                break
            if total is not None and offset >= total:
                break
            if count == 0:
                break

            self.http.polite_delay(1.0, 2.0)

    def _parse_requisition(self, req: dict) -> Job | None:
        official_id = str(req.get("Id", "")).strip()
        title = (req.get("Title") or "").strip()
        if not title:
            return None

        location = (req.get("PrimaryLocation") or "").strip()
        department = (req.get("JobFunction") or None)
        posted_at = _parse_iso_date(req.get("PostedDate"))

        external_url = (req.get("ExternalURL") or "").strip()
        if not external_url and official_id:
            external_url = f"https://careers.oracle.com/jobs/{official_id}"

        short_desc = (req.get("ShortDescription") or "").strip()
        raw_parts = [title, location]
        if department:
            raw_parts.append(department)
        if short_desc:
            raw_parts.append(short_desc)
        raw_text = " ".join(raw_parts).lower()

        job_id = make_job_id(
            company=self.company,
            source_platform=self.source_platform,
            title=title,
            location=location,
            official_id=official_id if official_id else None,
        )

        return Job(
            id=job_id,
            company=self.company,
            title=title,
            location=location,
            department=department,
            category=None,
            url=external_url,
            source_platform=self.source_platform,
            posted_at=posted_at,
            detected_at=datetime.now(tz=timezone.utc),
            raw_text=raw_text,
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Python 3.7+ handles ISO 8601 with timezone offset
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
