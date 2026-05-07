# amazon_jobs.py
"""
Amazon Jobs adapter — amazon.jobs/en/search.json API.

The adapter runs multiple query passes:
1. If config["include_internship_search"] is True: search with
   normalized_job_type[]=Intern
2. For each category in config["base_categories"]: search that category
3. For each category in config["gated_categories"]: search that category
   (gating is enforced by the filter pipeline via source_config, not here)

Deduplication: jobs seen in an earlier pass are NOT yielded again in later
passes (keyed by id_icims).

Response shape:
    {
        "hits": 10000,       <- total count (int)
        "jobs": [
            {
                "id_icims": "2876543",
                "title": "Software Development Engineer Intern",
                "location": "US, WA, Seattle",
                "normalized_location": "Seattle, Washington, USA",
                "job_category": "Software Development",
                "posted_date": "May  6, 2026",
                "business_category": "amazon web services",
                "job_path": "/en/jobs/2876543/software-development-engineer-intern",
                "description_short": "..."
            }
        ]
    }

Config keys:
    base_url                  (str): Default "https://www.amazon.jobs"
    search_path               (str): Default "/en/search.json"
    result_limit              (int): Page size. Default 25.
    include_internship_search (bool): Whether to do intern-type pass. Default True.
    base_categories           (list[str]): Category names to search.
    gated_categories          (list[str]): Categories requiring early-career gate
                                           (handled by filter pipeline, not adapter).
    country_codes             (list[str]): Country codes filter. Default ["USA"].
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
_POSTED_DATE_FMT = "%B %d, %Y"


class AmazonJobsAdapter(BaseAdapter):
    source_platform = "amazon_jobs"

    def fetch(self) -> Iterator[Job]:
        seen_ids: set[str] = set()

        base_url = self.config.get("base_url", "https://www.amazon.jobs")
        search_path = self.config.get("search_path", "/en/search.json")
        url = base_url.rstrip("/") + search_path

        result_limit = int(self.config.get("result_limit", _DEFAULT_LIMIT))
        country_codes = self.config.get("country_codes", ["USA"])

        # Build pass list: (label, extra_params)
        passes: list[tuple[str, dict]] = []

        if self.config.get("include_internship_search", True):
            passes.append(
                ("intern", {"normalized_job_type[]": "Intern"})
            )

        for cat in self.config.get("base_categories", []):
            passes.append((f"category:{cat}", {"category[]": cat}))

        for cat in self.config.get("gated_categories", []):
            passes.append((f"gated:{cat}", {"category[]": cat}))

        max_pages = int(self.config.get("max_pages_per_pass", 5))

        for label, extra_params in passes:
            yield from self._fetch_pass(
                url=url,
                result_limit=result_limit,
                country_codes=country_codes,
                extra_params=extra_params,
                seen_ids=seen_ids,
                pass_label=label,
                max_pages=max_pages,
            )

    def _fetch_pass(
        self,
        url: str,
        result_limit: int,
        country_codes: list[str],
        extra_params: dict,
        seen_ids: set[str],
        pass_label: str,
        max_pages: int = 5,
    ) -> Iterator[Job]:
        offset = 0
        total_hits: int | None = None
        page = 0

        while True:
            params: dict = {
                "result_limit": result_limit,
                "offset": offset,
            }
            for code in country_codes:
                params["normalized_country_code[]"] = code
            params.update(extra_params)

            try:
                resp = self.http.get(url, params=params)
            except requests.HTTPError as exc:
                logger.warning(
                    "Amazon Jobs pass '%s' HTTP error at offset %d: %s",
                    pass_label, offset, exc,
                )
                return
            except requests.RequestException as exc:
                logger.warning(
                    "Amazon Jobs pass '%s' request failed at offset %d: %s",
                    pass_label, offset, exc,
                )
                return

            try:
                data = resp.json()
            except ValueError as exc:
                logger.warning(
                    "Amazon Jobs pass '%s' invalid JSON at offset %d: %s",
                    pass_label, offset, exc,
                )
                return

            if data.get("error"):
                logger.warning(
                    "Amazon Jobs pass '%s' returned error: %s",
                    pass_label, data["error"],
                )
                return

            # "hits" is a raw int total in the real API
            if total_hits is None:
                hits_val = data.get("hits", 0)
                # hits may be int or list depending on API version
                total_hits = hits_val if isinstance(hits_val, int) else len(hits_val)

            jobs = data.get("jobs", [])
            if not jobs:
                break

            for raw_job in jobs:
                job = self._parse_job(raw_job)
                if job is None:
                    continue
                icims_id = str(raw_job.get("id_icims", ""))
                if icims_id and icims_id in seen_ids:
                    continue
                if icims_id:
                    seen_ids.add(icims_id)
                yield job

            page += 1
            if page >= max_pages:
                break

            offset += result_limit
            if offset >= total_hits:
                break

            self.http.polite_delay(1.0, 2.0)

    def _parse_job(self, raw: dict) -> Job | None:
        title = (raw.get("title") or "").strip()
        if not title:
            return None

        official_id = str(raw.get("id_icims", "")).strip()
        location = (
            raw.get("normalized_location") or raw.get("location") or ""
        ).strip()
        category = raw.get("job_category") or None
        department = (raw.get("business_category") or None)
        if department:
            department = department.strip()

        posted_at = _parse_amazon_date(raw.get("posted_date"))

        job_path = raw.get("job_path", "")
        base = self.config.get("base_url", "https://www.amazon.jobs")
        url = f"{base.rstrip('/')}{job_path}" if job_path else ""

        desc = (raw.get("description_short") or "").strip()
        raw_parts = [title, location]
        if department:
            raw_parts.append(department)
        if category:
            raw_parts.append(category)
        if desc:
            raw_parts.append(desc)
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
            category=category,
            url=url,
            source_platform=self.source_platform,
            posted_at=posted_at,
            detected_at=datetime.now(tz=timezone.utc),
            raw_text=raw_text,
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )


def _parse_amazon_date(value: str | None) -> datetime | None:
    """Parse 'May  6, 2026' or 'January 6, 2025' format."""
    if not value:
        return None
    value = value.strip()
    # Normalize double spaces (e.g. "May  6" → "May 6")
    import re
    value = re.sub(r"\s+", " ", value)
    try:
        return datetime.strptime(value, _POSTED_DATE_FMT).replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return None
