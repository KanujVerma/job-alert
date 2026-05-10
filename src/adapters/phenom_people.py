# src/adapters/phenom_people.py
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urlparse

from src.adapters.base import BaseAdapter
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)

_JOBS_KEY = "jobs"
_TOTAL_KEY = "totalHits"
_ID_KEY = "jobSeqNo"
_TITLE_KEY = "title"
_LOCATION_KEY = "location"
_DEPT_KEY = "category"
_URL_KEY = "detailUrl"
_POSTED_KEY = "postedDate"

_PAGE_PATH: list[str] = ["from"]
_PAGE_SIZE = 10


def _is_auth_failure(payload: dict) -> bool:
    search = payload.get("searchJobs")
    if isinstance(search, dict):
        if search.get("status") == "failure":
            return True
        if bool(search.get("errorMsg")):
            return True
    return payload.get("status") == "failure" or bool(payload.get("errorMsg"))


def _set_nested(d: dict, path: list[str], value: object) -> dict:
    """Return a shallow-copy of d with path set to value (no mutation)."""
    if not path:
        return d
    result = dict(d)
    if len(path) == 1:
        result[path[0]] = value
    else:
        result[path[0]] = _set_nested(dict(d.get(path[0]) or {}), path[1:], value)
    return result


def _extract_location(record: dict) -> str:
    loc = record.get(_LOCATION_KEY)
    if isinstance(loc, str):
        return loc.strip() or "Not specified"
    if isinstance(loc, dict):
        city = loc.get("city") or loc.get("name") or ""
        state = loc.get("state") or loc.get("stateCode") or ""
        parts = [p for p in (city, state) if p]
        return ", ".join(parts) or "Not specified"
    return "Not specified"


def _parse_posted_at(record: dict) -> datetime | None:
    raw = record.get(_POSTED_KEY)
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def _extract_jobs_list(payload: dict) -> list:
    # Real Phenom structure: payload["searchJobs"]["data"]["jobs"]
    search = payload.get("searchJobs")
    if isinstance(search, dict):
        data = search.get("data")
        if isinstance(data, dict):
            val = data.get(_JOBS_KEY)
            if isinstance(val, list):
                return val
    # Fallback for flat or alternative structures
    val = payload.get(_JOBS_KEY)
    if isinstance(val, list):
        return val
    data = payload.get("data")
    if isinstance(data, dict):
        for key in (_JOBS_KEY, "positions", "jobs"):
            sub = data.get(key)
            if isinstance(sub, list):
                return sub
    return []


def _extract_total(payload: dict) -> int | None:
    # Real Phenom structure: payload["searchJobs"]["data"]["totalHits"]
    search = payload.get("searchJobs")
    if isinstance(search, dict):
        data = search.get("data")
        if isinstance(data, dict):
            for key in (_TOTAL_KEY, "total", "count", "totalCount"):
                val = data.get(key)
                if isinstance(val, int):
                    return val
    # Fallback
    val = payload.get(_TOTAL_KEY)
    if isinstance(val, int):
        return val
    data = payload.get("data")
    if isinstance(data, dict):
        for key in (_TOTAL_KEY, "total", "count", "totalCount"):
            sub = data.get(key)
            if isinstance(sub, int):
                return sub
    return None


def _parse_phenom_job(
    record: dict,
    company: str,
    source_platform: str,
    detected_at: datetime,
) -> Job | None:
    """Parse one Phenom People job record into a Job. Returns None if title missing."""
    official_id = str(record.get(_ID_KEY) or "").strip()
    title = (record.get(_TITLE_KEY) or "").strip()
    if not title:
        return None

    location = _extract_location(record)
    department = (record.get(_DEPT_KEY) or "").strip() or None
    url = (record.get(_URL_KEY) or "").strip()
    posted_at = _parse_posted_at(record)
    raw_text = " ".join(filter(None, [title, location, department])).lower()

    job_id = make_job_id(
        company=company,
        source_platform=source_platform,
        title=title,
        location=location,
        official_id=official_id if official_id else None,
    )

    return Job(
        id=job_id,
        company=company,
        title=title,
        location=location,
        department=department,
        category=None,
        url=url,
        source_platform=source_platform,
        posted_at=posted_at,
        detected_at=detected_at,
        raw_text=raw_text,
        role_type="unknown",
        priority="normal",
        matched_keywords=(),
    )


