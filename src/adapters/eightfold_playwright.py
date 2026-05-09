# src/adapters/eightfold_playwright.py
"""Eightfold adapter with Playwright browser bootstrap for JS-rendered SPA auth.

Two-tier auth strategy:
1. Intercept XHR request headers during SPA boot → relay via HTTPClient (fast).
2. If relay returns 401/403 or auth error JSON → fall back to browser.evaluate_fetch().

Pilot adapter for Snowflake (careers.snowflake.com).
Config keys: base_url, api_path, location_country, use_playwright, browser_timeout_seconds.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone

import requests

from src.adapters.base import BaseAdapter
from src.adapters.eightfold import _strip_html, _parse_iso, _DESCRIPTION_MAX, _LIMIT
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)


def _is_auth_failure(payload: dict) -> bool:
    """Return True if the JSON payload indicates an authentication/tenant failure."""
    return payload.get("status") == "failure" or bool(payload.get("errorMsg"))


class EightfoldPlaywrightAdapter(BaseAdapter):
    """Eightfold adapter that bootstraps the SPA via Playwright to obtain auth."""

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

        # Step 1: Boot SPA, intercept XHR request headers
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

        api_url = f"{base_url}{api_path}"
        detected_at = datetime.now(tz=timezone.utc)
        offset = 0
        total: int | None = None
        use_fallback = False

        # Prefer captured request headers; fall back to session headers if empty
        relay_headers = session.captured_request_headers or session.headers

        # Step 2: Page-1 optimisation — use captured response if available
        if session.captured_first_response:
            try:
                payload = json.loads(session.captured_first_response)
                data = payload.get("data") or payload
                positions = data.get("positions", [])
                page_total = data.get("count", len(positions))
                if total is None:
                    total = page_total
                for pos in positions:
                    try:
                        job = _parse_position(
                            pos, self.company, self.source_platform, detected_at
                        )
                        if job is not None:
                            yield job
                    except Exception as exc:
                        logger.warning(
                            "EightfoldPlaywrightAdapter[%s]: skipping position %s: %s",
                            self.company, pos.get("id"), exc,
                        )
                offset += len(positions)
                if total is not None and offset >= total:
                    return
                self.http.polite_delay(1.0, 2.0)
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "EightfoldPlaywrightAdapter[%s]: bad captured_first_response, "
                    "continuing from offset 0: %s",
                    self.company, exc,
                )
                offset = 0  # reset and start from scratch

        # Step 3: Paginate remaining pages
        while True:
            params: dict = {
                "domain": domain,
                "limit": _LIMIT,
                "offset": offset,
                "json": "true",
            }
            if location_country:
                params["location_country"] = location_country

            if use_fallback:
                try:
                    payload = self.browser.evaluate_fetch(api_url, params)
                except Exception as exc:
                    logger.error(
                        "EightfoldPlaywrightAdapter[%s]: evaluate_fetch failed at offset=%d: %s",
                        self.company, offset, exc,
                    )
                    self.browser.capture_debug_artifacts(self.company, exc)
                    return
            else:
                try:
                    resp = self.http.get(
                        api_url,
                        params=params,
                        cookies=session.cookies,
                        headers=relay_headers,
                    )
                except requests.RequestException as exc:
                    logger.error(
                        "EightfoldPlaywrightAdapter[%s]: request failed at offset=%d: %s",
                        self.company, offset, exc,
                    )
                    return

                if resp.status_code in (401, 403):
                    logger.info(
                        "EightfoldPlaywrightAdapter[%s]: HTTP %d — switching to page.evaluate fallback",
                        self.company, resp.status_code,
                    )
                    use_fallback = True
                    continue  # retry this offset with fallback

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

                if _is_auth_failure(payload):
                    logger.info(
                        "EightfoldPlaywrightAdapter[%s]: auth error ('%s') — switching to page.evaluate fallback",
                        self.company, payload.get("errorMsg", "unknown"),
                    )
                    use_fallback = True
                    continue  # retry this offset with fallback

            data = payload.get("data") or payload
            positions = data.get("positions", [])
            count = data.get("count", len(positions))

            if total is None:
                total = count

            if not positions:
                break

            for pos in positions:
                try:
                    job = _parse_position(
                        pos, self.company, self.source_platform, detected_at
                    )
                    if job is not None:
                        yield job
                except Exception as exc:
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
