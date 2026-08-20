"""Microsoft Research careers adapter — WordPress REST API.

Endpoint:
    GET https://www.microsoft.com/en-us/research/wp-json/microsoft-research/v2/careers

Public, unauthenticated, and self-describing: GET the namespace root
(`/wp-json/microsoft-research/v2/`) and it returns the arg schema for every route,
including this one. Verified live 2026-08-19: 99 postings, one page at per_page=100.

History (why this file was rewritten):
    Until 2026-08-19 this adapter chased two endpoints that do not work — the
    Eightfold API at apply.careers.microsoft.com (HTTP 403, "Not authorized for
    PCSX") and jobs.careers.microsoft.com (a JS-rendered SPA with no static job
    data). It therefore returned [] on every run for months, silently, which is
    what motivated the per-company health tracking in src/health.py.

    The working endpoint was one level below the `base_url` already sitting in this
    company's own config: that careers page is WordPress-backed, and its REST API
    was public the whole time.

Query shape, and why it is deliberately broad:
    No server-side `type=internship` or `region=north-america` filter, even though
    the API supports both. A narrow query makes an empty response ambiguous — it
    could mean "nothing matched today" or "the adapter is broken" — and the
    adapter-health design (docs/superpowers/specs/2026-08-19-adapter-health-reporting-design.md)
    depends on `fetched == 0` meaning the site gave us nothing. The bot's own
    filter pipeline does the selecting.

    `fields` trims the response from ~970KB to ~164KB. `researchAreas` is worth its
    share of that: the area names ("Artificial intelligence", "Computer vision")
    are the strongest technical signal the list response carries, and a terse title
    can fail the tech-role filter without them.

Note on the WAF: microsoft.com 403s a bare "Mozilla/5.0" user agent, consistently.
This bot's real UA (job-alert-bot/0.1) and no UA at all both return 200. If that
ever changes the adapter degrades to [] and health tracking reports it.

Config keys:
    base_url: informational only — the human-facing careers page. The API URL is
              a module constant below.
"""

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

_API_URL = (
    "https://www.microsoft.com/en-us/research/wp-json/microsoft-research/v2/careers"
)
_FIELDS = (
    "id,name,url,datePublished,cities,regions,opportunityTypes,researchAreas,excerpt"
)
_PER_PAGE = 100  # the route's documented maximum
_DESCRIPTION_MAX = 500
_INTERNSHIP_SLUG = "internship"

# The response tells us how many pages there are, but a server that reports that
# wrong must not park the run. 10 pages is 1000 postings against a real total of 99.
_MAX_PAGES = 10


