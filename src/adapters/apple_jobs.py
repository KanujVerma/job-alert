# apple_jobs.py
"""
Apple Jobs adapter — jobs.apple.com/api/role/search (POST).

The adapter runs two passes based on config["sources"]:

1. Internship pass (kind: "internships"):
   POST body includes teams: ["internships-STDNT-INTRN"]
   All yielded jobs get role_type = "internship".

2. General pass (kind: "general"):
   POST body uses empty teams filter.
   Jobs get role_type = "unknown".
   Gating (require_early_career) is enforced by the filter pipeline, not here.

Deduplication: if a job id appears in pass 1, it is NOT yielded again in pass 2.

Response shape:
    {
        "searchResults": [
            {
                "id": "200606296",
                "postingTitle": "Software Engineering Intern",
                "location": "Cupertino, California, United States",
                "teamName": "Software and Services",
                "jobNumber": "200606296",
                "homeOffice": false,
                "jobUrl": "https://jobs.apple.com/en-us/details/200606296/..."
            }
        ],
        "currentPage": 1,
        "totalRecords": 87,
        "pageSize": 20
    }

HTML fallback (general source only):
    If the POST returns non-200, the adapter attempts a GET to
    https://jobs.apple.com/en-us/search?location=united-states-USA
    and parses job listings with BeautifulSoup. If that also fails,
    yields nothing and logs the error.

Note: As of 2026-05 the API endpoint redirects with 301 in this
environment; the adapter handles this gracefully by logging and
falling back or returning nothing.

Config keys:
    api_url   (str): Default "https://jobs.apple.com/api/role/search"
    fallback_url (str): Default "https://jobs.apple.com/en-us/search"
    locations (list[str]): Location filter slugs. Default ["united-states-USA"].
    sources   (list[dict]): List of source configs with keys:
                kind       (str): "internships" or "general"
                teams      (list[str], optional): team slugs to filter
                require_early_career (bool): passed through to filter pipeline
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import requests

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = "https://jobs.apple.com/api/role/search"
_DEFAULT_FALLBACK_URL = "https://jobs.apple.com/en-us/search"
_DEFAULT_LOCATIONS = ["united-states-USA"]

_DEFAULT_SOURCES = [
    {
        "kind": "internships",
        "teams": ["internships-STDNT-INTRN"],
        "require_early_career": False,
    },
    {
        "kind": "general",
        "teams": [],
        "require_early_career": True,
    },
]


class AppleJobsAdapter(BaseAdapter):
    source_platform = "apple_jobs"

    def fetch(self) -> Iterator[Job]:
        seen_ids: set[str] = set()

        api_url = self.config.get("api_url", _DEFAULT_API_URL)
        locations = self.config.get("locations", _DEFAULT_LOCATIONS)
        sources = self.config.get("sources", _DEFAULT_SOURCES)

        for source in sources:
            kind = source.get("kind", "general")
            teams = source.get("teams", [])
            role_type = "internship" if kind == "internships" else "unknown"

            yield from self._fetch_source(
                api_url=api_url,
                locations=locations,
                teams=teams,
                role_type=role_type,
                seen_ids=seen_ids,
                source_kind=kind,
            )

    def _fetch_source(
        self,
        api_url: str,
        locations: list[str],
        teams: list[str],
        role_type: str,
        seen_ids: set[str],
        source_kind: str,
    ) -> Iterator[Job]:
        page = 1
        page_size: int | None = None
        total_records: int | None = None

        while True:
            payload: dict[str, Any] = {
                "query": "",
                "filters": {
                    "range": {
                        "standardWeeklyHours": {"start": None, "end": None}
                    },
                    "roleChange": False,
                    "managementLevel": [],
                    "locations": locations,
                },
                "page": page,
                "locale": "en-US",
                "sort": "newest",
            }
            if teams:
                payload["filters"]["teams"] = teams

            try:
                resp = self.http.post(api_url, json=payload)
            except requests.HTTPError as exc:
                logger.warning(
                    "Apple Jobs '%s' HTTP error on page %d: %s",
                    source_kind, page, exc,
                )
                if source_kind == "general":
                    yield from self._html_fallback(role_type, seen_ids)
                return
            except requests.RequestException as exc:
                logger.warning(
                    "Apple Jobs '%s' request failed on page %d: %s",
                    source_kind, page, exc,
                )
                if source_kind == "general":
                    yield from self._html_fallback(role_type, seen_ids)
                return

            # Check content type — Apple may return HTML on error
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype:
                logger.warning(
                    "Apple Jobs '%s' returned non-JSON (status %d). "
                    "content-type: %s",
                    source_kind, resp.status_code, ctype,
                )
                if source_kind == "general":
                    yield from self._html_fallback(role_type, seen_ids)
                return

            try:
                data = resp.json()
            except ValueError as exc:
                logger.warning(
                    "Apple Jobs '%s' invalid JSON on page %d: %s",
                    source_kind, page, exc,
                )
                return

            if page_size is None:
                page_size = data.get("pageSize", 20)
            if total_records is None:
                total_records = data.get("totalRecords", 0)

            results = data.get("searchResults", [])
            if not results:
                break

            for raw_job in results:
                job = self._parse_job(raw_job, role_type)
                if job is None:
                    continue
                job_id_key = str(raw_job.get("id") or raw_job.get("jobNumber") or "")
                if job_id_key and job_id_key in seen_ids:
                    continue
                if job_id_key:
                    seen_ids.add(job_id_key)
                yield job

            # Pagination: continue while (page-1)*pageSize < totalRecords
            if total_records is not None and page_size:
                if page * page_size >= total_records:
                    break
            else:
                break

            page += 1
            self.http.polite_delay(1.0, 2.0)

    def _parse_job(self, raw: dict, role_type: str) -> Job | None:
        title = (raw.get("postingTitle") or "").strip()
        if not title:
            return None

        official_id = str(raw.get("id") or raw.get("jobNumber") or "").strip()
        location = (raw.get("location") or "").strip()
        department = (raw.get("teamName") or None)
        if department:
            department = department.strip()

        job_url = (raw.get("jobUrl") or "").strip()
        if not job_url and official_id:
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            job_url = f"https://jobs.apple.com/en-us/details/{official_id}/{slug}"

        raw_parts = [title, location]
        if department:
            raw_parts.append(department)
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
            url=job_url,
            source_platform=self.source_platform,
            posted_at=None,
            detected_at=datetime.now(tz=timezone.utc),
            raw_text=raw_text,
            role_type=role_type,
            priority="normal",
            matched_keywords=(),
        )

    def _html_fallback(self, role_type: str, seen_ids: set[str]) -> Iterator[Job]:
        """
        HTML fallback: GET the Apple jobs search page and parse with BeautifulSoup.
        Used only for the 'general' source when the API is unavailable.
        Returns nothing if BeautifulSoup parsing fails.
        """
        fallback_url = self.config.get("fallback_url", _DEFAULT_FALLBACK_URL)
        params = {"location": "united-states-USA"}
        logger.warning(
            "Apple Jobs API unavailable — falling back to HTML scrape: %s",
            fallback_url,
        )

        try:
            resp = self.http.get(fallback_url, params=params)
        except requests.RequestException as exc:
            logger.error("Apple Jobs HTML fallback request failed: %s", exc)
            return

        try:
            from bs4 import BeautifulSoup  # type: ignore
        except ImportError:
            logger.error(
                "Apple Jobs HTML fallback: BeautifulSoup not installed. "
                "Install beautifulsoup4 to enable fallback parsing."
            )
            return

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Apple's search page renders jobs in <a> tags with data attributes
            # or in JSON embedded in a <script id="__NEXT_DATA__"> block.
            script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
            if script_tag and script_tag.string:
                import json
                page_data = json.loads(script_tag.string)
                # Attempt to find job listings in the page data
                jobs_data = (
                    page_data.get("props", {})
                    .get("pageProps", {})
                    .get("searchResults", [])
                )
                for raw_job in jobs_data:
                    job = self._parse_job(raw_job, role_type)
                    if job is None:
                        continue
                    job_id_key = str(
                        raw_job.get("id") or raw_job.get("jobNumber") or ""
                    )
                    if job_id_key and job_id_key in seen_ids:
                        continue
                    if job_id_key:
                        seen_ids.add(job_id_key)
                    yield job
            else:
                logger.warning(
                    "Apple Jobs HTML fallback: could not find __NEXT_DATA__ "
                    "in page. No jobs extracted."
                )
        except Exception as exc:
            logger.error("Apple Jobs HTML fallback parsing failed: %s", exc)
