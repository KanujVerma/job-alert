from __future__ import annotations
import json
import os
import tempfile
import logging
from datetime import datetime, timedelta, timezone

from src.models import Job

logger = logging.getLogger(__name__)


def _empty_state() -> dict:
    return {"version": 2, "first_run_completed_at": None, "companies": {}}


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


def load_state(path: str) -> dict:
    """Load JSON state; return empty v2 state if file missing or corrupt.

    Automatically migrates v1 state (seen_ids lists) to v2 (seen_jobs dicts)
    on first load and persists the result atomically.
    """
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, "r") as f:
            data = json.load(f)
        data.setdefault("version", 1)
        data.setdefault("first_run_completed_at", None)
        data.setdefault("companies", {})

        if data["version"] == 1:
            logger.info("Migrating state from v1 to v2...")
            data = _migrate_v1_to_v2(data)
            try:
                save_state(data, path)
                logger.info("State migration complete.")
            except Exception as save_err:
                logger.warning("Migration succeeded but failed to persist: %s — will re-migrate next run.", save_err)

        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load state from %s: %s. Starting fresh.", path, e)
        return _empty_state()


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
    """Evict seen_jobs entries where last_seen is older than ttl_days. now must be tz-aware."""
    if now.tzinfo is None:
        raise ValueError("prune_seen_jobs: 'now' must be tz-aware")
    cutoff = now - timedelta(days=ttl_days)
    for company_state in state.get("companies", {}).values():
        seen_jobs = company_state.get("seen_jobs", {})
        to_remove = [
            jid for jid, entry in seen_jobs.items()
            if entry.get("last_seen") and datetime.fromisoformat(entry["last_seen"]) < cutoff
        ]
        for jid in to_remove:
            del seen_jobs[jid]


def is_first_run(state: dict) -> bool:
    """Return True if first_run_completed_at is None or missing."""
    return state.get("first_run_completed_at") is None


def mark_first_run_complete(state: dict) -> None:
    """Set first_run_completed_at to current ISO8601 timestamp."""
    state["first_run_completed_at"] = datetime.now(timezone.utc).isoformat()