def _strip_html(html: str) -> str:
    """Strip tags and decode entities. Excerpts end in a literal '[&hellip;]'."""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp. datePublished carries an offset, not a Z.

    Always returns an aware datetime. A naive one would reach filter_freshness,
    which subtracts it from an aware now() — TypeError — and main.py runs the
    filter pipeline outside any try/except, so a single naive timestamp would
    abort the run for every remaining company and state would never be saved.
    smartrecruiters.py guards the same way.
    """
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _names(terms: object) -> list[str]:
    """Collect the `name` of each taxonomy term, tolerating a missing list."""
    if not isinstance(terms, list):
        return []
    return [str(t["name"]).strip() for t in terms if isinstance(t, dict) and t.get("name")]


class MicrosoftResearchAdapter(BaseAdapter):
    """Adapter for Microsoft Research job listings via the MSR WordPress REST API."""

    source_platform = "microsoft_research"

    def fetch(self) -> Iterator[Job]:
        detected_at = datetime.now(tz=timezone.utc)
        page = 1
        total_pages = 1
        # One posting must become one Discord alert. Nothing downstream
        # deduplicates within a single run, so if the API ever ignores or clamps
        # `page`, repeated postings would become repeated embeds for one job.
        seen_ids: set[str] = set()

        while page <= min(total_pages, _MAX_PAGES):
            params = {
                "page": page,
                "per_page": _PER_PAGE,
                "fields": _FIELDS,
                "links": "minimal",
            }
            try:
                resp = self.http.get(_API_URL, params=params)
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                # Page 1 failing means no jobs at all; a later page failing keeps
                # whatever the earlier pages already yielded.
                logger.error(
                    "MicrosoftResearchAdapter: careers API page %d failed: %s", page, exc
                )
                return

            if not isinstance(payload, dict):
                logger.error(
                    "MicrosoftResearchAdapter: expected a JSON object, got %s",
                    type(payload).__name__,
                )
                return

            items = payload.get("items")
            if not isinstance(items, list) or not items:
                if page == 1:
                    logger.warning(
                        "MicrosoftResearchAdapter: careers API returned no items."
                    )
                else:
                    # Same argument as the page-cap warning: a short result that
                    # looks complete is worse than a loud partial one.
                    logger.warning(
                        "MicrosoftResearchAdapter: page %d of %d came back empty; "
                        "stopping with a partial read.",
                        page, total_pages,
                    )
                return

            for item in items:
                try:
                    job = self._parse(item, detected_at)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "MicrosoftResearchAdapter: skipping posting %s: %s",
                        (item or {}).get("id") if isinstance(item, dict) else "?",
                        exc,
                    )
                    continue
                if job is None or job.id in seen_ids:
                    continue
                seen_ids.add(job.id)
                yield job

            # Any shape but a dict means "assume one page". `.get` on a string
            # or list raises AttributeError, which is neither RequestException
            # nor ValueError, so it would escape this generator — and escape
            # AFTER page 1 had yielded, making main.py's list(fetch()) discard
            # postings it already had and record the company as fetched=0. A
            # healthy adapter would then look silent to the health tracking.
            pagination = payload.get("_pagination")
            if not isinstance(pagination, dict):
                pagination = {}
            try:
                total_pages = int(pagination.get("totalPages", 1))
            except (TypeError, ValueError):
                total_pages = 1

            page += 1
            if page > _MAX_PAGES and total_pages > _MAX_PAGES:
                # Never truncate quietly: a short result that looks complete is
                # worse than a loud partial one.
                logger.warning(
                    "MicrosoftResearchAdapter: stopped at the %d page cap; the API "
                    "reports %d pages, so some postings were not read.",
                    _MAX_PAGES, total_pages,
                )
            elif page <= min(total_pages, _MAX_PAGES):
                self.http.polite_delay(1.0, 2.0)

    def _parse(self, item: dict, detected_at: datetime) -> Job | None:
        title = str(item.get("name") or "").strip()
        if not title:
            return None

        official_id = str(item.get("id") or "").strip()

        # notifier.py puts job.url straight into a Discord embed field value,
        # and Discord rejects an empty value with HTTP 400. The send fails,
        # mark_alerted never runs, and the posting retries every run until it
        # ages out of the freshness window — ~192 failed sends. A posting with
        # no link cannot be applied to anyway.
        job_url = str(item.get("url") or "").strip()
        if not job_url:
            logger.warning(
                "MicrosoftResearchAdapter: skipping %r — no application URL.", title
            )
            return None
        posted_at = _parse_iso(item.get("datePublished"))

        # Every city, not just the first, so the alert is honest about where the
        # job actually is.
        #
        # KNOWN LIMITATION, and the opposite of what an earlier version of this
        # comment claimed: filter_location scans location + raw_text for
        # NON_US_SIGNALS and rejects on ANY hit, so a multi-city posting is
        # dropped by its worst city, not saved by its best. Verified:
        # 'Redmond, WA, US; Beijing, China' drops on "beijing". Costs nothing on
        # the current corpus — of the 44 postings filtered on location, none has
        # a US-eligible city that survives the other filters — but the first
        # genuinely dual-sited US/non-US internship MSR posts will be filtered
        # out. Left as-is deliberately: dropping it is the conservative error,
        # and trimming the non-US cities to sneak it through would make the
        # alert lie about the location.
        cities = _names(item.get("cities"))
        location = "; ".join(cities)

        research_areas = _names(item.get("researchAreas"))
        department = ", ".join(research_areas) or None

        opportunity_types = _names(item.get("opportunityTypes"))
        category = opportunity_types[0] if opportunity_types else None

        # The source states the role type outright, so don't make the filters
        # re-derive it from the title.
        slugs = {
            str(t.get("slug", "")).lower()
            for t in (item.get("opportunityTypes") or [])
            if isinstance(t, dict)
        }
        role_type = "internship" if _INTERNSHIP_SLUG in slugs else "unknown"

        excerpt = _strip_html(str(item.get("excerpt") or ""))[:_DESCRIPTION_MAX]
        regions = _names(item.get("regions"))
        raw_text = " ".join(
            filter(
                None,
                [
                    title,
                    location,
                    " ".join(regions),
                    " ".join(research_areas),
                    " ".join(opportunity_types),
                    excerpt,
                ],
            )
        ).lower()

        job_id = make_job_id(
            company=self.company,
            source_platform=self.source_platform,
            title=title,
            location=location,
            official_id=official_id or None,
        )

        return Job(
            id=job_id,
            company=self.company,
            title=title,
            location=location,
            department=department,
            category=category,
            url=job_url,
            source_platform=self.source_platform,
            posted_at=posted_at,
            detected_at=detected_at,
            raw_text=raw_text,
            role_type=role_type,
            priority="normal",
            matched_keywords=(),
        )
