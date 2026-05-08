# src/adapters/eightfold_playwright.py
"""Eightfold adapter with Playwright browser bootstrap for JS-rendered SPA auth.

Pilot adapter for Snowflake (careers.snowflake.com). Boots the SPA via
BrowserClient to capture session cookies, then uses the existing HTTPClient
for JSON pagination. Parser logic mirrors EightfoldAdapter._parse but is
implemented locally to avoid inheritance coupling.

Config keys (same as eightfold adapter, plus):
  use_playwright: true
  browser_timeout_seconds: 30    (optional, default 30)
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

import requests

from src.adapters.base import BaseAdapter
from src.adapters.eightfold import _strip_html, _parse_iso, _DESCRIPTION_MAX, _LIMIT
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)


class EightfoldPlaywrightAdapter(BaseAdapter):
    """Eightfold adapter that bootstraps the SPA via Playwright to obtain auth cookies."""

    source_platform = "eightfold_playwright"

    def fetch(self) -> Iterator[Job]:
        if self.browser is None or not self.browser.available:
            logger.warning(
                "EightfoldPlaywrightAdapter[%s]: no BrowserClient available — skipping",
                self.company,
            )
            return

        base_url = self.config["base_url"].rstrip("/")
        api_path = self.config.get("api_path", "/api/apply/v2/jobs")
        location_country = self.config.get("location_country", "United States")
        domain = self.config.get("domain") or base_url.split("//", 1)[-1].split("/")[0]
        timeout_seconds = int(self.config.get("browser_timeout_seconds", 30))

        # Step 1: Boot SPA, capture cookies + headers
        try:
            session = self.browser.bootstrap_session(
                base_url,
                company=self.company,
                wait_for_response_url="**/api/apply/v2/jobs**",
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            logger.warning(
                "EightfoldPlaywrightAdapter[%s]: browser bootstrap failed: %s",
                self.company, exc,
            )
            return

        if not session.cookies:
            logger.warning(
                "EightfoldPlaywrightAdapter[%s]: bootstrap returned no cookies — cannot auth",
                self.company,
            )
            return

        # Step 2: Paginate the JSON API with captured cookies + headers
        api_url = f"{base_url}{api_path}"
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
                resp = self.http.get(
                    api_url,
                    params=params,
                    cookies=session.cookies,
                    headers=session.headers,
                )
            except requests.RequestException as exc:
                logger.error(
                    "EightfoldPlaywrightAdapter[%s]: request failed at offset=%d: %s",
                    self.company, offset, exc,
                )
                return

            if not resp.ok:
                logger.error(
                    "EightfoldPlaywrightAdapter[%s]: HTTP %d at offset=%d",
                    self.company, resp.status_code, offset,
                )
                return

            try:
                payload = resp.json()
            except ValueError as exc:
                logger.error(
                    "EightfoldPlaywrightAdapter[%s]: JSON parse error at offset=%d: %s",
                    self.company, offset, exc,
                )
                return

            status = payload.get("status")
            if status == "failure":
                logger.warning(
                    "EightfoldPlaywrightAdapter[%s]: API returned failure: %s",
                    self.company, payload.get("errorMsg", "unknown"),
                )
                return

            data = payload.get("data") or payload
            positions = data.get("positions", [])
            count = data.get("count", len(positions))

            if total is None:
                total = count

            if not positions:
                break

            for pos in positions:
                try:
                    job = _parse_position(pos, self.company, self.source_platform, detected_at)
                    if job is not None:
                        yield job
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "EightfoldPlaywrightAdapter[%s]: skipping position %s: %s",
                        self.company, pos.get("id"), exc,
                    )

            offset += len(positions)
            if total is not None and offset >= total:
                break

            self.http.polite_delay(1.0, 2.0)


def _parse_position(
    pos: dict,
    company: str,
    source_platform: str,
    detected_at: datetime,
) -> Job | None:
    """Parse one Eightfold position dict into a Job. Returns None if title is missing."""
    official_id = str(pos.get("id") or "").strip()
    title = (pos.get("name") or "").strip()
    if not title:
        return None

    location = (pos.get("location") or "Not specified").strip()
    department = (pos.get("department") or "").strip() or None
    job_url = (pos.get("canonicalPositionUrl") or "").strip()
    posted_at = _parse_iso(pos.get("t_create"))
    raw_desc = _strip_html(pos.get("description") or "")[:_DESCRIPTION_MAX]
    raw_text = " ".join(filter(None, [title, location, department, raw_desc])).lower()

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
        url=job_url,
        source_platform=source_platform,
        posted_at=posted_at,
        detected_at=detected_at,
        raw_text=raw_text,
        role_type="unknown",
        priority="normal",
        matched_keywords=(),
    )
