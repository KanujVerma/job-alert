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


def compute_run_diagnostics(
    state: dict,
    start_time: datetime,
    finish_time: datetime,
    configured_cadence_minutes: int,
    company_stats: dict[str, dict],
    alert_count: int,
    alert_failure_count: int = 0,
) -> dict:
    """Compute run diagnostics, duration, and scheduler gap detection.

    Pure and deterministic: timestamps are parameters.
    """
    if start_time.tzinfo is None or finish_time.tzinfo is None:
        raise ValueError("compute_run_diagnostics: timestamps must be tz-aware")

    duration_sec = round((finish_time - start_time).total_seconds(), 2)

    # Check gap since previous run
    prev_finish_str = None
    last_heartbeat = state.get("last_heartbeat")
    if last_heartbeat and last_heartbeat.get("finished_at"):
        prev_finish_str = last_heartbeat["finished_at"]

    gap_sec = None
    scheduler_gap_detected = False
    if prev_finish_str:
        try:
            prev_finish = datetime.fromisoformat(prev_finish_str)
            gap_sec = round((start_time - prev_finish).total_seconds(), 2)
            # Gap detected if elapsed time > 45 minutes or 3x configured cadence
            threshold_sec = max(45 * 60, configured_cadence_minutes * 60 * 3)
            if gap_sec > threshold_sec:
                scheduler_gap_detected = True
        except Exception:
            pass

    adapters_attempted = len(company_stats)
    adapters_succeeded = sum(1 for s in company_stats.values() if s.get("status") in ("ok", "zero"))
    adapters_failed = sum(1 for s in company_stats.values() if s.get("status") == "failed")
    adapters_zero = sum(1 for s in company_stats.values() if s.get("status") == "zero")

    accepted = sum(s.get("matched", 0) for s in company_stats.values())
    review = sum(s.get("review", 0) for s in company_stats.values())
    excluded = sum(s.get("excluded", 0) for s in company_stats.values())

    return {
        "configured_cadence_minutes": configured_cadence_minutes,
        "started_at": start_time.isoformat(),
        "finished_at": finish_time.isoformat(),
        "duration_seconds": duration_sec,
        "gap_since_last_run_seconds": gap_sec,
        "scheduler_gap_detected": scheduler_gap_detected,
        "adapters_attempted": adapters_attempted,
        "adapters_succeeded": adapters_succeeded,
        "adapters_failed": adapters_failed,
        "adapters_zero_results": adapters_zero,
        "accepted_count": accepted,
        "review_count": review,
        "excluded_count": excluded,
        "alert_success_count": alert_count,
        "alert_failure_count": alert_failure_count,
        "per_adapter_breakdown": company_stats,
    }


def record_run_heartbeat(
    state: dict, diagnostics: dict, max_history: int = 10
) -> None:
    """Save diagnostics as last_heartbeat and append to state heartbeat_history."""
    state["last_heartbeat"] = diagnostics
    history = state.setdefault("heartbeat_history", [])
    history.append(diagnostics)
    if len(history) > max_history:
        state["heartbeat_history"] = history[-max_history:]
