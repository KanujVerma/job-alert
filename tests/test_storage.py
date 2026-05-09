"""Tests for src/storage.py."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

import pytest

from src.storage import (
    load_state,
    save_state,
    get_new_jobs,
    mark_seen,
    is_first_run,
    mark_first_run_complete,
)
from src.models import Job

_NOW = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_job(job_id: str, company: str = "Acme") -> Job:
    return Job(
        id=job_id,
        company=company,
        title="Software Engineer Intern",
        location="Remote",
        department=None,
        category=None,
        url="https://example.com/job/1",
        source_platform="workday",
        posted_at=None,
        detected_at=_NOW,
        raw_text="software engineer intern remote",
        role_type="internship",
        priority="normal",
        matched_keywords=("intern", "software"),
    )


class TestLoadState:
    def test_no_file_returns_empty_state(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        state = load_state(path)
        assert state["version"] == 2
        assert state["first_run_completed_at"] is None
        assert state["companies"] == {}

    def test_loads_existing_file(self, tmp_path):
        path = tmp_path / "state.json"
        data = {
            "version": 1,
            "first_run_completed_at": "2026-01-01T00:00:00+00:00",
            "companies": {"Acme": {"last_checked_at": None, "seen_ids": ["abc123"]}},
        }
        path.write_text(json.dumps(data))
        state = load_state(str(path))
        assert state["first_run_completed_at"] == "2026-01-01T00:00:00+00:00"
        assert "Acme" in state["companies"]
        # v1 file is migrated on load: seen_ids → seen_jobs
        assert "abc123" in state["companies"]["Acme"]["seen_jobs"]

    def test_corrupt_json_returns_empty_state(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{corrupt json{{")
        state = load_state(str(path))
        assert state["companies"] == {}


class TestSaveState:
    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "state.json")
        original = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {"Acme": {"last_checked_at": None, "seen_ids": ["id1"]}},
        }
        save_state(original, path)
        loaded = load_state(path)
        # v1 file is migrated on load: seen_ids → seen_jobs
        assert "id1" in loaded["companies"]["Acme"]["seen_jobs"]

    def test_atomic_no_temp_file_left(self, tmp_path):
        path = str(tmp_path / "state.json")
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        save_state(state, path)
        # No .tmp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "state.json")
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        save_state(state, path)
        assert os.path.exists(path)


class TestGetNewJobs:
    def test_new_id_is_included(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        jobs = [make_job("new-id-1"), make_job("new-id-2")]
        new = get_new_jobs(jobs, "Acme", state)
        assert len(new) == 2

    def test_known_id_is_excluded(self):
        state = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {"Acme": {"last_checked_at": None, "seen_ids": ["old-id"]}},
        }
        jobs = [make_job("old-id"), make_job("brand-new")]
        new = get_new_jobs(jobs, "Acme", state)
        assert len(new) == 1
        assert new[0].id == "brand-new"

    def test_empty_jobs_returns_empty(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        new = get_new_jobs([], "Acme", state)
        assert new == []


class TestMarkSeen:
    def test_adds_ids(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        jobs = [make_job("id1"), make_job("id2")]
        mark_seen(jobs, "Acme", state)
        assert "id1" in state["companies"]["Acme"]["seen_ids"]
        assert "id2" in state["companies"]["Acme"]["seen_ids"]

    def test_updates_last_checked_at(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        mark_seen([make_job("x")], "Acme", state)
        ts = state["companies"]["Acme"]["last_checked_at"]
        assert ts is not None
        # Should be a valid ISO timestamp
        datetime.fromisoformat(ts)

    def test_no_duplicate_ids(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        jobs = [make_job("same-id")]
        mark_seen(jobs, "Acme", state)
        mark_seen(jobs, "Acme", state)
        ids = state["companies"]["Acme"]["seen_ids"]
        assert ids.count("same-id") == 1

    def test_prunes_to_5000(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        # Pre-fill with 5000 IDs
        state["companies"]["Acme"] = {
            "last_checked_at": None,
            "seen_ids": [f"old-{i}" for i in range(5000)],
        }
        new_jobs = [make_job("brand-new")]
        mark_seen(new_jobs, "Acme", state)
        ids = state["companies"]["Acme"]["seen_ids"]
        assert len(ids) == 5000
        assert "brand-new" in ids

    def test_creates_company_entry_if_missing(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        mark_seen([], "NewCo", state)
        assert "NewCo" in state["companies"]


class TestIsFirstRun:
    def test_true_when_none(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        assert is_first_run(state) is True

    def test_true_when_missing(self):
        state = {"version": 1, "companies": {}}
        assert is_first_run(state) is True

    def test_false_when_set(self):
        state = {
            "version": 1,
            "first_run_completed_at": "2026-01-01T00:00:00+00:00",
            "companies": {},
        }
        assert is_first_run(state) is False


class TestMarkFirstRunComplete:
    def test_sets_timestamp(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        mark_first_run_complete(state)
        ts = state["first_run_completed_at"]
        assert ts is not None
        datetime.fromisoformat(ts)

    def test_is_first_run_becomes_false(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        mark_first_run_complete(state)
        assert is_first_run(state) is False


# ---------------------------------------------------------------------------
# v1 → v2 migration tests — Task 2 (v3)
# ---------------------------------------------------------------------------

from src.storage import _migrate_v1_to_v2  # will be added in step 3


class TestMigrateV1ToV2:
    def test_converts_seen_ids_to_seen_jobs(self):
        v1 = {
            "version": 1,
            "first_run_completed_at": "2026-01-01T00:00:00+00:00",
            "companies": {
                "Micron": {
                    "last_checked_at": "2026-05-08T10:00:00+00:00",
                    "seen_ids": ["micron::workday::ABC", "micron::workday::XYZ"],
                }
            },
        }
        result = _migrate_v1_to_v2(v1)

        assert result["version"] == 2
        assert result["first_run_completed_at"] == "2026-01-01T00:00:00+00:00"
        company = result["companies"]["Micron"]
        assert "seen_ids" not in company
        assert company["last_checked_at"] == "2026-05-08T10:00:00+00:00"
        seen_jobs = company["seen_jobs"]
        assert "micron::workday::ABC" in seen_jobs
        assert "micron::workday::XYZ" in seen_jobs
        entry = seen_jobs["micron::workday::ABC"]
        assert entry["alerted"] is True
        assert entry["first_seen"] is not None
        assert entry["last_seen"] == entry["first_seen"]

    def test_empty_seen_ids_becomes_empty_seen_jobs(self):
        v1 = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {
                "Amazon": {"last_checked_at": None, "seen_ids": []}
            },
        }
        result = _migrate_v1_to_v2(v1)
        assert result["companies"]["Amazon"]["seen_jobs"] == {}
        assert "seen_ids" not in result["companies"]["Amazon"]

    def test_multiple_companies_migrated_independently(self):
        v1 = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {
                "A": {"last_checked_at": None, "seen_ids": ["a::p::1"]},
                "B": {"last_checked_at": None, "seen_ids": ["b::p::2"]},
            },
        }
        result = _migrate_v1_to_v2(v1)
        assert "a::p::1" in result["companies"]["A"]["seen_jobs"]
        assert "b::p::2" in result["companies"]["B"]["seen_jobs"]


from datetime import timedelta
from src.storage import classify_jobs, mark_alerted, mark_cap_suppressed

_NOW_V3 = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
_FRESHNESS = 48.0  # hours


def _make_v2_state(company: str = "TestCo", seen_jobs: dict | None = None) -> dict:
    return {
        "version": 2,
        "first_run_completed_at": None,
        "companies": {
            company: {
                "last_checked_at": None,
                "seen_jobs": seen_jobs or {},
            }
        },
    }


def _jid(n: int = 1) -> str:
    return f"testco::platform::{n:03d}"


class TestClassifyJobs:
    def test_new_job_is_alert_candidate(self):
        job = make_job(_jid(1))
        state = _make_v2_state()
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job in result
        entry = state["companies"]["TestCo"]["seen_jobs"][_jid(1)]
        assert entry["alerted"] is False
        assert entry["first_seen"] == _NOW_V3.isoformat()

    def test_alerted_job_skipped(self):
        job = make_job(_jid(1))
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": True}
        })
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job not in result

    def test_stale_unalerted_job_suppressed(self):
        job = make_job(_jid(1))
        old = (_NOW_V3 - timedelta(hours=72)).isoformat()
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": old, "last_seen": old, "alerted": False}
        })
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job not in result
        entry = state["companies"]["TestCo"]["seen_jobs"][_jid(1)]
        assert entry.get("stale_suppressed") is True

    def test_fresh_unalerted_job_is_candidate(self):
        job = make_job(_jid(1))
        recent = (_NOW_V3 - timedelta(hours=24)).isoformat()
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": recent, "last_seen": recent, "alerted": False}
        })
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job in result

    def test_exactly_at_freshness_boundary_is_candidate(self):
        job = make_job(_jid(1))
        at_boundary = (_NOW_V3 - timedelta(hours=_FRESHNESS)).isoformat()
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": at_boundary, "last_seen": at_boundary, "alerted": False}
        })
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job in result, "job exactly at freshness_hours should still be a candidate (> not >=)"

    def test_last_seen_always_updated(self):
        job = make_job(_jid(1))
        old = (_NOW_V3 - timedelta(hours=1)).isoformat()
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": old, "last_seen": old, "alerted": True}
        })
        classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert state["companies"]["TestCo"]["seen_jobs"][_jid(1)]["last_seen"] == _NOW_V3.isoformat()

    def test_missing_company_created(self):
        job = make_job(_jid(1))
        state = {"version": 2, "first_run_completed_at": None, "companies": {}}
        result = classify_jobs([job], "NewCo", state, _FRESHNESS, _NOW_V3)
        assert job in result
        assert "NewCo" in state["companies"]


class TestMarkAlerted:
    def test_sets_alerted_true(self):
        job = make_job(_jid(1))
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": False}
        })
        mark_alerted([job], "TestCo", state)
        assert state["companies"]["TestCo"]["seen_jobs"][_jid(1)]["alerted"] is True

    def test_clears_cap_suppressed(self):
        job = make_job(_jid(1))
        state = _make_v2_state(seen_jobs={
            _jid(1): {
                "first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(),
                "alerted": False, "cap_suppressed": True,
            }
        })
        mark_alerted([job], "TestCo", state)
        entry = state["companies"]["TestCo"]["seen_jobs"][_jid(1)]
        assert entry["alerted"] is True
        assert "cap_suppressed" not in entry

    def test_empty_list_is_noop(self):
        state = _make_v2_state()
        mark_alerted([], "TestCo", state)  # must not raise


class TestMarkCapSuppressed:
    def test_sets_cap_suppressed(self):
        job = make_job(_jid(1))
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": False}
        })
        mark_cap_suppressed([job], "TestCo", state)
        entry = state["companies"]["TestCo"]["seen_jobs"][_jid(1)]
        assert entry.get("cap_suppressed") is True
        assert entry["alerted"] is False  # NOT marked as alerted

    def test_empty_list_is_noop(self):
        state = _make_v2_state()
        mark_cap_suppressed([], "TestCo", state)  # must not raise


from src.storage import update_last_checked, prune_seen_jobs


class TestUpdateLastChecked:
    def test_updates_existing_company(self):
        state = _make_v2_state()
        update_last_checked("TestCo", state, _NOW_V3)
        assert state["companies"]["TestCo"]["last_checked_at"] == _NOW_V3.isoformat()

    def test_creates_missing_company(self):
        state = {"version": 2, "first_run_completed_at": None, "companies": {}}
        update_last_checked("NewCo", state, _NOW_V3)
        assert "NewCo" in state["companies"]
        assert state["companies"]["NewCo"]["last_checked_at"] == _NOW_V3.isoformat()
        assert "seen_jobs" in state["companies"]["NewCo"]

    def test_preserves_seen_jobs(self):
        state = _make_v2_state(seen_jobs={_jid(1): {
            "first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": True
        }})
        update_last_checked("TestCo", state, _NOW_V3)
        assert _jid(1) in state["companies"]["TestCo"]["seen_jobs"]


class TestPruneSeenJobs:
    def test_removes_stale_entries(self):
        old = (_NOW_V3 - timedelta(days=200)).isoformat()
        state = _make_v2_state(seen_jobs={
            "old_job": {"first_seen": old, "last_seen": old, "alerted": True},
            "new_job": {"first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": True},
        })
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)
        assert "old_job" not in state["companies"]["TestCo"]["seen_jobs"]
        assert "new_job" in state["companies"]["TestCo"]["seen_jobs"]

    def test_keeps_recent_entries(self):
        recent = (_NOW_V3 - timedelta(days=30)).isoformat()
        state = _make_v2_state(seen_jobs={
            "recent_job": {"first_seen": recent, "last_seen": recent, "alerted": True},
        })
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)
        assert "recent_job" in state["companies"]["TestCo"]["seen_jobs"]

    def test_boundary_exactly_at_ttl(self):
        # Entry at exactly TTL days + 1 second old should be removed (< not <=)
        cutoff = (_NOW_V3 - timedelta(days=180, seconds=1)).isoformat()
        state = _make_v2_state(seen_jobs={
            "boundary_job": {"first_seen": cutoff, "last_seen": cutoff, "alerted": True},
        })
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)
        assert "boundary_job" not in state["companies"]["TestCo"]["seen_jobs"]

    def test_exactly_at_cutoff_is_kept(self):
        cutoff = (_NOW_V3 - timedelta(days=180)).isoformat()
        state = _make_v2_state(seen_jobs={
            "boundary": {"first_seen": cutoff, "last_seen": cutoff, "alerted": True}
        })
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)
        assert "boundary" in state["companies"]["TestCo"]["seen_jobs"]

    def test_empty_seen_jobs_no_error(self):
        state = _make_v2_state()
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)  # must not raise


class TestLoadStateMigration:
    def test_v1_file_migrated_and_saved(self, tmp_path):
        state_file = tmp_path / "seen_jobs.json"
        v1 = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {
                "Salesforce": {
                    "last_checked_at": None,
                    "seen_ids": ["sf::workday::001"],
                }
            },
        }
        state_file.write_text(json.dumps(v1))

        state = load_state(str(state_file))

        assert state["version"] == 2
        assert "seen_jobs" in state["companies"]["Salesforce"]
        # Verify migration was persisted to disk
        reloaded = json.loads(state_file.read_text())
        assert reloaded["version"] == 2
        assert "seen_jobs" in reloaded["companies"]["Salesforce"]

    def test_v2_file_loaded_without_migration(self, tmp_path):
        state_file = tmp_path / "seen_jobs.json"
        v2 = {
            "version": 2,
            "first_run_completed_at": None,
            "companies": {},
        }
        state_file.write_text(json.dumps(v2))
        original_mtime = state_file.stat().st_mtime

        state = load_state(str(state_file))

        assert state["version"] == 2
        # File should not have been rewritten (no migration needed)
        assert state_file.stat().st_mtime == original_mtime

    def test_empty_state_returns_v2(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        state = load_state(path)
        assert state["version"] == 2
