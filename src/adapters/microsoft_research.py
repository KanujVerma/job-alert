"""Microsoft Research careers adapter.

Strategy (tested 2026-05-07):
  1. Attempt Eightfold AI API at apply.careers.microsoft.com with domain=microsoft.com.
     The Microsoft careers site (jobs.careers.microsoft.com) uses Eightfold (vscdn.net).
     The API endpoint apply.careers.microsoft.com/api/apply/v2/jobs returns HTTP 403
     {"message": "Not authorized for PCSX"} — requires session auth from the SPA.
  2. Fallback: fetch https://jobs.careers.microsoft.com/global/en/search?q=research+intern
     and look for __NEXT_DATA__ embedded JSON. The page returns HTML (JS-rendered SPA
     from Eightfold) with no embedded job data in static HTML.

  Result: Both strategies return no usable job data without browser execution.
  The adapter logs a warning and returns []. It NEVER raises.

  If Microsoft exposes a public API in the future, update the _try_eightfold method
  with the correct domain/auth approach.

Config keys:
  base_url: https://www.microsoft.com/en-us/research/careers/open-positions/
  (no other required keys)
"""

from __future__ import annotations

import json
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
_EIGHTFOLD_API = "https://apply.careers.microsoft.com/api/apply/v2/jobs"
_SEARCH_URL = "https://jobs.careers.microsoft.com/global/en/search"


def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class MicrosoftResearchAdapter(BaseAdapter):
    """Adapter for Microsoft Research job listings.

    Attempts Eightfold API first, then falls back to HTML __NEXT_DATA__ scrape.
    Both currently blocked by auth/JS requirements; returns [] with a log warning.
    """

    source_platform = "microsoft_research"

    def fetch(self) -> Iterator[Job]:
        detected_at = datetime.now(tz=timezone.utc)

        # Strategy 1: try Eightfold API
        yield from self._try_eightfold(detected_at)

    def _try_eightfold(self, detected_at: datetime) -> Iterator[Job]:
        """Attempt Eightfold API at apply.careers.microsoft.com."""
        offset = 0
        total: int | None = None

        while True:
            params = {
                "domain": "microsoft.com",
                "limit": _LIMIT,
                "offset": offset,
                "json": "true",
                "q": "research intern",
            }
            try:
                resp = self.http.get(_EIGHTFOLD_API, params=params)
            except requests.RequestException as exc:
                logger.warning(
                    "MicrosoftResearchAdapter: Eightfold API request failed: %s. "
                    "Falling back to HTML scrape.",
                    exc,
                )
                yield from self._try_html_scrape(detected_at)
                return

            if not resp.ok:
                logger.warning(
                    "MicrosoftResearchAdapter: Eightfold API returned HTTP %d "
                    "(url=%s). Falling back to HTML scrape.",
                    resp.status_code, _EIGHTFOLD_API,
                )
                yield from self._try_html_scrape(detected_at)
                return

            try:
                payload = resp.json()
            except ValueError as exc:
                logger.warning(
                    "MicrosoftResearchAdapter: Eightfold API JSON parse error: %s. "
                    "Falling back to HTML scrape.",
                    exc,
                )
                yield from self._try_html_scrape(detected_at)
                return

            # Detect Eightfold failure / auth required
            status = payload.get("status")
            if status == "failure":
                logger.warning(
                    "MicrosoftResearchAdapter: Eightfold API failure: %s. "
                    "Falling back to HTML scrape.",
                    payload.get("errorMsg", "unknown"),
                )
                yield from self._try_html_scrape(detected_at)
                return

            if "message" in payload and "authorized" in payload.get("message", "").lower():
                logger.warning(
                    "MicrosoftResearchAdapter: Eightfold API not authorized: %s. "
                    "Falling back to HTML scrape.",
                    payload.get("message"),
                )
                yield from self._try_html_scrape(detected_at)
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
                    job = self._parse_position(pos, detected_at)
                    if job is not None:
                        yield job
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "MicrosoftResearchAdapter: skipping position %s: %s",
                        pos.get("id"), exc,
                    )

            offset += _LIMIT
            if total is not None and offset >= total:
                break

            self.http.polite_delay(1.0, 2.0)

    def _try_html_scrape(self, detected_at: datetime) -> Iterator[Job]:
        """Fallback: fetch search page and look for __NEXT_DATA__ JSON."""
        params = {
            "q": "research intern",
            "l": "en_us",
            "pg": 1,
            "pgSz": 20,
            "o": "Relevance",
            "flt": "true",
        }
        try:
            resp = self.http.get(_SEARCH_URL, params=params)
        except requests.RequestException as exc:
            logger.warning(
                "MicrosoftResearchAdapter: HTML scrape request failed: %s. "
                "Returning empty result.",
                exc,
            )
            return

        if not resp.ok:
            logger.warning(
                "MicrosoftResearchAdapter: HTML scrape returned HTTP %d. "
                "Returning empty result.",
                resp.status_code,
            )
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if script_tag and script_tag.string:
            try:
                page_data = json.loads(script_tag.string)
                jobs_data = (
                    page_data.get("props", {})
                    .get("pageProps", {})
                    .get("jobs", [])
                )
                if not jobs_data:
                    # Try alternate nesting
                    jobs_data = (
                        page_data.get("props", {})
                        .get("pageProps", {})
                        .get("searchResults", [])
                    )
                for raw_job in jobs_data:
                    job = self._parse_next_data_job(raw_job, detected_at)
                    if job is not None:
                        yield job
                return
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "MicrosoftResearchAdapter: __NEXT_DATA__ parse error: %s",
                    exc,
                )

        # No usable data found
        logger.warning(
            "MicrosoftResearchAdapter: page at %s appears to be a JS-rendered SPA "
            "(Eightfold) with no static job data. Returning empty result.",
            _SEARCH_URL,
        )

    def _parse_position(self, pos: dict, detected_at: datetime) -> Job | None:
        """Parse an Eightfold-style position dict."""
        official_id = str(pos.get("id") or "").strip()
        title = (pos.get("name") or "").strip()
        if not title:
            return None

        location = (pos.get("location") or "Redmond, Washington").strip()
        department = (pos.get("department") or "Microsoft Research").strip() or None
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

    def _parse_next_data_job(self, raw: dict, detected_at: datetime) -> Job | None:
        """Parse a job from __NEXT_DATA__ props (flexible field mapping)."""
        title = (
            raw.get("title")
            or raw.get("jobTitle")
            or raw.get("name")
            or ""
        ).strip()
        if not title:
            return None

        official_id = str(
            raw.get("jobId") or raw.get("id") or raw.get("jobNumber") or ""
        ).strip()
        location = (
            raw.get("location")
            or raw.get("primaryLocation")
            or "Redmond, Washington"
        ).strip()
        department = (
            raw.get("department")
            or raw.get("researchArea")
            or raw.get("discipline")
            or "Microsoft Research"
        )
        job_url = (raw.get("url") or raw.get("jobDetailsUrl") or "").strip()

        raw_desc = _strip_html(raw.get("description") or "")[:_DESCRIPTION_MAX]
        raw_text = " ".join(
            filter(None, [title, location, str(department), raw_desc])
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
            department=str(department) if department else None,
            category=None,
            url=job_url,
            source_platform=self.source_platform,
            posted_at=None,
            detected_at=detected_at,
            raw_text=raw_text,
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
