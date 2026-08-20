"""Eightfold "PCSX" search-API adapter — whole-company job search.

Endpoint (verified live 2026-08-20 against Microsoft):
    GET https://apply.careers.microsoft.com/api/pcsx/search
        ?domain=microsoft.com&query=&location=United%20States&start=0&sort_by=timestamp

Plain HTTP, no auth, no cookies, any User-Agent. `robots.txt` on that host is
`Disallow: /` with an explicit `Allow: /api/pcsx`, so this path is permitted.

Not to be confused with src/adapters/eightfold.py, which speaks the older
/api/apply/v2/jobs route and needs a tenant the SPA resolves from a session
cookie. This is a different, currently-working route on the same platform.

Config keys:
    base_url:         https://apply.careers.microsoft.com  (also the prefix for the
                      relative positionUrl each posting carries)
    api_path:         /api/pcsx/search                     (optional)
    domain:           microsoft.com                        (optional; derived from base_url)
    location:         United States                        (optional; server-side filter)
    stop_after_hours: 48                                   (optional; see below)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

_DEFAULT_API_PATH = "/api/pcsx/search"
_DEFAULT_LOCATION = "United States"
_DEFAULT_STOP_AFTER_HOURS = 48.0

# The API hard-fixes its page size at 10. `num`, `limit` and `page_size` are all
# accepted and all ignored — verified 2026-08-20. Paging is by `start` only.
PAGE_SIZE = 10

# Runaway guard. 30 pages is 300 postings; at the observed posting rate (~10 US
# postings every 3 hours) the 48h window is roughly 17 pages, so this is headroom
# rather than a routine limit. Hitting it is logged, never silent.
MAX_PAGES = 30


def _epoch_to_utc(value: object) -> datetime | None:
    """Unix epoch SECONDS to an aware UTC datetime.

    Always aware, never naive. A naive datetime reaches filter_freshness, which
    subtracts it from an aware now() — TypeError — and main.py runs the filter
    pipeline outside any try/except, so a single naive timestamp aborts the run
    for every remaining company and state is never saved. microsoft_research.py
    and smartrecruiters.py guard the same way.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _as_int(value: object) -> int | None:
    """Best-effort int, for a `count` the server could in principle send as junk."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class EightfoldPCSXAdapter(BaseAdapter):
    """Adapter for the Eightfold PCSX search API (e.g. the whole of Microsoft)."""

    source_platform = "eightfold_pcsx"

    def fetch(self) -> Iterator[Job]:
        base_url = str(self.config.get("base_url") or "").rstrip("/")
        api_path = self.config.get("api_path") or _DEFAULT_API_PATH
        domain = self.config.get("domain") or base_url.split("//", 1)[-1].split("/")[0]
        location = self.config.get("location", _DEFAULT_LOCATION)

        url = f"{base_url}{api_path}"
        detected_at = datetime.now(tz=timezone.utc)
        cutoff = detected_at - timedelta(hours=self._stop_after_hours())

        # One posting must become one Discord alert, and nothing downstream
        # deduplicates within a run. If the API ever ignores or clamps `start`,
        # repeated postings would otherwise become repeated embeds for one job.
        seen_ids: set[str] = set()

        start = 0
        pages_read = 0

        while True:
            params: dict = {
                "domain": domain,
                "query": "",
                "start": start,
                "sort_by": "timestamp",
            }
            if location:
                params["location"] = location

            try:
                resp = self.http.get(url, params=params)
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                # start=0 failing means no jobs at all; a later page failing keeps
                # whatever the earlier pages already yielded.
                logger.error(
                    "EightfoldPCSXAdapter[%s]: search failed at start=%d: %s",
                    self.company, start, exc,
                )
                return

            if not isinstance(payload, dict):
                logger.error(
                    "EightfoldPCSXAdapter[%s]: expected a JSON object, got %s",
                    self.company, type(payload).__name__,
                )
                return

            # NOTE payload["status"] is the INTEGER 200 on success, not a string
            # and not a failure flag. It is deliberately not inspected: HTTP
            # status is already handled by src/http.py, and treating a truthy
            # int as an error here is exactly the mistake that made the older
            # eightfold.py adapter bail on healthy responses.
            data = payload.get("data")
            if not isinstance(data, dict):
                logger.error(
                    "EightfoldPCSXAdapter[%s]: response carried no `data` object "
                    "(got %s) at start=%d.",
                    self.company, type(data).__name__, start,
                )
                return

            positions = data.get("positions")
            if not isinstance(positions, list) or not positions:
                if pages_read == 0:
                    logger.warning(
                        "EightfoldPCSXAdapter[%s]: search returned no positions.",
                        self.company,
                    )
                else:
                    # Same argument as the page-cap warning: a short result that
                    # looks complete is worse than a loud partial one.
                    logger.warning(
                        "EightfoldPCSXAdapter[%s]: page at start=%d came back "
                        "empty; stopping with a partial read.",
                        self.company, start,
                    )
                return

            page_oldest: datetime | None = None

            for pos in positions:
                try:
                    posted_at = (
                        _epoch_to_utc(pos.get("postedTs"))
                        if isinstance(pos, dict)
                        else None
                    )
                    if posted_at is not None and (
                        page_oldest is None or posted_at < page_oldest
                    ):
                        page_oldest = posted_at
                    job = self._parse(pos, detected_at) if isinstance(pos, dict) else None
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "EightfoldPCSXAdapter[%s]: skipping position %s: %s",
                        self.company,
                        pos.get("id") if isinstance(pos, dict) else "?",
                        exc,
                    )
                    continue
                if job is None:
                    continue
                if job.id in seen_ids:
                    # Expected, not a fault: the corpus is sorted by timestamp
                    # and shifts while we walk it, so a posting can land on two
                    # consecutive pages. Logged so that a fetched count short of
                    # pages*10 can be explained after the fact.
                    logger.debug(
                        "EightfoldPCSXAdapter[%s]: duplicate posting %s (%r) "
                        "already yielded this run.",
                        self.company, job.id, job.title,
                    )
                    continue
                seen_ids.add(job.id)
                yield job

            pages_read += 1
            start += PAGE_SIZE

            # ---- when to ask for another page -----------------------------
            #
            # Results are sorted newest-first (sort_by=timestamp), so paging can
            # stop as soon as a page falls out of the freshness window: the 48h
            # window is a handful of pages against 114 requests for the full
            # 1140-posting corpus, on an API that 429s after ~5 rapid requests.
            #
            # BUT the stop is deliberately evaluated only AFTER a whole page has
            # been read and yielded, and page 0 is therefore always yielded in
            # full no matter how old its postings are. That is not an oversight
            # and must not be "optimised" into skipping stale postings:
            #
            #   main.py feeds the PRE-FILTER fetched count into src/health.py,
            #   which reports a company as broken when it fetches zero. If this
            #   adapter early-stopped on date before yielding anything, a
            #   genuinely quiet day would produce fetched=0 and the health
            #   monitor would cry wolf on a perfectly healthy adapter.
            #
            # Yielding page 0 whole guarantees fetched >= 1 whenever the API is
            # healthy, so zero still means broken. The stale postings cost
            # nothing: filter_freshness drops them a moment later.
            if len(positions) < PAGE_SIZE:
                # Short page — the server has nothing more, whatever `count` says.
                break

            count = _as_int(data.get("count"))
            if count is not None and start >= count:
                break

            if page_oldest is None:
                # No usable timestamp anywhere on the page, so the window cannot
                # be evaluated. Stop rather than page the whole corpus — but say
                # so, because this is a partial read.
                logger.warning(
                    "EightfoldPCSXAdapter[%s]: no usable postedTs on the page at "
                    "start=%d; stopping with a partial read.",
                    self.company, start - PAGE_SIZE,
                )
                break

            if page_oldest < cutoff:
                logger.debug(
                    "EightfoldPCSXAdapter[%s]: page at start=%d is older than the "
                    "window; stopping after %d page(s).",
                    self.company, start - PAGE_SIZE, pages_read,
                )
                break

            if pages_read >= MAX_PAGES:
                # Never truncate quietly: a short result that looks complete is
                # worse than a loud partial one.
                logger.warning(
                    "EightfoldPCSXAdapter[%s]: stopped at the %d page cap with "
                    "postings still inside the window; some were not read.",
                    self.company, MAX_PAGES,
                )
                break

            self.http.polite_delay(3.0, 5.0)

    def _stop_after_hours(self) -> float:
        """The freshness window that governs the early stop.

        Should track `filters.freshness_hours` in companies.yaml; the adapter
        cannot see that section, so it is configured per company instead.
        """
        raw = self.config.get("stop_after_hours", _DEFAULT_STOP_AFTER_HOURS)
        try:
            return float(raw)
        except (TypeError, ValueError):
            logger.warning(
                "EightfoldPCSXAdapter[%s]: stop_after_hours=%r is not a number; "
                "falling back to %.0fh.",
                self.company, raw, _DEFAULT_STOP_AFTER_HOURS,
            )
            return _DEFAULT_STOP_AFTER_HOURS

    def _parse(self, pos: dict, detected_at: datetime) -> Job | None:
        title = str(pos.get("name") or "").strip()
        if not title:
            # Never a silent drop: the fetched count is the health signal, so a
            # posting that vanishes between the page and the count has to be
            # explainable from the log.
            logger.warning(
                "EightfoldPCSXAdapter[%s]: skipping position %s — no title.",
                self.company, pos.get("id"),
            )
            return None

        official_id = str(pos.get("id") or pos.get("displayJobId") or "").strip()

        # `positionUrl` is RELATIVE ("/careers/job/1970393556962891"); a bare path
        # is not a link anyone can open. urljoin also leaves an already-absolute
        # URL alone, should the API ever start sending one.
        #
        # An unusable link is a skip, not a yield: notifier.py puts job.url
        # straight into a Discord embed field value, Discord rejects an empty
        # value with HTTP 400, the send fails, mark_alerted never runs, and the
        # posting retries every run until it ages out of the freshness window.
        # A posting with no link cannot be applied to anyway.
        base_url = str(self.config.get("base_url") or "").rstrip("/")
        position_url = str(pos.get("positionUrl") or "").strip()
        job_url = urljoin(f"{base_url}/", position_url) if position_url else ""
        if not job_url.startswith(("http://", "https://")):
            logger.warning(
                "EightfoldPCSXAdapter[%s]: skipping %r — no usable application "
                "URL (positionUrl=%r, base_url=%r).",
                self.company, title, position_url, base_url,
            )
            return None

        locations = pos.get("locations")
        if not isinstance(locations, list):
            locations = []
        location = "; ".join(
            str(loc).strip() for loc in locations if str(loc or "").strip()
        )

        department = str(pos.get("department") or "").strip() or None
        posted_at = _epoch_to_utc(pos.get("postedTs"))

        # No description in the search response, and a per-job detail request is
        # deliberately not made: 1140 extra requests against an API that 429s
        # after ~5 rapid ones is not a trade worth making for a blurb.
        raw_text = " ".join(filter(None, [title, location, department or ""])).lower()

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
