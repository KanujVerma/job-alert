# apple_jobs.py
"""
Apple Jobs adapter — HTML scraping of jobs.apple.com/en-us/search.

The old POST API (jobs.apple.com/api/role/search) is dead as of 2026-05 —
it returns 404 for all requests. The search page is server-side rendered and
exposes job listings directly in HTML, so we scrape it with BeautifulSoup.

The adapter runs two passes based on config["sources"]:

1. Internship pass (kind: "internships"):
   GET with &team=internships-STDNT-INTRN query param.
   All yielded jobs get role_type = "internship".

2. General pass (kind: "general"):
   GET without a team filter (all US jobs).
   Jobs get role_type = "unknown".
   Gating (require_early_career) is enforced by the filter pipeline, not here.

Deduplication: if a job id appears in pass 1, it is NOT yielded again in pass 2.

Page structure (each page, 20 unique jobs):
    <div class="... job-list-item ..." id="search-search-job-title-PIPE-{id}-{n}">
      <div class="... job-title-link ...">
        <h3><a href="/en-us/details/{id}/{slug}?team=TEAM">Title</a></h3>
        <span class="team-name mt-0">Team Name</span>
        <span class="job-posted-date">May 07, 2026</span>
      </div>
      <div class="... job-title-location ...">
        <span class="a11y">Location</span>
        <span class="table--advanced-search__location-sub">Location Text</span>
      </div>
    </div>

Pagination:
    GET /en-us/search?location=united-states-USA&page=N
    Stop when page returns no job rows (past last page).
    Capped at max_pages (default 50) to prevent runaway.

Config keys:
    search_url (str): Default "https://jobs.apple.com/en-us/search"
    locations  (list[str]): Location slugs. Default ["united-states-USA"].
    max_pages  (int): Max pages per pass. Default 50.
    sources    (list[dict]): List of source configs with keys:
                kind       (str): "internships" or "general"
                team       (str, optional): team slug to filter
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

_DEFAULT_SEARCH_URL = "https://jobs.apple.com/en-us/search"
_DEFAULT_LOCATIONS = ["united-states-USA"]
_DEFAULT_MAX_PAGES = 20

_DEFAULT_SOURCES = [
    {
        "kind": "internships",
        "team": "internships-STDNT-INTRN",
        "require_early_career": False,
    },
    {
        "kind": "general",
        "require_early_career": True,
    },
]

_POSTED_DATE_FMT = "%b %d, %Y"  # "May 07, 2026"


class AppleJobsAdapter(BaseAdapter):
    source_platform = "apple_jobs"

    def fetch(self) -> Iterator[Job]:
        seen_ids: set[str] = set()

        search_url = self.config.get("search_url", _DEFAULT_SEARCH_URL)
        locations = self.config.get("locations", _DEFAULT_LOCATIONS)
        max_pages = int(self.config.get("max_pages", _DEFAULT_MAX_PAGES))
        sources = self.config.get("sources", _DEFAULT_SOURCES)

        for source in sources:
            kind = source.get("kind", "general")
            team = source.get("team", "")
            role_type = "internship" if kind == "internships" else "unknown"

            yield from self._fetch_source(
                search_url=search_url,
                locations=locations,
                team=team,
                role_type=role_type,
                seen_ids=seen_ids,
                source_kind=kind,
                max_pages=max_pages,
            )

    def _fetch_source(
        self,
        search_url: str,
        locations: list[str],
        team: str,
        role_type: str,
        seen_ids: set[str],
        source_kind: str,
        max_pages: int,
    ) -> Iterator[Job]:
        try:
            from bs4 import BeautifulSoup  # type: ignore
        except ImportError:
            logger.error(
                "Apple Jobs adapter requires beautifulsoup4. "
                "Install it: pip install beautifulsoup4"
            )
            return

        location_param = locations[0] if locations else "united-states-USA"

        for page in range(1, max_pages + 1):
            params: dict[str, Any] = {
                "location": location_param,
                "page": page,
            }
            if team:
                params["team"] = team

            try:
                resp = self.http.get(search_url, params=params)
            except requests.RequestException as exc:
                logger.warning(
                    "Apple Jobs '%s' request failed on page %d: %s",
                    source_kind, page, exc,
                )
                return

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.find_all(
                "div",
                class_=lambda c: c and "job-list-item" in c,
            )

            if not rows:
                break

            yielded_this_page = 0
            for row in rows:
                job = self._parse_row(row, role_type, seen_ids)
                if job is not None:
                    yielded_this_page += 1
                    yield job

            if yielded_this_page == 0:
                # All jobs on this page were already seen — stop
                break

            if page < max_pages:
                self.http.polite_delay(0.3, 0.7)

    def _parse_row(
        self,
        row: Any,
        role_type: str,
        seen_ids: set[str],
    ) -> Job | None:
        # Find the main job link (not the locationPicker variant)
        link = row.find(
            "a",
            href=lambda h: h and "/en-us/details/" in h and "locationPicker" not in h,
        )
        if link is None:
            return None

        title = link.get_text(strip=True)
        if not title:
            return None

        href = link.get("href", "")
        # Extract official ID: /en-us/details/{id}/{slug}
        id_match = re.match(r"/en-us/details/([^/]+)/", href)
        official_id = id_match.group(1) if id_match else ""

        # Dedup by official ID across passes
        if official_id and official_id in seen_ids:
            return None
        if official_id:
            seen_ids.add(official_id)

        job_url = "https://jobs.apple.com" + href if href.startswith("/") else href

        # Team / department
        team_span = row.find("span", class_="team-name")
        department = team_span.get_text(strip=True) if team_span else None
        if not department:
            department = None

        # Location
        loc_span = row.find("span", class_="table--advanced-search__location-sub")
        location = loc_span.get_text(strip=True) if loc_span else ""

        # Posted date
        date_span = row.find("span", class_="job-posted-date")
        posted_at = _parse_posted_date(date_span.get_text(strip=True) if date_span else "")

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
            posted_at=posted_at,
            detected_at=datetime.now(tz=timezone.utc),
            raw_text=raw_text,
            role_type=role_type,
            priority="normal",
            matched_keywords=(),
        )


def _parse_posted_date(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), _POSTED_DATE_FMT).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