class PhenomPeopleAdapter(BaseAdapter):
    source_platform = "phenom_people"

    def fetch(self) -> Iterator[Job]:
        if self.browser is None or not self.browser.available:
            logger.warning(
                "PhenomPeopleAdapter[%s]: no BrowserClient available — skipping",
                self.company,
            )
            return

        tenant = self.config["tenant"]
        base_url = self.config["base_url"].rstrip("/")
        search_url = self.config.get("search_url", base_url)
        timeout_seconds = int(self.config.get("browser_timeout_seconds", 30))
        wait_for_url = self.config.get(
            "wait_for_response_url",
            f"**/api/{tenant}/searchJobs**",
        )

        try:
            session = self.browser.bootstrap_session(
                search_url,
                company=self.company,
                wait_for_response_url=wait_for_url,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            logger.warning(
                "PhenomPeopleAdapter[%s]: browser bootstrap failed: %s",
                self.company, exc,
            )
            self.browser.capture_debug_artifacts(self.company, exc)
            return

        # Prefer captured URL (strip query string)
        if session.captured_request_url:
            parsed = urlparse(session.captured_request_url)
            api_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        else:
            api_base = self.config.get(
                "api_base_url", "https://content-us.phenompeople.com"
            ).rstrip("/")
            api_path = self.config.get(
                "api_path", "/api/{tenant}/searchJobs"
            ).format(tenant=tenant)
            api_url = f"{api_base}{api_path}"

        logger.info(
            "PhenomPeopleAdapter[%s]: boot complete — api_url=%s method=%s has_response=%s",
            self.company,
            api_url,
            session.captured_request_method,
            session.captured_first_response is not None,
        )

        detected_at = datetime.now(tz=timezone.utc)
        request_method = session.captured_request_method
        body_template: dict | None = None
        if session.captured_request_body:
            try:
                body_template = json.loads(session.captured_request_body)
            except (ValueError, TypeError):
                pass

        offset = 0
        total: int | None = None
        use_intercept = bool(session.captured_first_response)

        while True:
            if use_intercept:
                use_intercept = False
                try:
                    payload = json.loads(session.captured_first_response)  # type: ignore[arg-type]
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "PhenomPeopleAdapter[%s]: bad captured response, falling to evaluate_fetch: %s",
                        self.company, exc,
                    )
                    continue
                if _is_auth_failure(payload):
                    logger.warning(
                        "PhenomPeopleAdapter[%s]: captured response is auth failure, falling to evaluate_fetch",
                        self.company,
                    )
                    continue
            else:
                if request_method == "POST" and body_template is not None:
                    body: dict | None = _set_nested(body_template, _PAGE_PATH, offset)
                    params: dict = {}
                else:
                    body = None
                    params = {_PAGE_PATH[-1]: offset, "size": _PAGE_SIZE}

                try:
                    payload = self.browser.evaluate_fetch(
                        api_url,
                        params,
                        method=request_method,
                        body=body,
                    )
                except Exception as exc:
                    logger.error(
                        "PhenomPeopleAdapter[%s]: evaluate_fetch failed at offset=%d: %s",
                        self.company, offset, exc,
                    )
                    self.browser.capture_debug_artifacts(self.company, exc)
                    return

                if _is_auth_failure(payload):
                    logger.error(
                        "PhenomPeopleAdapter[%s]: evaluate_fetch auth failure at offset=%d",
                        self.company, offset,
                    )
                    self.browser.capture_debug_artifacts(
                        self.company,
                        RuntimeError(f"evaluate_fetch auth failure: {payload}"),
                    )
                    return

            jobs_list = _extract_jobs_list(payload)
            count = _extract_total(payload)
            if total is None and count is not None:
                total = count

            if not jobs_list:
                break

            for record in jobs_list:
                try:
                    job = _parse_phenom_job(
                        record, self.company, self.source_platform, detected_at
                    )
                    if job is not None:
                        yield job
                except Exception as exc:
                    logger.warning(
                        "PhenomPeopleAdapter[%s]: skipping record %s: %s",
                        self.company, record.get(_ID_KEY, "?"), exc,
                    )

            offset += len(jobs_list)
            if total is not None and offset >= total:
                break
