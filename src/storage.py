from __future__ import annotations
import json
import os
import tempfile
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from src.models import Job

logger = logging.getLogger(__name__)

POLICY_VERSION = "2026-11-newgrad-v1"

# Common tracking / marketing parameters to strip for deduplication
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "source",
    "lever-source",
    "gh_src",
    "fbclid",
    "gclid",
    "trk",
    "ns_mchannel",
    "sub_id",
}


class StateCorruptionError(Exception):
    """Raised when state JSON is invalid or structurally corrupt."""
    pass


def normalize_url(url: str | None) -> str:
    """Normalize a job posting URL for cross-run and cross-source deduplication.

    Strips tracking query params, fragments, and trailing slashes, and lowercases scheme/host.
    """
    if not url:
        return ""
    url = url.strip()
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        query_items = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in TRACKING_PARAMS
        ]
        query_items.sort(key=lambda x: x[0])
        query = urlencode(query_items)
        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return url.rstrip("/").lower()


def is_url_alerted(url: str | None, state: dict) -> bool:
    """Check if normalized URL has already been alerted across any company or run."""
    norm = normalize_url(url)
    if not norm:
        return False
    return norm in state.get("alerted_urls", {})


def record_alerted_url(
    url: str | None, company: str, job_id: str, state: dict, now: datetime
) -> None:
    """Record normalized URL in state.alerted_urls to prevent future duplicates."""
    norm = normalize_url(url)
    if not norm:
        return
    alerted_urls = state.setdefault("alerted_urls", {})
    alerted_urls[norm] = {
        "alerted_at": now.isoformat(),
        "company": company,
        "job_id": job_id,
    }


def _empty_state() -> dict:
    return {
        "version": 2,
        "first_run_completed_at": None,
        "policy_version": None,
        "companies": {},
        "alerted_urls": {},
        "review_queue": {},
        "heartbeat_history": [],
        "last_heartbeat": None,
        "migrations": {},
    }


def migrate_state(state: dict, target_policy: str = POLICY_VERSION) -> tuple[dict, bool]:
    """Ensure state contains version 2 + policy_version fields idempotently.

    Returns (state, migrated).
    """
    migrated = False
    state.setdefault("version", 2)
    state.setdefault("first_run_completed_at", None)
    state.setdefault("companies", {})
    state.setdefault("alerted_urls", {})
    state.setdefault("review_queue", {})
    state.setdefault("heartbeat_history", [])
    state.setdefault("last_heartbeat", None)
    state.setdefault("migrations", {})

    if state.get("policy_version") != target_policy:
        migrations = state["migrations"]
        if target_policy not in migrations:
            migrations[target_policy] = {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
                "backfill_completed": False,
            }
        state["policy_version"] = target_policy
        migrated = True

    return state, migrated


def is_backfill_pending(state: dict, policy_version: str = POLICY_VERSION) -> bool:
    """Check if the first-run backfill under policy_version is still pending."""
    migrations = state.get("migrations", {})
    policy_meta = migrations.get(policy_version, {})
    return not bool(policy_meta.get("backfill_completed", False))


def mark_backfill_completed(
    state: dict, policy_version: str = POLICY_VERSION, now: datetime | None = None
) -> None:
    """Mark the backfill for policy_version as completed."""
    if now is None:
        now = datetime.now(timezone.utc)
    migrations = state.setdefault("migrations", {})
    policy_meta = migrations.setdefault(policy_version, {})
    policy_meta["backfill_completed"] = True
    policy_meta["completed_at"] = now.isoformat()


def get_backfill_candidates(
    matched_jobs: list[Job],
    state: dict,
    now: datetime,
    lookback_days: int = 7,
) -> list[Job]:
    """Find source-verified eligible jobs from the last lookback_days for bounded backfill summary.

    Uses job.posted_at if credible; falls back to detected_at (or first_seen in state).
    Filters out already alerted URLs and returns candidates.
    """
    cutoff = now - timedelta(days=lookback_days)
    candidates: list[Job] = []
    seen_urls_in_batch: set[str] = set()

    for job in matched_jobs:
        norm_url = normalize_url(job.url)
        if norm_url and norm_url in seen_urls_in_batch:
            continue
        if is_url_alerted(job.url, state):
            continue

        ref_dt = job.posted_at
        if ref_dt is None:
            company_seen = state.get("companies", {}).get(job.company, {}).get("seen_jobs", {})
            entry = company_seen.get(job.id)
            if entry and entry.get("first_seen"):
                try:
                    ref_dt = datetime.fromisoformat(entry["first_seen"])
                except Exception:
                    ref_dt = job.detected_at
            else:
                ref_dt = job.detected_at

        if ref_dt and ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)

        if ref_dt and ref_dt >= cutoff:
            if norm_url:
                seen_urls_in_batch.add(norm_url)
            candidates.append(job)

    return candidates


