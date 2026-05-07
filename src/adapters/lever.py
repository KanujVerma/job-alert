# src/adapters/lever.py
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


def _strip_html(html: str) -> str:
    """Strip HTML tags; return plain text."""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()


class LeverAdapter(BaseAdapter):
    source_platform = "lever"

    def fetch(self) -> Iterator[Job]:
        slug = self.config["slug"]
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"

        try:
            resp = self.http.get(url)
            postings = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("LeverAdapter [%s] fetch failed: %s", slug, exc)
            return

        detected_at = datetime.now(tz=timezone.utc)

        for posting in postings:
            try:
                yield self._parse(posting, detected_at)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "LeverAdapter [%s] skipping posting %s: %s",
                    slug,
                    posting.get("id"),
                    exc,
                )

    def _parse(self, posting: dict, detected_at: datetime) -> Job:
        categories = posting.get("categories") or {}

        official_id = posting.get("id", "")
        title = posting.get("text", "")
        location = categories.get("location") or ""
        department = categories.get("department")
        team = categories.get("team")
        url = posting.get("hostedUrl", "")

        # createdAt is milliseconds epoch
        created_ms = posting.get("createdAt")
        posted_at: datetime | None = None
        if created_ms is not None:
            posted_at = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)

        # Strip HTML from description; take first 500 chars
        raw_description = _strip_html(posting.get("description") or "")[:_DESCRIPTION_MAX]

        raw_text = " ".join(
            filter(None, [title, location, department, team, raw_description])
        ).lower()

        job_id = make_job_id(
            company=self.company,
            source_platform=self.source_platform,
            title=title,
            location=location,
            official_id=official_id,
        )

        return Job(
            id=job_id,
            company=self.company,
            title=title,
            location=location,
            department=department,
            category=team,
            url=url,
            source_platform=self.source_platform,
            posted_at=posted_at,
            detected_at=detected_at,
            raw_text=raw_text,
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
