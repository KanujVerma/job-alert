"""Tests for src/storage.py."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

import pytest

from src.storage import (
    load_state,
    save_state,
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


# ---------------------------------------------------------------------------
# P1-C: Policy Migration, Corruption Handling, Deduplication, & Backfill
# ---------------------------------------------------------------------------

from src.storage import (
    POLICY_VERSION,
    StateCorruptionError,
    _empty_state,
    migrate_state,
    normalize_url,
    is_url_alerted,
    record_alerted_url,
    is_backfill_pending,
    mark_backfill_completed,
    get_backfill_candidates,
    record_review_job,
    get_daily_review_digest,
)


class TestStateCorruption:
    def test_corrupt_json_raises_corruption_error(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{invalid json{{")
        with pytest.raises(StateCorruptionError, match="Corrupt state file"):
            load_state(str(path), raise_on_corrupt=True)

    def test_non_dict_json_raises_corruption_error(self, tmp_path):
        path = tmp_path / "array.json"
        path.write_text("[1, 2, 3]")
        with pytest.raises(StateCorruptionError, match="did not contain a JSON object"):
            load_state(str(path), raise_on_corrupt=True)

    def test_invalid_companies_raises_corruption_error(self, tmp_path):
        path = tmp_path / "bad_companies.json"
        path.write_text('{"version": 2, "companies": "not_a_dict"}')
        with pytest.raises(StateCorruptionError, match="invalid 'companies' field"):
            load_state(str(path), raise_on_corrupt=True)

    def test_missing_file_never_raises(self, tmp_path):
        path = str(tmp_path / "missing.json")
        state = load_state(path, raise_on_corrupt=True)
        assert state["version"] == 2
        assert state["policy_version"] == POLICY_VERSION


class TestPolicyMigration:
    def test_migrate_state_sets_policy_version_and_structures(self):
        v2_raw = {
            "version": 2,
            "first_run_completed_at": "2026-05-01T00:00:00+00:00",
            "companies": {
                "Micron": {
                    "last_checked_at": None,
                    "seen_jobs": {"JR123": {"first_seen": "2026-05-01T00:00:00+00:00", "last_seen": "2026-05-01T00:00:00+00:00", "alerted": True}},
                }
            },
        }
        migrated_state, did_migrate = migrate_state(v2_raw)
        assert did_migrate is True
        assert migrated_state["policy_version"] == POLICY_VERSION
        assert POLICY_VERSION in migrated_state["migrations"]
        assert migrated_state["migrations"][POLICY_VERSION]["backfill_completed"] is False
        assert "alerted_urls" in migrated_state
        assert "review_queue" in migrated_state
        # Preserves historical seen_jobs
        assert "JR123" in migrated_state["companies"]["Micron"]["seen_jobs"]
        assert migrated_state["companies"]["Micron"]["seen_jobs"]["JR123"]["alerted"] is True

    def test_migrate_state_is_idempotent(self):
        state = _empty_state()
        migrate_state(state)
        # Calling migrate_state again
        state2, did_migrate2 = migrate_state(state)
        assert did_migrate2 is False
        assert state2["policy_version"] == POLICY_VERSION


class TestURLDeduplication:
    def test_normalize_url_strips_tracking_and_normalizes(self):
        url1 = "https://jobs.example.com/careers/job/123/?utm_source=linkedin&utm_medium=feed#overview"
        url2 = "https://jobs.example.com/careers/job/123?ref=social&lever-source=post"
        assert normalize_url(url1) == "https://jobs.example.com/careers/job/123"
        assert normalize_url(url2) == "https://jobs.example.com/careers/job/123"

    def test_is_url_alerted_and_record(self):
        state = _empty_state()
        url = "https://careers.microsoft.com/us/en/job/1812345/Software-Engineer-New-Grad?utm_source=board"
        assert is_url_alerted(url, state) is False

        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        record_alerted_url(url, "Microsoft", "ms::pcsx::1812345", state, now)

        # Exact match and match with different tracking parameters
        assert is_url_alerted(url, state) is True
        assert is_url_alerted("https://careers.microsoft.com/us/en/job/1812345/Software-Engineer-New-Grad", state) is True
        # Cross-source check (e.g. MSR pointing to same requisition)
        assert is_url_alerted("https://careers.microsoft.com/us/en/job/1812345/Software-Engineer-New-Grad?source=msr", state) is True


class TestBoundedBackfill:
    def test_backfill_completion_lifecycle(self):
        state = _empty_state()
        migrate_state(state)
        assert is_backfill_pending(state) is True

        mark_backfill_completed(state)
        assert is_backfill_pending(state) is False

    def test_get_backfill_candidates_seven_day_window(self):
        import dataclasses
        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        state = _empty_state()
        migrate_state(state)

        # Job 1: posted 3 days ago -> eligible candidate
        job_recent = dataclasses.replace(
            make_job("job_recent"),
            posted_at=now - timedelta(days=3),
            url="https://example.com/job/recent",
        )

        # Job 2: posted 10 days ago -> outside 7-day window
        job_old = dataclasses.replace(
            make_job("job_old"),
            posted_at=now - timedelta(days=10),
            url="https://example.com/job/old",
        )

        # Job 3: recent but already alerted URL
        job_alerted = dataclasses.replace(
            make_job("job_alerted"),
            posted_at=now - timedelta(days=2),
            url="https://example.com/job/alerted",
        )
        record_alerted_url(job_alerted.url, "Acme", job_alerted.id, state, now)

        candidates = get_backfill_candidates([job_recent, job_old, job_alerted], state, now, lookback_days=7)
        assert len(candidates) == 1
        assert candidates[0].id == "job_recent"


class TestReviewQueueAndDigest:
    def test_record_and_digest(self):
        state = _empty_state()
        migrate_state(state)
        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)

        import dataclasses
        job = dataclasses.replace(
            make_job("rev_1"),
            title="Software Engineer",
            raw_text="software engineer full-time remote core platform",
            role_type="unknown",
        )
        record_review_job(state, job, ["needs_review: generic software engineer"], now)

        assert "rev_1" in state["review_queue"]
        assert state["review_queue"]["rev_1"]["title"] == job.title

        # First digest should return items
        digest_res = get_daily_review_digest(state, now, cap=10)
        assert digest_res is not None
        items, count = digest_res
        assert count == 1
        assert items[0]["company"] == "Acme"

        # Mark digest sent
        state["review_digest"]["last_sent_at"] = now.isoformat()

        # Called 5 hours later -> should be throttled (returns None)
        assert get_daily_review_digest(state, now + timedelta(hours=5)) is None

        # Called 25 hours later -> returns digest
        later = now + timedelta(hours=25)
        digest_res2 = get_daily_review_digest(state, later)
        assert digest_res2 is not None

    def test_remove_review_job(self):
        from src.storage import remove_review_job
        state = _empty_state()
        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        job = make_job("rev_to_remove")
        record_review_job(state, job, ["needs_review"], now)
        assert "rev_to_remove" in state["review_queue"]

        assert remove_review_job(state, "rev_to_remove") is True
        assert "rev_to_remove" not in state["review_queue"]
        assert remove_review_job(state, "nonexistent") is False

    def test_clean_review_queue_prunes_excluded_senior_roles(self):
        from src.storage import clean_review_queue
        state = _empty_state()
        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Senior role that should be pruned
        queue = state.setdefault("review_queue", {})
        queue["senior_pmts"] = {
            "company": "Salesforce",
            "title": "Software Engineering, AI Systems (PMTS)",
            "url": "https://example.com/job/pmts",
            "location": "San Francisco, CA",
            "network_priority": True,
            "reasons": ["eligibility: needs_review"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }

        # 2. Genuine early career role that should remain
        queue["early_swe"] = {
            "company": "Apple",
            "title": "Software Engineer I",
            "url": "https://example.com/job/swe1",
            "location": "Cupertino, CA",
            "network_priority": True,
            "reasons": ["eligibility: needs_review"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }

        pruned = clean_review_queue(state)
        assert pruned == 1
        assert "senior_pmts" not in state["review_queue"]
        assert "early_swe" in state["review_queue"]

    def test_prioritized_digest_ranks_promising_tech_roles_first(self):
        state = _empty_state()
        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        queue = state.setdefault("review_queue", {})

        # Low relevance: non-network, non-tech
        queue["job_generic"] = {
            "company": "GenericCorp",
            "title": "Technical Writer",
            "url": "https://example.com/job/tw",
            "location": "Anytown, USA",
            "network_priority": False,
            "reasons": ["needs_review"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }

        # High relevance: Network Priority company + SWE I + Bay Area
        queue["job_network_swe1"] = {
            "company": "Salesforce",
            "title": "Software Engineer I",
            "url": "https://salesforce.com/job/swe1",
            "location": "San Francisco, CA",
            "network_priority": True,
            "reasons": ["needs_review"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }

        # Mid relevance: Network Priority, but generic title
        queue["job_network_eda"] = {
            "company": "Intel",
            "title": "EDA Tool Software Engineer",
            "url": "https://intel.com/job/eda",
            "location": "Austin, TX",
            "network_priority": True,
            "reasons": ["needs_review"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }

        digest_res = get_daily_review_digest(state, now, cap=10)
        assert digest_res is not None
        items, _ = digest_res
        assert len(items) >= 2
        # Highest ranked must be job_network_swe1
        assert items[0]["title"] == "Software Engineer I"
        assert items[0]["company"] == "Salesforce"


class TestPruneExtended:
    def test_prunes_alerted_urls_and_review_queue(self):
        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        old_ts = (now - timedelta(days=200)).isoformat()
        recent_ts = (now - timedelta(days=10)).isoformat()

        state = _empty_state()
        state["alerted_urls"] = {
            "https://example.com/old": {"alerted_at": old_ts, "company": "A", "job_id": "1"},
            "https://example.com/recent": {"alerted_at": recent_ts, "company": "A", "job_id": "2"},
        }
        state["review_queue"] = {
            "old_rev": {"last_seen": old_ts, "company": "A", "title": "Old"},
            "recent_rev": {"last_seen": recent_ts, "company": "A", "title": "Recent"},
        }

        prune_seen_jobs(state, ttl_days=180, now=now)

        assert "https://example.com/old" not in state["alerted_urls"]
        assert "https://example.com/recent" in state["alerted_urls"]
        assert "old_rev" not in state["review_queue"]
        assert "recent_rev" in state["review_queue"]


class TestRollbackCompatibility:
    def test_legacy_mode_compatible_with_versioned_state(self):
        """Verifies rollback rule: state with policy_version remains fully readable and functional in legacy mode."""
        state = _empty_state()
        migrate_state(state)
        # Add seen jobs
        job = make_job("job_legacy")
        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        candidates = classify_jobs([job], "Acme", state, freshness_hours=48, now=now)
        assert len(candidates) == 1
        mark_alerted(candidates, "Acme", state)
        assert state["companies"]["Acme"]["seen_jobs"]["job_legacy"]["alerted"] is True
        # Re-running classify suppresses already alerted job as expected
        candidates2 = classify_jobs([job], "Acme", state, freshness_hours=48, now=now)
        assert len(candidates2) == 0
