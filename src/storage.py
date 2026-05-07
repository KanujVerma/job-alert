from __future__ import annotations
import json
import os
import tempfile
import logging
from datetime import datetime, timezone

from src.models import Job

logger = logging.getLogger(__name__)

_EMPTY_STATE = {"version": 1, "first_run_completed_at": None, "companies": {}}
_MAX_SEEN_IDS = 5000


def _empty_state() -> dict:
    return {"version": 1, "first_run_completed_at": None, "companies": {}}


def load_state(path: str) -> dict:
    """Load JSON state; return empty state dict if file doesn't exist."""
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, "r") as f:
            data = json.load(f)
        # Ensure schema keys exist
        data.setdefault("version", 1)
        data.setdefault("first_run_completed_at", None)
        data.setdefault("companies", {})
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load state from {path}: {e}. Starting fresh.")
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


def get_new_jobs(jobs: list[Job], company: str, state: dict) -> list[Job]:
    """Return jobs whose id is NOT in state["companies"][company]["seen_ids"]."""
    company_state = state["companies"].get(company, {})
    seen_ids = set(company_state.get("seen_ids", []))
    return [job for job in jobs if job.id not in seen_ids]


def mark_seen(jobs: list[Job], company: str, state: dict) -> None:
    """Add job IDs to state, update last_checked_at, prune seen_ids to 5000."""
    if company not in state["companies"]:
        state["companies"][company] = {"last_checked_at": None, "seen_ids": []}

    company_state = state["companies"][company]
    existing_ids = company_state.get("seen_ids", [])
    new_ids = [job.id for job in jobs]

    # Merge and deduplicate preserving order (existing first, then new)
    seen_set = set(existing_ids)
    for jid in new_ids:
        if jid not in seen_set:
            existing_ids.append(jid)
            seen_set.add(jid)

    # Prune to last MAX_SEEN_IDS
    if len(existing_ids) > _MAX_SEEN_IDS:
        existing_ids = existing_ids[-_MAX_SEEN_IDS:]

    company_state["seen_ids"] = existing_ids
    company_state["last_checked_at"] = datetime.now(timezone.utc).isoformat()


def is_first_run(state: dict) -> bool:
    """Return True if first_run_completed_at is None or missing."""
    return state.get("first_run_completed_at") is None


def mark_first_run_complete(state: dict) -> None:
    """Set first_run_completed_at to current ISO8601 timestamp."""
    state["first_run_completed_at"] = datetime.now(timezone.utc).isoformat()
