"""Official unauthenticated Greenhouse Job Board GET API (not Harvest).

https://docs.greenhouse.io/job-board
The list endpoint returns all posts; it does not document cursor pagination.
Post ID identifies the advertised posting; internal_job_id identifies the
underlying job and MUST NOT merge distinct language/location advertisements.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urlsplit

from src.adapters.base import BaseAdapter
from src.adapters.public_board import (
    PublicBoardError, description, format_pay, listing_rows, pay_range,
    public_https_url, read_public_json, text, timestamp, unique_parts,
    validate_public_board_config,
)
from src.models import Job

logger = logging.getLogger(__name__)


def _numeric_id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0:
        return value
    return None


def _employment(metadata: object) -> str:
    mapping = {
        "fulltime": "full_time", "parttime": "part_time", "intern": "internship",
        "internship": "internship", "contract": "contract", "contractor": "contract",
        "temporary": "temporary", "coop": "co_op",
    }
    for field in metadata if isinstance(metadata, list) else []:
        if not isinstance(field, dict):
            continue
        if text(field.get("name")).lower() not in {"employment type", "employment_type"}:
            continue
        value = text(field.get("value")).lower().replace("-", "").replace("_", "").replace(" ", "")
        return mapping.get(value, "unknown")
    return "unknown"


class GreenhouseAdapter(BaseAdapter):
    source_platform = "greenhouse"

    @staticmethod
    def validate_source_config(config: dict) -> None:
        validate_public_board_config("greenhouse", config)

    def fetch(self) -> Iterator[Job]:
        cfg = validate_public_board_config("greenhouse", self.config)
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{cfg.slug}/jobs"
        payload = read_public_json(self.http, endpoint, {"content": "true"})
        rows = listing_rows(payload, greenhouse=True)
        now = datetime.now(timezone.utc)
        jobs: list[Job] = []
        seen: set[str] = set()
        bad = 0
        detail_requests = 0
        for row in rows:
            # Greenhouse explicitly documents null internal_job_id as a prospect post.
            if "internal_job_id" in row and row["internal_job_id"] is None:
                continue
            post_id = _numeric_id(row.get("id"))
            internal_id = _numeric_id(row.get("internal_job_id"))
            title = text(row.get("title"))
            url = public_https_url(row.get("absolute_url"), cfg.allowed_job_hosts)
            if not post_id or not internal_id or not title or len(title) > 4096 or not url:
                bad += 1
                continue
            # Do not accept a valid vendor domain that points at a different
            # employer board. Custom application hosts require explicit config.
            parsed_url = urlsplit(url)
            if parsed_url.hostname in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
                path_parts = parsed_url.path.strip("/").split("/")
                if len(path_parts) < 3 or path_parts[:2] != [cfg.slug, "jobs"] or path_parts[2] != post_id:
                    bad += 1
                    continue
            if post_id in seen:
                continue
            seen.add(post_id)
            data = row
            desc, complete = description(data.get("content"), is_html=True)
            # Optional bounded detail fallback; never fetch arbitrary URLs from payloads.
            if not complete and detail_requests < cfg.detail_limit:
                detail_requests += 1
                try:
                    detail = read_public_json(self.http, f"{endpoint}/{post_id}", {"pay_transparency": "true"})
                    if _numeric_id(detail.get("id")) != post_id or _numeric_id(detail.get("internal_job_id")) != internal_id:
                        raise PublicBoardError("detail identity mismatch")
                    data = dict(row, **detail)
                    desc, complete = description(data.get("content"), is_html=True)
                except PublicBoardError:
                    logger.warning("Greenhouse detail unavailable for post %s; preserve incomplete evidence", post_id)
            locations = []
            loc = data.get("location")
            if isinstance(loc, dict):
                locations.append(text(loc.get("name")))
            offices = data.get("offices")
            for office in offices if isinstance(offices, list) else []:
                if isinstance(office, dict):
                    locations.append(text(office.get("location")))
            location = unique_parts(locations)
            departments = data.get("departments")
            department = unique_parts([
                text(d.get("name")) for d in departments if isinstance(d, dict)
            ]) if isinstance(departments, list) else ""
            ranges = []
            pay = data.get("pay_input_ranges")
            for i, item in enumerate(pay if isinstance(pay, list) else []):
                if not isinstance(item, dict):
                    continue
                value = pay_range(item.get("min_cents"), item.get("max_cents"),
                                  item.get("currency_type"), None,
                                  f"pay_input_ranges[{i}]", item.get("title"), divisor=100)
                if value:
                    ranges.append(value)
            published = timestamp(data.get("first_published"))
            jobs.append(Job(
                id=f"{self.company}::greenhouse::{cfg.slug}:{post_id}",
                company=self.company, title=title, location=location,
                department=department or None, category=None,
                url=url, source_platform=self.source_platform,
                posted_at=published, detected_at=now,
                raw_text="\n".join([desc, title, location, department]).lower(),
                role_type="internship" if _employment(data.get("metadata")) == "internship" else "unknown",
                priority="normal", matched_keywords=(),
                source_url=f"{endpoint}/{post_id}", source_board=cfg.slug,
                source_job_id=post_id, source_internal_job_id=internal_id,
                source_updated_at=timestamp(data.get("updated_at")),
                posted_at_kind="first_published" if published else "unknown",
                employment_type=_employment(data.get("metadata")),
                description_complete=complete, compensation=tuple(ranges),
                salary=format_pay(tuple(ranges)),
            ))
        if bad:
            logger.warning("Greenhouse dropped %d records missing valid public identity/title/URL", bad)
            if not jobs:
                raise PublicBoardError("Greenhouse response contained invalid postings, not a healthy empty board")
        yield from jobs
