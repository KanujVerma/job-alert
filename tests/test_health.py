"""Tests for adapter health transitions in src/health.py.

Time is a parameter, never a mock: every case pins an exact instant so the
threshold boundary is testable without sleeping or patching the clock.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from src.health import update_health, HEALTH_STALE, HEALTH_RECOVERED

_T0 = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)
_STALE_AFTER = 24.0


def at(hours: float) -> datetime:
    return _T0 + timedelta(hours=hours)


class TestFirstSighting:
    def test_first_call_stamps_first_tracked_at(self):
        cs = {}
        assert update_health(cs, 0, _T0, _STALE_AFTER) is None
        assert cs["health"]["first_tracked_at"] == _T0.isoformat()

    def test_nonempty_fetch_stamps_last_nonempty_at(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert cs["health"]["last_nonempty_at"] == _T0.isoformat()


class TestGoingStale:
    def test_no_verdict_before_threshold(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(23), _STALE_AFTER) is None

    def test_stale_once_threshold_crossed(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(25), _STALE_AFTER) == HEALTH_STALE

    def test_stale_is_edge_triggered_not_repeated(self):
        """The whole point of alerted: a company broken for a week pings once."""
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(25), _STALE_AFTER) == HEALTH_STALE
        assert update_health(cs, 0, at(26), _STALE_AFTER) is None
        assert update_health(cs, 0, at(200), _STALE_AFTER) is None

    def test_never_nonempty_goes_stale_against_first_tracked_at(self):
        """microsoft_research has no healthy baseline; without this it never flags."""
        cs = {}
        update_health(cs, 0, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(25), _STALE_AFTER) == HEALTH_STALE


class TestRecovery:
    def test_recovered_when_flagged_company_returns_postings(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        update_health(cs, 0, at(25), _STALE_AFTER)
        assert update_health(cs, 3, at(26), _STALE_AFTER) == HEALTH_RECOVERED
        assert cs["health"]["alerted"] is False

    def test_no_recovery_verdict_if_never_flagged(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 3, at(1), _STALE_AFTER) is None


class TestBoundary:
    def test_exactly_at_threshold_is_not_yet_stale(self):
        """Strictly greater-than, so the boundary is unambiguous."""
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(24), _STALE_AFTER) is None
