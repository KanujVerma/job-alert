"""Per-company adapter health, so a permanently dead adapter stops being invisible.

Pure and clock-free: `now` is always a parameter and nothing here sends, logs, or
persists. main.py owns the side effects.
"""
from __future__ import annotations
from datetime import datetime, timedelta

HEALTH_STALE = "stale"
HEALTH_RECOVERED = "recovered"


def update_health(
    company_state: dict,
    fetched_count: int,
    now: datetime,
    stale_after_hours: float,
) -> str | None:
    """Record this run's fetch outcome and report any health transition.

    Returns "stale" the first run a company crosses the silence threshold,
    "recovered" the first run it produces postings again after being flagged,
    and None otherwise. Mutates company_state["health"] in place.

    fetched_count is the PRE-FILTER count. A healthy adapter routinely returns
    postings that all fail the filters; only an empty fetch means the site gave
    us nothing.
    """
    if now.tzinfo is None:
        raise ValueError("update_health: 'now' must be tz-aware")

    health = company_state.setdefault(
        "health",
        {"first_tracked_at": now.isoformat(), "last_nonempty_at": None, "alerted": False},
    )
    health.setdefault("first_tracked_at", now.isoformat())
    health.setdefault("last_nonempty_at", None)
    health.setdefault("alerted", False)

    if fetched_count > 0:
        health["last_nonempty_at"] = now.isoformat()
        if health["alerted"]:
            health["alerted"] = False
            return HEALTH_RECOVERED
        return None

    if health["alerted"]:
        return None

    # A company that has never been seen non-empty has no healthy baseline to
    # have fallen from, so measure from when we started watching it instead.
    reference = health["last_nonempty_at"] or health["first_tracked_at"]
    if now - datetime.fromisoformat(reference) > timedelta(hours=stale_after_hours):
        health["alerted"] = True
        return HEALTH_STALE

    return None