def record_review_job(
    state: dict,
    job: Job,
    reasons: list[str],
    now: datetime,
) -> None:
    """Record a position needing review in state.review_queue so it is not silently lost."""
    queue = state.setdefault("review_queue", {})
    entry = queue.get(job.id)
    if entry is None:
        queue[job.id] = {
            "company": job.company,
            "title": job.title,
            "url": job.url,
            "reasons": reasons,
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }
    else:
        entry["last_seen"] = now.isoformat()
        entry["reasons"] = reasons


def get_daily_review_digest(
    state: dict,
    now: datetime,
    cap: int = 10,
    digest_interval_hours: float = 24.0,
) -> tuple[list[dict], int] | None:
    """Return (items, total_count) for daily review digest if due, or None if throttled."""
    digest_meta = state.setdefault("review_digest", {"last_sent_at": None})
    last_sent = digest_meta.get("last_sent_at")
    if last_sent is not None:
        try:
            last_dt = datetime.fromisoformat(last_sent)
            if (now - last_dt) < timedelta(hours=digest_interval_hours):
                return None
        except Exception:
            pass

    queue = state.get("review_queue", {})
    if not queue:
        return None

    items = sorted(queue.values(), key=lambda x: x.get("last_seen", ""), reverse=True)
    return items[:cap], len(items)


def _migrate_v1_to_v2(state: dict) -> dict:
    """Convert v1 state (seen_ids lists) to v2 (seen_jobs dicts). Mutates and returns state."""
    migration_ts = datetime.now(timezone.utc).isoformat()
    for company_state in state.get("companies", {}).values():
        seen_ids = company_state.pop("seen_ids", [])
        company_state["seen_jobs"] = {
            jid: {
                "first_seen": migration_ts,
                "last_seen": migration_ts,
                "alerted": True,
            }
            for jid in seen_ids
        }
    state["version"] = 2
    return state


def load_state(path: str, raise_on_corrupt: bool = False) -> dict:
    """Load JSON state.

    If file is missing: returns empty v2 state.
    If file is corrupt:
        If raise_on_corrupt is True: raises StateCorruptionError.
        If raise_on_corrupt is False: logs error and returns empty v2 state.
    Automatically migrates v1 to v2, and initializes policy versioning structures.
    """
    if not os.path.exists(path):
        state = _empty_state()
        migrate_state(state)
        return state

    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load state from %s: %s.", path, e)
        if raise_on_corrupt:
            raise StateCorruptionError(f"Corrupt state file {path}: {e}") from e
        return _empty_state()

    if not isinstance(data, dict):
        msg = f"State file {path} did not contain a JSON object"
        logger.error(msg)
        if raise_on_corrupt:
            raise StateCorruptionError(msg)
        return _empty_state()

    data.setdefault("version", 1)
    data.setdefault("first_run_completed_at", None)
    data.setdefault("companies", {})

    if not isinstance(data.get("companies"), dict):
        msg = f"State file {path} has invalid 'companies' field (expected dict)"
        logger.error(msg)
        if raise_on_corrupt:
            raise StateCorruptionError(msg)
        return _empty_state()

    if data["version"] == 1:
        logger.info("Migrating state from v1 to v2...")
        data = _migrate_v1_to_v2(data)
        try:
            save_state(data, path)
            logger.info("State migration complete.")
        except Exception as save_err:
            logger.warning("Migration succeeded but failed to persist: %s — will re-migrate next run.", save_err)

    migrate_state(data)
    return data


