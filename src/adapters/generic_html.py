"""Generic HTML adapter for scraping job listings from static HTML career pages.

Supports any company with a static or server-rendered careers page by
configuring CSS selectors. Selectors can be auto-detected if not provided.

Applied Digital (applieddigital.com/careers) investigation (2026-05-07):
  The page is a Webflow-hosted SPA (27KB static HTML, JS-rendered content).
  No job listings appear in the static HTML — the page uses JavaScript to
  load job content after initial page load. Links to job board platforms
  (Lever, Greenhouse, Ashby, Workday) were not found in the static HTML.
  The adapter falls back to auto-detection which finds no jobs and returns [].

Config keys:
  url: https://www.applieddigital.com/careers     (required)
  job_card_selector: ".job-card"                  (optional, empty = auto-detect)
  title_selector:    ".job-title"                 (optional, relative to job card)
  location_selector: ".job-location"              (optional, relative to job card)
  url_selector:      "a.job-link"                 (optional, relative to job card)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

# CSS classes/tags used for auto-detection heuristics
_AUTO_CARD_PATTERNS = [
    "[class*='job-card']",
    "[class*='job_card']",
    "[class*='jobCard']",
    "[class*='position-card']",
    "[class*='career-card']",
    "[class*='opening']",
    "article",
]

_AUTO_TITLE_PATTERNS = [
    "[class*='job-title']",
    "[class*='job_title']",
    "[class*='jobTitle']",
    "[class*='position-title']",
    "h2",
    "h3",
    "h4",
]

_AUTO_LOCATION_PATTERNS = [
    "[class*='job-location']",
    "[class*='location']",
    "[class*='city']",
    "[class*='office']",
    "span",
]


class GenericHTMLAdapter(BaseAdapter):
    """Generic adapter for scraping job listings from HTML career pages."""

    source_platform = "generic_html"

    def fetch(self) -> Iterator[Job]:
        url = self.config.get("url", "")
        if not url:
            logger.warning(
                "GenericHTMLAdapter[%s]: no 'url' configured. Returning empty.",
                self.company,
            )
            return

        try:
            resp = self.http.get(url)
        except requests.RequestException as exc:
            logger.warning(
                "GenericHTMLAdapter[%s]: request failed for %s: %s",
                self.company, url, exc,
            )
            return

        if not resp.ok:
            logger.warning(
                "GenericHTMLAdapter[%s]: HTTP %d for %s. Returning empty.",
                self.company, resp.status_code, url,
            )
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        detected_at = datetime.now(tz=timezone.utc)

        job_card_selector = self.config.get("job_card_selector", "").strip()
        title_selector = self.config.get("title_selector", "").strip()
        location_selector = self.config.get("location_selector", "").strip()
        url_selector = self.config.get("url_selector", "").strip()

        if job_card_selector:
            cards = soup.select(job_card_selector)
            if not cards:
                logger.warning(
                    "GenericHTMLAdapter[%s]: selector '%s' matched 0 elements at %s.",
                    self.company, job_card_selector, url,
                )
                return
        else:
            # Auto-detect job cards
            cards = self._auto_detect_cards(soup)
            if not cards:
                logger.warning(
                    "GenericHTMLAdapter[%s]: auto-detection found no job cards at %s. "
                    "Page may be JS-rendered (SPA). Returning empty.",
                    self.company, url,
                )
                return

        for card in cards:
            job = self._parse_card(
                card,
                base_url=url,
                title_selector=title_selector,
                location_selector=location_selector,
                url_selector=url_selector,
                detected_at=detected_at,
            )
            if job is not None:
                yield job

    def _auto_detect_cards(self, soup: BeautifulSoup) -> list[Tag]:
        """Try a series of heuristic selectors to find job card elements."""
        for pattern in _AUTO_CARD_PATTERNS:
            cards = soup.select(pattern)
            if cards:
                logger.debug(
                    "GenericHTMLAdapter[%s]: auto-detected cards with selector '%s' (%d found)",
                    self.company, pattern, len(cards),
                )
                return cards
        return []

    def _parse_card(
        self,
        card: Tag,
        base_url: str,
        title_selector: str,
        location_selector: str,
        url_selector: str,
        detected_at: datetime,
    ) -> Job | None:
        # Extract title
        title = ""
        if title_selector:
            el = card.select_one(title_selector)
            if el:
                title = el.get_text(strip=True)
        if not title:
            for pattern in _AUTO_TITLE_PATTERNS:
                el = card.select_one(pattern)
                if el:
                    title = el.get_text(strip=True)
                    break
        if not title:
            title = card.get_text(separator=" ", strip=True)[:100]
        if not title:
            return None

        # Extract location
        location = "Not specified"
        if location_selector:
            el = card.select_one(location_selector)
            if el:
                location = el.get_text(strip=True) or "Not specified"
        if location == "Not specified":
            for pattern in _AUTO_LOCATION_PATTERNS:
                el = card.select_one(pattern)
                if el:
                    text = el.get_text(strip=True)
                    if text and text != title:
                        location = text
                        break

        # Extract URL
        job_url = ""
        if url_selector:
            el = card.select_one(url_selector)
            if el:
                href = el.get("href", "")
                if href:
                    job_url = urljoin(base_url, str(href))
        if not job_url:
            a_tag = card.find("a")
            if a_tag:
                href = a_tag.get("href", "")
                if href:
                    job_url = urljoin(base_url, str(href))

        raw_text = " ".join(filter(None, [title, location])).lower()

        job_id = make_job_id(
            company=self.company,
            source_platform=self.source_platform,
            title=title,
            location=location,
        )

        return Job(
            id=job_id,
            company=self.company,
            title=title,
            location=location,
            department=None,
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
