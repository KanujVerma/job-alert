"""Eightfold AI talent platform adapter.

Supports companies hosted on Eightfold by configuring base_url, api_path,
and location_country.

Known companies:
  Snowflake (careers.snowflake.com)

Working endpoint discovery (tested 2026-05-07):
  The Eightfold API at https://careers.snowflake.com/api/apply/v2/jobs returns
  "Tenant not identified" with plain query params because the tenant is resolved
  from the HTTP Origin/Referer or an internal session cookie set by the JS SPA.

  Attempted endpoints (all return 200 + {"status":"failure","errorMsg":"Tenant not identified"}):
    GET /api/apply/v2/jobs?domain=snowflake.com&...
    GET /api/apply/v2/jobs?domain=careers.snowflake.com&...
    GET /api/apply/v2/jobs?tenantId=SNCOUS&...
    POST /api/apply/v2/jobs with JSON body
  Careers site actually uses Phenom People (phenompeople.com) as the SPA layer.

  The adapter attempts a GET with the configured domain param. If the API
  returns a failure status or non-JSON, it logs a warning and returns [].

Expected response shape (when tenant resolves):
  {
    "status": "success",
    "data": {
      "count": 10,
      "positions": [
        {
          "id": "12345",
          "name": "Software Engineer Intern",
          "location": "San Mateo, California",
          "department": "Engineering",
          "canonicalPositionUrl": "https://careers.snowflake.com/...",
          "t_create": "2025-01-15T00:00:00Z",
          "description": "<p>...</p>"
        }
      ]
    }
  }
  Alternate shape (positions at top level):
  {
    "count": 10,
    "positions": [...]
  }

Config keys:
  base_url: https://careers.snowflake.com
  api_path: /api/apply/v2/jobs
  location_country: United States    (optional)
  domain: snowflake.com              (optional override; default derived from base_url)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

_DESCRIPTION_MAX = 500
_LIMIT = 20


def _strip_html(html: str) -> str:
    """Strip HTML tags; return plain text."""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse ISO8601 timestamp to UTC datetime."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class EightfoldAdapter(BaseAdapter):
    """Adapter for Eightfold AI talent platform (e.g., Snowflake)."""

    source_platform = "eightfold"

    def fetch(self) -> Iterator[Job]:
        base_url = self.config["base_url"].rstrip("/")
        api_path = self.config.get("api_path", "/api/apply/v2/jobs")
        location_country = self.config.get("location_country", "United States")
        # Derive domain from base_url if not explicitly configured
        domain = self.config.get("domain") or base_url.split("//", 1)[-1].split("/")[0]

        url = f"{base_url}{api_path}"
        offset = 0
        total: int | None = None
        detected_at = datetime.now(tz=timezone.utc)

        while True:
            params: dict = {
                "domain": domain,
                "limit": _LIMIT,
                "offset": offset,
                "json": "true",
            }
            if location_country:
                params["location_country"] = location_country

            try:
                resp = self.http.get(url, params=params)
            except requests.RequestException as exc:
                logger.error(
                    "EightfoldAdapter[%s]: request failed at offset=%d url=%s: %s",
                    self.company, offset, url, exc,
                )
                return

            if not resp.ok:
                logger.error(
                    "EightfoldAdapter[%s]: HTTP %d at offset=%d url=%s",
                    self.company, resp.status_code, offset, url,
                )
                return

            try:
                payload = resp.json()
            except ValueError as exc:
                logger.error(
                    "EightfoldAdapter[%s]: JSON parse error at offset=%d: %s",
                    self.company, offset, exc,
                )
                return

            # Handle Eightfold failure status
            status = payload.get("status")
            if status == "failure":
                logger.warning(
                    "EightfoldAdapter[%s]: API returned failure status: %s (url=%s). "
                    "Tenant may require session cookie or auth header from JS SPA.",
                    self.company,
                    payload.get("errorMsg", "unknown"),
                    url,
                )
                return

            # Positions may be at top level or nested under "data"
            data = payload.get("data") or payload
            positions = data.get("positions", [])
            count = data.get("count", len(positions))

            if total is None:
                total = count

            if not positions:
                break

            for pos in positions:
                try:
                    job = self._parse(pos, detected_at)
                    if job is not None:
                        yield job
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "EightfoldAdapter[%s]: skipping position %s: %s",
                        self.company, pos.get("id"), exc,
                    )

            offset += _LIMIT
            if total is not None and offset >= total:
                break

            self.http.polite_delay(1.0, 2.0)

    def _parse(self, pos: dict, detected_at: datetime) -> Job | None:
        official_id = str(pos.get("id") or "").strip()
        title = (pos.get("name") or "").strip()
        if not title:
            return None

        location = (pos.get("location") or "Not specified").strip()
        department = (pos.get("department") or "").strip() or None
        job_url = (pos.get("canonicalPositionUrl") or "").strip()

        posted_at = _parse_iso(pos.get("t_create"))

        raw_desc = _strip_html(pos.get("description") or "")[:_DESCRIPTION_MAX]

        raw_text = " ".join(
            filter(None, [title, location, department, raw_desc])
        ).lower()

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
            url=job_url,
            source_platform=self.source_platform,
            posted_at=posted_at,
            detected_at=detected_at,
            raw_text=raw_text,
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