def save_state(state: dict, path: str) -> None:
    """Atomic write via tempfile + os.replace."""
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def classify_jobs(
    jobs: list[Job],
    company: str,
    state: dict,
    freshness_hours: float,
    now: datetime,
    verbose: bool = False,
) -> list[Job]:
    """Classify jobs for alerting. Updates seen_jobs entries in state (in-memory).

    Returns only jobs that should proceed to Discord alerting.
    """
    if now.tzinfo is None:
        raise ValueError("classify_jobs: 'now' must be tz-aware")

    company_state = state["companies"].setdefault(
        company, {"last_checked_at": None, "seen_jobs": {}}
    )
    seen_jobs = company_state.setdefault("seen_jobs", {})

    candidates = []
    for job in jobs:
        entry = seen_jobs.get(job.id)

        if entry is None:
            seen_jobs[job.id] = {
                "first_seen": now.isoformat(),
                "last_seen": now.isoformat(),
                "alerted": False,
            }
            candidates.append(job)
        else:
            entry["last_seen"] = now.isoformat()

            if entry.get("alerted"):
                if verbose:
                    logger.debug("%s job %s suppressed: already alerted", company, job.id)
            else:
                first_seen_dt = datetime.fromisoformat(entry["first_seen"])
                age_hours = (now - first_seen_dt).total_seconds() / 3600
                if age_hours > freshness_hours:
                    entry["stale_suppressed"] = True
                    if verbose:
                        logger.debug(
                            "%s job %s suppressed: stale_suppressed "
                            "(first_seen %.0fh ago, limit %.0fh)",
                            company, job.id, age_hours, freshness_hours,
                        )
                else:
                    candidates.append(job)

    return candidates


def mark_alerted(jobs: list[Job], company: str, state: dict) -> None:
    """Set alerted=True for jobs successfully sent to Discord."""
    seen_jobs = state["companies"].get(company, {}).get("seen_jobs", {})
    for job in jobs:
        if job.id in seen_jobs:
            seen_jobs[job.id]["alerted"] = True
            seen_jobs[job.id].pop("cap_suppressed", None)


def mark_cap_suppressed(jobs: list[Job], company: str, state: dict) -> None:
    """Mark jobs silenced by max_alerts_per_run cap. They will retry next run."""
    seen_jobs = state["companies"].get(company, {}).get("seen_jobs", {})
    for job in jobs:
        if job.id in seen_jobs:
            seen_jobs[job.id]["cap_suppressed"] = True


def update_last_checked(company: str, state: dict, now: datetime) -> None:
    """Update last_checked_at for company. Creates the company entry if missing. now must be tz-aware."""
    if now.tzinfo is None:
        raise ValueError("update_last_checked: 'now' must be tz-aware")
    company_state = state["companies"].setdefault(
        company, {"last_checked_at": None, "seen_jobs": {}}
    )
    company_state.setdefault("seen_jobs", {})
    company_state["last_checked_at"] = now.isoformat()


def prune_seen_jobs(state: dict, ttl_days: int, now: datetime) -> None:
    """Evict seen_jobs, alerted_urls, and review_queue entries where timestamp is older than ttl_days. now must be tz-aware."""
    if now.tzinfo is None:
        raise ValueError("prune_seen_jobs: 'now' must be tz-aware")
    cutoff = now - timedelta(days=ttl_days)

    # Prune companies seen_jobs
    for company_state in state.get("companies", {}).values():
        seen_jobs = company_state.get("seen_jobs", {})
        to_remove = [
            jid for jid, entry in seen_jobs.items()
            if entry.get("last_seen") and datetime.fromisoformat(entry["last_seen"]) < cutoff
        ]
        for jid in to_remove:
            del seen_jobs[jid]

    # Prune alerted_urls
    alerted_urls = state.get("alerted_urls", {})
    url_removals = [
        url for url, entry in alerted_urls.items()
        if entry.get("alerted_at") and datetime.fromisoformat(entry["alerted_at"]) < cutoff
    ]
    for url in url_removals:
        del alerted_urls[url]

    # Prune review_queue
    review_queue = state.get("review_queue", {})
    review_removals = [
        jid for jid, entry in review_queue.items()
        if entry.get("last_seen") and datetime.fromisoformat(entry["last_seen"]) < cutoff
    ]
    for jid in review_removals:
        del review_queue[jid]


def is_first_run(state: dict) -> bool:
    """Return True if first_run_completed_at is None or missing."""
    return state.get("first_run_completed_at") is None


def mark_first_run_complete(state: dict) -> None:
    """Set first_run_completed_at to current ISO8601 timestamp."""
    state["first_run_completed_at"] = datetime.now(timezone.utc).isoformat()
