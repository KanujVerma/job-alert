"""Ashby *public* Job Postings API. No jobPosting.list/jobsRead credentials.

https://developers.ashbyhq.com/docs/public-job-posting-api
Only isListed=true is a discoverable posting. Missing fields remain unknown.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.adapters.base import BaseAdapter
from src.adapters.public_board import (
    PublicBoardError, description, format_pay, listing_rows, pay_range,
    postal_address, public_https_url, read_public_json, text, timestamp,
    unique_parts, validate_public_board_config,
)
from src.models import Job

logger = logging.getLogger(__name__)
_TYPES = {"FullTime": "full_time", "PartTime": "part_time", "Intern": "internship",
          "Contract": "contract", "Temporary": "temporary"}


def _identity(row: dict, job_url: str, board: str) -> tuple[str, str | None]:
    source_id = row.get("id")
    if isinstance(source_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", source_id):
        return f"{board}:{source_id}", source_id
    # The documented response does not promise an id field. Stable URL-based
    # fallback does not vary with title, description, location or tracking tags.
    parsed = urlsplit(job_url)
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query) if not k.lower().startswith("utm_")])
    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), query, ""))
    return f"{board}:url-{hashlib.sha256(canonical.encode()).hexdigest()[:24]}", None


def _compensation(value: object) -> tuple:
    if not isinstance(value, dict):
        return ()
    result = []
    tiers = value.get("compensationTiers")
    groups = []
    if isinstance(tiers, list) and tiers:
        groups = [(t.get("components"), f"compensation.compensationTiers[{i}].components", t.get("title"))
                  for i, t in enumerate(tiers) if isinstance(t, dict)]
    else:
        groups = [(value.get("summaryComponents"), "compensation.summaryComponents", "")]
    for components, path, label in groups:
        for i, c in enumerate(components if isinstance(components, list) else []):
            if not isinstance(c, dict) or c.get("compensationType") != "Salary":
                continue  # no equity/bonus or opaque combined total treated as cash salary
            interval = c.get("interval") if isinstance(c.get("interval"), str) else None
            interval = interval if interval in {"1 YEAR", "1 MONTH", "1 HOUR"} else None
            r = pay_range(c.get("minValue"), c.get("maxValue"), c.get("currencyCode"),
                          interval, f"{path}[{i}]", label)
            if r:
                result.append(r)
    return tuple(result)


class AshbyAdapter(BaseAdapter):
    source_platform = "ashby"

    @staticmethod
    def validate_source_config(config: dict) -> None:
        validate_public_board_config("ashby", config)

    def fetch(self) -> Iterator[Job]:
        cfg = validate_public_board_config("ashby", self.config)
        endpoint = f"https://api.ashbyhq.com/posting-api/job-board/{cfg.slug}"
        payload = read_public_json(self.http, endpoint, {"includeCompensation": "true"})
        if payload.get("apiVersion") != "1":
            raise PublicBoardError("unsupported/missing Ashby public API version")
        rows = listing_rows(payload)
        now = datetime.now(timezone.utc)
        jobs: list[Job] = []
        seen: set[str] = set()
        bad = 0
        for row in rows:
            if row.get("isListed") is not True:
                continue  # private-by-link/unlisted/unknown is never discovered publicly
            title = text(row.get("title"))
            job_url = public_https_url(row.get("jobUrl"), cfg.allowed_job_hosts)
            apply_url = public_https_url(row.get("applyUrl"), cfg.allowed_job_hosts)
            url = apply_url or job_url
            if not title or len(title) > 4096 or not url or not job_url:
                bad += 1
                continue
            # Hosted URLs must identify this configured board. Custom employer
            # hosts, when explicitly approved in config, are display-only links.
            if any(urlsplit(u).hostname == "jobs.ashbyhq.com" and
                   urlsplit(u).path.strip("/").split("/")[0] != cfg.slug
                   for u in (url, job_url)):
                bad += 1
                continue
            identity, source_id = _identity(row, job_url, cfg.slug)
            if identity in seen:
                continue
            seen.add(identity)
            plain = text(row.get("descriptionPlain"))
            desc, complete = description(plain if plain else row.get("descriptionHtml"), is_html=not bool(plain))
            locations = [text(row.get("location")), postal_address(row.get("address"))]
            secondary = row.get("secondaryLocations")
            for item in secondary if isinstance(secondary, list) else []:
                if isinstance(item, dict):
                    locations += [text(item.get("location")), postal_address(item.get("address"))]
            location = unique_parts(locations)
            department, category = text(row.get("department")), text(row.get("team"))
            kind = _TYPES.get(row.get("employmentType"), "unknown") if isinstance(row.get("employmentType"), str) else "unknown"
            published = timestamp(row.get("publishedAt"))
            pay = _compensation(row.get("compensation"))
            jobs.append(Job(
                id=f"{self.company}::ashby::{identity}", company=self.company,
                title=title, location=location, department=department or None,
                category=category or None, url=url, source_platform=self.source_platform,
                posted_at=published, detected_at=now,
                raw_text="\n".join([desc, title, location, department, category]).lower(),
                role_type="internship" if kind == "internship" else "unknown",
                priority="normal", matched_keywords=(),
                source_url=endpoint, source_board=cfg.slug, source_job_id=source_id,
                posted_at_kind="last_published" if published else "unknown",
                employment_type=kind, description_complete=complete,
                compensation=pay, salary=format_pay(pay),
            ))
        if bad:
            logger.warning("Ashby dropped %d records missing valid listed-post identity/title/URL", bad)
            if not jobs:
                raise PublicBoardError("Ashby response contained invalid postings, not a healthy empty board")
        yield from jobs
